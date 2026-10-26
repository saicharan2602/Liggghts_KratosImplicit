"""
fem_cmd.py -- the 'cmd' LIGGGHTS calls once per coupling window (via 03_BULK_ANALYSIS.bat)
===========================================================================================
Hands window N to the resident server (fem_server.py) and blocks until CSV\\NODE_COORD_N.csv
and STATUS\\DONE_N exist. Standard library only, so it starts fast.

    1. sticky FAILED in STATUS\\status.json                       -> 1 at once
    2. N = (last NODE_COORD written) + 1, never the newest forces file
       (LIGGGHTS-SIMBA 4.1.1 may call while forces_N+1 already exists)
    3. forces_N missing, but NODE_COORD_N-1 + DONE_N-1 exist      -> repeated call: 0 at once
    4. server DONE (planned stop) / STOPPED / missing / stale     -> 1 (stale or missing: FAILED made sticky)
    5. write STATUS\\REQUEST_N, wait for NODE_COORD_N + DONE_N; give up only on FAILED, a planned
       stop, or a heartbeat older than 300 s (no fixed timeout)

LIGGGHTS calls again when NODE_COORD_N is missing (9 retries, then MPI_Abort), so every failing
call returns within ~1 s. One line per call in LOG\\cmd.log.
"""
import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import settings as ST  # noqa: E402
import sheet_io as IO  # noqa: E402

STATUS_JSON = ST.STATUS_DIR / "status.json"


def heartbeat_wall_time():
    """wall_time of heartbeat.json, or None; a read may fail for a moment while the server replaces it
    (Windows) -> retry ~0.5 s."""
    for _ in range(10):
        hb = IO.read_json(ST.STATUS_DIR / "heartbeat.json") or {}
        try:
            return float(hb["wall_time"])
        except (KeyError, TypeError, ValueError):
            time.sleep(0.05)
    return None


def read_status():
    """status.json; a read may fail for a moment while the server replaces it -> retry ~0.5 s."""
    for _ in range(10):
        st = IO.read_json(STATUS_JSON)
        if st is not None or not STATUS_JSON.exists():
            return st
        time.sleep(0.05)
    return IO.read_json(STATUS_JSON, {})


def make_failed(reason):
    """Sticky FAILED written by the cmd (dead or hung server): every retry fails at once."""
    st = IO.read_json(STATUS_JSON) or {}
    if st.get("state") != "FAILED":
        st.update(state="FAILED", reason=f"fem_cmd: {reason}", message=f"fem_cmd: {reason}",
                  updated=IO.now_iso(), updated_epoch=time.time())
        try:
            IO.write_json(STATUS_JSON, st)
        except OSError:
            pass


def main(argv):
    t0 = time.time()
    ST.LOG_DIR.mkdir(parents=True, exist_ok=True)
    ctx = {"n": "?", "newest": "?"}

    def done(rc, msg):
        IO.append_line(ST.LOG_DIR / "cmd.log", f"{IO.now_iso()} N={ctx['n']} newest_forces={ctx['newest']} "
                                               f"result={rc} wait={time.time() - t0:.3f}s {msg} args={argv}")
        if rc:
            print(f"fem_cmd: {msg}", file=sys.stderr)
        return rc

    st = read_status()
    if st and st.get("state") == "FAILED":
        return done(1, f"server FAILED (sticky): {st.get('reason')} -- see LOG\\fem_server.log")
    nc = IO.numbers_in(ST.CSV_DIR, "NODE_COORD", "csv")
    last = max(nc) if nc else 0
    forces = IO.numbers_in(ST.FORCES_DIR, "forces", "csv")
    ctx["newest"] = max(forces) if forces else None
    n = ctx["n"] = last + 1
    if n not in forces:
        if last >= 1 and (ST.STATUS_DIR / f"DONE_{last}").exists():
            ctx["n"] = last
            return done(0, f"repeated call for solved window {last}")
        return done(2, f"forces_{n}.csv not found (last NODE_COORD {last})")
    if st is None:
        make_failed("no STATUS\\status.json -- 01_STL_DERIVATION did not start the server")
        return done(1, "no Kratos server for this folder -- see LOG\\stl_derivation.log")
    state = st.get("state")
    if state == "DONE":
        return done(1, f"PLANNED STOP: {st.get('message')} -- LIGGGHTS stops after its retries (intended)")
    if state == "STOPPED":
        return done(1, f"server stopped ({st.get('message')})")
    last_beat = heartbeat_wall_time()
    age = time.time() - last_beat if last_beat is not None else float("inf")
    if age > ST.HEARTBEAT_STALE_S:
        make_failed(f"heartbeat {age:.0f} s old before window {n}")
        return done(1, f"no heartbeat for {age:.0f} s -- server dead? see LOG\\fem_server_stderr.log")
    target = ST.CSV_DIR / f"NODE_COORD_{n}.csv"
    done_flag = ST.STATUS_DIR / f"DONE_{n}"
    req = ST.STATUS_DIR / f"REQUEST_{n}"
    if not req.exists():
        IO.atomic_write_text(req, f"{n}\nrequested {IO.now_iso()}\npid {os.getpid()}\n")
    next_check = 0.0
    while True:
        if target.exists() and done_flag.exists():
            return done(0, "done")
        now = time.time()
        if now >= next_check:
            next_check = now + 0.25
            st = IO.read_json(STATUS_JSON) or st
            state = st.get("state")
            if state == "FAILED":
                return done(1, f"server FAILED: {st.get('reason')} -- see LOG\\fem_server.log")
            if state in ("DONE", "STOPPED"):
                if target.exists() and done_flag.exists():      # window N written just before the stop
                    return done(0, "done")
                return done(1, f"server ended: {st.get('message')}")
            wt = heartbeat_wall_time()
            if wt is not None:                    # unreadable: count from the last good heartbeat
                last_beat = wt
            age = time.time() - last_beat
            if age > ST.HEARTBEAT_STALE_S:
                make_failed(f"heartbeat {age:.0f} s old in window {n}")
                return done(1, f"no heartbeat for {age:.0f} s while waiting for window {n}")
        time.sleep(ST.POLL_S)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as ex:                       # never hang LIGGGHTS on a cmd bug
        print(f"fem_cmd: unexpected error {type(ex).__name__}: {ex}", file=sys.stderr)
        sys.exit(3)

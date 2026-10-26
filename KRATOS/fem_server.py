"""
fem_server.py -- the resident Kratos FEM server of the coupled draw-down run
=============================================================================
    python fem_server.py launch      01_STL_DERIVATION.bat: write STL\\NODE_COORD_0.stl, start
                                     'serve' detached, wait until STATUS\\status.json says READY
    python fem_server.py serve       the server itself (started by 'launch', never by hand)
    python fem_server.py preflight   RUN.bat: refuse to start in a used folder
    python fem_server.py idle        CLEAN.bat: refuse while a server runs in this folder

The server builds the Kratos model once and stays resident (no FEM restart files):

    LIGGGHTS (03_BULK_ANALYSIS -> fem_cmd.py)          fem_server.py
    writes FORCES\\forces_N.csv
    writes STATUS\\REQUEST_N              --->        read forces_N, SURFACE_LOAD = F_e / A_e
    waits for NODE_COORD_N + DONE_N                   20 substeps of 5e-5 s (step load)
                                          <---        CSV\\NODE_COORD_N.csv, RESULTS\\laser.csv row, DONE_N

STATUS\\status.json   STARTING | READY | RUNNING | WAITING | DONE (planned stop) | STOPPED | FAILED
                      FAILED is sticky: nobody overwrites it, every later cmd call fails at once.
STATUS\\heartbeat.json window, substep, wall time: after every substep and every 2 s from a thread.
STATUS\\STOP          (STOP.bat) the server finishes the current window and exits.

Model (settings.py): 340 ShellThinElementCorotational3D4N + 340 SurfaceLoadCondition3D4N on the STL
mesh (same ids), implicit Newmark (beta 0.25), Rayleigh alpha 0 / beta 1e-4, displacement criterion,
20 fixed substeps per 1 ms window. A non-converged substep is logged and counted, not fatal;
NaN or |u| > 0.2 m stops the server (FAILED).
"""
import argparse
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
import traceback

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import settings as ST  # noqa: E402
import sheet_io as IO  # noqa: E402

STATUS_JSON = ST.STATUS_DIR / "status.json"
HEARTBEAT_JSON = ST.STATUS_DIR / "heartbeat.json"
LASER_COLS = ("window,t_s,uz_P1_mm,laser_mm,newton_mean,newton_max,nonconv_substeps,fem_s,dem_s,"
              "sum_Fz_read_N,sum_Fz_applied_N")


def get_logger(name, path, console=False):
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if console:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        log.addHandler(sh)
    return log


# ---------------------------------------------------------------------------
# status + heartbeat
# ---------------------------------------------------------------------------
class Status:
    """STATUS\\status.json. FAILED is sticky: the first reason stays."""

    def __init__(self):
        self.lock = threading.Lock()
        self.d = {"state": "STARTING", "pid": os.getpid(), "window": 0, "message": "", "reason": "",
                  "planned_stop": False, "started": IO.now_iso(), "started_epoch": time.time()}

    def _failed(self):
        cur = IO.read_json(STATUS_JSON) or {}
        return self.d["state"] == "FAILED" or cur.get("state") == "FAILED"

    def set(self, state=None, **kw):
        with self.lock:
            if self._failed():
                return
            if state:
                self.d["state"] = state
            self.d.update(kw, updated=IO.now_iso(), updated_epoch=time.time())
            IO.write_json(STATUS_JSON, self.d)

    def fail(self, reason):
        with self.lock:
            if self._failed():
                return
            self.d.update(state="FAILED", reason=str(reason), message=str(reason)[:500],
                          updated=IO.now_iso(), updated_epoch=time.time())
            IO.write_json(STATUS_JSON, self.d)


class Heartbeat:
    """STATUS\\heartbeat.json after every substep and every 2 s from a thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.d = {"pid": os.getpid(), "window": 0, "substep": 0}
        self.stop = threading.Event()
        self.beat()
        threading.Thread(target=self._run, daemon=True).start()

    def beat(self, **kw):
        with self.lock:
            self.d.update(kw, wall_time=time.time(), iso=IO.now_iso())
            try:
                IO.write_json(HEARTBEAT_JSON, self.d)
            except OSError:
                pass

    def _run(self):
        while not self.stop.wait(ST.HEARTBEAT_S):
            self.beat()


# ---------------------------------------------------------------------------
# Kratos model files and ProjectParameters
# ---------------------------------------------------------------------------
def mdpa_text(mesh):
    nodes, q = mesh["nodes"], mesh["quads"]
    ln = ["Begin ModelPartData", "End ModelPartData", "", "Begin Properties 1", "End Properties", "",
          "Begin Nodes"]
    ln += [f"  {i} {nodes[i][0]:.9f} {nodes[i][1]:.9f} {nodes[i][2]:.9f}" for i in sorted(nodes)]
    ln += ["End Nodes", "", f"Begin Elements {ST.ELEMENT}"]
    ln += [f"  {e} 1 {' '.join(map(str, q[e]))}" for e in sorted(q)]
    ln += ["End Elements", "", f"Begin Conditions {ST.CONDITION}"]
    ln += [f"  {e} 1 {' '.join(map(str, q[e]))}" for e in sorted(q)]
    ln += ["End Conditions", ""]
    for name, nids, elems, conds in (("Parts_Beam", sorted(nodes), sorted(q), []),
                                     ("Clamp", sorted(mesh["clamp"]), [], []),
                                     ("Coupling_Surface", sorted(nodes), [], sorted(q))):
        ln += [f"Begin SubModelPart {name}", "  Begin SubModelPartNodes"] + [f"    {i}" for i in nids]
        ln += ["  End SubModelPartNodes", "  Begin SubModelPartElements"] + [f"    {i}" for i in elems]
        ln += ["  End SubModelPartElements", "  Begin SubModelPartConditions"] + [f"    {i}" for i in conds]
        ln += ["  End SubModelPartConditions", "End SubModelPart", ""]
    return "\n".join(ln) + "\n"


def materials_text():
    """By hand, so YOUNG_MODULUS reads 1.85e+11 (not 185000000000.0)."""
    return ('{\n  "properties": [{\n'
            '    "model_part_name": "Structure.Parts_Beam",\n'
            '    "properties_id": 1,\n'
            '    "Material": {\n'
            f'      "constitutive_law": {{"name": "{ST.CONSTITUTIVE_LAW}"}},\n'
            '      "Variables": {\n'
            f'        "THICKNESS": {ST.THICKNESS:.1e},\n'
            f'        "YOUNG_MODULUS": {ST.YOUNG_MODULUS:.2e},\n'
            f'        "POISSON_RATIO": {ST.POISSON_RATIO},\n'
            f'        "DENSITY": {ST.DENSITY:.1f}\n'
            '      },\n'
            '      "Tables": {}\n'
            '    }\n  }]\n}\n')


def write_model_files(mesh, model_dir=ST.MODEL_DIR):
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.mdpa").write_text(mdpa_text(mesh), encoding="ascii")
    (model_dir / "model_materials.json").write_text(materials_text(), encoding="ascii")


def project_parameters(kind="dynamic", model_dir=ST.MODEL_DIR, gravity=None, n_eigen=6):
    """kind 'dynamic' (the coupled run), 'static' (check 2, linear) or 'eigen' (check 3)."""
    ss = {"model_part_name": "Structure", "domain_size": 3, "echo_level": 0, "rotation_dofs": True,
          "model_import_settings": {"input_type": "mdpa", "input_filename": (model_dir / "model").as_posix()},
          "material_import_settings": {"materials_filename": (model_dir / "model_materials.json").as_posix()}}
    newton = {"convergence_criterion": ST.CONVERGENCE_CRITERION,
              "displacement_relative_tolerance": ST.DISP_REL_TOL,
              "displacement_absolute_tolerance": ST.DISP_ABS_TOL,
              "max_iteration": ST.MAX_ITERATION,
              "linear_solver_settings": {"solver_type": ST.LINEAR_SOLVER}}
    end_time = 1.0
    if kind == "dynamic":
        ss.update({"solver_type": "Dynamic", "time_integration_method": "implicit",
                   "scheme_type": ST.SCHEME, "newmark_beta": ST.NEWMARK_BETA,
                   "analysis_type": ST.ANALYSIS_TYPE,
                   "rayleigh_alpha": ST.RAYLEIGH_ALPHA, "rayleigh_beta": ST.RAYLEIGH_BETA,
                   "time_stepping": {"time_step": ST.DT_SUB}}, **newton)
        end_time = 1.0e9                                # the server drives the loop itself
    elif kind == "static":
        ss.update({"solver_type": "Static", "analysis_type": "linear", "time_stepping": {"time_step": 1.0}},
                  **newton)
    elif kind == "eigen":
        ss.update({"solver_type": "eigen_value", "scheme_type": "dynamic", "time_stepping": {"time_step": 1.0},
                   "eigensolver_settings": {"solver_type": "spectra_sym_g_eigs_shift",
                                            "number_of_eigenvalues": int(n_eigen),
                                            "max_iteration": 1000, "echo_level": 0}})
    else:
        raise ValueError(kind)
    cons = [{"python_module": "assign_vector_variable_process", "kratos_module": "KratosMultiphysics",
             "Parameters": {"model_part_name": "Structure.Clamp", "variable_name": v,
                            "constrained": [True, True, True], "value": [0.0, 0.0, 0.0]}}
            for v in ("DISPLACEMENT", "ROTATION")]
    loads = []
    if gravity:                                         # check 2 only: the coupled sheet has no gravity
        loads.append({"python_module": "assign_vector_by_direction_process", "kratos_module": "KratosMultiphysics",
                      "Parameters": {"model_part_name": "Structure.Parts_Beam", "variable_name": "VOLUME_ACCELERATION",
                                     "modulus": float(gravity), "constrained": False, "direction": [0.0, 0.0, -1.0]}})
    return {"problem_data": {"problem_name": "drawdown_kratos", "parallel_type": "OpenMP", "echo_level": 0,
                             "start_time": 0.0, "end_time": end_time},
            "solver_settings": ss,
            "processes": {"constraints_process_list": cons, "loads_process_list": loads},
            "output_processes": {}}


def import_kratos():
    """Kratos on one thread. -> (KM, SMA, version string)."""
    os.environ["OMP_NUM_THREADS"] = "1"
    import KratosMultiphysics as KM
    KM.Logger.GetDefaultOutput().SetSeverity(KM.Logger.Severity.WARNING)
    import KratosMultiphysics.StructuralMechanicsApplication as SMA
    import KratosMultiphysics.LinearSolversApplication  # noqa: F401  (sparse_lu)
    KM.ParallelUtilities.SetNumThreads(1)
    return KM, SMA, str(KM.Kernel.Version())


def check_solver_keys(params):
    """Every solver_settings key must be known to this Kratos' solver (no keys 10.3 does not know)."""
    ss = params["solver_settings"]
    kind = ss["solver_type"].lower()
    if kind == "dynamic":
        from KratosMultiphysics.StructuralMechanicsApplication.structural_mechanics_implicit_dynamic_solver \
            import ImplicitMechanicalSolver as C
    elif kind == "static":
        from KratosMultiphysics.StructuralMechanicsApplication.structural_mechanics_static_solver \
            import StaticMechanicalSolver as C
    else:
        from KratosMultiphysics.StructuralMechanicsApplication.structural_mechanics_eigensolver \
            import EigenSolver as C
    defaults = C.GetDefaultParameters()
    unknown = [k for k in ss if not defaults.Has(k)]
    if unknown:
        raise RuntimeError(f"solver_settings keys unknown to this Kratos: {unknown}")


def analysis(KM, params):
    """StructuralMechanicsAnalysis, initialized. -> (analysis, model part, solver)."""
    from KratosMultiphysics.StructuralMechanicsApplication.structural_mechanics_analysis \
        import StructuralMechanicsAnalysis
    check_solver_keys(params)
    sim = StructuralMechanicsAnalysis(KM.Model(), KM.Parameters(json.dumps(params)))
    sim.Initialize()
    return sim, sim.model.GetModelPart("Structure"), sim._GetSolver()


class Sheet:
    """The resident dynamic model. One instance for the whole run."""

    def __init__(self, mesh, log):
        from KratosMultiphysics.analysis_stage import AnalysisStage
        import inspect
        self.KM, self.SMA, self.version = import_kratos()
        KM, SMA = self.KM, self.SMA
        self.log = log
        self.mesh = mesh
        self.params = project_parameters("dynamic")
        (ST.MODEL_DIR / "ProjectParameters.json").write_text(json.dumps(self.params, indent=2), encoding="ascii")
        self.sim, self.mp, self.solver = analysis(KM, self.params)
        # 10.3.0 calls Predict() in RunSolutionLoop, not in InitializeSolutionStep (10.4.4 does): call it once
        self.predict_inside = "Predict()" in inspect.getsource(AnalysisStage.InitializeSolutionStep)
        pi = self.mp.ProcessInfo
        self.info = {"kratos_version": self.version, "kratos_threads": KM.ParallelUtilities.GetNumThreads(),
                     "omp_num_threads": os.environ.get("OMP_NUM_THREADS"), "python": sys.version.split()[0],
                     "rayleigh_alpha": pi[SMA.RAYLEIGH_ALPHA], "rayleigh_beta": pi[SMA.RAYLEIGH_BETA],
                     "time_step": self.solver.ComputeDeltaTime(), "predict_in_InitializeSolutionStep": self.predict_inside,
                     "nodes": self.mp.NumberOfNodes(), "elements": self.mp.NumberOfElements(),
                     "conditions": self.mp.NumberOfConditions(),
                     "clamp_nodes": self.mp.GetSubModelPart("Clamp").NumberOfNodes()}
        if (self.info["rayleigh_alpha"], self.info["rayleigh_beta"]) != (ST.RAYLEIGH_ALPHA, ST.RAYLEIGH_BETA):
            raise RuntimeError(f"ProcessInfo Rayleigh alpha/beta {self.info['rayleigh_alpha']}/"
                               f"{self.info['rayleigh_beta']}, expected {ST.RAYLEIGH_ALPHA}/{ST.RAYLEIGH_BETA}")
        if (self.info["nodes"], self.info["elements"], self.info["conditions"], self.info["clamp_nodes"]) != \
                (ST.N_NODES, ST.N_ELEM, ST.N_ELEM, ST.N_CLAMP):
            raise RuntimeError(f"model sizes {self.info}")
        self.nodes = {n.Id: n for n in self.mp.Nodes}
        self.conds = [self.mp.GetCondition(e) for e in range(1, ST.N_ELEM + 1)]
        self.X0 = {i: (n.X0, n.Y0, n.Z0) for i, n in self.nodes.items()}

    def set_forces(self, F):
        """F: 340 (Fx, Fy, Fz) [N] -> SURFACE_LOAD = F_e / A_e on condition e. -> (sum Fz read, sum Fz applied)."""
        KM, SMA = self.KM, self.SMA
        for c, f in zip(self.conds, F):
            q = KM.Array3()
            q[0], q[1], q[2] = f[0] / ST.ELEM_AREA, f[1] / ST.ELEM_AREA, f[2] / ST.ELEM_AREA
            c.SetValue(SMA.SURFACE_LOAD, q)
        applied = sum(c.GetValue(SMA.SURFACE_LOAD)[2] * ST.ELEM_AREA for c in self.conds)
        return math.fsum(f[2] for f in F), applied

    def solve_window(self, n, on_substep):
        """20 substeps of window N, step load (set before). -> (iterations per substep, non-converged count)."""
        KM = self.KM
        pi = self.mp.ProcessInfo
        its, nonconv = [], 0
        for k in range(1, ST.N_SUBSTEPS + 1):
            t = self.solver.AdvanceInTime(ST.substep_time(n, k - 1))      # returns t + dt
            if abs(t - ST.substep_time(n, k)) > 1e-12:
                raise RuntimeError(f"window {n} substep {k}: AdvanceInTime gave t = {t!r}, "
                                   f"expected {ST.substep_time(n, k)!r}")
            self.sim.time = t
            self.sim.InitializeSolutionStep()
            if not self.predict_inside:
                self.solver.Predict()
            ok = bool(self.solver.SolveSolutionStep())
            it = int(pi[KM.NL_ITERATION_NUMBER])
            self.sim.FinalizeSolutionStep()
            its.append(it)
            if not ok:
                nonconv += 1
                self.log.warning("window %d substep %d (t = %.5f s): not converged in %d iterations",
                                 n, k, t, it)
            self.check_health(n, k)
            on_substep(k, it)
        return its, nonconv

    def check_health(self, n, k):
        KM = self.KM
        for i, node in self.nodes.items():
            u = node.GetSolutionStepValue(KM.DISPLACEMENT)
            r = node.GetSolutionStepValue(KM.ROTATION)
            if not all(math.isfinite(v) for v in (u[0], u[1], u[2], r[0], r[1], r[2])):
                raise RuntimeError(f"window {n} substep {k}: NaN/inf at node {i}")
            if math.sqrt(u[0] ** 2 + u[1] ** 2 + u[2] ** 2) > ST.U_MAX_M:
                raise RuntimeError(f"window {n} substep {k}: |u| > {ST.U_MAX_M} m at node {i}")

    def positions(self):
        """Deformed mid-surface positions {id: (x, y, z)} [m] = X0 + DISPLACEMENT."""
        KM = self.KM
        X = {}
        for i, node in self.nodes.items():
            u = node.GetSolutionStepValue(KM.DISPLACEMENT)
            x0 = self.X0[i]
            X[i] = (x0[0] + u[0], x0[1] + u[1], x0[2] + u[2])
        return X


# ---------------------------------------------------------------------------
# server loop
# ---------------------------------------------------------------------------
def requests():
    out = []
    with os.scandir(ST.STATUS_DIR) as it:
        for e in it:
            if e.name.startswith("REQUEST_") and e.name[8:].isdigit():
                out.append(int(e.name[8:]))
    return sorted(out)


def wait_request(status, log):
    """Block until LIGGGHTS asks for a window -> N, or None after STATUS\\STOP."""
    while True:
        if (IO.read_json(STATUS_JSON) or {}).get("state") == "FAILED":    # set by fem_cmd (stale heartbeat)
            raise RuntimeError("status FAILED was set outside the server")
        if (ST.STATUS_DIR / "STOP").exists():
            log.info("STATUS\\STOP found -- clean exit")
            status.set("STOPPED", message="STOP file")
            return None
        reqs = requests()
        if reqs:
            return reqs[0]
        time.sleep(ST.POLL_S)


def unlink(p):
    try:
        os.remove(p)
    except OSError:
        pass


def serve():
    for d in (ST.STATUS_DIR, ST.LOG_DIR, ST.RESULTS_DIR, ST.CSV_DIR):
        d.mkdir(parents=True, exist_ok=True)
    log = get_logger("fem_server", ST.LOG_DIR / "fem_server.log")
    status = Status()
    status.set("STARTING")
    hb = Heartbeat()
    max_w = ST.max_windows()
    tot = {"windows": 0, "substeps": 0, "newton_total": 0, "newton_max": 0, "nonconv": 0,
           "fem_s": 0.0, "dem_s": 0.0}
    try:
        log.info("=== Kratos FEM server, pid %d, folder %s ===", os.getpid(), ST.ROOT)
        mesh = IO.build_mesh()
        write_model_files(mesh)
        sheet = Sheet(mesh, log)
        log.info("Kratos %s  %s", sheet.version, json.dumps(sheet.info, sort_keys=True))
        if not sheet.version.startswith(ST.KRATOS_VERSION_EXPECTED):
            log.warning("Kratos %s loaded, this setup is for %s", sheet.version, ST.KRATOS_VERSION_EXPECTED)
        log.info("Newmark beta %.2f, Rayleigh alpha %g beta %g, %d substeps of %g s, %s, max windows %s",
                 ST.NEWMARK_BETA, ST.RAYLEIGH_ALPHA, ST.RAYLEIGH_BETA, ST.N_SUBSTEPS, ST.DT_SUB,
                 ST.CONVERGENCE_CRITERION, max_w or "no limit")
        if not ST.LASER_CSV.exists():
            ST.LASER_CSV.write_text(LASER_COLS + "\n", encoding="ascii")
        quads = mesh["quads"]
        last, X_prev = 0, dict(sheet.X0)
        X_last = V_last = None
        status.set("READY", message="model built", **sheet.info, max_windows=max_w)
        hb.beat(state="WAITING")
        t_ready = time.perf_counter()
        while True:
            n = wait_request(status, log)
            if n is None:
                break
            req = ST.STATUS_DIR / f"REQUEST_{n}"
            nc = ST.CSV_DIR / f"NODE_COORD_{n}.csv"
            done = ST.STATUS_DIR / f"DONE_{n}"
            if 1 <= n <= last:                                           # repeated request
                if not nc.exists() and n == last:
                    IO.atomic_write_bytes(nc, IO.node_coord_text(n, quads, X_last, V_last).encode("ascii"))
                    log.warning("window %d requested again, NODE_COORD missing -- rewritten", n)
                elif not nc.exists():
                    raise RuntimeError(f"window {n} requested again after window {last}, NODE_COORD_{n} missing")
                IO.atomic_write_text(done, f"{n}\n")
                unlink(req)
                continue
            if n != last + 1:
                raise RuntimeError(f"gap: window {n} requested, last solved {last}")
            dem_s = time.perf_counter() - t_ready
            F = IO.read_forces(ST.FORCES_DIR / f"forces_{n}.csv")
            status.set("RUNNING", window=n)
            hb.beat(state="RUNNING", window=n, substep=0)
            t0 = time.perf_counter()
            fz_read, fz_applied = sheet.set_forces(F)
            its, nonconv = sheet.solve_window(n, lambda k, it: hb.beat(substep=k, iterations=it))
            fem_s = time.perf_counter() - t0
            X = sheet.positions()
            V = {i: tuple((X[i][c] - X_prev[i][c]) / ST.DT_FEM for c in range(3)) for i in X}   # TOP_NVEL
            IO.atomic_write_bytes(nc, IO.node_coord_text(n, quads, X, V).encode("ascii"))
            p1, p2 = X[ST.P1_NODE], X[ST.P2_NODE]
            uz = p1[2] - sheet.X0[ST.P1_NODE][2]
            z_laser = IO.laser((p1[0], p1[2]), (p2[0], p2[2]), uz)
            t_end = n * ST.DT_FEM
            IO.append_line(ST.LASER_CSV, f"{n},{t_end:.3f},{uz * 1e3:.6f},{z_laser * 1e3:.6f},"
                                         f"{sum(its) / len(its):.2f},{max(its)},{nonconv},{fem_s:.3f},{dem_s:.3f},"
                                         f"{fz_read:.6e},{fz_applied:.6e}")
            IO.atomic_write_text(done, f"{n}\n")
            unlink(req)
            last, X_prev, X_last, V_last = n, X, X, V
            tot["windows"] += 1
            tot["substeps"] += len(its)
            tot["newton_total"] += sum(its)
            tot["newton_max"] = max(tot["newton_max"], max(its))
            tot["nonconv"] += nonconv
            tot["fem_s"] += fem_s
            tot["dem_s"] += dem_s
            if n <= 3 or n % 50 == 0 or nonconv:
                log.info("window %5d t=%.3f s  sum Fz %+.4e N (applied %+.4e)  uz(P1) %+.3f mm  laser %+.3f mm  "
                         "Newton mean %.1f max %d  nonconv %d  FEM %.2f s  DEM %.2f s", n, t_end, fz_read,
                         fz_applied, uz * 1e3, z_laser * 1e3, sum(its) / len(its), max(its), nonconv, fem_s, dem_s)
            status.set("WAITING", window=n, last_solved=n, totals=tot)
            hb.beat(state="WAITING", window=n, substep=0)
            t_ready = time.perf_counter()
            if max_w and n >= max_w:
                msg = f"planned stop after window {n} (DDK_MAX_WINDOWS={max_w})"
                log.info("%s -- the next cmd call returns non-zero, LIGGGHTS stops after its retries", msg)
                status.set("DONE", message=msg, planned_stop=True)
                break
        log.info("server ended: %s", json.dumps(tot))
        status.set(None, ended=IO.now_iso(), ended_epoch=time.time(), totals=tot)
        return 0
    except Exception as ex:
        log.error("Kratos server FAILED:\n%s", traceback.format_exc())
        status.fail(f"{type(ex).__name__}: {ex}")
        return 1
    finally:
        hb.stop.set()
        hb.beat(state=(IO.read_json(STATUS_JSON) or {}).get("state", "EXITED"))


# ---------------------------------------------------------------------------
# launch (01_STL_DERIVATION.bat) and preflight (RUN.bat)
# ---------------------------------------------------------------------------
def launch():
    for d in (ST.STATUS_DIR, ST.LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
    log = get_logger("launch", ST.LOG_DIR / "stl_derivation.log", console=True)
    if IO.numbers_in(ST.CSV_DIR, "NODE_COORD", "csv"):
        log.error("CSV\\ already holds NODE_COORD files -- copy the folder for a new run")
        return 1
    mesh = IO.write_stl_file()
    log.info("STL\\NODE_COORD_0.stl: %d nodes, %d elements, %d facets, %d clamped nodes",
             len(mesh["nodes"]), len(mesh["quads"]), 2 * len(mesh["quads"]), len(mesh["clamp"]))
    try:
        fd = os.open(ST.STATUS_DIR / "server.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        log.error("STATUS\\server.lock exists: a server was already started in this folder")
        return 1
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED, NEW_PROCESS_GROUP, NO_WINDOW
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", PYTHONUNBUFFERED="1")
    with open(ST.LOG_DIR / "fem_server_stdout.log", "ab") as out, open(ST.LOG_DIR / "fem_server_stderr.log", "ab") as err:
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "serve"], stdout=out, stderr=err,
                             stdin=subprocess.DEVNULL, cwd=str(ST.ROOT), env=env, close_fds=True, **kw)
    os.write(fd, f"pid {p.pid}\nstarted {IO.now_iso()}\npython {sys.executable}\n".encode())
    os.close(fd)
    log.info("Kratos server started: pid %d, %s (max windows %s)", p.pid, sys.executable,
             ST.max_windows() or "no limit")
    t0 = time.time()
    while time.time() - t0 < ST.READY_TIMEOUT_S:
        st = IO.read_json(STATUS_JSON) or {}
        if st.get("state") in ("READY", "WAITING"):
            log.info("server READY after %.1f s: Kratos %s, Rayleigh alpha %s beta %s, threads %s",
                     time.time() - t0, st.get("kratos_version"), st.get("rayleigh_alpha"),
                     st.get("rayleigh_beta"), st.get("kratos_threads"))
            return 0
        if st.get("state") == "FAILED":
            log.error("server FAILED during start-up: %s -- see LOG\\fem_server.log", st.get("reason"))
            return 1
        if p.poll() is not None:
            break
        time.sleep(0.2)
    msg = f"server not READY (exit code {p.poll()}) -- see LOG\\fem_server.log and fem_server_stderr.log"
    log.error("%s", msg)
    st = IO.read_json(STATUS_JSON) or {}
    if st.get("state") != "FAILED":
        st.update(state="FAILED", reason=f"launch: {msg}", message=msg, updated=IO.now_iso(), updated_epoch=time.time())
        IO.write_json(STATUS_JSON, st)
    return 1


def server_running():
    """A server of this folder beats (heartbeat < 30 s old, not ended). The read retries ~0.5 s:
    it may fail for a moment while the server replaces heartbeat.json."""
    for _ in range(10):
        hb = IO.read_json(HEARTBEAT_JSON)
        if hb is not None or not HEARTBEAT_JSON.exists():
            break
        time.sleep(0.05)
    hb = hb or {}
    return time.time() - float(hb.get("wall_time", 0)) < 30 and hb.get("state") not in ("DONE", "STOPPED", "FAILED")


def preflight():
    """RUN.bat: one run per folder."""
    if IO.numbers_in(ST.CSV_DIR, "NODE_COORD", "csv"):
        print("ERROR: CSV\\ already holds NODE_COORD files. One run per folder: run CLEAN.bat or copy "
              "the clean folder for a new run (see README).")
        return 1
    return idle()


def idle():
    """CLEAN.bat, RUN.bat: refuse while a server runs in this folder."""
    if server_running():
        print("ERROR: a Kratos server is still running in this folder -- STOP.bat first.")
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="resident Kratos FEM server")
    ap.add_argument("mode", choices=("launch", "serve", "preflight", "idle"))
    a = ap.parse_args(argv)
    return {"launch": launch, "serve": serve, "preflight": preflight, "idle": idle}[a.mode]()


if __name__ == "__main__":
    sys.exit(main())

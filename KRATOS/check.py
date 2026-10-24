"""
check.py -- the checks before the coupled run (task section 4)
===============================================================
    python check.py formats   1  STL, NODE_COORD header and structure, forces reader, laser (no Kratos)
    python check.py static    2  Kratos version / threads / sparse_lu, the dynamic model builds (Rayleigh
                                 in ProcessInfo, solver keys, one zero-load and one loaded window), then
                                 linear self-weight 1 g: w(-10, 0) = -4.682 mm +- 0.5 %
    python check.py modal     3  f1 = 7.653 Hz +- 1 %, bending 2 = 47.9 Hz +- 1 %
    python check.py           all three
Results are printed and appended to RESULTS\\checks.txt. Exit code 0 only if every check passed.
The ANSYS comparisons of the task (STL vs <ANSYS>, 5199 headers, forces_300, laser on the ANSYS
files) are not part of this setup; the formats are checked against the ANSYS layout examples.
"""
import logging
import math
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import settings as ST  # noqa: E402
import sheet_io as IO  # noqa: E402

W60_REF_MM = -4.682            # linear self-weight, g = 9.81 (ANSYS SHELL281 / earlier Kratos gate)
F1_REF_HZ = 7.653
F_BEND2_REF_HZ = 47.9
G = 9.81


class Report:
    def __init__(self):
        self.lines, self.ok = [], True

    def row(self, name, ok, detail):
        self.ok &= bool(ok)
        s = f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}"
        print(s)
        self.lines.append(s)

    def info(self, text):
        print("  " + text)
        self.lines.append("  " + text)


# ---------------------------------------------------------------------------
# 1  formats
# ---------------------------------------------------------------------------
E12 = re.compile(r"^(0|-)\.\d{6}E[+-]\d{2}$")


def check_formats(R):
    print("1  formats (no Kratos)")
    mesh = IO.build_mesh()
    nodes, q = mesh["nodes"], mesh["quads"]
    R.row("mesh", len(nodes) == 385 and len(q) == 340 and len(mesh["clamp"]) == 77,
          f"{len(nodes)} nodes, {len(q)} elements, {len(mesh['clamp'])} clamped nodes")
    xy = lambda e: [IO.node_xy_mm(i) for i in q[e]]                      # noqa: E731
    corners = {1: [(-290, -50), (-280, -50), (-280, -40), (-290, -40)],
               60: [(-240, 40), (-230, 40), (-230, 50), (-240, 50)],
               61: [(-230, -50), (-220, -50), (-220, -40), (-230, -40)],
               340: [(40, 40), (50, 40), (50, 50), (40, 50)]}
    R.row("AMESH numbering", all(xy(e) == c for e, c in corners.items()),
          "elements 1, 60, 61, 340: corners I J K L counter-clockwise from lower left")
    R.row("laser nodes", IO.node_xy_mm(ST.P1_NODE) == ST.P1_MM and IO.node_xy_mm(ST.P2_NODE) == ST.P2_MM,
          f"P1 = node {ST.P1_NODE} {ST.P1_MM} mm, P2 = node {ST.P2_NODE} {ST.P2_MM} mm")

    # number formats
    cases = {0.755: "0.755000E+00", -0.29: "-.290000E+00", 0.0: "0.000000E+00", -0.05: "-.500000E-01",
             1e-3: "0.100000E-02", 0.9999996: "0.100000E+01"}
    bad = {v: IO.e12(v) for v, s in cases.items() if IO.e12(v) != s}
    R.row("E12.6", not bad, f"{len(cases)} examples" + (f", wrong: {bad}" if bad else ""))
    cases14 = {0.755: "  0.755000E+00", -0.29: " -0.290000E+00", 0.0: "  0.000000E+00", 1.0: "  0.100000E+01"}
    bad = {v: IO.e14(v) for v, s in cases14.items() if IO.e14(v) != s}
    R.row("E14.6", not bad, f"{len(cases14)} examples" + (f", wrong: {bad}" if bad else ""))
    hcases = {1: "0", 2: "1.E-03", 300: "2.99E-01", 101: "1.E-01", 1001: "1", 1002: "1.001", 5199: "5.198"}
    bad = {n: IO.header_time(n) for n, s in hcases.items() if IO.header_time(n) != s}
    errs = []
    for n in range(1, 5201):
        s = IO.header_time(n)
        if abs(float(s) - (n - 1) / 1000.0) > 1e-12 or (n > 1 and (n - 1 < 1000) != ("E" in s)):
            errs.append((n, s))
    R.row("NODE_COORD header line 2", not bad and not errs,
          f"examples {hcases}; N = 1..5200 round-trip and style" + (f", wrong: {bad} {errs[:5]}" if bad or errs else ""))
    R.row("NODE_COORD header line 3", IO.header_num(ST.DT_FEM) == "1.E-03", IO.header_num(ST.DT_FEM))

    # STL
    text = IO.stl_text(mesh)
    lines = text.split("\r\n")[:-1]
    ok =(text.endswith("\r\n") and "\n" not in text.replace("\r\n", "") and lines[0] == "solid ANSYS STL"
          and lines[-1] == "endsolid ANSYS STL" and len(lines) == 2 + 680 * 7
          and lines[1] == "  facet normal  0.000000E+00  0.000000E+00  0.100000E+01       1.0       1.0"
          and lines[3] == "      vertex -0.290000E+00 -0.500000E-01  0.755000E+00"
          and lines[2] == "    outer loop" and lines[6] == "    endloop" and lines[7] == "  endfacet")
    ids = [(int(float(ln.split()[5])), int(float(ln.split()[6]))) for ln in lines if ln.startswith("  facet normal")]
    ok_ids = ids == [(e, 1) for e in range(1, 341) for _ in (0, 1)]
    R.row("STL NODE_COORD_0.stl", ok and ok_ids,
          f"{len(ids)} facets, element ids 1..340 twice in order, face 1, CRLF, E14.6, first facet as ANSYS")

    # NODE_COORD of the undeformed sheet
    X = dict(nodes)
    V = {i: (0.0, 0.0, 0.0) for i in nodes}
    nc = IO.node_coord_text(1, q, X, V)
    L = nc.split("\r\n")[:-1]
    head = [ST.NODE_COORD_HEADER, "0", "1.E-03"] + IO.LEGEND
    struct = all(L[7 + 4 * t] == f"{t + 1},{(t // 2) + 1},1" for t in range(680))
    nums = all(len(f.split(",")) == 6 and all(E12.match(x) for x in f.split(","))
               for t in range(680) for f in L[8 + 4 * t: 11 + 4 * t])
    R.row("NODE_COORD_1 structure", len(L) == 2727 and L[:7] == head and struct and nums and nc.endswith("\r\n")
          and L[8] == "-.290000E+00,-.500000E-01,0.755000E+00,0.000000E+00,0.000000E+00,0.000000E+00"
          and L[-4] == "680,340,1",
          f"{len(L)} lines (7 + 680 x 4), header, 'tri,e,1', IJK then IKL, E12.6, CRLF")

    # forces reader
    F = [((e % 7 - 3) * 1e-3, (e % 5 - 2) * 1e-4, -0.014 - e * 1e-6) for e in range(1, 341)]
    got = IO.parse_forces(IO.forces_text(F))
    sums_ok = all(abs(math.fsum(g[c] for g in got) - math.fsum(f[c] for f in F)) < 1e-12 for c in range(3))
    rejects = 0
    good = IO.forces_text(F).split("\r\n")[:-1]
    for bad_text in ("\r\n".join(good[:-1]),                                      # 339 rows
                     "\r\n".join([good[1], good[0]] + good[2:]),                  # ids out of order
                     "\r\n".join(good[:-1] + [good[-1].replace(good[-1].split()[4], "nan")]),
                     "\r\n".join(good[:-1] + [good[-1][:20] + "2" + good[-1][21:]])):   # face 2
        try:
            IO.parse_forces(bad_text)
        except IO.ForcesFormatError:
            rejects += 1
    R.row("forces reader", sums_ok and rejects == 4,
          f"340 rows read back, sums exact; {rejects}/4 bad files rejected (339 rows, order, NaN, face 2)")

    # laser (zdis_calc.mac)
    z0 = ST.Z_MM / 1000.0
    und = IO.laser((-0.010, z0), (0.0, z0), 0.0)
    th = 0.2                                                     # rigid rotation about the clamp line, down
    rot = lambda x: (-0.230 + (x + 0.230) * math.cos(th), z0 - (x + 0.230) * math.sin(th))   # noqa: E731
    p1, p2 = rot(-0.010), rot(0.0)
    zl = IO.laser(p1, p2, p1[1] - z0)
    R.row("laser", und == 0.0 and abs(zl - (-0.220 * math.tan(th))) < 1e-12,
          f"undeformed 0; rigid rotation 0.2 rad: {zl * 1e3:.4f} mm = -220 tan(0.2) = {-220 * math.tan(th):.4f} mm")


# ---------------------------------------------------------------------------
# 2  static (+ Kratos setup and the dynamic model)
# ---------------------------------------------------------------------------
def _log():
    log = logging.getLogger("check")
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("  %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def check_static(R):
    import fem_server as FS
    print("2  Kratos setup, dynamic model, linear self-weight")
    KM, SMA, ver = FS.import_kratos()
    R.row("Kratos version", ver.startswith(ST.KRATOS_VERSION_EXPECTED), f"KM.Kernel.Version() = {ver}")
    R.row("single core", KM.ParallelUtilities.GetNumThreads() == 1 and os.environ.get("OMP_NUM_THREADS") == "1",
          f"Kratos threads {KM.ParallelUtilities.GetNumThreads()}, OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS')}")
    mesh = IO.build_mesh()
    FS.write_model_files(mesh)
    sheet = FS.Sheet(mesh, _log())
    i = sheet.info
    R.row("dynamic model", True, f"{i['elements']} {ST.ELEMENT}, {i['conditions']} {ST.CONDITION}, "
                                 f"{i['clamp_nodes']} clamped nodes, dt {i['time_step']} s, solver keys known, "
                                 f"{ST.LINEAR_SOLVER}")
    R.row("Rayleigh in ProcessInfo", (i["rayleigh_alpha"], i["rayleigh_beta"]) == (0.0, 1e-4),
          f"RAYLEIGH_ALPHA {i['rayleigh_alpha']}, RAYLEIGH_BETA {i['rayleigh_beta']}")
    R.info(f"Predict() inside AnalysisStage.InitializeSolutionStep: {i['predict_in_InitializeSolutionStep']} "
           f"(False in 10.3.0 -> the server calls it once per substep)")
    sheet.set_forces([(0.0, 0.0, 0.0)] * ST.N_ELEM)
    its, nonconv = sheet.solve_window(1, lambda k, it: None)
    umax = max(abs(p[c] - sheet.X0[n][c]) for n, p in sheet.positions().items() for c in range(3))
    R.row("window 1, zero load", nonconv == 0 and umax == 0.0,
          f"20 substeps, Newton max {max(its)}, max |u| {umax:.1e} m")
    fz = -4.7604 / ST.N_ELEM
    rd, ap = sheet.set_forces([(0.0, 0.0, fz)] * ST.N_ELEM)
    its, nonconv = sheet.solve_window(2, lambda k, it: None)
    uz = (sheet.positions()[ST.P1_NODE][2] - sheet.X0[ST.P1_NODE][2]) * 1e3
    R.row("window 2, uniform step load", abs(rd - ap) < 1e-9 and nonconv == 0,
          f"sum Fz read {rd:+.4f} N, applied {ap:+.4f} N; Newton mean {sum(its) / len(its):.1f} max {max(its)}; "
          f"uz(P1) {uz:+.4f} mm at t = 2 ms (info)")

    sim, mp, _ = FS.analysis(KM, FS.project_parameters("static", gravity=G))
    sim.RunSolutionLoop()
    w = mp.GetNode(ST.P1_NODE).GetSolutionStepValue(KM.DISPLACEMENT_Z) * 1e3
    R.row("self-weight 1 g, linear", abs(w / W60_REF_MM - 1) <= 0.005,
          f"w(-10, 0) = {w:.4f} mm, reference {W60_REF_MM} mm +- 0.5 % ({(w / W60_REF_MM - 1) * 100:+.2f} %)")


# ---------------------------------------------------------------------------
# 3  modal
# ---------------------------------------------------------------------------
def check_modal(R):
    import fem_server as FS
    print("3  modal")
    KM, SMA, _ = FS.import_kratos()
    FS.write_model_files(IO.build_mesh())
    sim, mp, _ = FS.analysis(KM, FS.project_parameters("eigen", n_eigen=6))
    sim.RunSolutionLoop()
    f = [math.sqrt(max(v, 0.0)) / (2 * math.pi) for v in mp.ProcessInfo[SMA.EIGENVALUE_VECTOR]]
    R.info("f = " + ", ".join(f"{x:.3f}" for x in f) + " Hz")
    R.row("f1", abs(f[0] / F1_REF_HZ - 1) <= 0.01, f"{f[0]:.3f} Hz, reference {F1_REF_HZ} Hz +- 1 %")
    k = min(range(len(f)), key=lambda j: abs(f[j] - F_BEND2_REF_HZ))
    R.row("bending 2", abs(f[k] / F_BEND2_REF_HZ - 1) <= 0.01,
          f"mode {k + 1}: {f[k]:.3f} Hz, reference {F_BEND2_REF_HZ} Hz +- 1 %")


def main(argv):
    what = argv[0] if argv else "all"
    steps = {"formats": [check_formats], "static": [check_static], "modal": [check_modal],
             "all": [check_formats, check_static, check_modal]}.get(what)
    if steps is None:
        print(__doc__)
        return 2
    R = Report()
    for s in steps:
        try:
            s(R)
        except Exception as ex:
            import traceback
            traceback.print_exc()
            R.row(s.__name__, False, f"{type(ex).__name__}: {ex}")
    verdict = "ALL PASS" if R.ok else "FAILED"
    print(verdict)
    ST.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(ST.RESULTS_DIR / "checks.txt", "a", encoding="utf-8") as fh:
        fh.write(f"=== {IO.now_iso()}  check.py {what}: {verdict}\n" + "\n".join(R.lines) + "\n")
    return 0 if R.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

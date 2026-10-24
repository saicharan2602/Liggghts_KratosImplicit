"""
sheet_io.py -- mesh, STL, forces reader, NODE_COORD writer, laser, file helpers
================================================================================
Standard library only (fem_cmd.py imports it and must start fast; check.py 1 runs without Kratos).

    build_mesh()            385 nodes, 340 quads numbered as ANSYS AMESH (task 2.1)
    stl_text()              STL\\NODE_COORD_0.stl       (TOP_STL_2D_E93)
    read_forces()           FORCES\\forces_N.csv        (LIGGGHTS dump fem)
    node_coord_text()       CSV\\NODE_COORD_N.csv       (TOP_NVEL_2D_E93)
    laser()                 zdis_calc.mac, line by line
    atomic_write_*()        <name>.part + os.replace with retries

ANSYS number formats (all files CRLF):
    E12.6   0.755000E+00   -.290000E+00   0.000000E+00    NODE_COORD rows
    E14.6    0.755000E+00  -0.290000E+00                  STL (Fortran: leading blank or minus)
    %E      0   1.E-03   2.99E-01   1   1.001   5.198     NODE_COORD header lines 2 and 3
"""
import json
import math
import os
import re
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import settings as ST  # noqa: E402

CRLF = "\r\n"


# ---------------------------------------------------------------------------
# mesh  (03_GEOMETRIE.inp: AMESH of area 1 then area 2)
# ---------------------------------------------------------------------------
def node_xy_mm(nid):
    j, i = divmod(nid - 1, ST.NX_NODES)
    return ST.X_MIN_MM + i * ST.ESIZE_MM, ST.Y_MIN_MM + j * ST.ESIZE_MM


def build_mesh():
    """-> dict(nodes {id: (x, y, z) m}, quads {e: (I, J, K, L)}, clamp [ids]).
    Elements 1-60 = area 1 (x -290..-230), 61-340 = area 2 (x -230..+50); inside an area x runs
    fastest, then y; corners I, J, K, L counter-clockwise from the lower-left corner."""
    nodes = {}
    for nid in range(1, ST.N_NODES + 1):
        x, y = node_xy_mm(nid)
        nodes[nid] = (x / 1000.0, y / 1000.0, ST.Z_MM / 1000.0)
    i_clamp = (ST.X_CLAMP_MM - ST.X_MIN_MM) // ST.ESIZE_MM          # 6
    n_rows = ST.NY_NODES - 1                                        # 10
    nid = lambda i, j: j * ST.NX_NODES + i + 1                      # noqa: E731
    quads, e = {}, 0
    for i0, i1 in ((0, i_clamp), (i_clamp, ST.NX_NODES - 1)):      # area 1, then area 2
        for j in range(n_rows):
            for i in range(i0, i1):
                e += 1
                quads[e] = (nid(i, j), nid(i + 1, j), nid(i + 1, j + 1), nid(i, j + 1))
    clamp = [n for n in nodes if node_xy_mm(n)[0] <= ST.X_CLAMP_MM]
    assert e == ST.N_ELEM and len(clamp) == ST.N_CLAMP, (e, len(clamp))
    return {"nodes": nodes, "quads": quads, "clamp": clamp}


def triangles(quads):
    """(tri id, element, (a, b, c)) in ANSYS order: per element IJK, then IKL."""
    tri = 0
    for e in sorted(quads):
        I, J, K, L = quads[e]
        for abc in ((I, J, K), (I, K, L)):
            tri += 1
            yield tri, e, abc


# ---------------------------------------------------------------------------
# ANSYS number formats
# ---------------------------------------------------------------------------
def _mant_exp(v):
    """v = m * 10**ex with 0.1 <= |m| < 1, m rounded to 6 decimals."""
    ex = int(math.floor(math.log10(abs(v)))) + 1
    m = v / 10.0 ** ex
    if round(abs(m), 6) >= 1.0:                 # 0.9999996 -> 0.100000E+01
        m, ex = m / 10.0, ex + 1
    elif round(abs(m), 6) < 0.1:                # log10 rounding just below a power of ten
        m, ex = m * 10.0, ex - 1
    return m, ex


def e12(v):
    """ANSYS *VWRITE E12.6: 0.755000E+00, -.290000E+00, 0.000000E+00."""
    v = float(v)
    if not math.isfinite(v):
        raise ValueError(f"non-finite number {v!r}")
    if v == 0.0 or abs(v) < 1e-99:
        return "0.000000E+00"
    m, ex = _mant_exp(v)
    body = f"{abs(m):.6f}"                     # 0.290000
    return ("-" + body[1:] if m < 0 else body) + f"E{ex:+03d}"


def e14(v):
    """Fortran E14.6: '  0.755000E+00', ' -0.290000E+00'."""
    v = float(v)
    m, ex = (0.0, 0) if (v == 0.0 or abs(v) < 1e-99) else _mant_exp(v)
    return (("-" if m < 0 else " ") + f"{abs(m):.6f}" + f"E{ex:+03d}").rjust(14)


def header_num(v):
    """ANSYS %E of NODE_COORD header lines 2/3: 0 -> '0', 0.001 -> '1.E-03', 0.299 -> '2.99E-01',
    0.1 -> '1.E-01'; values >= 1 as a trimmed decimal: 1.0 -> '1', 1.001 -> '1.001', 5.198 -> '5.198'."""
    v = float(v)
    if v == 0.0:
        return "0"
    if abs(v) >= 1.0:
        return f"{v:.6f}".rstrip("0").rstrip(".")
    m, e = f"{v:.6E}".split("E")
    return m.rstrip("0") + "E" + e


def header_time(n):
    """Line 2 of NODE_COORD_N.csv: (N - 1) * 1e-3, from integers."""
    return header_num((int(n) - 1) / 1000.0)


# ---------------------------------------------------------------------------
# STL
# ---------------------------------------------------------------------------
def _unit_normal(a, b, c):
    u = [b[k] - a[k] for k in range(3)]
    w = [c[k] - a[k] for k in range(3)]
    n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
    s = math.sqrt(sum(x * x for x in n))
    return [x / s for x in n]


def stl_text(mesh):
    """NODE_COORD_0.stl: 'solid ANSYS STL', per element facets IJK, IKL with
    'facet normal nx ny nz ELEM FACE', 'endsolid ANSYS STL'; CRLF."""
    nodes = mesh["nodes"]
    out = ["solid ANSYS STL"]
    for _, e, abc in triangles(mesh["quads"]):
        P = [nodes[i] for i in abc]
        out.append("  facet normal" + "".join(e14(c) for c in _unit_normal(*P)) + f"{float(e):10.1f}{1.0:10.1f}")
        out.append("    outer loop")
        out += ["      vertex" + "".join(e14(c) for c in p) for p in P]
        out.append("    endloop")
        out.append("  endfacet")
    out.append("endsolid ANSYS STL")
    return CRLF.join(out) + CRLF


def read_stl(path):
    """-> list of (elem, face, [3 vertices]) in file order."""
    lines = Path(path).read_text(encoding="ascii").splitlines()
    facets = []
    for i, ln in enumerate(lines):
        p = ln.split()
        if p[:2] == ["facet", "normal"]:
            V = [tuple(float(x) for x in lines[i + 2 + k].split()[1:4]) for k in range(3)]
            facets.append((int(float(p[5])), int(float(p[6])), V))
    return facets


# ---------------------------------------------------------------------------
# forces_N.csv  ('%10d %10d %18.11e %18.11e %18.11e': element, face, Fx, Fy, Fz [N])
# ---------------------------------------------------------------------------
class ForcesFormatError(RuntimeError):
    pass


def parse_forces(text, name="forces"):
    """-> list of 340 (Fx, Fy, Fz). Checked: 340 rows, ids 1..340 in order, face 1, finite."""
    rows = []
    for ln in text.splitlines():
        p = ln.split()
        if not p:
            continue
        if len(p) != 5:
            raise ForcesFormatError(f"{name}: row {len(rows) + 1} has {len(p)} fields: {ln!r}")
        try:
            rows.append((int(p[0]), int(p[1]), float(p[2]), float(p[3]), float(p[4])))
        except ValueError:
            raise ForcesFormatError(f"{name}: cannot read row {len(rows) + 1}: {ln!r}")
    if len(rows) != ST.N_ELEM:
        raise ForcesFormatError(f"{name}: {len(rows)} rows, expected {ST.N_ELEM}")
    for k, r in enumerate(rows, 1):
        if r[0] != k or r[1] != 1:
            raise ForcesFormatError(f"{name}: row {k} is element {r[0]} face {r[1]}, expected {k} face 1")
        if not all(math.isfinite(x) for x in r[2:]):
            raise ForcesFormatError(f"{name}: element {k} has a non-finite force {r[2:]}")
    return [r[2:] for r in rows]


def read_forces(path, retry_s=2.0):
    """forces_N.csv -> list of 340 (Fx, Fy, Fz) [N]; retries briefly (antivirus may hold the file)."""
    t0 = time.time()
    while True:
        try:
            return parse_forces(Path(path).read_text(encoding="ascii"), Path(path).name)
        except (OSError, ForcesFormatError):
            if time.time() - t0 > retry_s:
                raise
            time.sleep(0.05)


def forces_text(F):
    """The LIGGGHTS 'dump fem' layout (check.py only)."""
    return CRLF.join(f"{e:10d} {1:10d} {f[0]:18.11e} {f[1]:18.11e} {f[2]:18.11e}"
                     for e, f in enumerate(F, 1)) + CRLF


# ---------------------------------------------------------------------------
# NODE_COORD_N.csv  (7 header lines + 680 x 4 lines)
# ---------------------------------------------------------------------------
LEGEND = ["tri_id,elem_num,elem_face", "x1,y1,z1,vx1,vy1,vz1", "x2,y2,z2,vx2,vy2,vz2", "x3,y3,z3,vx3,vy3,vz3"]


def node_coord_text(n, quads, X, V):
    """X, V: {node id: (x, y, z)} deformed position [m] and window velocity [m/s]."""
    out = [ST.NODE_COORD_HEADER, header_time(n), header_num(ST.DT_FEM)] + LEGEND
    for tri, e, abc in triangles(quads):
        out.append(f"{tri},{e},1")
        out += [",".join(e12(c) for c in (*X[i], *V[i])) for i in abc]
    return CRLF.join(out) + CRLF


# ---------------------------------------------------------------------------
# laser  (zdis_calc.mac, LS > 0 branch)
# ---------------------------------------------------------------------------
def laser(p1, p2, uz_p1, x_l=ST.X_LASER_MM / 1000.0):
    """p1, p2: deformed (x, z) of P1, P2 [m]; uz_p1: UZ(P1) [m] -> zdis_P1_add [m].
        VEC_12 = P2 - P1, VEC_13 = (P3_X - x(P1), 0)       (MPOINT_3 z = NZ(P1))
        phy_12_13 = ACOS(VEC_12 . VEC_13 / (|VEC_12| |VEC_13|))   (>= 0: sign-blind)
        delta_z_P1 = tan(phy_12_13) * |VEC_13|
        zdis_P1_add = UZ(P1) - delta_z_P1"""
    v12 = (p2[0] - p1[0], p2[1] - p1[1])
    v13 = (x_l - p1[0], 0.0)
    b12, b13 = math.hypot(*v12), math.hypot(*v13)
    if b12 == 0.0 or b13 == 0.0:                     # undeformed: ANSYS 0/0, the correction is 0
        return float(uz_p1)
    c = (v12[0] * v13[0] + v12[1] * v13[1]) / (b12 * b13)
    phi = math.acos(max(-1.0, min(1.0, c)))
    return float(uz_p1) - math.tan(phi) * b13


# ---------------------------------------------------------------------------
# file helpers
# ---------------------------------------------------------------------------
def atomic_write_bytes(path, data):
    """<name>.part, then os.replace; retries ~15 s (antivirus or LIGGGHTS reading the old file)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    t0 = time.time()
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.time() - t0 > ST.REPLACE_RETRY_S:
                raise
            time.sleep(0.1)


def atomic_write_text(path, text, crlf=False):
    if crlf:
        text = text.replace("\r\n", "\n").replace("\n", CRLF)
    atomic_write_bytes(path, text.encode("utf-8"))


def append_line(path, line):
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, d):
    atomic_write_text(path, json.dumps(d, indent=1, sort_keys=True))


_NUM = re.compile(r"^(?P<p>[A-Za-z_]+?)_(?P<n>\d+)\.(?P<x>\w+)$")


def numbers_in(folder, prefix, ext):
    """Window numbers N of <prefix>_N.<ext> in folder (ignores .part files)."""
    out = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                m = _NUM.match(e.name)
                if m and m["p"] == prefix and m["x"] == ext:
                    out.append(int(m["n"]))
    except FileNotFoundError:
        pass
    return sorted(out)


def now_iso():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def write_stl_file():
    """01_STL_DERIVATION: STL\\NODE_COORD_0.stl (atomic). Returns the mesh."""
    mesh = build_mesh()
    ST.STL_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(ST.STL_DIR / "NODE_COORD_0.stl", stl_text(mesh).encode("ascii"))
    return mesh

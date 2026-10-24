"""
settings.py -- every constant of the coupled draw-down run, in one place
=========================================================================
Units: SI (m, s, N, Pa, kg) everywhere, except where a name ends in _MM.
Sources: the ANSYS deck (02_VARIABLES.inp, 03_GEOMETRIE.inp, 05_BULK_ANALYSIS_ONE_STEP.inp),
in_DRAW_DOWN_410.lmp, zdis_calc.mac, and measurements on this configuration (run C, Kratos 10.3.0).
Change a value here only together with an entry in CHANGELOG.md.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# folders (derived from this file, no absolute paths)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
KRATOS_DIR = ROOT / "KRATOS"
LIGGGHTS_DIR = ROOT / "LIGGGHTS"
STL_DIR = ROOT / "STL"
CSV_DIR = ROOT / "CSV"
FORCES_DIR = ROOT / "FORCES"
STATUS_DIR = ROOT / "STATUS"
LOG_DIR = ROOT / "LOG"
RESULTS_DIR = ROOT / "RESULTS"
MODEL_DIR = RESULTS_DIR / "model"                 # mdpa, materials, ProjectParameters written at start
EXPERIMENT_CSV = ROOT / "Experimental_Data_for_Simulation.csv"
LASER_CSV = RESULTS_DIR / "laser.csv"

# ---------------------------------------------------------------------------
# coupling clock                                    in_DRAW_DOWN_410.lmp
# ---------------------------------------------------------------------------
DT_DEM = 2.5e-5            # delta_t_DEM            l.55
DT_FEM = 1.0e-3            # delta_t_FEM            l.56  (one coupling window)
CPL_STEP = 40              # cpl_step               l.57
GESAMTZEIT = 5.0           # Gesamtzeit             l.59  (+ 0.2 s flap rotation -> 5199 windows)
N_SUBSTEPS = 20            # NSUBST,20,20,20 + AUTOTS,OFF (05_BULK_ANALYSIS_ONE_STEP.inp)
DT_SUB = 5.0e-5            # DT_FEM / N_SUBSTEPS


def substep_time(window, k):
    """FEM time at the end of substep k (0..20) of window N, from integers: ((N-1)*20 + k) * 5e-5."""
    return ((int(window) - 1) * N_SUBSTEPS + int(k)) * DT_SUB


# ---------------------------------------------------------------------------
# sheet geometry                                    02_VARIABLES.inp, 03_GEOMETRIE.inp
# ---------------------------------------------------------------------------
X_MIN_MM, X_MAX_MM = -290, 50
Y_MIN_MM, Y_MAX_MM = -50, 50
Z_MM = 755
ESIZE_MM = 10              # 10 mm quads
X_CLAMP_MM = -230          # nodes with x <= -230 mm: DISPLACEMENT and ROTATION fixed (area 1)
NX_NODES = (X_MAX_MM - X_MIN_MM) // ESIZE_MM + 1      # 35
NY_NODES = (Y_MAX_MM - Y_MIN_MM) // ESIZE_MM + 1      # 11
N_NODES = NX_NODES * NY_NODES                         # 385
N_ELEM = 340               # 60 (area 1) + 280 (area 2) = STL cells, same ids
N_CLAMP = 77               # 7 x 11 nodes
ELEM_AREA = 1.0e-4         # undeformed element area [m^2]; SURFACE_LOAD = F_e / ELEM_AREA

# ---------------------------------------------------------------------------
# material and element                              02_VARIABLES.inp
# ---------------------------------------------------------------------------
YOUNG_MODULUS = 1.85e+11   # ym = 185000 N/mm^2
POISSON_RATIO = 0.3
DENSITY = 7850.0           # 7.85e-9 t/mm^3
THICKNESS = 7.5e-4         # 0.75 mm
ELEMENT = "ShellThinElementCorotational3D4N"
CONDITION = "SurfaceLoadCondition3D4N"
CONSTITUTIVE_LAW = "LinearElasticPlaneStress2DLaw"
# no gravity on the sheet: there is no ACEL in the ANSYS deck

# ---------------------------------------------------------------------------
# Kratos solver                                     task section 2.2
# ---------------------------------------------------------------------------
KRATOS_VERSION_EXPECTED = "10.3"
SCHEME = "newmark"         # never the Kratos default (Bossak -0.3, ~8 % damping at 290 Hz)
NEWMARK_BETA = 0.25        # gamma 0.5 is fixed by Kratos for damp_factor_m 0
ANALYSIS_TYPE = "non_linear"                    # ANSYS NLGEOM,ON
RAYLEIGH_ALPHA = 0.0
RAYLEIGH_BETA = 1.0e-4
CONVERGENCE_CRITERION = "displacement_criterion"   # a residual criterion does not converge here
DISP_REL_TOL = 1.0e-5
DISP_ABS_TOL = 1.0e-9
MAX_ITERATION = 30
LINEAR_SOLVER = "LinearSolversApplication.sparse_lu"
U_MAX_M = 0.2              # |u| above this (or NaN) stops the server: status FAILED

# ---------------------------------------------------------------------------
# laser                                             zdis_calc.mac (P1 = 951, P2 = 979, P3_X = -10)
# ---------------------------------------------------------------------------
P1_MM = (-10, 0)           # ANSYS node 951
P2_MM = (0, 0)             # ANSYS node 979
X_LASER_MM = -10           # P3_X


def node_id_mm(x_mm, y_mm):
    """Kratos node id of the grid point (x, y) [integer mm]: j*35 + i + 1."""
    i, ri = divmod(x_mm - X_MIN_MM, ESIZE_MM)
    j, rj = divmod(y_mm - Y_MIN_MM, ESIZE_MM)
    if ri or rj or not (0 <= i < NX_NODES and 0 <= j < NY_NODES):
        raise ValueError(f"({x_mm}, {y_mm}) mm is not a grid node")
    return j * NX_NODES + i + 1


P1_NODE = node_id_mm(*P1_MM)     # 204
P2_NODE = node_id_mm(*P2_MM)     # 205

# ---------------------------------------------------------------------------
# handshake                                         task section 2.4
# ---------------------------------------------------------------------------
NODE_COORD_HEADER = "Transfer Data FEM-DEM Coupling ANSYS-LIGGGHTS Version 1.0"
HEARTBEAT_S = 2.0          # heartbeat thread period
HEARTBEAT_STALE_S = 300.0  # the cmd gives up only on a heartbeat older than this (no fixed timeout)
READY_TIMEOUT_S = 300.0    # 01_STL_DERIVATION waits this long for READY
POLL_S = 0.05
REPLACE_RETRY_S = 15.0     # os.replace retries (antivirus / LIGGGHTS holding the old file)
SMOKE_WINDOWS = 50         # RUN.bat smoke: the server stops after this window (planned)


def max_windows():
    """0 = no limit; RUN.bat smoke sets DDK_MAX_WINDOWS=50 (inherited by LIGGGHTS -> 01_STL_DERIVATION)."""
    try:
        return int(os.environ.get("DDK_MAX_WINDOWS", "0") or 0)
    except ValueError:
        return 0

# CHANGELOG

## 2026-10-24: setup

- Built from scratch as a simple version of `DrawDown_Kratos_Implicit` (same handshake and ANSYS
  formats, without presets, damping studies, hex20, cut-back, mock or replay tools).
- Parameters (`KRATOS\settings.py`): `ShellThinElementCorotational3D4N`, Newmark β 0.25,
  Rayleigh α 0 / β 1e-4, 20 fixed substeps of 5e-5 s, step load, displacement criterion 1e-5 / 1e-9,
  max 30 iterations, `LinearSolversApplication.sparse_lu`, no gravity on the sheet.
- `LIGGGHTS\in_DRAW_DOWN_KRATOS.lmp` = ANSYS `in_DRAW_DOWN_410.lmp` with only the `shell` paths of
  `00_CLEAN_UP` / `01_STL_DERIVATION`, the `cmd` path and the ANSYS print text changed (`LOG\lmp_diff.txt`).
- **Kratos 10.3.0 via `SETUP_PYTHON.bat`.** This PC had no Kratos 10.3 installation (only 10.4.4), and
  the folder will run on another PC. With the user's OK, `SETUP_PYTHON.bat` creates `.venv` with
  `KratosMultiphysics-all==10.3.0` (the pin of `SimBa_Kratos_Ver1\requirements.txt`).
- **Predict() is called explicitly.** In Kratos 10.3.0, `AnalysisStage.InitializeSolutionStep()` does
  *not* call `Predict()` (10.4.4 does; `RunSolutionLoop` calls it in 10.3.0). The server therefore runs per
  substep `AdvanceInTime` → `InitializeSolutionStep` → `Predict` → `SolveSolutionStep` →
  `FinalizeSolutionStep`, the order of 10.3.0's own `RunSolutionLoop`. It checks the installed source,
  so `Predict()` is never called twice. Read from the 10.3.0 sources, not run here.
- **Window counting:** N = last `NODE_COORD` + 1. If `forces_N` does not exist but `DONE_N-1` does, the
  call is a repeated call for the solved window N−1 and returns 0 at once.
- **No ANSYS comparison** (user decision): check 1 tests the formats against the ANSYS layout examples.
  Here the STL and an undeformed `NODE_COORD_1` were also byte-identical to the files of the earlier,
  ANSYS-verified `DrawDown_Kratos_Implicit` SMOKE run.
- Checks 2 and 3 and the SMOKE run are run on the target PC. Check 1 passed here (`RESULTS\checks.txt`).

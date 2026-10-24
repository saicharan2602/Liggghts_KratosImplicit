# LIGGGHTS-SIMBA + Kratos 10.3 implicit: coupled draw-down run

One simple coupled run of the IWTM draw-down test (OvGU Magdeburg): LIGGGHTS-SIMBA computes the bulk
material, Kratos replaces ANSYS SHELL281 for the steel sheet. The coupling is the ANSYS one: the same
`.lmp` coupling commands, the same `forces_N.csv` / `NODE_COORD_N.csv` / STL files (byte layout, CRLF),
the same window counting.

- **No mapping:** the FEM mesh is the STL mesh: 340 elements = 340 STL cells, same ids.
- **Element forces:** each element gets its own force from `forces_N.csv` (`SURFACE_LOAD = F_e / 1e-4 m²`).
- **No FEM restart files:** Kratos stays resident and pauses between the 1 ms windows.

| | |
|---|---|
| Element | 340 × `ShellThinElementCorotational3D4N`, E 1.85e+11 Pa, ν 0.3, ρ 7850, t 0.75 mm, clamp x ≤ −230 mm |
| Time integration | Newmark β 0.25 / γ 0.5, non-linear, 20 fixed substeps of 5e-5 s per window, step load |
| Damping | Rayleigh α = 0, β = 1e-4 |
| Newton | displacement criterion 1e-5 / 1e-9, max 30 iterations, `sparse_lu`; a non-converged substep is counted, not fatal |
| Kratos | **10.3.0**, never upgraded; single core (Kratos 1 thread, LIGGGHTS 1 process) |

All constants are in `KRATOS\settings.py`; every change goes into `CHANGELOG.md`.

## What to click (`START\Windows\`)

1. **`SETUP_PYTHON.bat`**, once per PC (needs internet, 5–10 min). Creates `.venv` with
   `KratosMultiphysics-all==10.3.0`. If it can't find Python, set `BASE_PYTHON` in `00_SETTINGS.bat`
   (Python 3.12 works). A `.venv` cannot be copied between PCs.
2. **`CHECK.bat`** (< 5 min). You should see `ALL PASS`, written to `RESULTS\checks.txt`:
   1. formats (STL, `NODE_COORD` header and structure, forces reader, laser);
   2. `Kratos 10.3.0`, 1 thread, Rayleigh α 0 / β 1e-4 in ProcessInfo, two test windows, linear
      self-weight w(−10, 0) = −4.682 mm ± 0.5 %;
   3. f₁ = 7.653 Hz and bending 2 = 47.9 Hz ± 1 %.
3. **`RUN.bat smoke`**, the full chain with a planned stop after 50 windows (flap phase, zero
   forces, < 1 h). Expect in `LOG\liggghts.log`: restart read (231 043 atoms), `Start at : 300041 with
   mean 40`, then `CSV\NODE_COORD_1…50`, one line per window with `result=0` in `LOG\cmd.log`, ΣF = 0 in
   `RESULTS\laser.csv`. After window 50 the cmd returns non-zero, LIGGGHTS retries 9× and stops.
   **That is intended.**
4. **Full run:** use a fresh copy of the folder (see below), then **`RUN.bat`**. That is 5.2 s = 5199
   windows, about one day (≈ 12 s FEM + 5 s DEM per window). At the end `plot_results.py` writes
   `RESULTS\laser_vs_experiment.png` and `RESULTS\report.md`.
5. **`STOP.bat`** stops a run: Kratos finishes the current window and exits; then close the LIGGGHTS
   window.

**One run per folder.** `RUN.bat` refuses to start if `CSV\` already holds `NODE_COORD_*` files. For a new
run, copy the folder and empty `CSV\`, `FORCES\`, `STATUS\`, `LOG\`, `RESULTS\` and `LIGGGHTS\post`,
`POST`, `MEASUREMENT` (keep `RESULTS\checks.txt` if you like).

## What happens during a run

```
RUN.bat -> LIGGGHTS (LIGGGHTS\in_DRAW_DOWN_KRATOS.lmp, restart 300000, timestep 2.5e-5 s)
  shell 00_CLEAN_UP.bat        folders; clears what a failed start left (never results)
  shell 01_STL_DERIVATION.bat  fem_server.py launch: STL\NODE_COORD_0.stl, resident Kratos server, READY
  every 40 DEM steps (1 ms):   dump fem -> FORCES\forces_N.csv
    cmd 03_BULK_ANALYSIS.bat   fem_cmd.py: N = last NODE_COORD + 1, STATUS\REQUEST_N, wait
    fem_server.py              forces_N -> 20 substeps -> CSV\NODE_COORD_N.csv, RESULTS\laser.csv, DONE_N
```

`RESULTS\laser.csv` has one row per window: t, UZ(P1), laser (`zdis_calc.mac` ported literally),
Newton mean/max, non-converged substeps, FEM and DEM seconds, Σ Fz read and applied.

## If it fails

| Look at | For |
|---|---|
| `STATUS\status.json` | `state` (READY / RUNNING / WAITING / DONE / STOPPED / FAILED) and `reason`. FAILED is sticky. |
| `LOG\fem_server.log` | Kratos version, model check, one line every 50 windows, every non-converged substep, the traceback |
| `LOG\fem_server_stderr.log` | a crash before the log exists (e.g. Kratos not importable) |
| `LOG\stl_derivation.log` | server start (`READY after … s`) |
| `LOG\cmd.log` | one line per cmd call: window, result, wait time |
| `LOG\liggghts.log` | LIGGGHTS; `LOG\lmp_diff.txt` shows the only changes to the ANSYS deck |

The server stops (FAILED) only on NaN, |u| > 0.2 m or an error. The cmd gives up only if the
heartbeat (`STATUS\heartbeat.json`, every 2 s) is older than 300 s; there is no fixed timeout.

## Files

```
KRATOS\settings.py      all constants, with their source
KRATOS\sheet_io.py      mesh, STL, forces reader, NODE_COORD writer (ANSYS number formats), laser
KRATOS\fem_server.py    resident Kratos server (launch / serve / preflight)
KRATOS\fem_cmd.py       per-window handshake (standard library only)
KRATOS\check.py         checks 1-3
KRATOS\plot_results.py  laser vs experiment, report.md
LIGGGHTS\               in_DRAW_DOWN_KRATOS.lmp (+ the unchanged ANSYS deck in_DRAW_DOWN_410.lmp),
                        STL\, TRICK\RESTART\restart300000.bin (Git LFS), bin\ (LIGGGHTS exe + vtk DLLs)
```

Not part of this setup: the comparison with the ANSYS run (STL / `NODE_COORD` / `forces_300` / laser vs
the ANSYS files); the format check uses the ANSYS layout examples instead. Shell stresses are not written.

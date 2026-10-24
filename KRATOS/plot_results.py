"""
plot_results.py -- laser vs experiment, key numbers, RESULTS\\report.md
=======================================================================
    python plot_results.py          (RUN.bat calls it when LIGGGHTS has ended)

Reads RESULTS\\laser.csv (one row per window, written by fem_server.py), the experiment
(Experimental_Data_for_Simulation.csv: time_extra = time since flap opening = FEM t) and
STATUS\\status.json. Writes RESULTS\\laser_vs_experiment.png and RESULTS\\report.md and prints
onset, peak, rebound, plateau 0.5-1.5 s, z(5 s) and the RMSE vs the experiment.
"""
import csv
import math
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import settings as ST  # noqa: E402
import sheet_io as IO  # noqa: E402

# run C: the same settings in Kratos 10.3.0 (task section 5) -- the reference for this run
RUN_C = {"peak_mm": -53.78, "t_peak_s": 0.325, "rebound_mm": -20.78, "t_rebound_s": 0.444,
         "plateau_mm": -26.57, "z5_mm": -4.63, "fem_s": 11.7, "dem_s": 4.7, "wall_h": 23.0}
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#898781", "#e6e5e1"
C_KRATOS, C_EXP = "#2a78d6", "#eb6834"             # categorical slots 1 and 2 (dataviz palette)


def read_laser():
    with open(ST.LASER_CSV, encoding="ascii") as fh:
        rows = list(csv.DictReader(fh))
    col = lambda k, f=float: np.array([f(r[k]) for r in rows])   # noqa: E731
    return {k: col(k) for k in rows[0]} if rows else None


def read_experiment():
    text = ST.EXPERIMENT_CSV.read_text(encoding="utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    head = [h.strip() for h in lines[0].split(",")]
    it, iz = head.index("time_extra"), head.index("zdis_60mm")
    t, z = [], []
    for ln in lines[1:]:
        p = ln.split(",")
        try:
            t.append(float(p[it]))
            z.append(float(p[iz]))
        except (ValueError, IndexError):
            continue
    return np.array(t), np.array(z)


def metrics(t, z):
    m = (t >= 0.0)
    t, z = t[m], z[m]
    below = np.nonzero(z < -1.0)[0]
    ip = int(np.argmin(z))
    out = {"onset_s": float(t[below[0]]) if len(below) else None,
           "peak_mm": float(z[ip]), "t_peak_s": float(t[ip]), "rebound_mm": None, "t_rebound_s": None}
    w = (t > t[ip]) & (t <= t[ip] + 0.3)                      # first local maximum within 0.3 s
    tt, zz = t[w], z[w]
    for k in range(1, len(zz) - 1):
        if zz[k] >= zz[k - 1] and zz[k] > zz[k + 1]:
            out["rebound_mm"], out["t_rebound_s"] = float(zz[k]), float(tt[k])
            break
    p = (t >= 0.5) & (t <= 1.5)
    out["plateau_mm"] = float(np.mean(z[p])) if p.any() else None
    out["z5_mm"] = float(z[np.argmin(np.abs(t - 5.0))]) if t[-1] >= 4.999 else None
    return out


def rmse(ta, za, tb, zb, t0, t1):
    lo, hi = max(ta[0], tb[0], t0), min(ta[-1], tb[-1], t1)
    if hi <= lo:
        return None
    g = np.arange(math.ceil(lo * 1000) / 1000, hi + 1e-12, 1e-3)
    return float(np.sqrt(np.mean((np.interp(g, ta, za) - np.interp(g, tb, zb)) ** 2)))


def fmt(v, f="{:.2f}"):
    return "–" if v is None else f.format(v)


def plot(L, te, ze, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(10, 7.5), facecolor=SURFACE,
                             gridspec_kw={"height_ratios": [1, 1], "hspace": 0.35})
    t_end = float(L["t_s"][-1])
    for ax, (a, b) in zip(axes, ((0.0, min(t_end, 0.8)), (0.0, max(t_end, 0.8)))):
        m = (te >= a - 0.02) & (te <= b)
        ax.plot(te[m], ze[m], color=C_EXP, lw=2, label="Experiment (laser 60 mm)")
        ax.plot(L["t_s"], L["laser_mm"], color=C_KRATOS, lw=2, label="Kratos 10.3, Newmark, β = 1e-4")
        ax.set_xlim(a, b)
        ax.set_facecolor(SURFACE)
        ax.grid(True, color=GRID, lw=0.8)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(MUTED)
        ax.tick_params(colors=MUTED, labelcolor=INK)
        ax.set_xlabel("time since flap opening [s]", color=INK)
        ax.set_ylabel("z at laser x = -10 mm [mm]", color=INK)
    axes[0].set_title("Draw-down: laser displacement, first 0.8 s", color=INK, loc="left")
    axes[1].set_title("Whole run", color=INK, loc="left")
    axes[0].legend(frameon=False, loc="lower right", labelcolor=INK)
    i = int(np.argmin(L["laser_mm"]))
    axes[0].annotate(f"peak {L['laser_mm'][i]:.2f} mm @ {L['t_s'][i]:.3f} s", (L["t_s"][i], L["laser_mm"][i]),
                     xytext=(12, -4), textcoords="offset points", color=INK, fontsize=9)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def main():
    L = read_laser()
    if L is None:
        print("RESULTS\\laser.csv has no rows yet")
        return 1
    te, ze = read_experiment()
    st = IO.read_json(ST.STATUS_DIR / "status.json", {}) or {}
    k, e = metrics(L["t_s"], L["laser_mm"]), metrics(te, ze)
    r045 = rmse(L["t_s"], L["laser_mm"], te, ze, 0.0, 0.45)
    rall = rmse(L["t_s"], L["laser_mm"], te, ze, 0.0, 1e9)
    n = len(L["window"])
    dem = L["dem_s"][1:] if n > 1 else L["dem_s"]               # window 1 includes the restart read
    wall_h = (float(st.get("updated_epoch", 0)) - float(st.get("started_epoch", 0))) / 3600.0 if st else None
    stats = {"windows": n, "t_end": float(L["t_s"][-1]), "newton_mean": float(np.mean(L["newton_mean"])),
             "newton_max": int(np.max(L["newton_max"])), "nonconv": int(np.sum(L["nonconv_substeps"])),
             "substeps": n * ST.N_SUBSTEPS, "fem_s": float(np.mean(L["fem_s"])), "dem_s": float(np.mean(dem)),
             "wall_h": wall_h, "fz_diff": float(np.max(np.abs(L["sum_Fz_read_N"] - L["sum_Fz_applied_N"])))}
    png = ST.RESULTS_DIR / "laser_vs_experiment.png"
    plot(L, te, ze, png)

    row = lambda name, m, extra: (f"| {name} | {fmt(m['peak_mm'])} @ {fmt(m['t_peak_s'], '{:.3f}')} | "   # noqa: E731
                                  f"{fmt(m['rebound_mm'])} @ {fmt(m['t_rebound_s'], '{:.3f}')} | "
                                  f"{fmt(m['plateau_mm'])} | {fmt(m.get('z5_mm'))} | {extra} |")
    c = RUN_C
    md = ["# Coupled draw-down run: LIGGGHTS-SIMBA + Kratos 10.3 implicit", "",
          f"Kratos {st.get('kratos_version', '?')}, Kratos threads {st.get('kratos_threads', '?')}, "
          f"OMP_NUM_THREADS={st.get('omp_num_threads', '?')}; {ST.ELEMENT}, Newmark beta {ST.NEWMARK_BETA}, "
          f"Rayleigh alpha {ST.RAYLEIGH_ALPHA} / beta {ST.RAYLEIGH_BETA} (ProcessInfo: {st.get('rayleigh_alpha')} / "
          f"{st.get('rayleigh_beta')}), {ST.N_SUBSTEPS} substeps per 1 ms window, step load.", "",
          f"Server state: {st.get('state', '?')} {st.get('message', '')}".rstrip(), "",
          "Laser at x = -10 mm (zdis_calc.mac), mm and s; time since flap opening.", "",
          "| | Peak | Rebound | Plateau 0.5–1.5 s | z(5 s) | RMSE vs experiment 0–0.45 s / full · FEM / DEM s/window · wall time |",
          "|---|---|---|---|---|---|",
          row("Experiment", e, "–"),
          f"| Run C (reference, Kratos 10.3.0) | {c['peak_mm']:.2f} @ {c['t_peak_s']:.3f} | {c['rebound_mm']:.2f} @ "
          f"{c['t_rebound_s']:.3f} | {c['plateau_mm']:.2f} | {c['z5_mm']:.2f} | – · {c['fem_s']} / {c['dem_s']} · "
          f"{c['wall_h']} h |",
          row("This run", k, f"{fmt(r045)} / {fmt(rall)} · {stats['fem_s']:.1f} / {stats['dem_s']:.1f} · "
                             f"{fmt(stats['wall_h'], '{:.1f}')} h"),
          "",
          f"- Windows solved: {n} (t = {stats['t_end']:.3f} s), substeps {stats['substeps']}",
          f"- Newton iterations per substep: mean {stats['newton_mean']:.1f}, max {stats['newton_max']}",
          f"- Non-converged substeps: {stats['nonconv']} of {stats['substeps']} (run C: 13 of 103 980)",
          f"- Onset (< -1 mm): this run {fmt(k['onset_s'], '{:.3f}')} s, experiment {fmt(e['onset_s'], '{:.3f}')} s",
          f"- max |sum Fz read - sum Fz applied| = {stats['fz_diff']:.2e} N",
          f"- Agreement with run C within about 1–2 mm counts as a pass (the coupled system is chaotic "
          f"after the impact): peak {k['peak_mm'] - c['peak_mm']:+.2f} mm, rebound "
          f"{(k['rebound_mm'] or float('nan')) - c['rebound_mm']:+.2f} mm, plateau "
          f"{(k['plateau_mm'] or float('nan')) - c['plateau_mm']:+.2f} mm", "",
          "![laser vs experiment](laser_vs_experiment.png)", "",
          "## Not demonstrated", "",
          "- No comparison with the ANSYS run (left out of this setup by decision): no STL / NODE_COORD / "
          "forces_300 / laser check against the ANSYS files, no RMSE vs ANSYS.",
          "- Kratos' Newmark update does not update ANGULAR_VELOCITY, so the beta damping on the rotation "
          "DOFs is not the textbook Rayleigh term (accepted, task 2.3).",
          "- Shell stresses are not written (wrong at large rotation in this element).",
          "- One run only: run-to-run scatter (about 0.4 mm in the rebound) is not quantified here.", ""]
    (ST.RESULTS_DIR / "report.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[8:20]))
    print(f"\nwritten: {png}\n         {ST.RESULTS_DIR / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

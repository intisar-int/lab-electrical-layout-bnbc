"""Independent checks and charts for the LASSET Lab electrical-service designs.

Run:  python analysis/run_analysis.py
Writes analysis/results.json and docs/figures/chart_*.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "calc"))
from service_calc import Model  # noqa: E402

M = Model()
OUT = {}

# ------------------------------------------------------------------ tables
print("\n== Protection coordination (I_b <= I_n <= I_z; I_z = ampacity printed in the report) ==")
OUT["coordination"] = {}
for k, d in M.designs.items():
    rows = M.coordination_table(d)
    OUT["coordination"][k] = rows
    print(f"\n{d.title}")
    print(f"{'ckt':7s}{'I_b [A]':>9s}{'I_n [A]':>9s}{'I_z [A]':>9s}{'load %':>8s}   I_n<=I_z")
    for r in rows:
        print(f"{r['circuit']:7s}{r['i_b']:9.2f}{r['i_n']:9.0f}{r['i_z']:9.0f}{r['loading_pct']:8.0f}   "
              f"{'ok' if r['in_le_iz'] else 'FAIL'}")

print("\n== Like-for-like maximum demand (report factors: lighting 1.0, fans+sockets 0.8, heavy 1.0) ==")
OUT["max_demand"] = {}
for k, d in M.designs.items():
    md = M.max_demand_w(d)
    t = M.totals(d)
    OUT["max_demand"][k] = {"connected_w": t["watts"], "max_demand_w": md["total_w"],
                            "current_a": md["current_a"], "by_cat": md["demand_by_cat"]}
    print(f"{d.title:48s} connected {t['watts']:6.0f} W  max demand {md['total_w']:6.0f} W  = {md['current_a']:5.2f} A")

print("\n== Main-feeder options for Approach 1 ==")
a1 = M.designs["approach1"]
i_md_design = M.margin * M.max_demand_w(a1)["current_a"]
OUT["main_options"] = {
    "design_current_a": M.totals(a1)["i_design"],
    "demand_based_design_current_a": i_md_design,
    "iz_4mm2_report_a": M.ampacity[4.0],
}
print(f"sum-of-circuits design current          : {M.totals(a1)['i_design']:.2f} A")
print(f"max-demand current x 1.2                : {i_md_design:.2f} A")
print(f"4 mm2 ampacity in the report            : {M.ampacity[4.0]:.0f} A")

print("\n== Maximum one-way run for a voltage-drop limit (conductor at 70 C, resistive) ==")
OUT["max_run_m"] = {}
rows = []
for c in a1.circuits:
    rows.append((c.id, M.i_design(c), c.cable_mm2))
rows.append(("Main", M.totals(a1)["i_design"], a1.main_cable_mm2))
for name, i, mm2 in rows:
    r3, r5 = M.max_run_m(i, mm2, 3), M.max_run_m(i, mm2, 5)
    OUT["max_run_m"][name] = {"i_design_a": i, "cable_mm2": mm2, "L_3pct_m": r3, "L_5pct_m": r5}
    print(f"{name:6s} {mm2:>4} mm2  I={i:6.2f} A   L_max(3%)={r3:6.1f} m   L_max(5%)={r5:6.1f} m")
print(f"room diagonal (reference): {M.room_diagonal_m():.1f} m")

print("\n== Lighting: lumens per tube needed for the report's >= 300 lux claim (lumen method) ==")
area = M.room["area_m2"]
OUT["lighting"] = {"area_m2": area, "required_lm_per_tube": {}}
for dk, n in (("approach1", 12), ("approach2", 14)):
    for uf in (0.4, 0.5, 0.6):
        for mf in (0.7, 0.8):
            phi = M.required_lumens_per_luminaire(300, area, n, uf, mf)
            OUT["lighting"]["required_lm_per_tube"][f"{dk}|UF={uf}|MF={mf}"] = phi
    print(f"{dk}: N={n}  " + "  ".join(
        f"UF{uf}/MF{mf}: {M.required_lumens_per_luminaire(300, area, n, uf, mf):5.0f} lm"
        for uf in (0.4, 0.5, 0.6) for mf in (0.8,)))
for dk in ("approach1", "approach2"):
    s = M.lighting_summary(M.designs[dk])
    OUT["lighting"][dk] = s
    print(f"{dk}: {s['tubes']} tubes, {s['watts']} W, {s['lpd_w_per_m2']:.2f} W/m2")

print("\n== Entry / lobby lighting present in Base Design (45 W) but absent from Approach 1/2 schedules ==")
extra_i = 45 / M.v
print(f"adds {extra_i:.2f} A calc, {M.margin*extra_i:.2f} A design to a lighting circuit "
      f"(CKT-1 would be {M.i_design(a1.circuits[0]) + M.margin*extra_i:.2f} A on a 6 A MCB)")
OUT["lobby"] = {"extra_w": 45, "extra_i_design_a": M.margin * extra_i,
                "ckt1_i_design_with_lobby_a": M.i_design(a1.circuits[0]) + M.margin * extra_i}

(ROOT / "analysis" / "results.json").write_text(json.dumps(OUT, indent=2))

# ------------------------------------------------------------------ charts
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE, CRIT = "#2a78d6", "#eb6834", "#d03b3b"
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
                     "text.color": INK, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED})


def style(ax):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


names = {"base": "Base Design\n(6 circuits)", "approach1": "Approach 1\n(3 circuits)", "approach2": "Approach 2\n(6 circuits)"}
keys = list(M.designs)

# chart 1 - connected load vs maximum demand
fig, ax = plt.subplots(figsize=(7.4, 4.2))
w = 0.30
conn = [OUT["max_demand"][k]["connected_w"] for k in keys]
dem = [OUT["max_demand"][k]["max_demand_w"] for k in keys]
x = range(len(keys))
b1 = ax.bar([i - w / 2 - 0.01 for i in x], conn, w, color=BLUE, label="Connected load")
b2 = ax.bar([i + w / 2 + 0.01 for i in x], dem, w, color=ORANGE, label="Maximum demand (report factors)")
for bars, vals in ((b1, conn), (b2, dem)):
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 70, f"{v:,.0f} W", ha="center", va="bottom", fontsize=9, color=INK)
ax.set_xticks(list(x))
ax.set_xticklabels([names[k] for k in keys], fontsize=9.5, color=INK2)
ax.set_ylim(0, 5600)
ax.set_ylabel("W")
style(ax)
ax.set_title("Connected load vs. like-for-like maximum demand", loc="left", fontsize=11.5, color=INK, pad=22)
ax.legend(loc="upper left", bbox_to_anchor=(0, 1.09), ncol=2, frameon=False, fontsize=9, labelcolor=INK2)
fig.tight_layout()
fig.savefig(ROOT / "docs/figures/chart_load_vs_demand.png", dpi=170)
plt.close(fig)

# chart 2 - main feeder: design current & MCB vs cable ampacity
fig, ax = plt.subplots(figsize=(7.4, 4.2))
ib = [OUT["coordination"][k][-1]["i_b"] for k in keys]
inn = [OUT["coordination"][k][-1]["i_n"] for k in keys]
iz = M.ampacity[4.0]
b1 = ax.bar([i - w / 2 - 0.01 for i in x], ib, w, color=BLUE, label="Design current I_b")
b2 = ax.bar([i + w / 2 + 0.01 for i in x], inn, w, color=ORANGE, label="Main MCB rating I_n")
for bars, vals, fmt in ((b1, ib, "{:.1f} A"), (b2, inn, "{:.0f} A")):
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.7, fmt.format(v), ha="center", va="bottom", fontsize=9, color=INK)
ax.axhline(iz, color=INK2, linewidth=1.2, linestyle=(0, (5, 3)), label="4 mm² Cu ampacity in the report (30 A)")
for i, v in zip(x, inn):
    ax.text(i + w / 2 + 0.01, v + 4.0, "✕ I_n > I_z", ha="center", fontsize=8.5, color=CRIT, fontweight="bold")
ax.set_xticks(list(x))
ax.set_xticklabels([names[k] for k in keys], fontsize=9.5, color=INK2)
ax.set_ylim(0, 52)
ax.set_ylabel("A")
style(ax)
ax.set_title("Main feeder: MCB rating exceeds the cable ampacity the report assigns", loc="left", fontsize=11.5, color=INK, pad=22)
ax.legend(loc="upper left", bbox_to_anchor=(0, 1.09), ncol=3, frameon=False, fontsize=8.5, labelcolor=INK2, columnspacing=1.2)
fig.tight_layout()
fig.savefig(ROOT / "docs/figures/chart_main_feeder.png", dpi=170)
plt.close(fig)

# chart 3 - max run for voltage drop (Approach 1)
fig, ax = plt.subplots(figsize=(7.4, 3.9))
labels = [r[0] for r in rows]
l3 = [OUT["max_run_m"][n]["L_3pct_m"] for n in labels]
l5 = [OUT["max_run_m"][n]["L_5pct_m"] for n in labels]
yy = list(range(len(labels)))[::-1]
h = 0.30
b1 = ax.barh([y + h / 2 + 0.01 for y in yy], l3, h, color=BLUE, label="3 % drop limit")
b2 = ax.barh([y - h / 2 - 0.01 for y in yy], l5, h, color=ORANGE, label="5 % drop limit")
for bars, vals in ((b1, l3), (b2, l5)):
    for b, v in zip(bars, vals):
        ax.text(v + 2, b.get_y() + b.get_height() / 2, f"{v:.0f} m", va="center", fontsize=9, color=INK)
ax.axvline(M.room_diagonal_m(), color=INK2, linewidth=1.2, linestyle=(0, (5, 3)), label=f"room diagonal ({M.room_diagonal_m():.1f} m)")
ax.set_yticks(yy)
ax.set_yticklabels([f"{n}  ({OUT['max_run_m'][n]['cable_mm2']} mm²)" for n in labels], fontsize=9.5, color=INK2)
ax.set_xlim(0, 305)
ax.set_xlabel("longest one-way cable run at design current [m]")
ax.grid(axis="x", color=GRID, linewidth=0.8)
ax.grid(axis="y", visible=False)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color("#c3c2b7")
ax.tick_params(length=0)
ax.set_axisbelow(True)
ax.set_title("Design Approach 1: how long can each run be?", loc="left", fontsize=11.5, color=INK, pad=22)
ax.legend(loc="upper left", bbox_to_anchor=(0, 1.1), ncol=3, frameon=False, fontsize=9, labelcolor=INK2)
fig.tight_layout()
fig.savefig(ROOT / "docs/figures/chart_voltage_drop_runs.png", dpi=170)
plt.close(fig)
print("\ncharts written")

"""Render already recorded results; this script runs no solver or experiment."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullFormatter
import numpy as np


ROOT = Path(__file__).resolve().parent
report = json.loads((ROOT / "attempt_01/RESULTS.json").read_text())
expiry = json.loads((ROOT / "expiry_diagnostic_01/RESULTS.json").read_text())
labels = {"positive_drift": "Positive drift", "zero_drift": "Zero drift",
          "negative_drift": "Negative drift", "reset_at_cost": "Reset at spike cost"}
colors = ["#2878a4", "#d28a19", "#278565", "#9356ad"]
fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.8))
for case, color in zip(report["cases"], colors):
    fine = json.loads((ROOT / "attempt_01" / case["levels"][-1]["file"]).read_text())
    boundary = np.array(fine["boundary"])
    axes[0].plot(boundary[1:, 0], boundary[1:, 1], color=color,
                 label=labels[case["name"]], linewidth=1.8)
    axes[1].loglog([row["grid"]["dx"] for row in case["levels"]],
                   [row["probe_error"] for row in case["levels"]],
                   "o-", color=color, linewidth=1.8, markersize=4)
axes[0].axhline(.6, color="#707070", linestyle=":", linewidth=1)
axes[0].plot([0, 0], [.6, 1.2], ":", color="#707070", linewidth=1.4)
axes[0].scatter([0], [.6], color="#303030", s=22, zorder=5)
axes[0].set(title="Computed threshold schedule", xlabel="Time remaining h", ylabel="Threshold b(h)")
axes[0].legend(fontsize=8, loc="best", framealpha=.95, edgecolor="none")
axes[1].invert_xaxis()
axes[1].set(title="Independent value discrepancy", xlabel="State grid spacing (finer to the right)",
            ylabel="Max probe |LCP − fixed-policy kernel value|")
axes[1].set_xticks([.04, .02, .01], labels=["0.04", "0.02", "0.01"])
axes[1].xaxis.set_minor_formatter(NullFormatter())
rows = expiry["rows"]
dt = [row["grid"]["dt"] for row in rows]
axes[2].loglog(dt, [row["lcp_boundary"] - .6 for row in rows], "o-", color="#303030",
               label="LCP = exact lattice boundary", markersize=4)
axes[2].loglog(dt, [row["continuum_implicit_boundary"] - .6 for row in rows], "--",
               color="#d28a19", label="Continuum implicit-step oracle")
axes[2].loglog(dt[:3], [3 * .45 * np.sqrt(row["grid"]["dt"]) + 2 * row["grid"]["dx"]
                       for row in rows[:3]], "s:", color="#b44545", markersize=4,
               label="Original endpoint envelope")
axes[2].invert_xaxis()
axes[2].set(title="Zero-drift endpoint diagnosis", xlabel="First time step Δ (finer to the right)",
            ylabel="First-layer threshold − c")
axes[2].legend(fontsize=7.5, loc="best", frameon=False)
for ax in axes:
    ax.grid(alpha=.18)
    ax.spines[["top", "right"]].set_visible(False)
fig.suptitle("Finite-deadline scalar natural firing: numerical evidence", fontsize=14, y=.98)
fig.text(.5, .025,
         "Original protocol: 91/92 gates. The endpoint envelope failed; a separate post-failure exact diagnostic passed.\n"
         "Value differences and discrete residuals are not certified continuous optimality gaps.",
         ha="center", va="bottom", fontsize=9)
fig.tight_layout(rect=(0, .13, 1, .94), w_pad=2.3)
fig.savefig(ROOT / "deadline_numerical_checks.svg")
fig.savefig(ROOT / "deadline_numerical_checks.png", dpi=160)
print(json.dumps({"matplotlib": matplotlib.__version__, "scope": "rendered existing result files only"}))

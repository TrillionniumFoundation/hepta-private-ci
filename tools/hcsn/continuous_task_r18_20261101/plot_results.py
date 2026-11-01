"""Post-run figure from saved contact samples; no model selection or new worlds."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


root = Path(__file__).parent
result = json.loads((root / "run_02/RESULTS.json").read_text())
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "svg.hashsalt": "hcsn-continuous-task-r18"})
figure, axes = plt.subplots(1, 3, figsize=(11.4, 3.4), sharex=True, sharey=True)
for axis, profile in zip(axes, result["numerical"]):
    samples = [r for r in profile["levels"][-1]["boundaries"] if r["mode"] == 0]
    times = [r["remaining"] for r in samples]
    axis.scatter(times, [r["reset_contact"] for r in samples], color="#b44c34", marker="v", s=45, label="RESET contact")
    axis.scatter(times, [r["stop_contact"] for r in samples], color="#205b8d", marker="^", s=45, label="STOP contact")
    for row in samples:
        axis.vlines(row["remaining"], row["reset_contact"], row["stop_contact"], color="#899da8", alpha=.55, linewidth=3)
    axis.set_title(f'Risk sigma = {profile["sigma"]:.1f}')
    axis.set_xlabel("Remaining time")
    axis.set_xticks(times)
    axis.grid(axis="y", alpha=.15)
axes[0].set_ylabel("Public quality x (content mode 0)")
axes[-1].legend(frameon=False, loc="lower left", fontsize=8)
figure.suptitle("Task-derived boundaries: discrete samples away from recovery-admission dates", fontsize=12)
figure.tight_layout()
figure.savefig(root / "BOUNDARY_CONTACTS.svg", metadata={"Date": None})
figure.savefig("/tmp/hcsn-r18-boundary-contacts.png", dpi=120)

"""Render the four prespecified fit-level primary contrasts from retained data."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ndu_policy/execution_r1/run/RESULTS.json"
result = json.loads(SOURCE.read_bytes())
keys = ["J_iid", "J_ood", "D_gated_iid", "D_gated_ood"]
labels = ["Full own-law planner J · IID", "Full own-law planner J · OOD",
          "Gated direct head edit D · IID", "Gated direct head edit D · OOD"]
colors = ["#166e58", "#166e58", "#5f6570", "#5f6570"]
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                     "svg.hashsalt": "hepta-wsp-primary-20261105"})
fig, ax = plt.subplots(figsize=(10.8, 5.2), layout="constrained")
fig.patch.set_facecolor("white")
ax.axvline(0, color="#bbc1c9", linewidth=1, zorder=0)
ax.axvline(0.005, color="#b16420", linestyle="--", linewidth=1.5,
           label="Prespecified minimum gain: 0.005", zorder=0)
for index, (key, color) in enumerate(zip(keys, colors)):
    row = result["primary"][key]
    value = row["delta"]
    low, high = row["familywise_95_interval"]
    y = 3 - index
    ax.errorbar(value, y, xerr=[[value-low], [high-value]], color=color,
                fmt="o", markersize=7.5, elinewidth=2.5, capsize=5, zorder=2)
    annotation = f"{value:+.4f}  [{low:.4f}, {high:.4f}]"
    ax.text(max(value, 0.015), y+0.24, annotation, color=color,
            ha="center" if value > 0.06 else "left", va="center", fontsize=10)
ax.set_yticks([3, 2, 1, 0], labels)
ax.set_ylim(-0.55, 3.58)
ax.set_xlim(-0.018, 0.307)
ax.set_xlabel("Expected task-utility difference versus incumbent C")
ax.set_title("Finite-task structural gain; direct head edits fail validation",
              loc="left", fontsize=15, fontweight="bold", pad=20)
ax.grid(axis="x", color="#edf0f2", linewidth=0.8)
ax.set_axisbelow(True)
ax.spines[["top", "right", "left"]].set_visible(False)
ax.tick_params(axis="y", length=0, pad=12)
ax.legend(loc="lower right", frameon=False, fontsize=9)
fig.supxlabel("Five paired fitted checkpoints · four Bonferroni-adjusted 95% intervals\n"
              "All direct/gradient/random candidates restored to C. OOD distribution was exposed during validation.",
              fontsize=9, color="#4d535b")
destination = Path(__file__).parent
for extension in ("png", "svg", "pdf"):
    metadata = {"Creator": "Hepta WSP retained-record plot"}
    if extension == "svg":
        metadata["Date"] = None
    elif extension == "pdf":
        metadata.update({"CreationDate": None, "ModDate": None})
    fig.savefig(destination / ("primary_contrasts."+extension), dpi=180, metadata=metadata)
record = {"schema": "hepta.wsp.primary-plot-provenance.v1",
          "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
          "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "matplotlib_version": matplotlib.__version__, "primary_keys": keys,
          "new_model_evaluation": False, "new_statistical_test": False}
(destination / "PROVENANCE.json").write_text(json.dumps(record, indent=2, sort_keys=True)+"\n")
print(json.dumps(record, sort_keys=True))

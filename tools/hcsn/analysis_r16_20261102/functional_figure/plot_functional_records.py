"""Render archived f52 records; this script never imports or evaluates a model."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


parser = argparse.ArgumentParser()
parser.add_argument("--records-dir", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
args = parser.parse_args()
expected = {
    "two-layer-audit.json.gz": "8b9b02b39e55ec60e4ad79787862c03510c247aae354d4b8e3bdfc86d91b28f8",
    "two-layer-training.json.gz": "4685ce7b0deac4d006e469565cd758238f6ef8d550af4f6fa060a9789038d7c1",
}
records = {}
for name, digest in expected.items():
    data = (args.records_dir / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"Unexpected source identity: {name}")
    records[name] = json.loads(gzip.decompress(data))
audit = records["two-layer-audit.json.gz"]
training = records["two-layer-training.json.gz"]
initial = np.asarray(training["history"][0]["trajectory"]["layer2"]["boundary"])
final = np.asarray(training["final_trajectory"]["layer2"]["boundary"])
boundaries = [initial[:16], final[:16]]
delta = [values - values[0] for values in boundaries]
loss = [item["loss_before_update"] for item in training["history"]]
loss.append(training["final_loss"])
modes = ["full", "drive_only", "conditioning_only", "both_detached"]
norms = [float(np.linalg.norm(audit["modes"][mode]["actual"]["raw1"])) for mode in modes]
if initial.shape != (17, 8) or final.shape != (17, 8) or len(loss) != 13:
    raise ValueError("Unexpected archived trajectory layout")
if norms[-1] != 0:
    raise ValueError("The archived detached control is not zero")

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.spines.top": False, "axes.spines.right": False})
fig, axs = plt.subplots(2, 2, figsize=(11.6, 8.4))
fig.subplots_adjust(left=.09, right=.97, bottom=.10, top=.83, hspace=.60, wspace=.27)
fig.suptitle("Hepta: two-layer continuous boundary flow", x=.09, ha="left", y=.97,
             fontsize=20, fontweight="bold", color="#152238")
fig.text(.09, .91, "Actual archived CI records | 2 cells, 8 sequences, 16 Euler steps, 18 trainable parameters",
         fontsize=10.5, color="#44546a")
limit = max(float(np.abs(values).max()) for values in delta) * 1.15
colors = plt.get_cmap("tab10").colors[:8]
for ax, values, absolute, title in zip(
        axs[0], delta, boundaries, ["A  Before training", "B  After 12 updates"], strict=True):
    for sample in range(8):
        ax.plot(np.arange(16) * .05, values[:, sample], color=colors[sample],
                linewidth=1.8, label=f"S{sample + 1}")
    ax.axhline(0, color="#9fa9b6", linewidth=.7, zorder=0)
    ax.set(xlim=(0, .75), ylim=(-limit, limit), xlabel="Time within rollout (model units)",
           ylabel=r"Boundary movement $b_2(t)-b_2(0)$")
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=13)
    ax.text(0, 1.02, f"Used boundary range: [{absolute.min():.5f}, {absolute.max():.5f}]",
            transform=ax.transAxes, fontsize=8.6, color="#526277")
    ax.grid(alpha=.13)
axs[0, 1].legend(ncol=4, loc="lower left", fontsize=7.4, frameon=False,
                 handlelength=1.2, columnspacing=.7)

ax = axs[1, 0]
ax.plot(np.arange(13), loss, color="#245b91", marker="o", markersize=4, linewidth=2)
ax.set(xlim=(-.3, 12.3), ylim=(0, max(loss) * 1.13),
       xlabel="Completed optimizer updates", ylabel="Fixed training-set terminal loss")
ax.set_xticks([0, 3, 6, 9, 12])
ax.set_title("C  Training observation", loc="left", fontsize=12, fontweight="bold", pad=13)
decrease = 100 * (loss[0] - loss[-1]) / loss[0]
ax.text(.04, .58, f"{loss[0]:.8f}  →  {loss[-1]:.8f}\n{decrease:.4f}% decrease\nNo held-out quality comparison",
        transform=ax.transAxes, color="#293a50", fontsize=10, linespacing=1.7)
ax.grid(alpha=.13)

ax = axs[1, 1]
ax.bar(np.arange(3), norms[:3], color=["#233a59", "#4388b9", "#c5704b"], width=.6)
ax.set_yscale("log")
ax.set(ylim=(1e-7, 1.5e-3), ylabel="First-layer parameter-gradient L2 norm")
ax.set_xticks(np.arange(3), ["Both routes", "Drive only", "Conditioning only"])
ax.set_title("D  Same forward values, different gradient routes", loc="left",
             fontsize=11.2, fontweight="bold", pad=13)
for index, value in enumerate(norms[:3]):
    ax.text(index, value * 1.25, f"{value:.3e}", ha="center", fontsize=9)
ax.text(.04, .06, "Both detached: exactly 0\nNorm ratios are not fractions of task benefit",
        transform=ax.transAxes, fontsize=8.8, color="#526277", linespacing=1.6,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": .96, "pad": 4})
ax.grid(axis="y", alpha=.13)
fig.text(.09, .025,
         "Source: f52dc359 / CI job 125027835819. Record-only plot; no new model calls. "
         "Boundary panels use only the 16 steps that drive dynamics.",
         fontsize=8, color="#526277")
args.output_dir.mkdir(parents=True, exist_ok=True)
outputs = {}
for extension in ("png", "svg"):
    path = args.output_dir / f"FUNCTIONAL_EVIDENCE.{extension}"
    fig.savefig(path, dpi=175, facecolor="white")
    raw = path.read_bytes()
    outputs[path.name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
plt.close(fig)
receipt = {
    "schema": "hcsn.archived-record-figure.v1",
    "source_head": "f52dc359344cd0eb9b5dba84d4af3d5815aeb629",
    "source_job": 125027835819,
    "source_sha256": expected,
    "used_time_indices": list(range(16)),
    "boundary_panel_definition": "Each sequence minus its own initial boundary; no interpolation or selected sequence exclusion.",
    "loss_history": loss,
    "gradient_modes": dict(zip(modes, norms, strict=True)),
    "new_financial_calls": 0,
    "new_network_rollouts": 0,
    "new_optimizer_updates": 0,
    "limits": "Descriptive frozen functional records, not held-out quality, causal benefit, sparse spiking or scaling evidence.",
    "outputs": outputs,
}
(args.output_dir / "FIGURE_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({"outputs": outputs, "new_model_calls": 0}))

"""Independent posthoc check of one completed development fit; no training."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import numpy as np
import torch

started, cpu_started = time.monotonic(), time.process_time()
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
BASE = Path("/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training")
SOURCE = BASE / "run-source-v1"
FIT = BASE / "campaign-v1/gru-s101-lr0.001"
OUT = Path("/home/qian-qi/hepta-hcsn-independent-review-20261110-c385-v1")
OUT.mkdir(parents=True, exist_ok=False)
if "REVIEW_SOURCE" in globals():
    (OUT / "review_first_fit.py").write_text(REVIEW_SOURCE)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

inputs = {str(p): sha(p) for p in (
    BASE / "campaign-v1-plan.json", FIT / "plan.json", FIT / "result.json",
    FIT / "initial.pt", FIT / "best.pt", FIT / "last.pt",
    FIT / "development_logits.pt", FIT / "events.jsonl")}
fit_plan = json.loads((FIT / "plan.json").read_bytes())
report = json.loads((FIT / "result.json").read_bytes())
prepared = Path(fit_plan["prepared"])
data_manifest = prepared / "data-manifest.json"
assert sha(data_manifest) == fit_plan["manifest_sha256"]
inputs[str(data_manifest)] = sha(data_manifest)
manifest = json.loads(data_manifest.read_bytes())
assert manifest["mode"] == "all-development"
assert manifest["confirmation_access"] is False
episodes, seen = [], set()
for entry in manifest["episodes"]:
    if entry["partition"] != "dev":
        continue
    path = (prepared / entry["path"]).resolve()
    assert path.is_relative_to(prepared.resolve())
    assert sha(path) == entry["sha256"]
    inputs[str(path)] = sha(path)
    row = json.loads(path.read_bytes())
    assert row["id"] == entry["id"] and row["id"] not in seen
    assert row["partition"] == "dev" and row["sequence"].startswith("D")
    assert len(row["y"]) == entry["events"]
    assert row["dt"] == [tick / 10000000 for tick in row["delta_ticks"]]
    assert all(type(y) is int and 0 <= y < 11 for y in row["y"])
    seen.add(row["id"])
    episodes.append(row)

stored = torch.load(FIT / "development_logits.pt", weights_only=True, map_location="cpu")
labels = np.array([y for row in episodes for y in row["y"]], dtype=np.int64)
assert stored["episode_ids"] == [row["id"] for row in episodes]
assert np.array_equal(stored["labels"].numpy(), labels)
logits = stored["logits"].numpy()
assert logits.shape == (len(labels), 11) and np.isfinite(logits).all()

# Independent metric implementation: NumPy reductions and indexed confusion
# accumulation, with no import of the trainer's metrics helper.
shifted = logits - logits.max(axis=1, keepdims=True)
log_prob = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
probabilities = np.exp(log_prob)
predictions = np.argmax(logits, axis=1)
confusion = np.zeros((11, 11), dtype=np.int64)
np.add.at(confusion, (labels, predictions), 1)
support, predicted, correct = confusion.sum(1), confusion.sum(0), confusion.diagonal()
denominator = support + predicted
f1 = np.divide(2 * correct, denominator, out=np.zeros(11), where=denominator > 0)
confidence = probabilities.max(axis=1)
bins = np.minimum(14, np.floor(confidence * 15).astype(int))
ece = 0.0
for index in range(15):
    selected = bins == index
    if np.any(selected):
        ece += selected.mean() * abs(confidence[selected].mean() - (predictions[selected] == labels[selected]).mean())
onehot = np.eye(11)[labels]
metrics = {
    "events": len(labels), "accuracy": float(np.mean(predictions == labels)),
    "macro_f1_11_classes": float(f1.mean()),
    "macro_f1_present_classes": float(f1[support > 0].mean()),
    "balanced_accuracy_present_classes": float(np.mean(correct[support > 0] / support[support > 0])),
    "nll": float(-log_prob[np.arange(len(labels)), labels].mean()),
    "brier_half_sum": float(0.5 * np.square(probabilities - onehot).sum(axis=1).mean()),
    "brier_mean_classes": float(np.square(probabilities - onehot).mean()),
    "ece_15_equal_width_bins": float(ece), "confusion_matrix": confusion.tolist(),
}
metric_differences = {key: abs(value - report["selected_development"][key])
    for key, value in metrics.items() if key != "confusion_matrix"}
assert metrics["confusion_matrix"] == report["selected_development"]["confusion_matrix"]

initial = torch.load(FIT / "initial.pt", weights_only=True, map_location="cpu")
best = torch.load(FIT / "best.pt", weights_only=True, map_location="cpu")
last = torch.load(FIT / "last.pt", weights_only=True, map_location="cpu")
common = [name for name in initial if name.startswith(("frontend.", "head."))]
assert common
common_comparisons = {checkpoint: {name: torch.equal(value["model"][name], initial[name])
    for name in common} for checkpoint, value in (("best", best), ("last", last))}
changed_core = [name for name in initial if name.startswith("core.")
    and not torch.equal(initial[name], best["model"][name])]

# Load the exact frozen candidate implementation, but rebuild batches and the
# evaluation loop here instead of invoking any training/evaluation function.
sys.path.insert(0, str(SOURCE / "proposals/localization-v3"))
from cores import CoreStudyModel
model = CoreStudyModel(fit_plan["arm"], width=fit_plan["width"], seed=fit_plan["seed"],
    s4_repo=fit_plan.get("s4_repo"), active_cells=fit_plan["active_cells"],
    freeze_shared=not fit_plan["train_shared"])
model.load_state_dict(best["model"], strict=True)
model.eval()
recomputed = []
with torch.no_grad():
    for start in range(0, len(episodes), fit_plan["batch_size"]):
        group = episodes[start:start + fit_plan["batch_size"]]
        length = max(len(row["y"]) for row in group)
        x = torch.zeros(len(group), length, 25, dtype=torch.float64)
        dt = torch.zeros(len(group), length, dtype=torch.float64)
        for index, row in enumerate(group):
            x[index, :len(row["y"])] = torch.tensor(row["x"], dtype=torch.float64)
            dt[index, :len(row["y"])] = torch.tensor(row["dt"], dtype=torch.float64)
        values = model(x, dt)
        for index, row in enumerate(group):
            recomputed.append(values[index, :len(row["y"])] )
recomputed = torch.cat(recomputed)
maximum_logit_difference = float((recomputed - stored["logits"]).abs().max())
torch.save({"logits": recomputed, "labels": torch.from_numpy(labels),
    "episode_ids": [row["id"] for row in episodes]}, OUT / "recomputed-development-logits.pt")

source_comparisons = {path: Path(path).is_file() and sha(path) == digest
    for path, digest in report["source_before"].items()}
ledger = [json.loads(line) for line in (FIT / "events.jsonl").read_text().splitlines()]
main_done = [event for event in ledger if event["kind"] == "optimizer_completed" and event["phase"] == "main"]
diagnostic_done = [event for event in ledger if event["kind"] == "optimizer_completed" and event["phase"] == "diagnostic"]
epochs_done = [event for event in ledger if event["kind"] == "epoch_completed"]
inputs_after = {path: sha(path) for path in inputs}
passed = (maximum_logit_difference <= 2e-12 and max(metric_differences.values()) <= 2e-12
    and all(all(values.values()) for values in common_comparisons.values())
    and all(source_comparisons.values()) and inputs == inputs_after
    and len(main_done) == report["main_updates"] and len(diagnostic_done) == report["diagnostic_updates"]
    and len(epochs_done) == len(report["epochs"]) and bool(changed_core))
result = {
    "schema": "hcsn-independent-development-reproduction-v1",
    "created_utc": datetime.now(timezone.utc).isoformat(),
    "reviewer": "/root/math_contract", "fit": str(FIT), "candidate_source": str(SOURCE),
    "scope": "One completed ABC/D development fit; no E data, campaign-wide adequacy, HCSN benefit or formal admission.",
    "scientific_admission": "HOLD", "confirmation_access": False,
    "fit_reported_status": report["status"], "fit_reported_training_adequacy": report["training_adequacy_established"],
    "fit_stop_reason": report.get("stop_reason"), "selected_epoch": report["best_epoch"],
    "fit_epochs": len(report["epochs"]), "fit_main_updates": report["main_updates"],
    "fit_diagnostic_updates": report["diagnostic_updates"],
    "input_sha256": inputs, "inputs_unchanged": inputs == inputs_after,
    "source_sha256": report["source_before"], "source_matches_fit": source_comparisons,
    "review_source_sha256": sha(OUT / "review_first_fit.py") if (OUT / "review_first_fit.py").exists() else None,
    "recomputed_logits_sha256": sha(OUT / "recomputed-development-logits.pt"),
    "maximum_logit_absolute_difference": maximum_logit_difference,
    "independent_metrics": metrics, "absolute_metric_differences": metric_differences,
    "common_tensor_equality": common_comparisons, "changed_core_tensors": changed_core,
    "development_episodes": len(episodes), "development_events": len(labels),
    "ledger_completed_main_updates": len(main_done), "ledger_completed_diagnostic_updates": len(diagnostic_done),
    "ledger_completed_epochs": len(epochs_done),
    "python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__,
    "review_wall_seconds": time.monotonic() - started,
    "review_cpu_seconds": time.process_time() - cpu_started,
    "review_energy_joules": None, "passed": passed,
}
with (OUT / "RESULT.json").open("x") as stream:
    json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
    stream.write("\n")
print(json.dumps({key: result[key] for key in ("passed", "fit_reported_status", "fit_reported_training_adequacy", "fit_epochs", "development_events", "maximum_logit_absolute_difference", "independent_metrics", "review_wall_seconds")}, sort_keys=True))
print(json.dumps({"result_path": str(OUT / "RESULT.json"), "result_sha256": sha(OUT / "RESULT.json")}))
raise SystemExit(0 if passed else 1)

"""Independent raw-36 development audit; never trains or edits a candidate."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

os.environ.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                  CUDA_VISIBLE_DEVICES="", PYTHONDONTWRITEBYTECODE="1")
import numpy as np
import torch

STARTED, CPU_STARTED = time.monotonic(), time.process_time()
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
BASE = Path("/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training")
CANDIDATE = BASE / "run-source-v1"
CAMPAIGN = BASE / "campaign-v1"
OUT = Path("/home/qian-qi/hepta-hcsn-independent-campaign-review-20261110-c385-v1")
OUT.mkdir(parents=True, exist_ok=False)
if "REVIEW_SOURCE" in globals():
    (OUT / "review_campaign_raw36.py").write_text(REVIEW_SOURCE)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def artifact(path):
    return {"bytes": path.stat().st_size, "sha256": sha(path)}


def tensor_digest(state, prefix):
    digest = hashlib.sha256()
    for name, value in sorted(state.items()):
        if name.startswith(prefix):
            digest.update(name[len(prefix):].encode())
            digest.update(str((tuple(value.shape), value.dtype)).encode())
            digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def independent_metrics(logits, labels):
    shifted = logits - logits.max(axis=1, keepdims=True)
    logp = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
    probabilities = np.exp(logp)
    predictions = logits.argmax(1)
    matrix = np.zeros((11, 11), dtype=np.int64)
    np.add.at(matrix, (labels, predictions), 1)
    support, predicted, correct = matrix.sum(1), matrix.sum(0), matrix.diagonal()
    f1 = np.divide(2 * correct, support + predicted, out=np.zeros(11), where=support + predicted > 0)
    confidence = probabilities.max(1)
    bins = np.minimum(14, np.floor(confidence * 15).astype(int))
    ece = 0.
    for index in range(15):
        selected = bins == index
        if selected.any():
            ece += selected.mean() * abs(confidence[selected].mean() - (predictions[selected] == labels[selected]).mean())
    squared = np.square(probabilities - np.eye(11)[labels])
    return {"events": len(labels), "accuracy": float(np.mean(predictions == labels)),
        "macro_f1_11_classes": float(f1.mean()), "macro_f1_present_classes": float(f1[support > 0].mean()),
        "balanced_accuracy_present_classes": float(np.mean(correct[support > 0] / support[support > 0])),
        "nll": float(-logp[np.arange(len(labels)), labels].mean()),
        "brier_half_sum": float(.5 * squared.sum(1).mean()), "brier_mean_classes": float(squared.mean()),
        "ece_15_equal_width_bins": float(ece), "confusion_matrix": matrix.tolist()}


input_hashes = {}
for filename in ("RESULT.json", "commands.jsonl", "locked-plan.json", "source-manifest.json"):
    path = CAMPAIGN / filename
    input_hashes[str(path)] = sha(path)
plan = json.loads((CAMPAIGN / "locked-plan.json").read_bytes())
campaign = json.loads((CAMPAIGN / "RESULT.json").read_bytes())
commands = [json.loads(line) for line in (CAMPAIGN / "commands.jsonl").read_text().splitlines()]
expected_names = [f"{arm}-s{seed}-lr{lr:g}" for seed in plan["seeds"]
                  for lr in plan["learning_rates"] for arm in plan["arms"]]
assert len(expected_names) == 36 and len(set(expected_names)) == 36
assert sorted(row["name"] for row in campaign["attempts"]) == sorted(expected_names)
assert campaign["confirmation_access"] is False and campaign["scientific_admission"] == "HOLD"
attempts = {row["name"]: row for row in campaign["attempts"]}

prepared = Path(plan["prepared"]).resolve()
manifest_path = prepared / "data-manifest.json"
assert sha(manifest_path) == plan["manifest_sha256"]
input_hashes[str(manifest_path)] = sha(manifest_path)
manifest = json.loads(manifest_path.read_bytes())
assert manifest["mode"] == "all-development" and manifest["confirmation_access"] is False
for filename, key in (("frontend.json", "frontend_sha256"), ("selection.json", "selection_sha256")):
    path = prepared / filename
    assert sha(path) == manifest[key]
    input_hashes[str(path)] = sha(path)
episodes, training_events, data_files = [], {}, {}
for entry in manifest["episodes"]:
    path = (prepared / entry["path"]).resolve()
    assert path.is_relative_to(prepared)
    assert sha(path) == entry["sha256"]
    input_hashes[str(path)] = sha(path)
    data_files[entry["path"]] = artifact(path)
    row = json.loads(path.read_bytes())
    assert row["id"] == entry["id"] and row["partition"] == entry["partition"]
    assert len(row["y"]) == entry["events"]
    assert all(type(y) is int and 0 <= y < 11 for y in row["y"])
    if entry["partition"] == "dev":
        assert row["sequence"].startswith("D")
        assert row["dt"] == [tick / 10000000 for tick in row["delta_ticks"]]
        episodes.append(row)
    else:
        assert entry["partition"] == "train" and row["sequence"][0] in "ABC"
        assert row["id"] not in training_events
        training_events[row["id"]] = len(row["y"])
labels = np.array([y for row in episodes for y in row["y"]], dtype=np.int64)
episode_ids = [row["id"] for row in episodes]
assert len(labels) == 31952 and sum(training_events.values()) == 89216


def check_journal(path, report):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    completed = {phase: [] for phase in ("main", "diagnostic")}
    started = Counter()
    epochs, current_order, visited, pending = [], None, [], None
    for event in rows:
        if event["kind"] == "epoch_started":
            assert current_order is None
            current_order, visited = event["episode_order"], []
            assert len(current_order) == len(training_events) and set(current_order) == set(training_events)
        elif event["kind"] == "update_started":
            assert pending is None
            pending = event
            started[event["phase"]] += 1
            assert all(item in training_events for item in event["episode_ids"])
            if event["phase"] == "main":
                assert current_order is not None
                visited.extend(event["episode_ids"])
        elif event["kind"] == "optimizer_completed":
            assert pending is not None and pending["phase"] == event["phase"]
            assert event["events"] == sum(training_events[item] for item in pending["episode_ids"])
            completed[event["phase"]].append(event["number"])
            pending = None
        elif event["kind"] == "epoch_completed":
            assert visited == current_order
            assert event["events"] == sum(training_events.values())
            epochs.append(event["epoch"])
            current_order, visited = None, []
    for phase in completed:
        assert completed[phase] == list(range(1, report[phase + "_updates"] + 1))
    assert epochs == list(range(1, len(report["epochs"]) + 1))
    if report["status"] == "completed_development":
        assert pending is None and current_order is None
        assert all(started[phase] == len(completed[phase]) for phase in completed)
    return {"main_updates": len(completed["main"]), "diagnostic_updates": len(completed["diagnostic"]),
            "completed_epochs": len(epochs), "every_completed_epoch_is_complete_abc": True,
            "partial_update_retained": pending is not None}


def fresh_forward(fit_plan, state):
    sys.path.insert(0, str(CANDIDATE / "proposals/localization-v3"))
    from cores import CoreStudyModel
    model = CoreStudyModel(fit_plan["arm"], width=fit_plan["width"], seed=fit_plan["seed"],
        s4_repo=fit_plan.get("s4_repo"), active_cells=fit_plan["active_cells"],
        freeze_shared=not fit_plan["train_shared"])
    model.load_state_dict(state, strict=True)
    model.eval()
    outputs = []
    with torch.no_grad():
        for start in range(0, len(episodes), fit_plan["batch_size"]):
            group = episodes[start:start + fit_plan["batch_size"]]
            length = max(len(row["y"]) for row in group)
            x = torch.zeros(len(group), length, 25, dtype=torch.float64)
            dt = torch.zeros(len(group), length, dtype=torch.float64)
            for index, row in enumerate(group):
                x[index, :len(row["y"])] = torch.tensor(row["x"], dtype=torch.float64)
                dt[index, :len(row["y"])] = torch.tensor(row["dt"], dtype=torch.float64)
            value = model(x, dt)
            outputs.extend(value[index, :len(row["y"])] for index, row in enumerate(group))
    return torch.cat(outputs)


records, checked_forward_arms, shared_by_seed, source_hashes = [], set(), {}, {}
for name in expected_names:
    fit = CAMPAIGN / name
    row = {"name": name, "audit_status": "started", "fresh_forward": False}
    try:
        report = json.loads((fit / "result.json").read_bytes())
        fit_plan = json.loads((fit / "plan.json").read_bytes())
        row.update(arm=report["arm"], seed=report["seed"], learning_rate=fit_plan["learning_rate"],
            original_fit_status=report["status"], original_training_adequacy=report["training_adequacy_established"],
            original_stop_reason=report.get("stop_reason"), original_selected_epoch=report.get("best_epoch"))
        assert f"{report['arm']}-s{report['seed']}-lr{fit_plan['learning_rate']:g}" == name
        assert fit_plan["manifest_sha256"] == plan["manifest_sha256"] and not fit_plan["train_shared"]
        assert report["source_before"] == report["source_after"] and report["source_unchanged"] is True
        for path, expected in report["source_before"].items():
            assert sha(path) == expected
            if path in source_hashes:
                assert source_hashes[path] == expected
            source_hashes[path] = expected
        row["source_manifest_sha256"] = canonical_sha(report["source_before"])
        row["files"] = {p.name: artifact(p) for p in sorted(fit.iterdir()) if p.is_file()}
        for filename, value in row["files"].items():
            input_hashes[str(fit / filename)] = value["sha256"]
        row["outer_logs"] = {}
        for suffix in ("stdout", "stderr"):
            log_path = CAMPAIGN / (name + "." + suffix)
            row["outer_logs"][suffix] = artifact(log_path)
            assert sha(log_path) == attempts[name][suffix + "_sha256"]
            input_hashes[str(log_path)] = sha(log_path)
        assert sha(fit / "result.json") == attempts[name]["result_sha256"]
        assert sha(fit / "events.jsonl") == report["events_sha256"]
        row["journal"] = check_journal(fit / "events.jsonl", report)
        command_rows = [event for event in commands if event["name"] == name]
        assert len(command_rows) == 2 and command_rows[0]["status"] == "started"
        assert command_rows[-1]["status"] == attempts[name]["status"]
        row["outer_attempt_rows"] = len(command_rows)
        if report["status"] != "completed_development":
            row.update(audit_status="retained_original_failed_attempt", metrics_available=False)
            records.append(row)
            continue
        for filename, key in (("initial.pt", "initialization_sha256"), ("best.pt", "best_checkpoint_sha256"), ("last.pt", "last_checkpoint_sha256")):
            assert sha(fit / filename) == report[key]
        initial = torch.load(fit / "initial.pt", weights_only=True, map_location="cpu")
        best = torch.load(fit / "best.pt", weights_only=True, map_location="cpu")["model"]
        last = torch.load(fit / "last.pt", weights_only=True, map_location="cpu")["model"]
        common_keys = [key for key in initial if key.startswith(("frontend.", "head."))]
        equal = {point: all(torch.equal(initial[key], values[key]) for key in common_keys)
                 for point, values in (("best", best), ("last", last))}
        assert all(equal.values())
        shared = {part: tensor_digest(initial, part + ".") for part in ("frontend", "head")}
        assert shared["frontend"] == report["initial_frontend_sha256"]
        assert shared["head"] == report["initial_head_sha256"]
        if report["seed"] in shared_by_seed:
            assert shared_by_seed[report["seed"]] == shared
        else:
            shared_by_seed[report["seed"]] = shared
        row.update(shared_initial_hashes=shared, common_tensors_unchanged=equal)
        stored = torch.load(fit / "development_logits.pt", weights_only=True, map_location="cpu")
        assert stored["episode_ids"] == episode_ids and np.array_equal(stored["labels"].numpy(), labels)
        logits = stored["logits"].numpy()
        assert logits.shape == (len(labels), 11) and np.isfinite(logits).all()
        metrics = independent_metrics(logits, labels)
        assert metrics["confusion_matrix"] == report["selected_development"]["confusion_matrix"]
        differences = {key: abs(value - report["selected_development"][key]) for key, value in metrics.items() if key != "confusion_matrix"}
        assert max(differences.values()) <= 2e-12
        row.update(independent_metrics=metrics, absolute_metric_differences=differences, metrics_available=True)
        if report["arm"] not in checked_forward_arms:
            forward_started = time.monotonic()
            recomputed = fresh_forward(fit_plan, best)
            error = float((recomputed - stored["logits"]).abs().max())
            assert error <= 2e-12
            destination = OUT / ("fresh-forward-" + report["arm"] + ".pt")
            torch.save({"logits": recomputed, "labels": torch.from_numpy(labels), "episode_ids": episode_ids}, destination)
            row.update(fresh_forward=True, maximum_logit_absolute_difference=error,
                fresh_forward_file=destination.name, fresh_forward_sha256=sha(destination),
                fresh_forward_seconds=time.monotonic() - forward_started)
            checked_forward_arms.add(report["arm"])
        row["audit_status"] = "passed_completed_fit"
    except Exception:
        row.update(audit_status="audit_failed", error=traceback.format_exc())
    records.append(row)
    print(json.dumps({key: row.get(key) for key in ("name", "audit_status", "original_training_adequacy", "fresh_forward")}), flush=True)

source_unchanged = all(sha(path) == digest for path, digest in source_hashes.items())
inputs_unchanged = all(sha(path) == digest for path, digest in input_hashes.items())
complete = len(records) == 36 and all(row["audit_status"] != "audit_failed" for row in records)
passed = complete and source_unchanged and inputs_unchanged
report = {"schema": "hcsn-independent-raw36-audit-v1", "created_utc": datetime.now(timezone.utc).isoformat(),
    "reviewer": "/root/math_contract", "candidate_source": str(CANDIDATE), "campaign": str(CAMPAIGN),
    "records": records, "expected_attempts": 36, "source_sha256": source_hashes,
    "input_sha256": input_hashes, "episode_files": data_files,
    "shared_weights_by_seed": shared_by_seed, "source_unchanged": source_unchanged,
    "inputs_unchanged": inputs_unchanged, "development_episodes": len(episodes),
    "development_events": len(labels), "train_events": sum(training_events.values()),
    "passed": passed, "scientific_admission": "HOLD", "confirmation_access": False,
    "fresh_forward_arms": sorted(checked_forward_arms), "numpy": np.__version__, "torch": torch.__version__,
    "review_wall_seconds_after_imports": time.monotonic() - STARTED,
    "review_cpu_seconds_after_imports": time.process_time() - CPU_STARTED, "review_energy_joules": None,
    "scope": "Metrics and original raw shared-weight/ledger integrity for all available completed attempts; one fresh forward per core. This does not grant training adequacy, E confirmation or HCSN benefit."}
(OUT / "RESULT.json").write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
summary = {"schema": report["schema"], "passed": passed, "expected_attempts": 36,
    "audit_status_counts": dict(Counter(row["audit_status"] for row in records)),
    "original_training_adequacy_passes": sum(row.get("original_training_adequacy", False) for row in records),
    "fresh_forward_arms": report["fresh_forward_arms"], "source_unchanged": source_unchanged,
    "inputs_unchanged": inputs_unchanged, "scientific_admission": "HOLD", "confirmation_access": False,
    "result_sha256": sha(OUT / "RESULT.json"), "review_wall_seconds_after_imports": report["review_wall_seconds_after_imports"],
    "fits": [{key: row.get(key) for key in ("name", "audit_status", "original_training_adequacy", "fresh_forward", "maximum_logit_absolute_difference")} for row in records]}
(OUT / "SUMMARY.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
files = {str(p.relative_to(OUT)): artifact(p) for p in sorted(OUT.rglob("*")) if p.is_file()}
(OUT / "MANIFEST.json").write_text(json.dumps({"files": files, "scope": report["scope"]}, sort_keys=True, indent=2) + "\n")
archive = Path(str(OUT) + ".zip")
with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=9) as zipped:
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            info = ZipInfo(str(path.relative_to(OUT)), (1980, 1, 1, 0, 0, 0))
            info.create_system, info.external_attr, info.compress_type = 3, 0o100644 << 16, ZIP_DEFLATED
            zipped.writestr(info, path.read_bytes(), compresslevel=9)
with ZipFile(archive) as zipped:
    assert zipped.testzip() is None and len(zipped.namelist()) == len(set(zipped.namelist()))
export = {"archive": str(archive), **artifact(archive), "result_sha256": summary["result_sha256"],
          "summary_sha256": sha(OUT / "SUMMARY.json"), "manifest_sha256": sha(OUT / "MANIFEST.json")}
(OUT / "ARCHIVE.json").write_text(json.dumps(export, sort_keys=True, indent=2) + "\n")
print(json.dumps({"summary": str(OUT / "SUMMARY.json"), "passed": passed, "archive": export}), flush=True)
raise SystemExit(0 if passed else 1)

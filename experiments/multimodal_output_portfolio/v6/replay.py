"""Replay a completed census from frozen checkpoints without training or tuning.

The original remains read-only. Every accepted replay row must preserve its
original actions, decisions, latent state, emitted bytes, observed metrics and
modeled work. Physical timings and native receipts are freshly measured. The
current four-slot contract is added without inventing unsupported media.
"""

import argparse
from copy import deepcopy
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time
import traceback

import torch

from .data import load_corpus
from .forecast import ForecastBundle
from .joint_contract import PROFILE, bind_v6_output, require_v6_capabilities
from .observer import METRIC_DIGEST, Recognizer, observe_tensors, read_bundle, write_bundle
from .plan_training import ControlledSnapshot
from .reporting import evaluate_native, owner_tsv, summarize
from .run import canonical, case_batch, digest, rollout, source_identity, write_json


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare_original(original, trace, metrics, hashes):
    """Timing changes are allowed; all policy and quality observations are exact."""
    for name in ("actions", "initial_content_plan", "decisions", "calls", "final_state_sha256"):
        if trace[name] != original[name]:
            raise ValueError(f"Replay changed original {name}")
    for name in ("modeled_work", "search_units", "execution_units"):
        if trace["cost"][name] != original["cost"][name]:
            raise ValueError(f"Replay changed original {name}")
    if hashes != original["output_hashes"] or metrics != original["metrics"]:
        raise ValueError("Replay changed emitted bytes or independently observed metrics")


def paired_timing_summary(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in ("training", "policy", "split", "budget"))].append(row)
    result = []
    for key, group in sorted(groups.items()):
        timing = {}
        for field in ("wall_ns", "cpu_ns", "inference_ns", "controller_ns", "observer_ns"):
            original = [row["original_cost"][field] for row in group]
            replayed = [row["cost"][field] for row in group]
            old_mean, new_mean = statistics.fmean(original), statistics.fmean(replayed)
            timing[field] = {"original_mean": old_mean, "replay_mean": new_mean,
                             "mean_paired_difference": statistics.fmean(b - a for a, b in zip(original, replayed)),
                             "original_over_replay_ratio": old_mean / new_mean if new_mean else None}
        result.append(dict(zip(("training", "policy", "split", "budget"), key)) | {"rows": len(group), "timing": timing})
    return {"groups": result,
            "scope": "Complete paired replay census; wall includes writing, reopening and audit observation; timings are descriptive of these executions, not independent randomized hardware benchmarks."}


def replay(original, cache, output, native_binary):
    original, cache, output, native_binary = map(lambda p: Path(p).resolve(),
                                                (original, cache, output, native_binary))
    if output == original or original in output.parents or output in original.parents:
        raise ValueError("Replay output must be separate from the preserved original tree")
    if cache == original or original in cache.parents:
        raise ValueError("Dataset cache must be outside the preserved original tree")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "status.json", {"state": "initializing"})
    rows, native_receipts, last_candidate = [], [], None
    previous_directory, started = Path.cwd(), time.perf_counter_ns()
    try:
        old_status = json.loads((original / "status.json").read_text())
        if old_status.get("state") != "completed":
            raise ValueError("Checkpoint replay requires a completed original run")
        old_protocol = json.loads((original / "protocol.json").read_text())
        old_summary = json.loads((original / "summary.json").read_text())
        if digest(old_summary) != old_status["summary_sha256"] or digest(old_protocol) != old_summary["protocol_sha256"]:
            raise ValueError("Original completed summary/protocol binding changed")
        old_rows = [json.loads(line) for line in (original / "rows.jsonl").read_text().splitlines()]
        required = require_v6_capabilities(old_protocol.get("hard_output_modalities"))
        source = source_identity()
        if source["dirty"]:
            raise ValueError("Replay requires a clean committed source tree")
        for name in ("data.py", "neural.py", "observer.py", "plan_training.py", "control.py"):
            key = "experiments/multimodal_output_portfolio/v6/" + name
            if source["files"][key] != old_protocol["source"]["files"][key]:
                raise ValueError("Replay may not change data, neural dynamics, objective or controller code")
        if old_protocol["source"]["dirty"] or digest(old_protocol["source"]["files"]) != old_protocol["source"]["bundle_sha256"]:
            raise ValueError("Original source identity manifest changed")
        root = Path(__file__).resolve().parents[3]
        subprocess.run(["git", "cat-file", "-e", old_protocol["source"]["git_commit"] + "^{commit}"],
                       cwd=root, check=True, capture_output=True)
        for name, expected in old_protocol["source"]["files"].items():
            committed = subprocess.check_output(["git", "show", old_protocol["source"]["git_commit"] + ":" + name], cwd=root)
            if hashlib.sha256(committed).hexdigest() != expected:
                raise ValueError("Original source artifact differs from declared clean commit")
        os.chdir(original)
        checked = summarize(old_rows, old_protocol)  # Includes every original raw-output hash.
        if checked["rows"] != old_status["rows"] or checked["rows"] != old_summary["rows"]:
            raise ValueError("Original census differs from completed status")
        os.chdir(previous_directory)
        artifact_names = ["protocol.json", "status.json", "summary.json", "rows.jsonl", "training.json",
                          "forecast.json", "observer.json", "audit-observer.pt", "reward-observer.pt", "native-receipts.json"]
        labels = [f"seed-{seed}-{training}" for seed in old_protocol["seeds"] for training in old_protocol["trainings"]]
        artifact_names += [label + suffix for label in labels for suffix in (".pt", "-forecast.pt")]
        (output / "artifacts").mkdir()
        artifacts = {}
        for name in artifact_names:
            path, copied = original / name, output / "artifacts" / name
            expected = file_sha(path)
            shutil.copyfile(path, copied)
            if file_sha(copied) != expected:
                raise ValueError("Checkpoint artifact copy changed bytes")
            artifacts[name] = {"sha256": expected, "copied_path": str(copied.relative_to(output)),
                               "original_relative_path": os.path.relpath(path, output)}
        original_binding = {"original_directory": os.path.relpath(original, output), "artifacts": artifacts,
                            "protocol_sha256": digest(old_protocol), "rows_sha256": artifacts["rows.jsonl"]["sha256"],
                            "source": old_protocol["source"], "summary_sha256": old_status["summary_sha256"]}
        write_json(output / "original-manifest.json", original_binding)
        corpus = load_corpus(cache, evaluator_sources=old_protocol["observer_sources"])
        if corpus.manifest["manifest_sha256"] != old_protocol["dataset_manifest"]["manifest_sha256"]:
            raise ValueError("Public-input source corpus differs from original")
        torch.set_num_threads(old_protocol["training"]["threads"])
        torch.use_deterministic_algorithms(True)
        models, forecasts = {}, {}
        for label in labels:
            models[label] = ControlledSnapshot.load(output / "artifacts" / f"{label}.pt")
            forecasts[label] = ForecastBundle.load(output / "artifacts" / f"{label}-forecast.pt")
            if forecasts[label].snapshot_digest != models[label].fingerprint:
                raise ValueError("Forecast checkpoint belongs to another model")
        observer_report = json.loads((output / "artifacts/observer.json").read_text())
        for name in ("audit", "reward"):
            if artifacts[f"{name}-observer.pt"]["sha256"] != observer_report["weights_sha256"][name]:
                raise ValueError("Original observer metadata differs from frozen weights")
        audit = Recognizer()
        audit.load_state_dict(torch.load(output / "artifacts/audit-observer.pt", map_location="cpu", weights_only=True), strict=True)
        audit.eval().requires_grad_(False)
        if old_protocol["metric_sha256"] != METRIC_DIGEST:
            raise ValueError("Replay metric differs from frozen original objective")
        protocol = {**deepcopy(old_protocol), "mode": "frozen_checkpoint_identity_replay",
                    "source": source, "joint_contract": PROFILE,
                    "native_binary_sha256": file_sha(native_binary),
                    "replay": {"original_manifest_sha256": digest(original_binding),
                               "original_protocol_sha256": digest(old_protocol),
                               "original_rows_sha256": artifacts["rows.jsonl"]["sha256"],
                               "training_executed": False, "checkpoint_updates": False,
                               "execution_order": "exact original rows.jsonl order",
                               "acceptance": "exact policy/state/output/metric/modeled-cost equality; physical timings remeasured"}}
        write_json(output / "protocol.json", protocol)
        write_json(output / "status.json", {"state": "running", "protocol_sha256": digest(protocol)})
        os.chdir(output)
        cases = {(split, item["case_id"]): item for split, entries in protocol["cases"].items() for item in entries}
        batches = {key: case_batch(corpus, key[0], item["index"], item["corruption"]) for key, item in cases.items()}
        if any(list(batch.source_ids[0]) != cases[key]["source_ids"] for key, batch in batches.items()):
            raise ValueError("Reconstructed public cases differ from registered source identities")
        objective_digest = digest({"metric": protocol["metric"], "requirements": ["text", "image"]})
        group = []
        group_key = None
        for old in old_rows:
            label = f"seed-{old['seed']}-{old['training']}"
            snapshot, forecast = models[label], forecasts[label]
            if (old["snapshot_sha256"] != snapshot.fingerprint or old["forecast_sha256"] != forecast.fingerprint
                    or old["observer_sha256"] != observer_report["weights_sha256"]["audit"]
                    or old["reward_observer_sha256"] != observer_report["weights_sha256"]["reward"]):
                raise ValueError("Original row model/forecast/observer binding differs from checkpoint")
            case = cases[(old["split"], old["case_id"])]
            batch = batches[(old["split"], old["case_id"])]
            key = (old["seed"], old["training"], old["split"], old["case_id"], old["budget"])
            if group and key != group_key:
                raise ValueError("Original native episode order is not contiguous")
            group_key = key
            last_candidate = f"{label}-{old['case_id']}-b{old['budget']}-{old['policy']}"
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            pixels, caption, trace = rollout(snapshot, forecast, batch.observation, old["policy"], old["budget"],
                                             protocol, old["case_id"], old["seed"] * 10000 + case["index"])
            paths = write_bundle(output / "outputs" / last_candidate, caption, pixels)
            observed_start = time.perf_counter_ns()
            raw_pixels, raw_caption, hashes = read_bundle(paths)
            joint = bind_v6_output(required, snapshot.fingerprint, trace["final_state_sha256"],
                                  trace["latent_sha256"], hashes, old["case_id"])
            metrics = observe_tensors(audit, raw_pixels, [raw_caption], batch.target.pixels, batch.target.labels)[0]
            trace["cost"]["observer_ns"] = time.perf_counter_ns() - observed_start
            trace["cost"]["inference_ns"] = trace["cost"]["wall_ns"]
            trace["cost"]["wall_ns"] = time.perf_counter_ns() - wall
            trace["cost"]["cpu_ns"] = time.process_time_ns() - cpu
            compare_original(old, trace, metrics, hashes)
            row = {**{k: v for k, v in old.items() if k != "receipt_sha256"}, **trace,
                   "metrics": metrics, "output_hashes": hashes, "joint_output_contract": joint,
                   "output_paths": {k: str(Path(v).relative_to(output)) for k, v in paths.items()},
                   "replay_of_receipt_sha256": old["receipt_sha256"], "original_cost": old["cost"]}
            row["receipt_sha256"] = digest(row)
            rows.append(row)
            group.append(row)
            with (output / "rows.jsonl").open("a") as handle:
                handle.write(canonical(row) + "\n")
            if len(group) == len(protocol["policies"]):
                if {row["policy"] for row in group} != set(protocol["policies"]):
                    raise ValueError("Native episode does not contain every original policy")
                exported = owner_tsv(group, objective_digest, source["bundle_sha256"], METRIC_DIGEST, old["budget"], 60_000_000_000)
                native_start = time.perf_counter_ns()
                receipt = evaluate_native(exported, native_binary)
                receipt.update(adapter_wall_ns=time.perf_counter_ns() - native_start, binary_sha256=protocol["native_binary_sha256"])
                native_receipts.append(receipt)
                with (output / "native-receipts.jsonl").open("a") as handle:
                    handle.write(canonical(receipt) + "\n")
                group = []
            if len(rows) % 140 == 0:
                print(canonical({"replayed_rows": len(rows), "required_rows": len(old_rows)}), flush=True)
        if group or len(rows) != len(old_rows) or len(native_receipts) * len(protocol["policies"]) != len(rows):
            raise ValueError("Replay census or native receipt census is incomplete")
        if source_identity() != source or file_sha(native_binary) != protocol["native_binary_sha256"]:
            raise ValueError("Replay source or native executable changed during execution")
        for name, identity in artifacts.items():
            if file_sha(original / name) != identity["sha256"] or file_sha(output / identity["copied_path"]) != identity["sha256"]:
                raise ValueError("Original or copied checkpoint artifacts changed")
        for old in old_rows:
            for modality, path in old["output_paths"].items():
                if file_sha(original / path) != old["output_hashes"][modality]:
                    raise ValueError("Preserved original output bytes changed during replay")
        for snapshot in models.values():
            snapshot.verify_integrity()
        for forecast in forecasts.values():
            forecast.verify_integrity()
        report = summarize(rows, protocol)
        report.update(source=source, protocol_sha256=digest(protocol), observer=observer_report,
                      native_receipt_count=len(native_receipts), end_to_end_wall_ns=time.perf_counter_ns() - started,
                      paired_replay_timings=paired_timing_summary(rows),
                      environment={"python": sys.version, "torch": torch.__version__, "platform": platform.platform(), "cuda": torch.cuda.is_available()},
                      replay_validation={"original_summary_sha256": old_status["summary_sha256"], "identical_rows": len(rows),
                                         "identical_raw_outputs": 2 * len(rows), "original_execution_order_preserved": True,
                                         "original_artifacts_unchanged": True, "new_physical_cost_only": True,
                                         "original_raw_outputs_unchanged": True,
                                         "training_executed": False, "four_slot_contract": True},
                      energy_joules=None, energy_measurement_available=False)
        write_json(output / "native-receipts.json", native_receipts)
        write_json(output / "summary.json", report)
        write_json(output / "status.json", {"state": "completed", "rows": len(rows), "summary_sha256": digest(report)})
        print(canonical({"completed": str(output), "replayed_rows": len(rows)}), flush=True)
        return report
    except BaseException as error:
        write_json(output / "status.json", {"state": "failed", "rows": len(rows), "last_candidate": last_candidate,
                                            "error": str(error), "traceback": traceback.format_exc()})
        raise
    finally:
        os.chdir(previous_directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "cache", "output", "native-binary"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    replay(args.original, args.cache, args.output, args.native_binary)


if __name__ == "__main__":
    main()

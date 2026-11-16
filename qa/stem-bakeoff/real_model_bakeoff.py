"""Reproduce fixed-checkpoint text learning and resource evidence on real data.

All experiment choices are recorded before model execution. Historical UCI
holdouts score the frozen result; they never select a winner or tune training.
The output demonstrates bounded research execution, not production admission.
"""

import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import time

import psutil
import torch

from cell_head_training import (HeadCohortV1, HeadTrainingConfigV1,
    load_head_artifact, save_head_artifact, train_cell_head)
from prepare_news_cohorts import canonical, load_cohorts, sha
from real_encoder import CANDIDATES, FrozenRealEncoder
from real_head_fanout import SCALES, measure_fanout, validate_fanout_plan


def code_identity():
    root = Path(__file__).parent
    return {p.name: sha(p.read_bytes()) for p in sorted(root.iterdir())
            if p.suffix in (".py", ".json") and not p.name.startswith("test_")}


def model_tensor_digest(model):
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(canonical([name, list(tensor.shape), str(tensor.dtype)]))
        digest.update(memoryview(tensor.reshape(-1).view(torch.uint8).numpy()))
    return digest.hexdigest()


def compact_training_report(result):
    report = result.report
    report["splits"] = {name: {key: value for key, value in split.items()
        if key not in ("source_record_digests", "bundle_digests")}
        for name, split in report["splits"].items()}
    return report


def rss_observation():
    """Read actual process RSS, including PID-isolated executor environments."""
    try:
        lines = Path("/proc/self/status").read_text().splitlines()
    except (OSError, UnicodeError):
        lines = []
    proc_pid = None
    for line in lines:
        fields = line.split()
        if (len(fields) == 2 and fields[0] == "Pid:"
                and fields[1].isascii() and fields[1].isdigit()):
            proc_pid = int(fields[1])
        if (len(fields) == 3 and fields[0] == "VmRSS:" and fields[2] == "kB"
                and fields[1].isascii() and fields[1].isdigit()):
            return {"bytes": int(fields[1]) * 1024, "source": "/proc/self/status"}
    # An apparently valid /proc/<os.getpid()> may name a different process when
    # the executor and procfs use different PID namespaces. Fail closed unless
    # the real self status establishes that their PID numbering agrees.
    if proc_pid == os.getpid():
        try:
            rss = psutil.Process(os.getpid()).memory_info().rss
            if type(rss) is int and rss >= 0:
                return {"bytes": rss, "source": "psutil-verified-self-pid"}
        except (psutil.Error, OSError):
            pass
    return {"bytes": None, "source": "unavailable"}


def run_bakeoff(*, candidate, snapshot, inventory_sha256, cohorts, archive,
                output, operator_accepted_terms, batch_size=16, threads=4,
                scales=SCALES, repeats=3):
    if (candidate not in CANDIDATES or type(batch_size) is not int
            or not 1 <= batch_size <= 32 or type(threads) is not int
            or not 1 <= threads <= 8 or operator_accepted_terms is not True):
        raise ValueError("invalid fixed-candidate execution plan")
    validate_fanout_plan(scales, repeats)
    torch.set_num_threads(threads)
    torch.manual_seed(7)
    manifest_bytes = (Path(cohorts) / "manifest.json").read_bytes()
    dataset, rows = load_cohorts(cohorts, expected_manifest_sha256=sha(manifest_bytes),
                                archive=archive)
    config = HeadTrainingConfigV1(task_count=4, seed=7, steps=200, learning_rate=0.2)
    code = code_identity()
    plan = {"schema": "hepta.real-model-text-plan.v1", "candidate": candidate,
        "checkpoint_revision": CANDIDATES[candidate]["revision"],
        "checkpoint_inventory_sha256": inventory_sha256,
        "dataset_manifest_sha256": sha(manifest_bytes),
        "head_config": asdict(config), "comparators": ["linear", "gated"],
        "private_cell_tasks": ["business_vs_rest", "entertainment_vs_rest",
                               "health_vs_rest", "science_technology_vs_rest"],
        "max_tokens": 128, "batch_size": batch_size, "encoder_cpu_threads": threads,
        "fanout_cpu_threads": 1, "fanout_scales": list(scales), "fanout_repeats": repeats,
        "task_prefix": "classification", "code_file_sha256": code,
        "holdouts_select_hyperparameters_or_winner": False}
    target = Path(output)
    target.mkdir(parents=True, exist_ok=False)
    (target / "plan.json").write_bytes(canonical(plan) + b"\n")
    start = time.perf_counter()
    rss_before = rss_observation()
    owner = FrozenRealEncoder(candidate=candidate, snapshot=snapshot,
        revision=plan["checkpoint_revision"], expected_inventory_sha256=inventory_sha256,
        operator_accepted_terms=True, profile="text", max_tokens=128)
    encoder_before = model_tensor_digest(owner._model)
    rss_loaded = rss_observation()
    encoded, receipts, feature_manifests = {}, [], {}
    for name, split in rows.items():
        bundles = []
        feature_manifests[name] = []
        for offset in range(0, len(split), batch_size):
            batch = split[offset:offset + batch_size]
            bundle = owner.encode_text([r["text"] for r in batch], source_records=batch)
            bundles.append(bundle)
            receipts.append({"split": name, "offset": offset, **owner.last_receipt})
            feature_manifests[name].append(bundle.manifest())
        encoded[name] = HeadCohortV1(tuple(bundles), tuple(r["label"] for r in split),
                                      tuple(r["source_group_id"] for r in split))
        print(json.dumps({"encoded": name, "rows": len(split), "candidate": candidate}), flush=True)
    (target / "feature_manifests.json").write_bytes(canonical(feature_manifests) + b"\n")
    heads, trained, artifacts = {}, {}, {}
    artifacts_dir = target / "heads"
    artifacts_dir.mkdir()
    for mode in ("linear", "gated"):
        head_config = HeadTrainingConfigV1(**{**asdict(config), "mode": mode})
        began = time.perf_counter()
        result = train_cell_head(encoded["train"], encoded["calibration"],
            {name: encoded[name] for name in ("future_1", "future_2", "ood")}, config=head_config)
        training_ms = 1000 * (time.perf_counter() - began)
        artifact = save_head_artifact(result, artifacts_dir / mode)
        restored = load_head_artifact(artifacts_dir / mode,
            expected_manifest_sha256=artifact["manifest_sha256"], expected_identity=owner.identity)
        parity = all(torch.equal(result.predict_task(bundle)["task_probabilities"],
                                 restored.predict_task(bundle)["task_probabilities"])
                     for bundle in encoded["ood"].bundle)
        if not parity:
            raise ValueError("saved Head does not reproduce heldout predictions")
        artifact["directory"] = f"heads/{mode}"
        artifacts[mode] = {**artifact, "reload_prediction_exact": parity}
        heads[mode] = {**compact_training_report(result), "training_ms": training_ms}
        trained[mode] = result
    if heads["linear"]["initial_tensor_sha256"] != heads["gated"]["initial_tensor_sha256"]:
        raise ValueError("linear and gated arms did not start from the same initialization")
    private_cells = []
    for label, task in enumerate(plan["private_cell_tasks"]):
        binary = {name: HeadCohortV1(cohort.bundle,
            tuple(int(y == label) for y in cohort.labels), cohort.source_group_ids)
            for name, cohort in encoded.items()}
        result = train_cell_head(binary["train"], binary["calibration"],
            {name: binary[name] for name in ("future_1", "future_2", "ood")},
            config=HeadTrainingConfigV1(task_count=2, seed=7, steps=200, learning_rate=0.2))
        artifact = save_head_artifact(result, artifacts_dir / task)
        artifact["directory"] = f"heads/{task}"
        private_cells.append({"task": task, "report": compact_training_report(result),
                              "artifact": artifact})
    encoder_after = model_tensor_digest(owner._model)
    if encoder_before != encoder_after or any(p.grad is not None for p in owner._model.parameters()):
        raise ValueError("private Head learning changed the shared Encoder")
    one = rows["future_2"][0]
    source_bundle = owner.encode_text([one["text"]], source_records=[one])
    fanout = measure_fanout(owner, source_bundle, trained["gated"], scales=scales, repeats=repeats)
    encoder_after_fanout = model_tensor_digest(owner._model)
    if (encoder_before != encoder_after_fanout
            or any(p.requires_grad or p.grad is not None for p in owner._model.parameters())
            or any(m.training for m in owner._model.modules())):
        raise ValueError("shared Encoder changed while producing or serving the final feature bundle")
    if code != code_identity():
        raise ValueError("source code changed during the experiment")
    versions = {name: importlib.metadata.version(name) for name in
                ("torch", "transformers", "numpy", "safetensors", "tokenizers", "psutil")}
    rss_end = rss_observation()
    report = {"schema": "hepta.real-model-text-bakeoff.v1", "plan_sha256": sha(canonical(plan)),
        "plan": plan, "dataset": dataset, "feature_identity": asdict(owner.identity),
        "feature_manifests_sha256": sha((target / "feature_manifests.json").read_bytes()),
        "encoder": {**owner.accounting, "snapshot_artifact_bytes": owner.snapshot_artifact_bytes,
            "load_ms": owner.load_ms, "tensor_sha256_before": encoder_before,
            "tensor_sha256_after_learning": encoder_after,
            "tensor_sha256_after": encoder_after_fanout, "weights_unchanged_after_learning": True,
            "weights_unchanged_after_fanout": True,
            "model_forward_calls_for_dataset": sum(r["model_forward_calls"] for r in receipts),
            "encoded_source_rows": sum(len(r) for r in rows.values()),
            "total_dataset_encode_ms": sum(r["encode_ms"] for r in receipts),
            "loaded_scope": "encoder_only" if candidate == "laya_encoder_only" else "text"},
        "forward_receipts": receipts, "heads": heads, "head_artifacts": artifacts,
        "independently_trained_private_cells": private_cells, "fanout": fanout,
        "runtime": {"platform": platform.platform(), "python": platform.python_version(),
            "versions": versions, "logical_cpu_count": os.cpu_count(), "cuda_used": False,
            "rss_before_model_bytes": rss_before["bytes"], "rss_after_model_load_bytes": rss_loaded["bytes"],
            "rss_at_end_bytes": rss_end["bytes"],
            "rss_measurement_sources": {"before_model": rss_before["source"],
                "after_model_load": rss_loaded["source"], "at_end": rss_end["source"]},
            "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "wall_ms": 1000 * (time.perf_counter() - start)},
        "scope": {"historical_public_text_task_executed": True,
            "foundation_pretraining_contamination_excluded": False,
            "full_laya_policy_compared": False, "multimodal_quality_measured": False,
            "gpu_or_target_device_qualified": False, "action_value_policy_trained": False,
            "latency_or_energy_slo_qualified": False,
            "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
            "production_activation_allowed": False}}
    payload = canonical(report) + b"\n"
    (target / "report.json").write_bytes(payload)
    print(json.dumps({"candidate": candidate, "report_sha256": sha(payload),
        "loaded_parameters": owner.accounting["loaded_parameter_count"],
        "gated_accuracy": {name: data["metrics"]["calibrated"]["accuracy"]
                           for name, data in heads["gated"]["splits"].items()}}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=sorted(CANDIDATES), required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--cohorts", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--operator-accepted-terms", action="store_true")
    parser.add_argument("--scales", default=",".join(map(str, SCALES)))
    parser.add_argument("--repeats", type=int, default=3)
    args = vars(parser.parse_args())
    args["scales"] = tuple(int(n) for n in args["scales"].split(","))
    run_bakeoff(**args)


if __name__ == "__main__":
    main()

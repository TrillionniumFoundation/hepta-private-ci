"""Cost-only, source-pinned physical full-vs-eight Encoder comparison.

A cross-run trained-Head SHA mismatch is an *observed negative fact*, not a
reason to discard genuine same-process CPU timing. No quality/model promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for name in ("stem-optimal-v1", "stem-optimal-v4", "stem-optimal-v5",
             "stem-optimal-v8", "stem-optimal-v10"):
    sys.path.insert(0, str(ROOT / name))

import paired_workload_v10 as v10

SCHEMA = "hepta.stem.same-process-cost-only.v13"
CANDIDATES = ("granite47", "granite97")
SOURCE_SHA = "3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900"
MAX_INTERNAL_SCORE_DRIFT = 5e-4


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def loading_inventory(info):
    """Reject an incomplete source-to-model mapping, never a random fill-in."""
    require(type(info) is dict, "pretrained loader did not return a bounded report")
    result = {}
    for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"):
        entries = info.get(key, [])
        require(type(entries) in (list, tuple, set, frozenset) and len(entries) <= 8192,
                "unsupported or unbounded pretrained loading report")
        result[key] = list(entries)
        require(not entries, "pinned model loading incomplete: " + key)
    return {"missing_parameter_count": 0, "unexpected_parameter_count": 0,
            "mismatched_parameter_count": 0, "loader_error_count": 0,
            "complete_base_material_admitted": True}


def load_checked(spec):
    """Read and hash all pinned safetensors, then require a complete base load."""
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModel, AutoTokenizer

    require(spec["repo"] in (
        "ibm-granite/granite-embedding-small-english-r2",
        "ibm-granite/granite-embedding-97m-multilingual-r2"),
        "only originally complete 47M/97M base models admitted")
    require(len(spec["revision"]) == 40 and len(spec["weight_sha256"]) == 64 and
            spec["weight_file"] == "model.safetensors" and spec["width"] == 384,
            "unfrozen model registry")
    root = Path(snapshot_download(repo_id=spec["repo"], revision=spec["revision"],
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"],
        ignore_patterns=["*.bin", "*.pt", "*.h5", "*.onnx"], local_files_only=False))
    tensor_path = root / spec["weight_file"]
    require(tensor_path.is_file() and 0 < tensor_path.stat().st_size < 1_000_000_000,
            "original model safetensors missing or oversized")
    digest = hashlib.sha256()
    with tensor_path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    require(digest.hexdigest() == spec["weight_sha256"], "original model weight bytes drift")
    tok = AutoTokenizer.from_pretrained(str(root), trust_remote_code=False,
                                         local_files_only=True)
    model, loading = AutoModel.from_pretrained(
        str(root), trust_remote_code=False, local_files_only=True,
        use_safetensors=True, torch_dtype=torch.float32, output_loading_info=True)
    proof = loading_inventory(loading)
    model.eval().to("cpu")
    observed = sum(t.numel() for t in model.parameters())
    require(abs(observed - spec["parameters_approx"]) <= 2_000_000,
            "loaded pretrained parameter census differs from original source")
    return tok, model, proof | {"loaded_parameter_scalars": observed,
                                "model_weight_sha256": digest.hexdigest()}


def internal_parity(outputs, selected):
    """Only compare the two physically executed arms of the SAME model/Head."""
    require(type(outputs) is dict and set(outputs) == {"selected", "full"} and
            all(len(outputs[name]) == 4 for name in outputs), "missing matched repeats")
    selected_ids = {r["case_id"] for r in selected}
    require(len(selected_ids) == 8, "missing selected inputs")
    maximum = 0.0
    for full, sparse in zip(outputs["full"], outputs["selected"]):
        require(len(full) == 32 and set(sparse) == selected_ids, "different paired inputs")
        for cid in selected_ids:
            a, b = full[cid], sparse[cid]
            require(type(a) is list and type(b) is list and len(a) == len(b) == 4,
                    "invalid paired numeric output")
            for x, y in zip(a, b):
                require(all(type(v) in (float, int) and math.isfinite(v) for v in (x,y)),
                        "nonfinite paired numeric output")
                maximum = max(maximum, abs(x-y))
    require(maximum <= MAX_INTERNAL_SCORE_DRIFT,
            "same-run full vs selected numeric parity failure")
    return maximum


def cost_only(source, cheap, original, materials, candidate):
    """Pay route, full model load, full fit, and BOTH paired inference arms."""
    import torch
    import stem_candidate_v1 as v1
    import cheap_lexical_stem_v4 as lexical
    import selective_route_v8 as v8

    require(candidate in CANDIDATES, "unqualified candidate cannot enter cost probe")
    require(original["candidate"] == candidate and
            original["source_plan_sha256"] == SOURCE_SHA and
            original["actual_weight_sha256"] == materials["candidates"][candidate]["weight_sha256"] and
            original["authority"] == "DENY_ALL" and
            v1.sha256(v1.canonical(materials)) == original["material_manifest_sha256"],
            "original model/Head source was substituted")
    cheap_probs = v8._scores(cheap, source["heldout"], v8.CHEAP_ARM, cheap=True)
    selected_ids = v8.select_unlabelled(cheap_probs)
    cases = {r["case_id"]: r for r in source["heldout"]}
    require(source["source_plan_sha256"] == SOURCE_SHA and len(source["train"]) == 64
            and len(cases) == 32 and len(selected_ids) == 8 and
            all("label" not in c for c in source["heldout"]),
            "source scope, frozen route or withheld labels changed")
    selected = [cases[cid] for cid in selected_ids]
    torch.set_num_threads(2)
    start, cpu = time.perf_counter(), time.process_time()
    lexical_receipt = lexical.compute(source)
    require(lexical_receipt["source_plan_sha256"] == cheap["source_plan_sha256"]
            and all(all(abs(a-b) < 1e-11 for arm in lexical.ARMS
            for a,b in zip(r["scores"][arm],
              next(x["scores"][arm] for x in cheap["rows"] if x["case_id"] == r["case_id"])))
            for r in lexical_receipt["rows"]),
            "cheap original routing/production mismatch")
    load_start = time.perf_counter()
    tokenizer, model, loading = load_checked(materials["candidates"][candidate])
    load_time = time.perf_counter() - load_start
    fit_start = time.perf_counter()
    fit, fit_batches = v1._encode([r["text"] for r in source["train"]], tokenizer, model)
    fit_time = time.perf_counter() - fit_start
    require(tuple(fit.shape) == (64,384) and fit_batches == 4,
            "unqualified actual training feature count")
    head, hashes = v10.make_head_and_fit(fit, [r["label"] for r in source["train"]],
                                        config=materials["training"])
    require(hashes["initial_sha256"] == original["initial_head_sha256"],
            "original Head initial checkpoint changed")
    times, outputs, paid, batches = v10.paired_runs(
        model, tokenizer, head, source["train"], source["heldout"], selected)
    maximum = internal_parity(outputs, selected)
    require(paid == {"selected": 32, "full": 128} and
            batches == {"selected": 4, "full": 8}, "model forward counts not actually observed")
    original_rows = {row["case_id"]: row["scores"]["learned"] for row in original["rows"]}
    require(set(original_rows) == set(cases), "original historical case census drift")
    historical_max = max(abs(value - original_rows[cid][i])
                         for trial in outputs["full"] for cid, probs in trial.items()
                         for i, value in enumerate(probs))
    # Historical trained-SHA equality is deliberately reported, NEVER inferred
    # from high numeric parity. This study only licenses descriptive COST evidence.
    report = {
        "schema": SCHEMA, "candidate": candidate,
        "source_plan_sha256": SOURCE_SHA,
        "original_model_revision": original["model_revision"],
        "original_weight_sha256": original["actual_weight_sha256"],
        "original_head_initial_sha256": original["initial_head_sha256"],
        "original_head_trained_sha256": original["trained_head_sha256"],
        "observed_head_initial_sha256": hashes["initial_sha256"],
        "observed_head_trained_sha256": hashes["trained_sha256"],
        "historical_trained_head_byte_equal": hashes["trained_sha256"] == original["trained_head_sha256"],
        "historical_prediction_numerically_admitted": False,
        "max_historical_prediction_abs_drift_descriptive": historical_max,
        "max_within_run_selected_full_abs_drift": maximum,
        "actual_selected_case_ids": selected_ids,
        "complete_loader_inventory": loading,
        "cheap_route_wall_seconds": lexical_receipt["cost"]["elapsed_wall_seconds"],
        "cheap_route_cpu_seconds": lexical_receipt["cost"]["elapsed_cpu_seconds"],
        "model_load_wall_seconds": load_time,
        "fit_encoder_wall_seconds": fit_time,
        "head_training_wall_seconds": hashes["train_wall_seconds"],
        "fit_encoder_sequences": 64, "fit_encoder_batches": 4,
        "trained_head_optimizer_updates": hashes["actual_optimizer_updates"],
        "measured_order": [list(x) for x in v10.ARM_ORDER],
        "measured_arm_times": times,
        "measured_arm_sequence_counts": paid,
        "measured_arm_batch_counts": batches,
        "actual_total_encoder_sequences": 224,
        "actual_total_encoder_batches": 16,
        "median_arm_wall_seconds": {name:statistics.median(t["wall_seconds"] for t in times[name])
                                    for name in ("selected", "full")},
        "median_arm_cpu_seconds": {name:statistics.median(t["cpu_seconds"] for t in times[name])
                                   for name in ("selected", "full")},
        "total_paid_workload_wall_seconds": time.perf_counter() - start,
        "total_paid_workload_cpu_seconds": time.process_time() - cpu,
        "self_reported_process_maxrss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "physical_8_vs_32_matched_process_cost_observed": True,
        "full_lifecycle_resource_savings_verified": False,
        "test_gold_ever_reopened": False,
        "historical_test_labels_previously_exposed": True,
        "independent_source_families": 1, "future_windows": 0,
        "target_host_p99_energy_attested": False,
        "stem_winner_verified": False, "ndu_gain_verified": False,
        "production_authorized": False, "cell_split_authorized": False,
        "authority": "DENY_ALL", "disposition": "HOLD_NO_GO",
    }
    return report


def main():
    p = argparse.ArgumentParser()
    for name in ("manifest", "zip-dir", "materials", "candidate", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    import paired_review_v5 as v5
    import stem_candidate_v1 as old
    lock = json.loads(Path(a.manifest).read_text())
    require(lock["schema"] == "hepta.stem.original-hard-charge.lock.v5" and
            lock["authority"] == "DENY_ALL", "wrong original artifact manifest")
    root = Path(a.zip_dir)
    source = v5.locked_json(root / "source_v3.zip", lock["artifacts"], "source_v3")
    copy = v5.locked_json(root / "source_v4.zip", lock["artifacts"], "source_v4")
    require(source == copy, "V3 and V4 frozen input bytes differ")
    cheap = v5.locked_json(root / "cheap_v4.zip", lock["artifacts"], "cheap_v4")
    original = v5.locked_json(root / (a.candidate + ".zip"), lock["artifacts"], a.candidate)
    material = old.load_materials(Path(a.materials))
    report = cost_only(source, cheap, original, material, a.candidate)
    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(v10.canonical(report) + b"\n")
        stream.flush()
    print(json.dumps({"sha256": sha(output.read_bytes()), "candidate": a.candidate,
                      "cost_only": True, "authority": "DENY_ALL"}, sort_keys=True))


if __name__ == "__main__":
    main()

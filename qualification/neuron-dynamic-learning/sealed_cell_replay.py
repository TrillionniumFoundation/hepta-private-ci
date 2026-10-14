"""Exact checkpoint-reloaded local Cell evaluation on independently pinned val2.

Never retrains: load_checkpoint returns prediction-only Heads. The snapshot is
created from original train before any val2 features. All reports remain
untrusted, non-authorizing, cross-sectional public diagnostics. This is NOT
an attempt to replay the missing historical 2026-10-14 Head snapshot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from sealed_cell_checkpoint import CheckpointError, load_checkpoint
from public_agnews_panel import canonical, sha
from agnews_paired_shadow import check_panel
from public_agnews_confirmatory import check_panel as validate_fresh
from embeddinggemma2_shadow import rust_feature_digest_q24
from exploratory_temperature_probe import scale_probability

MAX_BATCH = 8


class ReplayError(ValueError):
    """Invalid model output, source identity, checkpoint or claim."""


def _scores(rows: list[dict], labels: dict) -> dict:
    pairs = [(row["prob_sports"], labels[row["case_id"]]) for row in rows]
    n = len(pairs)
    if n != 128:
        raise ReplayError("incomplete fixed new-source evaluation")
    bins = []
    for i in range(8):
        group = [(p, y) for p, y in pairs if min(7, int(max(p, 1-p) * 8)) == i]
        if group:
            correct = sum((p >= .5) == y for p, y in group) / len(group)
            confidence = sum(max(p, 1-p) for p, _ in group) / len(group)
            bins.append(len(group) / n * abs(correct - confidence))
    return {"cases": n, "accuracy": sum((p >= .5) == y for p, y in pairs) / n,
            "brier": sum((p - y) ** 2 for p, y in pairs) / n,
            "descriptive_ece_8_equal_width": sum(bins)}


def evaluate(*, original_panel: dict, val2_panel: dict, runner, bundle_path: Path) -> dict:
    from sealed_cell_checkpoint import _sha
    original_digest, _ = check_panel(original_panel)
    new_digest, examples = validate_fresh(val2_panel, original_panel)
    if (getattr(runner, "_verified_local_weights", False) is not True or
            runner.manifest.get("dimension") != 256 or
            runner.manifest.get("profile") != "text"):
        raise ReplayError("real pinned frozen 256d shared Encoder required")
    receipt = load_checkpoint(
        bundle_path, source_panel_digest=original_digest,
        model_revision=runner.manifest["revision"],
        pipeline_digest=runner.profile_digest,
        scope_id="public.agnews", purpose_id="capability.noeffects",
        generation=1, authority_epoch=1)
    if (receipt["receipt"]["historical_20261014_head_byte_identity_claimed"] is not False
            or receipt["receipt"]["production_promotion"] != "DENY_ALL"):
        raise ReplayError("checkpoint replay may not assert historical/production authority")
    sealed_bytes_digest = receipt["receipt"]["snapshot_file_sha256"]
    features: list[list[int]] = []
    allocated_encoder_micros = 0
    api_calls = 0
    for start in range(0, len(examples), MAX_BATCH):
        chunk = examples[start:start+MAX_BATCH]
        requests = []
        for case in chunk:
            payload = canonical(case["joint_input"]).decode("utf-8")
            requests.append({
                "scope_id":"public.agnews", "principal_id":"shadow.cpu",
                "purpose_id":"capability.noeffects", "cell_id":"sealed."+case["case_id"],
                "generation":1, "authority_epoch":1,
                "input":{"modality":"text", "role":"classification",
                         "value":payload, "sha256":sha(payload.encode("utf-8"))},
            })
        start_ns = time.perf_counter_ns()
        outputs = runner.encode_cells(requests)
        allocated_encoder_micros += max(1, (time.perf_counter_ns()-start_ns)//1000)
        if (not isinstance(outputs, dict) or
                outputs.get("evidence_type") != "local_weight_execution_unverified_origin" or
                outputs.get("physical_local_model_execution") is not True or
                outputs.get("production_promotion") != "DENY_ALL" or
                outputs.get("model_revision") != runner.manifest["revision"] or
                outputs.get("feature_dimension") != 256 or
                outputs.get("cell_requests") != len(requests) or
                not isinstance(outputs.get("rows"), list) or
                len(outputs["rows"]) != len(requests) or
                type(outputs.get("sentence_transformer_encode_calls")) is not int or
                outputs["sentence_transformer_encode_calls"] < 1):
            raise ReplayError("unsigned or incomplete frozen Encoder output")
        api_calls += outputs["sentence_transformer_encode_calls"]
        for request, row in zip(requests, outputs["rows"]):
            try:
                q24 = row["features_q24"]
                computed = rust_feature_digest_q24(q24)
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ReplayError("malformed Q24 feature") from exc
            if (not isinstance(q24, list) or len(q24) != 256 or
                    row.get("feature_digest") != computed or
                    row.get("input_digest") != request["input"]["sha256"] or
                    row.get("pipeline_digest") != runner.profile_digest or
                    row.get("cell_id") != request["cell_id"] or
                    row.get("authority") != "DENY_ALL" or
                    row.get("modality") != "text" or row.get("role") != "classification" or
                    row.get("requires_new_neuron_profile") is not False or
                    any(row.get(key) != request[key] for key in (
                        "scope_id", "principal_id", "purpose_id", "generation", "authority_epoch"))):
                raise ReplayError("cross-case feature identity or Q24 hash mismatch")
            features.append(q24)
    if len(features) != len(examples) or len(examples) != 128:
        raise ReplayError("missing exact public new-source feature rows")
    if _sha(bundle_path.read_bytes()) != sealed_bytes_digest:
        raise ReplayError("selected checkpoint mutated after model use")
    x = np.asarray(features, dtype=np.float64) / (1 << 24)
    frozen, learned = receipt["frozen"], receipt["trained"]
    arms = {"gemma2_frozen_head": frozen, "gemma2_trained_head": learned,
            "gemma2_trained_head_scaled_1024": learned}
    source = {c["case_id"]: c for c in examples}
    reports = {}
    start_ns = time.perf_counter_ns()
    for name, cell in arms.items():
        logits = np.asarray(cell.predict(x), dtype=np.float64)
        if logits.shape != (len(examples),) or not np.isfinite(logits).all():
            raise ReplayError("reloaded frozen Head produced bad logits")
        p = np.exp(-np.logaddexp(0, -logits))
        if name.endswith("scaled_1024"):
            p = np.asarray([scale_probability(float(y), 1024) for y in p])
        if not np.isfinite(p).all() or not np.all((p > 0) & (p < 1)):
            raise ReplayError("invalid post-replay probability")
        cases = [{"case_id": case["case_id"],
                  "source_digest": case["source_digest"],
                  "joint_input_digest": case["joint_input_digest"],
                  "prob_sports": float(prob), "production_promotion": "DENY_ALL"}
                 for case, prob in zip(examples, p)]
        reports[name] = {"head_digest": receipt["receipt"][
            "frozen_head_digest" if name == "gemma2_frozen_head" else "trained_head_digest"],
            "rows": cases,
            "metrics": _scores(cases, {cid: row["label"] for cid, row in source.items()})}
    head_us = max(1, (time.perf_counter_ns() - start_ns)//1000)
    if _sha(bundle_path.read_bytes()) != sealed_bytes_digest:
        raise ReplayError("frozen Head bytes changed during inference")
    return {
        "schema": "hepta.stem.val2-sealed-head-shadow-replay.v1",
        "original_source_panel_digest": original_digest,
        "val2_panel_digest": new_digest,
        "new_file_source_sha256": val2_panel["dataset_file_sha256"],
        "case_count": len(examples),
        "snapshot_file_sha256": sealed_bytes_digest,
        "snapshot_payload_sha256": receipt["receipt"]["snapshot_payload_sha256"],
        "physical_model_revision": runner.manifest["revision"],
        "feature_pipeline_digest": runner.profile_digest,
        "checkpoint_q24_head_digests_checked_after_reload": True,
        "full_float64_head_bytes_unchanged_during_replay": True,
        "head_optimizer_steps_during_val2_evaluation": 0,
        "model_encode_api_calls": api_calls,
        "physical_transformer_forward_calls": None,
        "observed_encoder_batch_wall_micros": allocated_encoder_micros,
        "observed_head_cpu_wall_micros": head_us,
        "arms": reports,
        "independent_model_origin_authenticated": False,
        "historical_20261014_head_byte_identity_claimed": False,
        "public_new_file_but_same_dataset_family": True,
        "three_chronological_future_windows": False,
        "equal_full_lifecycle_cost_authenticated": False,
        "production_promotion": "DENY_ALL",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Immutable new candidate Cell replay on val2")
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--val2", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    from embeddinggemma2_shadow import FrozenGemmaShadow
    runner = FrozenGemmaShadow(arguments.manifest, device="cpu")
    result = evaluate(
        original_panel=json.loads(arguments.original.read_text()),
        val2_panel=json.loads(arguments.val2.read_text()),
        runner=runner, bundle_path=arguments.bundle)
    if arguments.out.exists() or not arguments.out.parent.is_dir():
        raise ReplayError("fresh read-only output location required")
    arguments.out.write_bytes(canonical(result))
    print(json.dumps({"source_cases": result["case_count"],
                      "snapshot_sha256": result["snapshot_file_sha256"],
                      "production_promotion": "DENY_ALL"}, sort_keys=True))

#!/usr/bin/env python3
"""Assemble externally executed Model A arms without accepting unbound logits.

Extends the existing decision_421m.py experiment. Verifies local SHA-pinned
prediction files and run manifests; it does NOT authenticate the model
operator, NDU outcomes, licensed data, or a live Hepta inference Worker.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from decision_421m import (
    PHASES, SCORING, SOURCES, audit_dataset, check_sha,
    input_fingerprint, load_plan, read_strict_jsonl, sha256_file,
)

SCHEMA = "hepta.decision-421m-shadow-arm-bundle.v1"
MAX_PREDICTION_BYTES = 64 * 1024 * 1024
MAX_ROWS = 100000


def strict_json_pairs(pairs):
    values = {}
    for name, value in pairs:
        if name in values:
            raise ValueError("duplicate JSON key in evidence")
        values[name] = value
    return values


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=strict_json_pairs)


def inside(root, relative):
    if (not isinstance(relative, str) or not relative or
            Path(relative).is_absolute() or ".." in Path(relative).parts):
        raise ValueError("evidence path must be strictly relative")
    resolved = (root / relative).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("evidence path escapes root or is not a file")
    return resolved


def load_predictions(path, expected_arm, run, scored_index, classes):
    if path.stat().st_size > MAX_PREDICTION_BYTES:
        raise ValueError("prediction file exceeds capped byte budget")
    declared = run.get("output_predictions_sha256")
    if not check_sha(declared) or declared != sha256_file(path):
        raise ValueError("model execution receipt does not bind prediction bytes")
    seen, result = set(), []
    with path.open(encoding="utf-8") as handle:
        for n, line in enumerate(handle, 1):
            if not line.strip() or n > MAX_ROWS:
                raise ValueError("blank line or excessive model predictions")
            try:
                row = json.loads(line, object_pairs_hook=strict_json_pairs)
            except (ValueError, TypeError) as exc:
                raise ValueError("unparsable prediction/duplicate field") from exc
            if type(row) is not dict or row.get("arm") != expected_arm:
                raise ValueError("model arm identity mismatch")
            sid = row.get("sample_id")
            if not isinstance(sid, str) or sid not in scored_index or sid in seen:
                raise ValueError("duplicate/unknown/incomplete model sample")
            if any(k in row for k in ("label", "external_ndu_utility",
                                       "total_cost", "observer_digest")):
                raise ValueError("model output illegally contains outcome or authority evidence")
            logits = row.get("logits")
            if (not isinstance(logits, list) or len(logits) != classes or
                    any(type(x) not in (float, int) or not math.isfinite(x)
                        or abs(x) > 1e6 for x in logits)):
                raise ValueError("malformed aligned legal-action logits")
            if row.get("weights_sha256") != run.get("weights_sha256"):
                raise ValueError("predicted Head weights differ from run manifest")
            if row.get("input_digest") != input_fingerprint(scored_index[sid]):
                raise ValueError("predicted sample source/options digest mismatch")
            if "token_count" in row:
                limit = run["runtime_profile"]["context_tokens"]
                if (type(row["token_count"]) is not int or
                        not 1 <= row["token_count"] <= limit):
                    raise ValueError("prediction exceeded registered token budget")
            duration = row.get("latency_ms")
            if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
                raise ValueError("missing measured per-sample latency")
            seen.add(sid)
            result.append(row)
    if seen != set(scored_index):
        raise ValueError("missing paired scored sample in source model arm")
    return result


def assemble(plan, evidence_root, entries, dataset, scope):
    if scope not in ("full", "equal_budget"):
        raise ValueError("unknown frozen study scope")
    phases = PHASES if scope == "full" else ("equal_budget",)
    required = {f"{model}:{phase}" for model in SOURCES for phase in phases}
    if not isinstance(entries, list) or len(entries) != len(required):
        raise ValueError("one execution receipt is required per planned arm")
    scored = {sid: row for sid, row in dataset.items() if row["split"] in SCORING}
    if not scored or len(scored) > MAX_ROWS:
        raise ValueError("scored dataset is empty or exceeds research bound")
    manifests, predictions, references = [], [], []
    observed = set()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {
                "arm", "prediction_path", "run_manifest_path"}:
            raise ValueError("unexpected/ambiguous local model artifact descriptor")
        arm = entry["arm"]
        if arm not in required or arm in observed:
            raise ValueError("missing, duplicate or extra model arm descriptor")
        observed.add(arm)
        model, phase = arm.split(":")
        pred_path = inside(evidence_root, entry["prediction_path"])
        run_path = inside(evidence_root, entry["run_manifest_path"])
        run = read_json(run_path)
        if type(run) is not dict:
            raise ValueError("run metadata must be object")
        original = plan["checkpoints"][model]
        if (run.get("arm") != arm or
                run.get("model_source") != SOURCES[model][0] or
                run.get("checkpoint_sha256") != original["sha256"] or
                run.get("upstream_revision") != original["upstream_revision"] or
                run.get("dataset_sha256") != plan["dataset_sha256"] or
                run.get("training_sample_groups_sha256") != plan["training_sample_groups_sha256"] or
                run.get("runtime_profile") != {
                    "device": plan["device"], "dtype": plan["dtype"],
                    "batch_size": plan["batch_size"],
                    "context_tokens": plan["context_tokens"]} or
                run.get("seed") != plan["seed"] or
                run.get("physical_encoder_microbatch_ceiling", 1) !=
                plan.get("encoder_microbatch_size", 1) or
                run.get("truncated_input_count") != 0 or
                run.get("input_contract") != plan["input_contract"] or
                run.get("production_promotion_permitted") is not False or
                not check_sha(run.get("weights_sha256"))):
            raise ValueError("run artifact is not bound to the immutable model/data plan")
        # DeBERTa/ModernBERT run evidence must actually come from the
        # pinned reviewed local safetensors execution implementation. A model
        # identifier and logits alone cannot prove real pretrained weights
        # loaded instead of random base-model layers.
        if model in ("deberta_v3_large", "modernbert_large") and phase == "equal_budget":
            local_runner = Path(__file__).with_name("hf_joint_decision_runner.py")
            loading = run.get("verified_encoder_loading")
            materialized = run.get("verified_exact_tensor_materialization")
            checked_tensors = (type(materialized) is dict and
                               materialized.get("schema") ==
                               "hepta.local-hf-exact-tensor-materialization.v1" and
                               materialized.get("complete") is True and
                               materialized.get("all_state_dict_tensors_compared") is True and
                               materialized.get("production_authorization") is False and
                               type(materialized.get("tensor_count")) is int and
                               materialized["tensor_count"] > 0 and
                               type(materialized.get("tensor_elements")) is int and
                               materialized["tensor_elements"] >= materialized["tensor_count"] and
                               type(materialized.get("safetensors_shards")) is int and
                               1 <= materialized["safetensors_shards"] <= 64)
            if (run.get("schema") != "hepta.stem-cell-actual-hf-joint-decision.v1" or
                    run.get("runner_source_sha256") != sha256_file(local_runner) or
                    type(loading) is not dict or loading != {
                        "schema": "hepta.local-hf-encoder-weight-load.v1",
                        "complete": True,
                        "missing_keys": 0, "unexpected_keys": 0,
                        "mismatched_keys": 0, "error_msgs": 0,
                    } or not checked_tensors or
                    run.get("pretrained_typed_decision_head_existed") is not False or
                    run.get("checkpoint_zero_shot_score_emitted") is not False):
                raise ValueError("HF arm lacks complete audited safetensors loading/runner evidence")
        if phase == "checkpoint":
            if (run.get("pretrained_typed_decision_head_present") is not True or
                    run.get("trainable_parameters") != 0 or
                    run.get("train_steps") != 0):
                raise ValueError("untrained HF checkpoint falsely claims typed zero-shot capability")
        else:
            count = run.get("trainable_parameters")
            if (type(count) is not int or
                    not 0 < count <= plan["trainable_parameter_budget"] or
                    run.get("train_steps") != plan["train_steps"] or
                    run.get("training_split") != "train" or
                    run.get("optimizer") != "adamw"):
                raise ValueError("unmatched learned Head training budget")
        rows = load_predictions(pred_path, arm, run, scored, plan["classes"])
        manifests.append(run)
        predictions.extend(rows)
        references.append({
            "arm": arm, "run_manifest_sha256": sha256_file(run_path),
            "prediction_file_sha256": sha256_file(pred_path),
            "paired_case_count": len(rows),
        })
    if observed != required:
        raise ValueError("registered arm coverage mismatch")
    return sorted(manifests, key=lambda r: r["arm"]), sorted(
        predictions, key=lambda r: (r["arm"], r["sample_id"])), {
        "schema": SCHEMA, "comparison_scope": scope,
        "status": "offline_operator_artifacts_byte_checked_not_owner_attested",
        "production_promotion_permitted": False,
        "independent_outcomes_authenticated": False,
        "owner_signatures_verified": False,
        "complete_checkpoint_comparison": scope == "full",
        "paired_sample_count_per_arm": len(scored),
        "arms": sorted(references, key=lambda r: r["arm"]),
        "limitations": [
            "SHA verifies exact local evidence bytes, not trusted model execution",
            "No-change, future NDU, target hardware and production final-use remain separate",
            "Equal-budget scope cannot make a checkpoint/zero-shot claim",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--comparison-scope", choices=("full", "equal_budget"),
                        default="equal_budget")
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()
    plan, plan_sha = load_plan(args.plan)
    data, width, groups_sha = audit_dataset(list(read_strict_jsonl(plan["dataset_path"])))
    if (width != plan["classes"] or
            groups_sha != plan["training_sample_groups_sha256"]):
        raise ValueError("dataset lineage changed from frozen experiment plan")
    root = Path(args.evidence_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("evidence root must be directory")
    entries = read_json(args.descriptor)
    if type(entries) is not dict or set(entries) != {"arms"}:
        raise ValueError("evidence descriptor requires arms only")
    prefixes = {
        name: Path(args.output_prefix + suffix) for name, suffix in (
            ("runs", ".runs.json"),
            ("predictions", ".predictions.jsonl"),
            ("summary", ".bundle.json"),
        )
    }
    if any(path.exists() for path in prefixes.values()):
        raise FileExistsError("refusing overwrite of frozen evidence bundle")
    runs, predictions, summary = assemble(plan, root, entries["arms"],
                                          data, args.comparison_scope)
    lines = "".join(json.dumps(p, ensure_ascii=False, sort_keys=True,
                               allow_nan=False) + "\n" for p in predictions)
    runs_json = json.dumps(runs, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    summary.update({
        "assembler_source_sha256": sha256_file(__file__),
        "plan_sha256": plan_sha,
        "dataset_sha256": plan["dataset_sha256"],
        "runs_bundle_sha256": hashlib.sha256(runs_json.encode("utf-8")).hexdigest(),
        "predictions_bundle_sha256": hashlib.sha256(lines.encode("utf-8")).hexdigest(),
    })
    for p in prefixes.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    with prefixes["runs"].open("x", encoding="utf-8") as handle:
        handle.write(runs_json)
    with prefixes["predictions"].open("x", encoding="utf-8") as handle:
        handle.write(lines)
    with prefixes["summary"].open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False,
                               sort_keys=True, indent=2) + "\n")
    print(json.dumps({
        "bundle": str(prefixes["summary"]), "arms": len(runs),
        "production_promotion_permitted": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

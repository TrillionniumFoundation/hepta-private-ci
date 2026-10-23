"""Independent-format five-arm raw shadow report audit.

This validator recomputes metrics and row identities from untrusted raw files.
It does NOT authenticate model execution or qualify production admission.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from replacement_gate import EXPECTED, SPLITS, score_rows, validate_registry
from replacement_physical import TRAIN_RATE, TRAIN_SEED, TRAIN_STEPS, TEMPERATURES

KEYS = frozenset(("schema", "candidate", "checkpoint", "loaded_parameter_count",
                  "execution_kind", "observed_forward_calls", "source_archive_sha256",
                  "frozen_selected_rows_sha256", "per_split_limit", "scores",
                  "head_training", "performance", "limits", "mode", "authority",
                  "production_activation_allowed"))
HEX = set("0123456789abcdef")


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def _finite(value: Any) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


def audit_arm(name: str, result: Any, spec: dict) -> list[str]:
    errors = []
    if not isinstance(result, dict) or set(result) != KEYS:
        return [f"{name}: source schema incomplete or has unapproved fields"]
    if (result["schema"] != "hepta.neuron.replacement-physical-shadow.v1"
            or result["candidate"] != name or result["authority"] != "DENY_ALL"
            or result["mode"] != "SHADOW_ONLY" or result["production_activation_allowed"] is not False):
        errors.append(f"{name}: wrong arm or promoted authority")
    ck = result["checkpoint"]
    if (not isinstance(ck, dict) or ck.get("repository") != spec["repository"]
            or ck.get("revision") != spec["revision"]
            or ck.get("loaded_weight_sha256") != spec["weight_sha256"]
            or type(ck.get("weight_bytes")) is not int
            or ck["weight_bytes"] < 100_000_000):
        errors.append(f"{name}: checkpoint original-weight pin missing or mismatched")
    required_components = (("rl_agent_config.json", "encoder/config.json", "tokenizer/tokenizer.json")
                           if name.startswith("laya_") else ("config.json", "tokenizer.json"))
    components = ck.get("component_sha256") if isinstance(ck, dict) else None
    if (not isinstance(components, dict) or set(components) != set(required_components)
            or any(not _sha(digest) for digest in components.values())):
        errors.append(f"{name}: tokenizer/config component hashes not physically bound")
    kind = "full_policy" if name.startswith("laya_") else "encoder_plus_new_task_head"
    if result["execution_kind"] != kind:
        errors.append(f"{name}: encoder-only result cannot stand in for full policy")
    if type(result["loaded_parameter_count"]) is not int or result["loaded_parameter_count"] < 100_000_000:
        errors.append(f"{name}: physical tensor inventory absent")
    if not _sha(result["source_archive_sha256"]) or not _sha(result["frozen_selected_rows_sha256"]):
        errors.append(f"{name}: source and row manifest digests absent")
    if (type(result["per_split_limit"]) is not int or
            result["per_split_limit"] not in (0, 8, 12, 16, 20, 24, 32, 64, 96, 128)):
        errors.append(f"{name}: unexpected fixed sampling budget")
    splits = result["scores"]
    sample_count = 0
    if not isinstance(splits, dict) or set(splits) != set(SPLITS):
        return errors + [f"{name}: five disjoint raw score splits required"]
    observed_groups = set()
    for split in SPLITS:
        entry = splits[split]
        if not isinstance(entry, dict) or set(entry) != {"rows", "metrics"}:
            errors.append(f"{name}:{split}: exact raw rows and recomputed metrics required")
            continue
        rows = entry["rows"]
        try:
            if not isinstance(rows, list):
                raise ValueError("raw rows required")
            actual_metrics = score_rows(rows)
            # Exact equality is intentional: all P39 fields are produced by the same
            # deterministic score_rows implementation, not by a claimed model report.
            if actual_metrics != entry["metrics"]:
                errors.append(f"{name}:{split}: published metrics differ from raw rows")
            if split == "ood" and actual_metrics["ood_rows"] != len(rows):
                errors.append(f"{name}:{split}: OOD partition incorrect")
            if split != "ood" and actual_metrics["ood_rows"] != 0:
                errors.append(f"{name}:{split}: non-OOD partition contaminated")
            groups = {r["source_group_id"] for r in rows}
            if observed_groups & groups:
                errors.append(f"{name}:{split}: groups overlap across future/train cohorts")
            observed_groups |= groups
            if result["per_split_limit"] and len(rows) != result["per_split_limit"]:
                errors.append(f"{name}:{split}: wrong preregistered per-split size")
            if any(r["language"] != "en" for r in rows):
                errors.append(f"{name}:{split}: P39 historical pilot is English only")
            sample_count += len(rows)
        except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            errors.append(f"{name}:{split}: raw predictions rejected ({exc})")
    if type(result["observed_forward_calls"]) is not int or result["observed_forward_calls"] != sample_count:
        errors.append(f"{name}: model forward counter does not match raw samples")
    head = result["head_training"]
    if kind == "full_policy":
        if head is not None:
            errors.append(f"{name}: pretrained full policy cannot claim independently trained task Head")
    elif (not isinstance(head, dict)
          or head.get("seed") != TRAIN_SEED
          or head.get("steps") != TRAIN_STEPS
          or head.get("optimizer") != "AdamW"
          or head.get("learning_rate") != TRAIN_RATE
          or not _sha(head.get("head_initial_sha256"))
          or not _sha(head.get("head_trained_sha256"))
          or head.get("head_initial_sha256") == head.get("head_trained_sha256")
          or head.get("calibration_temperature") not in TEMPERATURES
          or type(head.get("head_parameters")) is not int
          or head["head_parameters"] < 4):
        errors.append(f"{name}: frozen equal-step Head training/temperature contract failed")
    perf = result["performance"]
    if not isinstance(perf, dict):
        errors.append(f"{name}: performance data missing")
    else:
        timing = perf.get("original_forward_latency_ms")
        if (perf.get("device") != "cpu"
                or type(perf.get("forward_count")) is not int
                or perf["forward_count"] != sample_count
                or not isinstance(timing, list) or len(timing) != sample_count
                or any(not _finite(x) or x <= 0 for x in timing)
                or not _finite(perf.get("load_ms")) or perf["load_ms"] <= 0
                or not _finite(perf.get("forward_latency_p50_ms"))
                or not _finite(perf.get("raw_forward_throughput_per_second"))
                or perf["raw_forward_throughput_per_second"] <= 0):
            errors.append(f"{name}: raw full-CPU forward timing sample/identity missing")
    # Pinned upstream Agent can normalize tokenizer_config.json in place.
    # A complete Laya shadow receipt must disclose its private compatibility
    # view and must never silently attribute rewritten bytes to the publisher.
    compat = perf.get("laya_tokenizer_compat") if isinstance(perf, dict) else None
    if name.startswith("laya_"):
        expected_keys = {"isolation", "original_tokenizer_inventory_sha256",
                         "effective_tokenizer_inventory_sha256",
                         "original_tokenizer_config_sha256",
                         "effective_tokenizer_config_sha256",
                         "registered_config_rewrite", "original_weight_sha256",
                         "no_original_snapshot_mutation_observed"}
        if not isinstance(compat, dict) or set(compat) != expected_keys:
            errors.append(f"{name}: missing isolated Laya tokenizer compatibility receipt")
        elif (
            compat["isolation"] != "private_tokenizer_copy_original_weight_symlink"
            or compat["original_weight_sha256"] != spec["weight_sha256"]
            or not _sha(compat["original_tokenizer_inventory_sha256"])
            or not _sha(compat["effective_tokenizer_inventory_sha256"])
            or any(value is not None and not _sha(value)
                   for value in (compat["original_tokenizer_config_sha256"],
                                 compat["effective_tokenizer_config_sha256"]))
            or type(compat["registered_config_rewrite"]) is not bool
            or compat["registered_config_rewrite"] !=
               (compat["original_tokenizer_inventory_sha256"] !=
                compat["effective_tokenizer_inventory_sha256"])
            or compat["registered_config_rewrite"] !=
               (compat["original_tokenizer_config_sha256"] !=
                compat["effective_tokenizer_config_sha256"])
            or compat["no_original_snapshot_mutation_observed"] is not True
        ):
            errors.append(f"{name}: inconsistent tokenizer rewrite or original-weight identity")
    elif compat is not None:
        errors.append(f"{name}: non-Laya Encoder must not claim Laya tokenizer compatibility")
    limits = result["limits"]
    if (not isinstance(limits, dict)
            or limits.get("historical_2014_dataset") is not True
            or limits.get("target_device_qualified") is not False
            or limits.get("prospective_holdout") is not False
            or limits.get("independent_observer_attested") is not False
            or limits.get("retrieval_quality_measured") is not False
            or limits.get("multilingual_quality_measured") is not False):
        errors.append(f"{name}: shadow-only research limitations are missing")
    return errors


def assess(registry: dict, observations: Any) -> dict:
    errors = validate_registry(registry)
    if not isinstance(observations, dict) or set(observations) != set(EXPECTED):
        errors.append("all five separately observed and uploaded original-output files required")
        observations = observations if isinstance(observations, dict) else {}
    for name in EXPECTED:
        errors.extend(audit_arm(name, observations.get(name), registry["models"][name]))
    if all(isinstance(observations.get(n), dict) for n in EXPECTED):
        try:
            fingerprints = {observations[n]["frozen_selected_rows_sha256"] for n in EXPECTED}
            archive_pins = {observations[n]["source_archive_sha256"] for n in EXPECTED}
            if len(fingerprints) != 1 or len(archive_pins) != 1:
                errors.append("model arms do not share one fixed source/row snapshot")
            for split in SPLITS:
                populations = []
                for name in EXPECTED:
                    rows = observations[name]["scores"][split]["rows"]
                    populations.append(tuple(
                        (r["source_id"], r["source_group_id"], r["label"], r["is_ood"])
                        for r in rows))
                if any(x != populations[0] for x in populations[1:]):
                    errors.append(f"{split}: real output samples differ across model arms")
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"cross-arm comparison rejected: {exc}")
    return {
        "schema": "hepta.neuron.five-model-physical-audit.v1",
        "raw_shadow_preflight": "BLOCKED" if errors else "REVIEW_REQUIRED",
        "blockers": sorted(set(errors)),
        "models_observed": sorted(k for k in EXPECTED if isinstance(observations.get(k), dict)),
        "all_six_production_blockers_closed": False,
        "production_activation_allowed": False,
        "authority": "DENY_ALL",
        "unclosed_external_gates": [
            "large independent preregistered full-policy/heldout results",
            "multilingual quality on real labeled non-English cohorts",
            "matched finetuning budget plus retrieval nDCG/MRR and Head artifact reloading",
            "independent calibration, selective risk, future/OOD negative transfer",
            "64/256/1024/4096 real target-host Cells and CPU/GPU/energy p95/p99",
            "Artifact CAS/checkpoint migration/CNS routing/fence/restart/rollback and signed Final-use denial"
        ],
    }


def load_directory(root: Path) -> dict:
    observed = {}
    for name in EXPECTED:
        path = root / name / "physical-output.json"
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
            continue
        observed[name] = json.loads(path.read_bytes())
    return observed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(Path(__file__).with_name("replacement_models.json")))
    parser.add_argument("--input-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        registry = json.loads(Path(args.registry).read_bytes())
        evidence = load_directory(args.input_directory)
        result = assess(registry, evidence)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result = {"raw_shadow_preflight": "BLOCKED", "blockers": [str(exc)],
                  "production_activation_allowed": False, "authority": "DENY_ALL"}
    raw = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(raw)
    print(raw)
    return 0 if result["raw_shadow_preflight"] == "REVIEW_REQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

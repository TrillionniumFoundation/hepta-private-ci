#!/usr/bin/env python3
"""Stdlib-only, nonauthorizing audit of three nominal Meta/Granite seed trials.

Identical original data plus zero-initialized, full-batch deterministic SGD
can make different seed labels numerical duplicates. Detect that, rather than
misreporting three independently sampled model fits or a statistical winner.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from qualification.cell_meta_execution_af import physical_router_audit as original_audit
from qualification.cell_meta_execution_af import physical_router_frozen_old_audit as frozen_audit

SEEDS = (41, 47, 53)
ARMS = ("no_change", "fixed_router", "learned_router", "adaptive_split", "frozen_old_parent")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise original_audit.AuditError(message)


def sha256_string(value: Any) -> bool:
    return (type(value) is str and len(value) == 64 and
            any(ch != '0' for ch in value) and
            all(ch in '0123456789abcdef' for ch in value))


def shared_inputs(panels: dict[int, dict[str, Any]]) -> str:
    """Require the same full training/evaluation material across seed labels."""
    require(type(panels) is dict and set(panels) == set(SEEDS), "exact seeded panel census")
    identities: set[str] = set()
    for seed in SEEDS:
        panel = panels[seed]
        frozen_audit.validate_panel_contract(panel)
        source = panel["source"]
        require(source["seed"] == seed and type(source["seed"]) is int, "seed misbinding")
        stable_source = {key: value for key, value in source.items() if key != "seed"}
        identities.add(original_audit.digest({"source": stable_source,
                                              "partitions": panel["partitions"]}))
    require(len(identities) == 1, "seed input drift: cannot compare numeric replicas")
    return next(iter(identities))


def classify_signatures(signatures: dict[int, dict[str, tuple[str, str]]]) -> dict[str, Any]:
    """Classify already-validated numerical outputs; hashes are not origin proof."""
    require(type(signatures) is dict and set(signatures) == set(SEEDS), "missing seeded fit")
    distinct: dict[str, int] = {}
    duplicates: dict[str, list[list[int]]] = {}
    for arm in ARMS:
        groups: dict[tuple[str, str], list[int]] = {}
        for seed in SEEDS:
            row = signatures[seed]
            require(type(row) is dict and set(row) == set(ARMS), "incomplete 5-arm census")
            pair = row[arm]
            require(type(pair) is tuple and len(pair) == 2 and
                    sha256_string(pair[0]) and sha256_string(pair[1]),
                    "invalid complete weight/prediction identity")
            groups.setdefault(pair, []).append(seed)
        distinct[arm] = len(groups)
        duplicates[arm] = [group for group in groups.values() if len(group) > 1]
    collapsed = all(count == 1 for count in distinct.values())
    return {
        "outcome": "IDENTICAL_NUMERIC_REPLICATES" if collapsed else "NUMERIC_VARIATION_ONLY",
        "registered_seed_labels": list(SEEDS),
        "nominal_trials": len(SEEDS),
        "unique_complete_weight_prediction_profiles": distinct,
        "identical_seed_clusters": duplicates,
        "minimum_unique_profiles": min(distinct.values()),
        "different_seed_labels_prove_independent_training": False,
        "independent_outcome_samples_established": False,
        "statistical_winner_certified": False,
        "ndu_selection_authorized": False,
        "production_admission": "BLOCKED",
        "authority_posture": "DENY_ALL",
    }


def audit(panels: dict[int, dict[str, Any]], trials: dict[int, dict[str, Any]],
          frozen: dict[int, dict[str, Any]],
          bridges: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run both original independent FP32 auditors before seed classification."""
    common_input_digest = shared_inputs(panels)
    require(type(trials) is dict and set(trials) == set(SEEDS), "incomplete original fits")
    require(type(frozen) is dict and set(frozen) == set(SEEDS), "incomplete frozen fits")
    if bridges is not None:
        require(type(bridges) is dict and set(bridges) == set(SEEDS), "incomplete bridge receipts")
    original_table_hash: str | None = None
    signatures: dict[int, dict[str, tuple[str, str]]] = {}
    steps: int | None = None
    for seed in SEEDS:
        p, t, f = panels[seed], trials[seed], frozen[seed]
        result = original_audit.validate(p, t)
        require(result["outcome"] == "NUMERIC_REPLAY_ONLY", "original FP32 replay incomplete")
        frozen_result = frozen_audit.validate(p, f, continued=t)
        require(frozen_result["outcome"] == "FROZEN_OLD_PARENT_REPLAY_ONLY", "frozen replay incomplete")
        require(frozen_result["existing_v1_no_change_is_frozen"] is False and
                frozen_result["training_budget_matched"] is False and
                frozen_result["production_admission"] == "BLOCKED", "false baseline claim")
        require(t["seed"] == seed and f["seed"] == seed, "result/seed mismatch")
        require(p["source"]["kind"] == "external_unverified" and
                t["future_window_prospective"] is False and
                f["future_window_prospective"] is False and
                t["ndu_selection_authorized"] is False and
                f["ndu_selection_authorized"] is False,
                "synthetic/real/prospective/authority confusion")
        trial_steps = t["training_steps_each_stage"]
        require(type(trial_steps) is int and trial_steps == f["optimizer_steps_old_only"],
                "old-stage training mismatch")
        if steps is None:
            steps = trial_steps
        require(steps == trial_steps, "cross-seed optimizer step drift")
        row: dict[str, tuple[str, str]] = {}
        for item in t["results"]:
            row[item["arm"]] = (item["weights_sha256"], item["prediction_sha256"])
        row["frozen_old_parent"] = (f["weights_sha256"], f["prediction_sha256"])
        signatures[seed] = row
        if bridges is not None:
            b = bridges[seed]
            require(type(b) is dict and b.get("schema") ==
                    "hepta.cell-meta-granite-retrospective-bind.v1" and
                    type(b.get("panel_seed")) is int and b["panel_seed"] == seed and
                    b.get("meta_trial_panel_sha256") == original_audit.digest(p) and
                    b.get("future_window_prospective") is False and
                    b.get("real_ood_verified") is False and
                    b.get("production_admission") == "BLOCKED" and
                    b.get("authority_posture") == "DENY_ALL", "bridge identity/authority drift")
            table_sha = b.get("real_encoder_feature_table_sha256")
            require(sha256_string(table_sha), "bridge table missing")
            if original_table_hash is None:
                original_table_hash = table_sha
            require(original_table_hash == table_sha, "different Q24 table across seeds")
    output = classify_signatures(signatures)
    output.update({"same_complete_seed_input_sha256": common_input_digest,
                   "all_original_four_arm_fp32_replays": True,
                   "all_frozen_fp32_replays": True,
                   "original_shared_q24_table_digest_claim": original_table_hash,
                   "pretrained_model_forward_independently_attested": False,
                   "future_windows_are_retrospective": True,
                   "total_lifecycle_compute_matched": False})
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root
        def rows(suffix: str) -> dict[int, dict[str, Any]]:
            return {seed: original_audit.load(root / f"{seed}-{suffix}.json") for seed in SEEDS}
        report = audit(rows("trial-panel"), rows("trial-report"),
                       rows("frozen-old-report"), rows("bridge-receipt"))
        payload = original_audit.canonical(report) + b"\n"
        require(len(payload) <= 65536, "seed report exceeded bounded size")
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps({"seed_census": report["outcome"],
                          "distinct": report["unique_complete_weight_prediction_profiles"],
                          "authority_posture": "DENY_ALL"}, sort_keys=True))
        return 0
    except (original_audit.AuditError, OSError, KeyError, TypeError, ValueError,
            IndexError, OverflowError, RecursionError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pair actual selected no-change evidence with Laya/Head trial observations.

Read-only evaluator diagnostic. Owner signatures attest imported claims, not
physical truth. Neither this code nor an improvement score can promote a model.
The independent evaluator must use a *sealed* cohort; the model worker must
never receive this file, its labels, or the baseline decision receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from hepta_neuron_real_cohort_preflight import (
    COHORT_SCHEMA,
    InvalidCohort,
    canonical,
    check_sha,
    check_time,
    read_json,
    read_sealed,
    require,
    sha_bytes,
    verify,
)
from hepta_neuron_paired_uncertainty import paired_cluster_interval
from hepta_neuron_model_trials import (
    ARMS,
    Q24,
    InvalidTrial,
    blind_rows,
    canonical_jsonl,
    compare,
    load_inputs,
    sha_file,
    checked_probabilities,
    write_new,
)

SCHEMA = "hepta.neuron.production-baseline-pair.v1"
REPORT_SCHEMA = "hepta.neuron.production-baseline-paired-evaluation.diagnostic.v1"
SIGNATURE_DOMAIN = b"hepta.neuron.production-baseline-pair.v1\x00"
WINDOWS = ("holdout", "future_1", "future_2")
SOURCE_SPLITS = ("calibration", *WINDOWS)
MAX_RECEIPT_BYTES = 4 * 1024 * 1024


def read_pinned(path: Path, max_bytes: int = MAX_RECEIPT_BYTES):
    path = Path(path)
    require(
        path.is_file()
        and not path.is_symlink()
        and 0 < path.stat().st_size <= max_bytes,
        "receipt must be bounded regular file without symlinks",
    )
    return read_json(path)


def _verify_owner_signature(receipt: dict, trust: dict, revalidated_time: int):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    require(
        isinstance(receipt, dict)
        and set(receipt) == {"schema", "body", "owner_signature"}
        and receipt["schema"] == SCHEMA,
        "unrecognized signed baseline receipt schema",
    )
    s = receipt["owner_signature"]
    require(
        isinstance(s, dict)
        and set(s)
        == {"role", "key_id", "signed_at_unix_micros", "signature_ed25519_hex"},
        "missing baseline owner signature",
    )
    owner = trust["roles"]["baseline_owner"]
    require(
        s["role"] == "baseline_owner"
        and s["key_id"] == owner["key_id"]
        and check_time(s["signed_at_unix_micros"])
        and s["signed_at_unix_micros"] >= revalidated_time,
        "baseline signed by wrong/early owner",
    )
    sig = s["signature_ed25519_hex"]
    require(
        isinstance(sig, str)
        and len(sig) == 128
        and all(c in "0123456789abcdef" for c in sig),
        "invalid baseline signature encoding",
    )
    message = SIGNATURE_DOMAIN + canonical(
        {
            "schema": SCHEMA,
            "body": receipt["body"],
            "role": s["role"],
            "key_id": s["key_id"],
            "signed_at_unix_micros": s["signed_at_unix_micros"],
        }
    )
    try:
        Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(owner["ed25519_public_key_hex"])
        ).verify(bytes.fromhex(sig), message)
    except (InvalidSignature, ValueError) as error:
        raise InvalidCohort("baseline owner signature failed") from error
    return sha_bytes(message)


def _check_baseline_receipt(
    receipt, cohort, sealed_rows, manifest_path, manifest, trust, cohort_path
):
    body = receipt["body"]
    require(
        isinstance(body, dict)
        and set(body)
        == {
            "cohort_sha256",
            "trial_manifest_sha256",
            "dataset_sha256",
            "blind_dataset_sha256",
            "source_dataset_digest",
            "frozen_plan_digest",
            "no_change",
            "revalidated_at_unix_micros",
            "observations",
        },
        "baseline packet missing full source/freeze/selected state binding",
    )
    payload = cohort["payload"]
    require(
        body["cohort_sha256"] == sha_file(cohort_path)
        and body["trial_manifest_sha256"] == sha_file(manifest_path)
        and body["dataset_sha256"] == manifest["dataset_sha256"]
        and body["blind_dataset_sha256"] == manifest["blind_dataset_sha256"]
        and body["source_dataset_digest"] == payload["dataset"]["dataset_digest"]
        and body["frozen_plan_digest"] == payload["frozen_plan_digest"]
        and body["no_change"] == payload["no_change"]
        and body["revalidated_at_unix_micros"]
        == payload["source_current_revalidated_at_unix_micros"],
        "baseline source, plan, bytes or current selected model drift",
    )
    require(
        body["no_change"]["kind"] in ("deployed_learned", "deployed_deterministic"),
        "test arm is not the selected production no-change",
    )
    signature_sha = _verify_owner_signature(
        receipt, trust, body["revalidated_at_unix_micros"]
    )
    rows = {r["id"]: r for r in sealed_rows if r["split"] in SOURCE_SPLITS}
    cohort_rows = {r["id"]: r for r in payload["rows"] if r["split"] in SOURCE_SPLITS}
    observed = body["observations"]
    require(
        isinstance(observed, list)
        and 1 <= len(observed) <= 4096
        and len(observed) == len(rows),
        "incomplete/no baseline outcome coverage",
    )
    results = {}
    family = manifest["family"]
    for item in observed:
        core = {
            "id",
            "split",
            "decision_record_digest",
            "observation_sha256",
            "production_runtime_receipt_digest",
            "decision_at_unix_micros",
            "generation",
        }
        extra = (
            {"drive_q24", "prediction_q24"}
            if family == "heads"
            else {"disposition", "selected_option"}
        )
        require(
            isinstance(item, dict) and set(item) == core | extra,
            "baseline decision row has missing/unexpected fields",
        )
        cid = item["id"]
        require(
            cid in rows and cid not in results,
            "unknown or duplicated baseline decision ID",
        )
        cohort_row = cohort_rows[cid]
        require(
            item["split"] == rows[cid]["split"] == cohort_row["split"]
            and item["decision_record_digest"] == cohort_row["decision_record_digest"]
            and item["observation_sha256"] == cohort_row["observation_sha256"],
            "baseline decision doesn't match original Ledger/source observation",
        )
        require(
            check_sha(item["production_runtime_receipt_digest"])
            and type(item["generation"]) is int
            and item["generation"] == body["no_change"]["generation"],
            "missing real per-event runtime/selected generation binding",
        )
        at = item["decision_at_unix_micros"]
        require(
            check_time(at)
            and cohort_row["observed_at_unix_micros"]
            <= at
            <= cohort_row["terminal_at_unix_micros"],
            "baseline decision cannot occur outside observed decision/outcome interval",
        )
        if family == "heads":
            width = len(rows[cid]["target_q24"]) // 2
            for key in ("drive_q24", "prediction_q24"):
                vec = item[key]
                require(
                    isinstance(vec, list)
                    and len(vec) == width
                    and width > 0
                    and all(type(x) is int and abs(x) <= 8 * Q24 for x in vec),
                    "baseline Q24 output dimensions/ranges differ from selected Cell",
                )
        else:
            disposition = item["disposition"]
            require(
                disposition in ("selected", "abstained", "slow_path"),
                "unrecognized production behavior disposition",
            )
            choice = item["selected_option"]
            require(
                (disposition == "selected" and choice in rows[cid]["option_order"])
                or (disposition != "selected" and choice is None),
                "baseline production choice/abstention is inconsistent",
            )
        results[cid] = item
    require(
        set(results) == set(rows), "baseline omitted a calibration/holdout/future event"
    )
    return results, signature_sha


def _selected_accuracy(bench, rows, family):
    scores = {}
    for split in WINDOWS:
        examples = [r for r in rows if r["split"] == split]
        require(examples, "missing paired true holdout/future cases")
        selected, correct, abstained, slow = 0, 0, 0, 0
        for row in examples:
            obs = bench[row["id"]]
            if family != "heads":
                if obs["disposition"] == "selected":
                    selected += 1
                    correct += int(obs["selected_option"] == row["gold"])
                elif obs["disposition"] == "abstained":
                    abstained += 1
                else:
                    slow += 1
        if family == "heads":
            pairs = [
                (
                    bench[row["id"]]["drive_q24"] + bench[row["id"]]["prediction_q24"],
                    row["target_q24"],
                )
                for row in examples
            ]
            mse = statistics.mean(
                ((x - y) / Q24) ** 2
                for pred, target in pairs
                for x, y in zip(pred, target)
            )
            scores[split] = {
                "count": len(examples),
                "mse": mse,
                "accuracy": None,
                "brier_multiclass": None,
                "ece10": None,
                "calibration_verified": False,
            }
        else:
            scores[split] = {
                "count": len(examples),
                "selected": selected,
                "abstained": abstained,
                "slow_path": slow,
                "selective_accuracy": correct / selected if selected else None,
                "correct_decision_coverage": correct / len(examples),
                "decision_coverage": selected / len(examples),
                "brier_multiclass": None,
                "ece10": None,
                "calibration_verified": False,
            }
    return scores


def _paired_deltas(rows, baseline, arm_receipts, family, seed_context):
    out = {}
    for arm in ARMS[family]:
        trial = {v["id"]: v for v in arm_receipts[arm]["observations"]}
        out[arm] = {}
        for window in WINDOWS:
            eligible = [r for r in rows if r["split"] == window]
            improved, harmed, unchanged = 0, 0, 0
            clustered_differences = []
            for r in eligible:
                current = baseline[r["id"]]
                candidate = trial[r["id"]]
                if family == "heads":
                    x = current["drive_q24"] + current["prediction_q24"]
                    y = candidate["drive_q24"] + candidate["prediction_q24"]
                    gold = r["target_q24"]
                    before = sum((a - c) ** 2 for a, c in zip(x, gold))
                    after = sum((a - c) ** 2 for a, c in zip(y, gold))
                    new_win, harm = after < before, after > before
                    clustered_differences.append(
                        (
                            r["source_group"],
                            (after - before) / (len(gold) * Q24**2),
                        )
                    )
                else:
                    # A model's answer is not the production policy. This is
                    # only a paired accuracy proxy on independently sealed labels.
                    options = r["option_order"]
                    probs = checked_probabilities(
                        candidate["probabilities"], len(options)
                    )
                    model_choice = options[
                        max(range(len(options)), key=probs.__getitem__)
                    ]
                    if current["disposition"] != "selected":
                        # Abstentions/slow-path are reported separately, not
                        # misclassified as wrong predictions.
                        continue
                    old_right = current["selected_option"] == r["gold"]
                    new_right = model_choice == r["gold"]
                    new_win, harm = (
                        (not old_right and new_right),
                        (old_right and not new_right),
                    )
                    clustered_differences.append(
                        (r["source_group"], int(new_right) - int(old_right))
                    )
                improved += int(new_win)
                harmed += int(harm)
                unchanged += int(not new_win and not harm)
            paired_n = improved + harmed + unchanged
            out[arm][window] = {
                "paired_count": paired_n,
                "candidate_better_count": improved,
                "candidate_worse_count": harmed,
                "candidate_equal_count": unchanged,
                "paired_net_accuracy_proxy": ((improved - harmed) / paired_n)
                if family != "heads" and paired_n
                else None,
                "paired_mean_mse_delta": None,
                "baseline_abstentions_or_slow_path_excluded": len(eligible) - paired_n
                if family != "heads"
                else 0,
            }
            if family == "heads":
                out[arm][window]["paired_mean_mse_delta"] = statistics.mean(
                    value for _, value in clustered_differences
                )
            # Resample whole source groups, never correlated rows. Fewer than
            # eight groups explicitly give null bounds instead of fake precision.
            # This is still a diagnostic proxy, not an NDU or promotion gate.
            out[arm][window]["paired_uncertainty"] = (
                paired_cluster_interval(
                    clustered_differences,
                    seed_identity=f"{seed_context}:{arm}:{window}",
                    unit="mse" if family == "heads" else "accuracy",
                )
                if clustered_differences
                else None
            )
    return out


def compare_to_production(
    cohort_path: Path,
    sealed_path: Path,
    trust_path: Path,
    trust_sha: str,
    manifest_path: Path,
    baseline_path: Path,
    arm_paths: dict[str, Path],
):
    # This verifies role signatures over complete cohort and source membership,
    # but not native LedgerWriter current state or host clock truth.
    verify(cohort_path, sealed_path, trust_path, trust_sha)
    cohort = read_pinned(cohort_path)
    trust = read_pinned(trust_path)
    sealed = read_sealed(sealed_path)
    for path in [manifest_path, baseline_path, *arm_paths.values()]:
        read_pinned(path)
    manifest, rows = load_inputs(manifest_path, sealed_path, role="evaluator")
    require(
        manifest["family"] == cohort["payload"]["family"],
        "real Ledger cohort differs from the model experiment family",
    )
    require(
        manifest["dataset_sha256"] == sha_file(sealed_path)
        and manifest["blind_dataset_sha256"]
        == hashlib.sha256(
            canonical_jsonl(blind_rows(rows, manifest["family"]))
        ).hexdigest(),
        "trial manifest not tied to sealed and blinded original bytes",
    )
    packet = read_pinned(baseline_path)
    owner_observed, signature_sha = _check_baseline_receipt(
        packet, cohort, sealed, manifest_path, manifest, trust, cohort_path
    )
    require(
        set(arm_paths) == set(ARMS[manifest["family"]]),
        "all external A/B trial arms required (no cherry-picked candidate)",
    )
    test_baseline_arm = ARMS[manifest["family"]][0]
    external_comparison = compare(
        manifest, rows, arm_paths, sha_file(arm_paths[test_baseline_arm])
    )
    trial_receipts = {arm: read_pinned(path) for arm, path in arm_paths.items()}
    baseline_metrics = _selected_accuracy(owner_observed, sealed, manifest["family"])
    paired = _paired_deltas(
        sealed,
        owner_observed,
        trial_receipts,
        manifest["family"],
        f"{sha_file(cohort_path)}:{sha_file(baseline_path)}:{manifest['family']}",
    )
    return {
        "schema": REPORT_SCHEMA,
        "status": "signed-claims-and-paired-diagnostic-only",
        "family": manifest["family"],
        "cohort_sha256": sha_file(cohort_path),
        "baseline_receipt_sha256": sha_file(baseline_path),
        "baseline_owner_signature_message_sha256": signature_sha,
        "trial_manifest_sha256": sha_file(manifest_path),
        "frozen_plan_digest": cohort["payload"]["frozen_plan_digest"],
        "production_no_change": {
            "kind": cohort["payload"]["no_change"]["kind"],
            "selected_snapshot_digest": sha_bytes(
                canonical(cohort["payload"]["no_change"])
            ),
            "measured": baseline_metrics,
        },
        "external_arm_comparison": external_comparison,
        "production_baseline_paired_proxies": paired,
        "caveat": "Signatures establish attribution of imported claims, not physical owner status or causal utility; paired accuracy/MSE is not NDU gain. No automatic promotion.",
        "actual_native_ledger_reopened_and_revalidated_here": False,
        "production_baseline_executed_by_this_process": False,
        "independent_future_calendar_attestation_verified_here": False,
        "ndu_net_gain_verified": False,
        "selection_authorized": False,
        "production_promotion_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", required=True, type=Path)
    parser.add_argument("--sealed", required=True, type=Path)
    parser.add_argument("--trusted-issuers", required=True, type=Path)
    parser.add_argument("--trust-sha256", required=True)
    parser.add_argument("--trial-manifest", required=True, type=Path)
    parser.add_argument("--production-baseline", required=True, type=Path)
    parser.add_argument(
        "--arm-receipt",
        action="append",
        default=[],
        help="arm=/absolute/file.json; all family arms required",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        pairs = [entry.split("=", 1) for entry in args.arm_receipt]
        require(
            all(len(x) == 2 for x in pairs)
            and len(set(x[0] for x in pairs)) == len(pairs),
            "duplicate or malformed arm=path",
        )
        require(
            args.output.is_absolute() and not args.output.exists(),
            "diagnostic receipt path must be new and absolute",
        )
        result = compare_to_production(
            args.cohort,
            args.sealed,
            args.trusted_issuers,
            args.trust_sha256,
            args.trial_manifest,
            args.production_baseline,
            {arm: Path(path) for arm, path in pairs},
        )
        write_new(args.output, result)
    except (
        InvalidCohort,
        InvalidTrial,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        ZeroDivisionError,
    ) as exc:
        parser.exit(2, f"blocked: {exc}\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Exact-source, read-only audit preserving P1's preregistered negative result.

Does not authenticate raw heldout worlds or create new scientific evidence.
"""
import argparse
import json
import math
from pathlib import Path


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def audit(protocol, summary, review):
    _require(protocol.get("protocol_id") == "hepta-output-portfolio-pilot-v1.1-20261021", "protocol identity")
    _require(summary.get("protocol_id") == protocol["protocol_id"], "summary protocol identity")
    _require(summary.get("execution_tier") == "local-preflight", "provenance unexpectedly changed")
    _require(summary.get("seeds") == protocol["seeds"] == [17, 29, 43], "seed identity")
    _require(summary.get("audit_count") == 32, "oracle audit-count mismatch")
    _require(not summary.get("primary_claim_passed"), "unexpected reported primary success")
    _require(review.get("primary_claim_passed_recorded") is False, "review primary claim changed")
    _require(review.get("validity_assessment", {}).get("scientific_claim_confirmed_on_fresh_holdout") is False,
             "review independent conclusion changed")
    _require(review.get("violations") == {}, "unresolved review violations")
    _require(review.get("counts", {}).get("unique_worlds") == 8064, "world-count provenance")
    _require(review.get("counts", {}).get("oracle_augmented_states_checked") == 403712, "oracle provenance")
    _require(review.get("oracle", {}).get("value_action_stop_portfolio_mismatches") == 0, "oracle mismatch")

    comp = protocol["primary_comparison"]
    _require(comp["contrast"] == "ndu_recursive_dp minus validation_selected_fixed_portfolio", "different estimand")
    _require(comp["budget"] == 4 and comp["scenario"] == "test_iid", "changed primary scope")
    minimum = comp["minimum_reduction"]
    _require(minimum == 0.02, "changed primary practical margin")
    summary_primary = summary["primary_budget4_iid_contrasts"]["validation_selected_fixed_portfolio"]
    review_primary = review["contrasts_budget4_iid"]["validation_selected_fixed_portfolio"]
    original = summary_primary["cvar90"]
    independent = review_primary["cvar90"]
    for key in ("estimate", "ci_low", "ci_high"):
        a = original[key]
        b = independent[key]
        _require(math.isfinite(a) and math.isfinite(b) and abs(a - b) < 1e-10,
                 "summary/review discrepancy for " + key)
    _require(original["n_seeds"] == 3 and original["n_worlds_per_seed"] == 1536, "primary sample size")
    _require(original["ci_low"] <= original["estimate"] <= original["ci_high"], "invalid interval")
    _require(original["ci_high"] >= 0 and (-original["estimate"] < minimum),
             "this frozen heldout would not be a failed primary result")
    _require(review["primary_gates_recomputed"] == summary["primary_gates"], "primary gate divergence")
    gates = summary["primary_gates"]
    _require(gates["cvar_reduction_at_least_0_02"] is False, "practical threshold rewritten")
    _require(gates["cvar_95pct_interval_below_zero"] is False, "CI gate rewritten")
    _require(gates["verified_dedicated_cloud"] is False, "dedicated cloud incorrectly claimed")
    _require(review["key_findings"]["incremental_ndu_preference"]["incremental_superiority_demonstrated"] is False,
             "false incremental NDU claim")
    _require(review["key_findings"]["recursion"]["primary_recursive_benefit_demonstrated"] is False,
             "false recursive benefit")
    _require(review["amendment_checks"]["amendment_published_before_runtime"] is True,
             "amendment provenance invalid")
    _require(review["integrity"]["remote_source_commit"]["sha"] ==
             "f44540ab59a0a8f013437ccbe8579db607fac03e", "amendment source changed")
    return {
        "scope": "frozen_prior_local_evidence_only",
        "qualification": "P1_HOLD_NO_GO",
        "fresh_holdout_cv ar90_delta".replace(" ", ""): original["estimate"],
        "confidence_interval": [original["ci_low"], original["ci_high"]],
        "required_absolute_reduction": minimum,
        "dedicated_execution_accepted": False,
        "note": "Cross-check of published summaries, not a rerun or independent raw-world audit."
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    try:
        p = args.pilot_root
        protocol = json.loads((p / "protocol.json").read_text())
        evidence = p / "evidence"
        summary = json.loads((evidence / "local_preflight_v1_1_summary.json").read_text())
        review = json.loads((evidence / "independent_review_v1_1.json").read_text())
        result = audit(protocol, summary, review)
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("HOLD_NO_GO: legacy evidence audit failed:", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

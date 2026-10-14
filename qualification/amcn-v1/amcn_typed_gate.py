"""Conservative typed MemoryCell research gate; never self-authorizes deployment.

A complete score receipt is necessary but insufficient: prospective source
independence and original Reader/RAG task-success must arrive from separately
qualified owners. This module deliberately cannot manufacture their signatures.
"""
from __future__ import annotations

from amcn_core import digest, is_sha, require, shadow_disposition

PROFILE = "hepta.amcn.typed-evidence-gate.shadow.v1"
ARMS = frozenset(("frozen", "single_shared", "untyped_equal_budget",
                  "typed_equal_budget", "typed_swapped_negative"))
FUTURES = ("future_a", "future_b")


def typed_evidence_gate(score_receipt, *, external_evidence=None):
    """Fail closed with explicit blockers; no promotion / operator permission.

    The external input is an audit inventory, not an authoritative signature.
    It cannot transform externally *claimed* successes into trusted facts.
    """
    require(isinstance(score_receipt, dict)
            and score_receipt.get("production_accepted") is False,
            "non-authorizing original score required")
    m = score_receipt.get("metrics")
    require(isinstance(m, dict) and
            m.get("profile") == "hepta.amcn.typed-equal-budget.shadow.v1.heldout-score",
            "original typed scoring profile required")
    require(all(is_sha(m.get(x)) for x in
                ("features_sha256", "type_inventory_sha256",
                 "original_predictions_sha256")), "unbound score identity")
    rows = m.get("descriptive_scores")
    require(isinstance(rows, list), "no original scored census")
    by_key = {}
    for r in rows:
        require(isinstance(r, dict) and set(r) ==
                {"split", "arm", "n", "accuracy", "brier"},
                "original score schema drift")
        split, arm = r["split"], r["arm"]
        require(split in ("select", "future_a", "future_b", "retention")
                and arm in ARMS and (split, arm) not in by_key,
                "invalid or duplicated score arm")
        require(type(r["n"]) is int and r["n"] >= 1
                and type(r["accuracy"]) in (int, float)
                and type(r["brier"]) in (int, float)
                and 0 <= r["accuracy"] <= 1 and 0 <= r["brier"] <= 1,
                "score values invalid")
        by_key[(split, arm)] = r
    require(all((split, arm) in by_key for split in FUTURES for arm in ARMS),
            "missing future split or control")
    for split in FUTURES:
        counts = {by_key[(split, arm)]["n"] for arm in ARMS}
        require(len(counts) == 1, "unpaired future case count")
    require(type(m.get("complete_case_count")) is int
            and m["complete_case_count"] >=
            sum(by_key[(s, "typed_equal_budget")]["n"] for s in FUTURES),
            "incomplete scored census")

    blockers = ["no independent prospective calendar-window observation",
                "no source-family independent effective-sample proof",
                "no externally adjudicated paired Reader task-success",
                "no original same-budget strong-hybrid-RAG comparisons",
                "no independently verified citation entailment",
                "no signed evaluator / selector / artifact final-use grants",
                "no validated full lifecycle costs and revocation"]
    if external_evidence is not None:
        require(isinstance(external_evidence, dict) and
                set(external_evidence) ==
                {"source_family_count", "calendar_window_count",
                 "reader_evaluated", "strong_rag_evaluated"},
                "unknown external evidence contract")
        require(type(external_evidence["source_family_count"]) is int and
                0 <= external_evidence["source_family_count"] <= 10**7
                and type(external_evidence["calendar_window_count"]) is int
                and 0 <= external_evidence["calendar_window_count"] <= 1000
                and all(type(external_evidence[x]) is bool
                        for x in ("reader_evaluated", "strong_rag_evaluated")),
                "invalid external inventory")
        # Claim flags are not source receipts, signatures or independent judges.
        blockers.append("external inventory is unauthenticated commentary")
    observed = {
        s: by_key[(s, "typed_equal_budget")]["accuracy"]
           - by_key[(s, "untyped_equal_budget")]["accuracy"]
        for s in FUTURES
    }
    return shadow_disposition(
        profile=PROFILE,
        original_score_sha256=digest(score_receipt),
        prospective_accuracy_delta_descriptive=observed,
        insufficient_for_production=True,
        independently_verified_effective_sample_count=None,
        independently_verified_future_windows=None,
        qualifying_reader_success_delta=None,
        strong_rag_utility_delta=None,
        full_lifecycle_cost_delta=None,
        all_required_gates_pass=False,
        blocking_reasons=blockers,
    )

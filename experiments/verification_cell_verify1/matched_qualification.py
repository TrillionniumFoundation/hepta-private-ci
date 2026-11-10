"""Fail-closed paired prospective evaluation of advisory VERIFY schedulers.

This is a *scoring* boundary, not an evaluator, a receipt signer or an
independence proof. Authenticator callbacks must verify original external
receipts against a separately frozen study; an issuer string/digest is not an
attestation. No result from this module grants execution or production rights.
"""

from collections import defaultdict
import hashlib
import itertools
import json
import math

DISPOSITIONS = ("accept", "reject", "interrupted", "unknown")
SHA_LEN = 64
MAX_PAIRS = 1000
MAX_SIGNFLIP_GROUPS = 20


def _require(condition, explanation):
    if not condition:
        raise ValueError(explanation)


def _sha(value):
    return (
        type(value) is str
        and len(value) == SHA_LEN
        and all(char in "0123456789abcdef" for char in value)
    )


def _text(value):
    return type(value) is str and 0 < len(value) <= 256


def _nonnegative(value):
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1e12


def _probability(value):
    return _nonnegative(value) and value <= 1


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _exact_signflip(deltas):
    """One-sided whole-cluster sign flips of contributions to the pair mean."""
    _require(0 < len(deltas) <= MAX_SIGNFLIP_GROUPS, "unsupported sign-flip size")
    observed = math.fsum(deltas)
    threshold = observed - 1e-10 * max(1.0, math.fsum(abs(x) for x in deltas))
    tail = 0
    # Simple enumeration deliberately limits the audit to 2^20 signs.
    for signs in itertools.product((-1, 1), repeat=len(deltas)):
        if math.fsum(x * s for x, s in zip(deltas, signs)) >= threshold:
            tail += 1
    return tail / (2 ** len(deltas))


def _design_status(manifest, design, verify_design):
    """Check the supported allocation design; hashes alone establish no trust.

    This scorer supports one independent fair coin per cluster, with that coin
    assigning the same first arm to every pair in the cluster. Other matched or
    observational designs need their own inference procedure.
    """
    assignments = defaultdict(set)
    for pair in manifest["pairs"]:
        assignments[pair["cluster_id"]].add(pair["first_arm"])
    consistent = all(len(values) == 1 for values in assignments.values())
    assignment_sha = _digest(sorted(manifest["pairs"], key=lambda p: p["pair_id"]))
    keys = {
        "schema",
        "manifest_sha256",
        "assignment_sha256",
        "method",
        "authority_id",
        "frozen_ns",
        "evidence_sha256",
        "attestation",
    }
    bound = (
        type(design) is dict
        and set(design) == keys
        and design["schema"] == "hepta.verify.cluster-randomization.v1"
        and design["method"] == "independent_fair_cluster_coin"
        and design["manifest_sha256"] == _digest(manifest)
        and design["assignment_sha256"] == assignment_sha
        and _text(design["authority_id"])
        and _text(design["attestation"])
        and _sha(design["evidence_sha256"])
        and type(design["frozen_ns"]) is int
        and 0 <= design["frozen_ns"] <= manifest["freeze_ns"]
    )
    authenticated = False
    if bound and consistent:
        receipt_sha = _digest(design)
        try:
            authenticated = (
                verify_design is not None and verify_design(manifest, design) is True
            )
        except Exception:
            authenticated = False
        _require(_digest(design) == receipt_sha, "design changed during authentication")
    return consistent, bound, authenticated, assignment_sha


def _validate_manifest(manifest):
    keys = {
        "schema",
        "source_sha256",
        "target_sha256",
        "risk_model_sha256",
        "checker_model_sha256",
        "scheduler_sha256",
        "evaluator_id",
        "continuation_policy_sha256",
        "horizon_end",
        "evaluator_version_sha256",
        "baseline",
        "candidate",
        "pairs",
        "losses",
        "criteria",
        "freeze_ns",
        "cost_unit",
    }
    _require(
        type(manifest) is dict and set(manifest) == keys, "manifest fields changed"
    )
    _require(
        manifest["schema"] == "hepta.verify.matched-qualification.v1", "manifest schema"
    )
    for key in (
        "source_sha256",
        "target_sha256",
        "risk_model_sha256",
        "checker_model_sha256",
        "scheduler_sha256",
        "evaluator_version_sha256",
        "continuation_policy_sha256",
    ):
        _require(_sha(manifest[key]), "invalid " + key)
    for key in ("evaluator_id", "baseline", "candidate", "cost_unit"):
        _require(_text(manifest[key]), "invalid " + key)
    _require(manifest["baseline"] != manifest["candidate"], "same arms")
    _require(
        type(manifest["horizon_end"]) is int and 0 < manifest["horizon_end"] <= 1000000,
        "invalid terminal horizon",
    )
    _require(
        type(manifest["freeze_ns"]) is int and 0 <= manifest["freeze_ns"] < 2**63,
        "invalid freeze time",
    )
    pairs = manifest["pairs"]
    _require(
        type(pairs) is list and 0 < len(pairs) <= MAX_PAIRS, "invalid frozen pairs"
    )
    pair_ids = set()
    environment_sessions = set()
    for pair in pairs:
        _require(
            type(pair) is dict
            and set(pair)
            == {"pair_id", "cluster_id", "first_arm", "environment_a", "environment_b"},
            "invalid pair entry",
        )
        _require(
            all(
                _text(pair[key])
                for key in ("pair_id", "cluster_id", "environment_a", "environment_b")
            ),
            "invalid pair identity",
        )
        _require(pair["pair_id"] not in pair_ids, "duplicate pair")
        pair_ids.add(pair["pair_id"])
        _require(
            pair["first_arm"] in (manifest["baseline"], manifest["candidate"]),
            "invalid assignment",
        )
        _require(
            pair["environment_a"] != pair["environment_b"],
            "same physical environment for paired effects",
        )
        for environment in (pair["environment_a"], pair["environment_b"]):
            _require(
                environment not in environment_sessions,
                "reused physical environment session",
            )
            environment_sessions.add(environment)
    losses = manifest["losses"]
    _require(
        type(losses) is dict and set(losses) == set(DISPOSITIONS),
        "loss table incomplete",
    )
    for disposition in DISPOSITIONS:
        _require(
            type(losses[disposition]) is dict
            and set(losses[disposition]) == {"correct", "error"}
            and all(_nonnegative(v) for v in losses[disposition].values()),
            "invalid disposition loss",
        )
    c = manifest["criteria"]
    _require(
        type(c) is dict
        and set(c)
        == {
            "max_error_increase_per_task",
            "min_candidate_coverage",
            "max_coverage_drop",
            "min_terminal_error_reduction_per_task",
            "min_mean_gain",
            "max_one_sided_p",
        }
        and all(
            _probability(c[k])
            for k in (
                "max_error_increase_per_task",
                "min_candidate_coverage",
                "max_coverage_drop",
                "max_one_sided_p",
                "min_terminal_error_reduction_per_task",
            )
        )
        and _nonnegative(c["min_mean_gain"]),
        "invalid frozen criteria",
    )
    return {p["pair_id"]: p for p in pairs}


def _validate_observation(row, manifest, pairs):
    keys = {
        "pair_id",
        "arm",
        "environment_id",
        "disposition",
        "terminal_error",
        "label_evidence_sha256",
        "label_issued_ns",
        "label_observed_step",
        "decision_issued_ns",
        "evaluator_id",
        "label_attestation",
        "cost_units",
        "cost_roster_sha256",
        "cost_receipt_sha256",
        "source_sha256",
    }
    _require(type(row) is dict and set(row) == keys, "observation fields changed")
    _require(
        row["pair_id"] in pairs
        and row["arm"] in (manifest["baseline"], manifest["candidate"]),
        "unplanned observation",
    )
    pair = pairs[row["pair_id"]]
    expected_env = (
        pair["environment_a"]
        if row["arm"] == pair["first_arm"]
        else pair["environment_b"]
    )
    _require(row["environment_id"] == expected_env, "environment or assignment drift")
    _require(row["disposition"] in DISPOSITIONS, "invalid disposition")
    _require(
        _sha(row["source_sha256"])
        and row["source_sha256"] == manifest["source_sha256"],
        "source drift",
    )
    _require(
        type(row["decision_issued_ns"]) is int
        and manifest["freeze_ns"] <= row["decision_issued_ns"] < 2**63,
        "decision predates freeze",
    )
    label = row["terminal_error"]
    _require(label is None or type(label) is bool, "invalid terminal label")
    if label is None:
        _require(
            row["label_evidence_sha256"] is None
            and row["label_issued_ns"] is None
            and row["label_observed_step"] is None
            and row["label_attestation"] is None
            and row["evaluator_id"] is None,
            "fabricated missing-label receipt",
        )
    else:
        _require(
            _sha(row["label_evidence_sha256"])
            and type(row["label_issued_ns"]) is int
            and row["decision_issued_ns"] <= row["label_issued_ns"] < 2**63
            and type(row["label_observed_step"]) is int
            and row["label_observed_step"] >= manifest["horizon_end"]
            and _text(row["label_attestation"])
            and row["evaluator_id"] == manifest["evaluator_id"],
            "unbound or early terminal label",
        )
    _require(
        row["cost_units"] is None or _nonnegative(row["cost_units"]),
        "invalid cost units",
    )
    if row["cost_units"] is None:
        _require(
            row["cost_roster_sha256"] is None and row["cost_receipt_sha256"] is None,
            "unbound missing cost",
        )
    else:
        _require(
            _sha(row["cost_roster_sha256"]) and _sha(row["cost_receipt_sha256"]),
            "cost evidence missing",
        )


def _arm_metrics(rows, planned):
    accepts = sum(r["disposition"] == "accept" for r in rows)
    accepted_errors = sum(
        r["disposition"] == "accept" and r["terminal_error"] is True for r in rows
    )
    missing_accepts = sum(
        r["disposition"] == "accept" and r["terminal_error"] is None for r in rows
    )
    missing_total = planned - sum(r["terminal_error"] is not None for r in rows)
    unobserved = planned - len(rows)
    possible_accepts = accepts + unobserved
    known_clean = sum(r["terminal_error"] is False for r in rows)
    blocked = [r for r in rows if r["disposition"] in ("reject", "interrupted")]
    clean_blocked = sum(r["terminal_error"] is False for r in blocked)
    blocked_missing = sum(r["terminal_error"] is None for r in blocked)
    return {
        "planned": planned,
        "observed": len(rows),
        "unobserved": unobserved,
        "accepted": accepts,
        "acceptance_coverage": accepts / planned if not unobserved else None,
        "acceptance_coverage_bounds": [accepts / planned, possible_accepts / planned],
        "accepted_error_count_known": accepted_errors,
        "accepted_missing_label_count": missing_accepts,
        "accepted_error_rate_bounds": (
            [
                accepted_errors / possible_accepts,
                (accepted_errors + missing_accepts + unobserved) / possible_accepts,
            ]
            if possible_accepts
            else None
        ),
        "accepted_errors_per_planned_bounds": [
            accepted_errors / planned,
            (accepted_errors + missing_accepts + unobserved) / planned,
        ],
        "terminal_error_rate_bounds": [
            sum(r["terminal_error"] is True for r in rows) / planned,
            (sum(r["terminal_error"] is True for r in rows) + missing_total) / planned,
        ],
        "known_terminal_labels": planned - missing_total,
        "missing_terminal_labels": missing_total,
        "by_disposition": {
            disposition: {
                "observed": sum(r["disposition"] == disposition for r in rows),
                "known_clean": sum(
                    r["disposition"] == disposition and r["terminal_error"] is False
                    for r in rows
                ),
                "known_errors": sum(
                    r["disposition"] == disposition and r["terminal_error"] is True
                    for r in rows
                ),
                "missing_labels": sum(
                    r["disposition"] == disposition and r["terminal_error"] is None
                    for r in rows
                ),
            }
            for disposition in DISPOSITIONS
        },
        "clean_blocked_count_known": clean_blocked,
        "clean_blocked_per_planned_bounds": [
            clean_blocked / planned,
            (clean_blocked + blocked_missing + unobserved) / planned,
        ],
        "clean_blocked_rate_among_known_clean": (
            clean_blocked / known_clean if known_clean else None
        ),
        # A clean outcome may have resulted from a successful intervention.
        # These labels alone cannot identify an unnecessary intervention.
        "causal_false_interruption_rate": None,
        "clean_blocked_interpretation": "post_decision_clean_not_causal_false_positive",
        "unknown_dispositions": sum(r["disposition"] == "unknown" for r in rows),
        "cost_missing_or_unobserved": planned
        - sum(r["cost_units"] is not None for r in rows),
        "known_partial_cost_units": math.fsum(r["cost_units"] or 0 for r in rows),
    }


def analyze_matched(
    manifest,
    observations,
    *,
    verify_label=None,
    verify_cost=None,
    design=None,
    verify_design=None,
):
    """Return complete-denominator diagnostics, never self-authorized promotion.

    `verify_label(manifest,row)` must check independently held original evidence,
    including signed actor/version and canonical task relation. `verify_cost` must
    also prove full physical roster attribution, not merely receipt formatting.
    `verify_design(manifest,design)` must authenticate independently held study
    authority and original allocation evidence: criteria/roster fixed before
    outcomes, independent fair cluster coins, and no cross-arm interference.
    The checked component must not supply its own trusted verifier or trust root.
    Receipt fields and timestamps are assertions until that host verifier checks
    them. Without this bound receipt the sign-flip value is diagnostic only.
    Passing a callback is a host assertion; independent custody is not established
    by this implementation or by source-group strings.
    """
    pairs = _validate_manifest(manifest)
    _require(
        type(observations) is list and len(observations) <= 2 * len(pairs),
        "invalid observation roster",
    )
    seen = {}
    for row in observations:
        _validate_observation(row, manifest, pairs)
        key = (row["pair_id"], row["arm"])
        _require(key not in seen, "duplicate observation")
        seen[key] = row
    _require(verify_label is None or callable(verify_label), "invalid label verifier")
    _require(verify_cost is None or callable(verify_cost), "invalid cost verifier")
    _require(
        verify_design is None or callable(verify_design), "invalid design verifier"
    )
    input_sha = _digest([manifest, observations])
    consistent, design_bound, design_ok, assignment_sha = _design_status(
        manifest, design, verify_design
    )
    arms = (manifest["baseline"], manifest["candidate"])
    results = {
        arm: _arm_metrics(
            [row for (pid, a), row in seen.items() if a == arm], len(pairs)
        )
        for arm in arms
    }
    label_ok, cost_ok = True, True
    for row in observations:
        if row["terminal_error"] is not None:
            # Fail closed: no callback, exception, None or truthy non-bool is not proof.
            try:
                okay = verify_label is not None and verify_label(manifest, row) is True
            except Exception:
                okay = False
            label_ok &= okay
        if row["cost_units"] is not None:
            try:
                okay = verify_cost is not None and verify_cost(manifest, row) is True
            except Exception:
                okay = False
            cost_ok &= okay
    _require(
        _digest([manifest, observations]) == input_sha,
        "validated inputs changed during authentication",
    )
    fully_observed = len(seen) == 2 * len(pairs)
    all_labels_known = fully_observed and all(
        r["terminal_error"] is not None for r in observations
    )
    all_costs_known = fully_observed and all(
        r["cost_units"] is not None for r in observations
    )
    label_ok = label_ok and all_labels_known
    cost_ok = cost_ok and all_costs_known
    group_effects = defaultdict(list)
    paired_gain = None
    p_value = None
    if all_labels_known and all_costs_known:
        per_pair_gains = []
        for pid, pair in pairs.items():
            values = {}
            for arm in arms:
                row = seen[pid, arm]
                truth = "error" if row["terminal_error"] else "correct"
                values[arm] = (
                    manifest["losses"][row["disposition"]][truth] + row["cost_units"]
                )
            gain = values[manifest["baseline"]] - values[manifest["candidate"]]
            per_pair_gains.append(gain)
            group_effects[pair["cluster_id"]].append(gain)
        paired_gain = math.fsum(per_pair_gains) / len(per_pair_gains)
        if len(group_effects) <= MAX_SIGNFLIP_GROUPS:
            # Retain frozen pair-count weights in the reported pair-mean estimand.
            # Cluster randomization flips the whole contribution, not each pair.
            cluster_contributions = [
                math.fsum(g) / len(pairs) for _, g in sorted(group_effects.items())
            ]
            p_value = _exact_signflip(cluster_contributions)
    base, candidate, c = results[arms[0]], results[arms[1]], manifest["criteria"]
    coverage_ok = (
        fully_observed
        and candidate["acceptance_coverage"] >= c["min_candidate_coverage"]
        and candidate["acceptance_coverage"] + c["max_coverage_drop"]
        >= base["acceptance_coverage"]
    )
    error_ok = (
        all_labels_known
        and candidate["accepted_errors_per_planned_bounds"][1]
        <= base["accepted_errors_per_planned_bounds"][0]
        + c["max_error_increase_per_task"]
    )
    terminal_reduction = (
        base["terminal_error_rate_bounds"][0]
        - candidate["terminal_error_rate_bounds"][1]
        if all_labels_known
        else None
    )
    terminal_improved = (
        terminal_reduction is not None
        and terminal_reduction > 0
        and terminal_reduction >= c["min_terminal_error_reduction_per_task"]
    )
    gain_ok = (
        paired_gain is not None
        and paired_gain > 0
        and paired_gain >= c["min_mean_gain"]
    )
    p_ok = design_ok and p_value is not None and p_value <= c["max_one_sided_p"]
    data_complete = all_labels_known and all_costs_known
    ready_for_external_review = (
        data_complete
        and label_ok
        and cost_ok
        and coverage_ok
        and error_ok
        and terminal_improved
        and gain_ok
        and p_ok
    )
    return {
        "schema": "hepta.verify.matched-analysis.v2",
        "manifest_sha256": _digest(manifest),
        "observations_sha256": _digest(
            sorted(observations, key=lambda row: (row["pair_id"], row["arm"]))
        ),
        "arms": results,
        "paired_mean_loss_improvement": paired_gain,
        "terminal_error_rate_reduction": terminal_reduction,
        "cluster_count": len({p["cluster_id"] for p in pairs.values()}),
        "assignment_sha256": assignment_sha,
        "design_receipt_sha256": _digest(design) if design_bound else None,
        "conditional_group_signflip_one_sided_p": p_value,
        "paired_group_signflip_one_sided_p": p_value if design_ok else None,
        "signflip_statistic": "whole_cluster_contributions_to_paired_mean",
        "signflip_validity_requires_independent_randomized_groups": True,
        "conditional_signflip_is_inferential_evidence": False,
        "gates": {
            "roster_complete": fully_observed,
            "horizon_labels_complete": all_labels_known,
            "physical_costs_complete_claim_verified": cost_ok,
            "independent_labels_receipt_authenticated": label_ok,
            "whole_cluster_assignment_consistent": consistent,
            "frozen_design_receipt_bound": design_bound,
            "independent_randomized_design_authenticated": design_ok,
            "coverage": coverage_ok,
            "accepted_error_noninferiority": error_ok,
            "terminal_error_reduction": terminal_improved,
            "mean_total_loss_improvement": gain_ok,
            "paired_statistical_threshold": p_ok,
            "externally_reviewable": ready_for_external_review,
        },
        "independent_custody_established_by_this_code": False,
        "sampling_independence_established_by_this_code": False,
        "production_authority": "NONE",
        "scientific_admission": "HOLD",
    }

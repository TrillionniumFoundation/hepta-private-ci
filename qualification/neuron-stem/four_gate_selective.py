"""Labelled selective-risk checks used only by the canonical plan.v2 reviewer.

Accepting a benign distribution shift is not an error. Calibration and evaluation
must use the same immutable Head. This checks unsigned evidence consistency; it
does not authenticate source independence, future chronology or outcome truth.
"""
from collections import defaultdict
import math
import random

from four_gate_common import digest, integer, number, percentile, require, result, sha, timestamp

ARMS = ("no_change", "frozen", "trained")
DETECTORS = ("confidence", "feature_support", "learned_rejector")
KINDS = ("in_domain", "benign_shift", "difficult_in_domain", "unknown_task",
         "changed_rule", "missing_evidence")


def validate_selective_plan(cfg):
    require(set(cfg) == {"calibration_reject_fraction", "max_accepted_error",
            "min_answerable_coverage", "max_unknown_acceptance", "max_benign_rejection", "selected_detector"},
            "complete preregistered selective-risk limits")
    require(cfg["selected_detector"] in DETECTORS, "preregistered detector required")
    for name, value in cfg.items():
        if name == "selected_detector":
            continue
        require(0 <= number(value, name) <= 1, "selective limit outside [0,1]")
    require(cfg["min_answerable_coverage"] > 0, "reject-all is not a successful policy")


def _counts(rows):
    """Seven exact integers are sufficient for all four episode-ratio metrics."""
    return (len(rows), sum(r[0] for r in rows), sum(r[0] and r[2] for r in rows),
            sum(r[1] for r in rows), sum(r[0] and r[2] and r[3] for r in rows),
            sum(not r[0] and r[2] for r in rows), sum(r[1] and not r[2] for r in rows))


def _ratios(counts):
    total, answerable, accepted, benign, errors, unknown_accepted, benign_rejected = counts
    unknown = total - answerable
    return {"accepted_error": errors / accepted if accepted else None,
            "answerable_coverage": accepted / answerable if answerable else None,
            "unknown_acceptance": unknown_accepted / unknown if unknown else None,
            "benign_rejection": benign_rejected / benign if benign else None}


def _metrics(rows):
    """No pseudo-label for unknowns and no zero-risk interpretation of reject-all."""
    return _ratios(_counts(rows))


def clustered_metrics(rows, plan):
    clusters = defaultdict(list)
    for group, values in rows:
        clusters[group].append(values)
    ordered = [clusters[g] for g in sorted(clusters)]
    n = len(ordered)
    require(n > 0 and n * plan["bootstrap_replicates"] <= 20_000_000, "selective bootstrap budget")
    # Match the original cluster draws exactly, without expanding every sampled
    # cluster into Cell rows. Work is now O(rows + groups * replicates), consistent
    # with the budget above; many correlated Cells do not amplify each draw.
    sufficient = [_counts(cluster) for cluster in ordered]
    rng = random.Random(plan["seed"])
    draws = defaultdict(list)
    for _ in range(plan["bootstrap_replicates"]):
        total = answerable = accepted = benign = errors = unknown = rejected = 0
        for _ in range(n):
            c = sufficient[rng.randrange(n)]
            total += c[0]
            answerable += c[1]
            accepted += c[2]
            benign += c[3]
            errors += c[4]
            unknown += c[5]
            rejected += c[6]
        for name, value in _ratios((total, answerable, accepted, benign,
                                   errors, unknown, rejected)).items():
            # A draw without its denominator cannot certify low error or coverage.
            draws[name].append(value if value is not None else
                               (0.0 if name == "answerable_coverage" else 1.0))
    alpha = plan["alpha"] / (2 * len(ARMS) * len(DETECTORS) * 4)
    counts = {"answerable_coverage": sum(any(r[0] for r in c) for c in ordered),
              "accepted_error": sum(any(r[0] and r[2] for r in c) for c in ordered),
              "unknown_acceptance": sum(any(not r[0] for r in c) for c in ordered),
              "benign_rejection": sum(any(r[1] for r in c) for c in ordered)}
    report = {name: {"estimate": value, "lcb": percentile(draws[name], alpha / 2),
                   "ucb": percentile(draws[name], 1 - alpha / 2),
                   "eligible_source_clusters": counts[name],
                   "enough_groups": counts[name] >= plan["min_groups"],
                   "estimator": "episode_ratio_with_source_cluster_bootstrap"}
            for name, value in _metrics([r for c in ordered for r in c]).items()}
    # Percentile bootstrap degenerates at an all-zero error boundary. For the
    # current observed profile, enclose it in a conservative conditional bound.
    # The additional premise is fixed pre-outcome cluster sizes and independent
    # source-cluster observations. This is NOT a distribution-shift guarantee.
    guarded = (plan.get("schema") == "hepta.four-gate.plan.v2" and
               plan["evidence_kind"] == "observed")
    if guarded:
        size = sum(map(len, ordered))
        weights = [len(c) / size for c in ordered]
        epsilon = math.sqrt(0.5 * sum(w*w for w in weights) * math.log(4/alpha))
        contributions = {
            "accepted_error": lambda r: (int(r[0] and r[2] and r[3]), int(r[0] and r[2])),
            "answerable_coverage": lambda r: (int(r[0] and r[2]), int(r[0])),
            "unknown_acceptance": lambda r: (int(not r[0] and r[2]), int(not r[0])),
            "benign_rejection": lambda r: (int(r[1] and not r[2]), int(r[1])),
        }
        for name, contribution in contributions.items():
            pairs = [contribution(r) for c in ordered for r in c]
            numerator = sum(a for a, _ in pairs) / size
            denominator = sum(b for _, b in pairs) / size
            lower = max(0, numerator-epsilon) / min(1, denominator+epsilon)
            upper = (min(1, (numerator+epsilon)/(denominator-epsilon))
                     if denominator > epsilon else 1.0)
            report[name]["lcb"] = min(report[name]["lcb"], lower)
            report[name]["ucb"] = max(report[name]["ucb"], upper)
            report[name]["conditional_weighted_cluster_guard"] = {
                "epsilon": epsilon, "sum_squared_cluster_weights": sum(w*w for w in weights),
                "assumptions": "fixed_preoutcome_cluster_sizes_and_independent_clusters",
                "assumptions_authenticated": False,
            }
    for item in report.values():
        item["finite_sample_guard_applied"] = guarded
    return report


def review_selective(plan, evidence, *, trial, nochange_identity):
    cfg = plan["learning"]["selective"]
    validate_selective_plan(cfg)
    require(evidence["schema"] == "hepta.four-gate.selective.v1", "selective schema")
    require(evidence["trial_sha256"] == digest(trial), "selective evidence changed Cell trial")
    require(evidence["objective_sha256"] == plan["objective_sha256"], "selective objective drift")
    detectors = evidence["detectors"]
    require(set(detectors) == set(DETECTORS), "all three uncertainty detectors required")
    require(len({d["training_data_sha256"] for d in detectors.values()}) == 1,
            "detector controls changed approved training data")
    for detector in detectors.values():
        sha(detector["artifact_sha256"])
        sha(detector["training_data_sha256"])
        require(timestamp(detector["fit_completed_at"]) <= timestamp(evidence["calibration_sealed_at"]),
                "detector trained after calibration seal")
    sealed = timestamp(evidence["calibration_sealed_at"])
    require(sealed <= timestamp(plan["assessment_time"]), "calibration not yet observed")
    calibration, evaluation = evidence["calibration"], evidence["evaluation"]
    require(type(calibration) is list and type(evaluation) is list and calibration and evaluation
            and len(calibration) + len(evaluation) <= 100_000, "bounded nonempty selective stream")
    calib_groups, calib_inputs, seen = set(), set(), set()
    input_groups = {}
    scores, records = defaultdict(list), []
    expected = {"frozen": trial["initial_head_digests"], "trained": trial["final_head_digests"]}
    for split, rows in (("calibration", calibration), ("evaluation", evaluation)):
        for row in rows:
            key = row["case_id"]
            require(isinstance(key, str) and 0 < len(key) <= 256 and key not in seen,
                    "duplicate selective case")
            seen.add(key)
            group = (row["scope_id"], row["source_cluster"])
            require(all(isinstance(x, str) and 0 < len(x) <= 128 for x in group), "source cluster identity")
            sha(row["input_sha256"])
            require(input_groups.setdefault(row["input_sha256"], group) == group,
                    "same input counted as independent selective sources")
            require(row["kind"] in KINDS and type(row["answerable"]) is bool, "answerability semantics")
            if row["kind"] in ("in_domain", "benign_shift", "difficult_in_domain", "changed_rule"):
                require(row["answerable"], "known shifted task cannot be relabelled unknown")
            elif row["kind"] in ("unknown_task", "missing_evidence"):
                require(not row["answerable"] and row["label"] is None, "no invented unknown-task label")
            event = timestamp(row["event_time"])
            require(event <= timestamp(plan["assessment_time"]), "future selective outcome")
            if split == "calibration":
                require(row["kind"] == "in_domain" and event <= timestamp(plan["selection_cutoff"]),
                        "calibration requires historical in-domain data")
                calib_groups.add(group)
                calib_inputs.add(row["input_sha256"])
            else:
                require(event > sealed and group not in calib_groups and row["input_sha256"] not in calib_inputs,
                        "calibration/future overlap or retrospective threshold")
                sha(row["outcome_receipt_sha256"])
                require(event <= timestamp(row["outcome_observed_at"]) <= timestamp(plan["assessment_time"]),
                        "outcome chronology")
            require(set(row["predictions"]) == set(ARMS), "matched selective arms required")
            for arm, prediction in row["predictions"].items():
                p = prediction["probabilities"]
                require(type(p) is list and 2 <= len(p) <= 128 and
                        all(type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 1 for v in p)
                        and abs(sum(p) - 1) <= 1e-6, "invalid selective probability")
                if row["answerable"]:
                    integer(row["label"], "independent known label", 0, len(p) - 1)
                cell = str((row["scope_id"], row["cell_id"]))
                weights = nochange_identity[1] if arm == "no_change" else expected[arm].get(cell)
                require(prediction["weights_digest"] == sha(weights), "calibration/selected Head identity drift")
                revision = nochange_identity[0] if arm == "no_change" else trial["revision"]
                require(prediction["model_revision"] == revision, "model revision drift")
                if arm == "no_change":
                    require(prediction["generation"] == nochange_identity[2], "no-change generation drift")
                require(prediction["detector_bundle_sha256"] == digest(detectors),
                        "detector scores not bound to fitted detector artifacts")
                at = timestamp(prediction["predicted_at"])
                if split == "calibration":
                    require(at <= sealed, "calibration prediction after seal")
                else:
                    require(event <= at <= timestamp(row["outcome_observed_at"]), "prediction after outcome")
                    require(row["observer_id"] != prediction["producer_id"], "self-observed selective success")
                require(set(prediction["scores"]) == set(DETECTORS), "missing detector score")
                for detector, value in prediction["scores"].items():
                    require(0 <= number(value, "acceptance score") <= 1, "detector score range")
                    if detector == "confidence":
                        require(abs(value - max(p)) <= 1e-6, "confidence differs from actual probabilities")
                    if split == "calibration":
                        scores[(cell, arm, detector)].append(value)
                records.append((split, row, arm, prediction))
    require({r["kind"] for r in evaluation} == set(KINDS), "complete selective challenge strata required")
    thresholds = {}
    for key, values in scores.items():
        require(len(values) >= 2, "insufficient per-Head calibration")
        thresholds[key] = sorted(values)[min(len(values) - 1, math.floor(len(values) * cfg["calibration_reject_fraction"]))]
    paired = defaultdict(list)
    descriptive = defaultdict(list)
    for split, row, arm, prediction in records:
        if split != "evaluation":
            continue
        cell = str((row["scope_id"], row["cell_id"]))
        p = prediction["probabilities"]
        wrong = row["answerable"] and max(range(len(p)), key=lambda i: p[i]) != row["label"]
        for detector, value in prediction["scores"].items():
            require((cell, arm, detector) in thresholds, "new Head has no compatible calibration")
            accepted = value >= thresholds[(cell, arm, detector)]
            observation = (row["answerable"], row["kind"] == "benign_shift", accepted, wrong)
            paired[(arm, detector)].append((digest([row["scope_id"], row["source_cluster"]]), observation))
            descriptive[(arm, detector, row["kind"])].append(observation)
    reports = {f"{arm}:{detector}": clustered_metrics(values, plan)
               for (arm, detector), values in paired.items()}
    passed = []
    for detector in DETECTORS:
        metrics = reports[f"trained:{detector}"]
        passed.append(all(v["enough_groups"] and v["estimate"] is not None for v in metrics.values())
            and metrics["accepted_error"]["ucb"] <= cfg["max_accepted_error"]
            and metrics["answerable_coverage"]["lcb"] >= cfg["min_answerable_coverage"]
            and metrics["unknown_acceptance"]["ucb"] <= cfg["max_unknown_acceptance"]
            and metrics["benign_rejection"]["ucb"] <= cfg["max_benign_rejection"])
    selected_passed = passed[DETECTORS.index(cfg["selected_detector"])]
    return result(selected_passed, {"profiles": reports,
        "selected_detector": cfg["selected_detector"], "detector_passes": dict(zip(DETECTORS, passed)),
        "strata": {":".join(key): _metrics(values) for key, values in descriptive.items()},
        "calibration_thresholds": {str(key): value for key, value in thresholds.items()},
        "high_shift_acceptance_is_not_answer_error": True,
        "calibration_uses_same_selected_head": True},
        [] if selected_passed else ["selective error/coverage/unknown/benign limits or source support failed"])

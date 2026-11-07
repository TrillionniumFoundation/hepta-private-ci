"""Independent, artifact-bound phase-2 scoring and paired evidence summaries.

These gates assess a preregistered panel, not an internal utility. Fixture outputs,
missing baselines, unknown usage, and changed evaluation identities remain HOLD.
"""

from dataclasses import asdict, dataclass
import math
import subprocess

import numpy as np

from .generation import (
    BASELINES,
    checked_digest,
    checked_number,
    digest,
    verify_artifact,
)


@dataclass(frozen=True)
class EvaluatorManifest:
    evaluator_id: str
    revision: str
    artifact_sha256: str
    rubric_sha256: str
    evidence_kind: str
    minimum_quality: float = 0.7

    def __post_init__(self):
        if not self.evaluator_id or not self.revision:
            raise ValueError("independent evaluator identity/revision required")
        checked_digest(self.artifact_sha256)
        checked_digest(self.rubric_sha256)
        checked_number(self.minimum_quality, "minimum quality", 1.0)
        if self.evidence_kind not in ("real", "synthetic_fixture"):
            raise ValueError("explicit evaluator evidence kind required")

    @property
    def sha256(self):
        return digest(asdict(self))


def evaluate(
    session,
    evaluator,
    manifest,
    controller_id,
    *,
    group_id,
    split,
    evaluation_compute_limit,
    evaluation_timeout_seconds,
    critic_success_probability=None,
):
    """Evaluate once through an explicit callable/JsonlCommand independent scorer.

    The evaluator receives task identity and artifact references; it receives no
    baseline label, NDU score or critic prediction. Its rubric is pinned. Costs
    include offline scoring so the selected accounting convention is explicit.
    Every attempt, including rejected/failed evaluation, seals the session against
    retries; incurred scoring costs persist in its resource ledger.
    """
    if session.evaluation_attempted:
        raise ValueError("evaluation already attempted for this session")
    session.evaluation_attempted = True
    if manifest.evaluator_id in (
        controller_id,
        session.provider.manifest.provider_id,
        session.provider.manifest.observer_id,
    ):
        raise ValueError("evaluator must be distinct from controller/provider observer")
    if not controller_id or not group_id or split not in ("test", "ood", "retention"):
        raise ValueError("controller identity and grouped held-out split required")
    limit = checked_number(evaluation_compute_limit, "evaluation compute reservation")
    timeout = checked_number(evaluation_timeout_seconds, "evaluation timeout", 60.0)
    if limit <= 0 or timeout <= 0:
        raise ValueError("positive evaluator limits required")
    if critic_success_probability is not None:
        checked_number(critic_success_probability, "critic probability", 1.0)
    run = session.evidence()
    reasons = list(run["reasons"])
    if manifest.evidence_kind != "real":
        reasons.append("synthetic_evaluator_not_quality_evidence")
    else:
        reasons.append("independent_evaluator_provenance_unverified")
    row = {
        **run,
        "group_id": group_id,
        "split": split,
        "evaluator_sha256": manifest.sha256,
        "controller_id": controller_id,
        "evaluator_evidence_kind": manifest.evidence_kind,
        "evaluator_provenance": "DECLARED_UNVERIFIED",
        "critic_success_probability": critic_success_probability,
        "evaluation_compute": 0.0,
        "evaluation_seconds": 0.0,
        "outcome": None,
        "reasons": reasons,
    }
    if (
        limit > session.budget_compute - session.spent_compute
        or timeout > session.budget_seconds - session.spent_seconds
    ):
        reasons.append("insufficient_evaluator_reservation")
    else:
        start = session.clock()
        actual_compute = None
        try:
            artifacts = [
                verify_artifact(
                    session.artifact_root,
                    {k: item[k] for k in ("path", "modality", "sha256")},
                )
                for item in session.artifacts.values()
            ]
            request = {
                "protocol": "hepta.ndu-portfolio.evaluation.v1",
                "evaluator_sha256": manifest.sha256,
                "objective_sha256": session.objective_sha256,
                "dataset_sha256": session.dataset_sha256,
                "task_id": session.task_id,
                "sample_id": session.sample_id,
                "seed": session.seed,
                "artifacts": artifacts,
                "artifact_directory": str(session.artifact_root),
                "max_compute_units": limit,
            }
            request["request_sha256"] = digest(request)
            response = evaluator(request, timeout)
            if not isinstance(response, dict):
                raise ValueError("evaluator response must be an object")
            if (
                response["request_sha256"] != request["request_sha256"]
                or response["evaluator_sha256"] != manifest.sha256
            ):
                raise ValueError("evaluator substituted request or scoring identity")
            actual_compute = checked_number(
                response["compute_units"], "evaluation compute"
            )
            row["evaluation_compute"] = actual_compute
            if actual_compute > limit:
                raise ValueError("evaluator_reservation_exceeded")
            outcome = response["outcome"]
            if not isinstance(outcome["task_success"], bool):
                raise ValueError("task_success must be observed boolean")
            quality = {
                key: checked_number(outcome["quality"][key], f"{key} quality", 1.0)
                for key in ("text", "image")
            }
            contradictions = outcome["contradictions"]
            if (
                isinstance(contradictions, bool)
                or not isinstance(contradictions, int)
                or contradictions < 0
            ):
                raise ValueError("contradictions must be a nonnegative integer")
            missing = outcome["missing_modalities"]
            if (
                not isinstance(missing, list)
                or any(x not in ("text", "image") for x in missing)
                or len(set(missing)) != len(missing)
            ):
                raise ValueError("invalid missing-modalities observation")
            actual_missing = sorted({"text", "image"} - set(session.artifacts))
            if sorted(missing) != actual_missing:
                raise ValueError(
                    "evaluator missing-delivery observation conflicts with artifact ledger"
                )
            weakest = min(quality.values())
            success = (
                outcome["task_success"]
                and not missing
                and contradictions == 0
                and weakest >= manifest.minimum_quality
            )
            row["outcome"] = {
                "joint_success": bool(success),
                "task_success": outcome["task_success"],
                "quality": quality,
                "weakest_quality": weakest,
                "contradictions": contradictions,
                "missing_modalities": missing,
            }
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as error:
            reasons.append(
                "evaluator_reservation_exceeded"
                if actual_compute is not None and actual_compute > limit
                else "independent_evaluation_failed:" + type(error).__name__
            )
            row["evaluation_compute"] = (
                actual_compute if actual_compute is not None else limit
            )
        finally:
            elapsed = session.clock() - start
            if not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("clock must be finite and monotonic")
            row["evaluation_seconds"] = elapsed
            session.spent_compute += row["evaluation_compute"]
            session.spent_seconds += elapsed
            row["total_compute"] = session.spent_compute
            row["total_seconds"] = session.spent_seconds
            if elapsed > timeout:
                reasons.append("independent_evaluation_deadline_exceeded")
                row["outcome"] = None
        if (
            row["total_compute"] > session.budget_compute
            or row["total_seconds"] > session.budget_seconds
        ):
            reasons.append("total_budget_including_evaluator_exceeded")
    row["status"] = "HOLD" if reasons or row["outcome"] is None else "MEASURED"
    session.evaluation_receipt = {
        "status": row["status"],
        "reasons": list(reasons),
        "compute": row["evaluation_compute"],
        "seconds": row["evaluation_seconds"],
        "evaluator_sha256": manifest.sha256,
    }
    row["evaluation_receipt"] = session.evaluation_receipt.copy()
    return row


def _summary(rows, expected_count):
    """Use the registered denominator even when whole rows/outcomes are absent."""
    if expected_count <= 0 or len(rows) > expected_count:
        raise ValueError("invalid registered denominator")
    observed = [r for r in rows if r["outcome"] is not None]
    n_observed = len(observed)
    missing = expected_count - n_observed
    successes = sum(r["outcome"]["joint_success"] for r in observed)
    result = {
        "n_expected": expected_count,
        "n_received": len(rows),
        "n_observed_outcomes": n_observed,
        "n_missing_outcomes": missing,
        "outcome_coverage": n_observed / expected_count,
        "observed_successes": successes,
        "all_case_joint_success_rate_lower_bound": successes / expected_count,
        "all_case_joint_success_rate_upper_bound": (successes + missing)
        / expected_count,
        "joint_success_rate": None,
        "wilson_95": None,
        "observed_only_mean_quality": None,
        "observed_only_weakest_quality_mean": None,
        "observed_only_worst_decile_quality_mean": None,
        "observed_contradictions": sum(
            r["outcome"]["contradictions"] for r in observed
        ),
        "observed_missing_deliveries": sum(
            bool(r["outcome"]["missing_modalities"]) for r in observed
        ),
        "resource_record_coverage": len(rows) / expected_count,
        "recorded_only_mean_total_compute": None,
        "recorded_only_mean_total_seconds": None,
        "recorded_only_mean_controller_seconds": None,
        "critic_calibration": "UNAVAILABLE_INCOMPLETE_OUTCOMES_OR_PREDICTIONS",
    }
    if rows:
        result.update(
            recorded_only_mean_total_compute=float(
                np.mean([r["total_compute"] for r in rows])
            ),
            recorded_only_mean_total_seconds=float(
                np.mean([r["total_seconds"] for r in rows])
            ),
            recorded_only_mean_controller_seconds=float(
                np.mean(
                    [sum(x["controller_seconds"] for x in r["receipts"]) for r in rows]
                )
            ),
        )
    if observed:
        weakest = np.array([r["outcome"]["weakest_quality"] for r in observed])
        result.update(
            observed_only_mean_quality={
                m: float(np.mean([r["outcome"]["quality"][m] for r in observed]))
                for m in ("text", "image")
            },
            observed_only_weakest_quality_mean=float(weakest.mean()),
            observed_only_worst_decile_quality_mean=float(
                np.sort(weakest)[: max(1, math.ceil(n_observed / 10))].mean()
            ),
        )
    if missing:
        return result
    success = np.array([r["outcome"]["joint_success"] for r in observed], dtype=float)
    z = 1.959963984540054
    p = successes / expected_count
    centre = (p + z * z / (2 * expected_count)) / (1 + z * z / expected_count)
    radius = (
        z
        * math.sqrt(p * (1 - p) / expected_count + z * z / (4 * expected_count**2))
        / (1 + z * z / expected_count)
    )
    result.update(joint_success_rate=p, wilson_95=[centre - radius, centre + radius])
    predictions = [r["critic_success_probability"] for r in observed]
    if all(value is not None for value in predictions):
        pred = np.asarray(predictions)
        result["critic_calibration"] = "COMPLETE"
        result["critic_brier"] = float(np.mean((pred - success) ** 2))
        bins = np.minimum((pred * 10).astype(int), 9)
        result["critic_ece_10bins"] = float(
            sum(
                np.sum(bins == b)
                / expected_count
                * abs(pred[bins == b].mean() - success[bins == b].mean())
                for b in range(10)
                if np.any(bins == b)
            )
        )
    return result


def panel_report(
    rows,
    expected_cases,
    *,
    required_baselines=BASELINES,
    training_group_ids=(),
    minimum_independent_test_groups=None,
):
    """Require complete matched panels; estimates never certify NDU necessity.

    expected_cases contains (task_id, sample_id, seed, split) for every case.
    Missing outcomes stay in the denominator; success is a bounded interval until
    coverage is complete and quality summaries explicitly condition on observations.
    Wilson intervals assume independent cases; repeated groups cause HOLD until a
    clustered estimator is registered. The optional group minimum is a final
    qualification prerequisite (100 in the pilot preregistration), not an efficacy
    decision. This helper never turns a descriptive panel into an efficacy PASS.
    """
    reasons = []
    expected = set(tuple(x) for x in expected_cases)
    if not expected or len(expected) != len(expected_cases):
        raise ValueError("nonempty unique expected case list required")
    if any(
        len(case) != 4 or case[3] not in ("test", "ood", "retention")
        for case in expected
    ):
        raise ValueError("invalid registered case or split")
    if (
        not required_baselines
        or any(x not in BASELINES for x in required_baselines)
        or len(set(required_baselines)) != len(required_baselines)
    ):
        raise ValueError("invalid baseline panel")
    if minimum_independent_test_groups is not None and (
        isinstance(minimum_independent_test_groups, bool)
        or not isinstance(minimum_independent_test_groups, int)
        or minimum_independent_test_groups <= 0
    ):
        raise ValueError("minimum independent groups must be a positive integer")
    selected = {name: {} for name in required_baselines}
    training_groups = set(training_group_ids)
    for row in rows:
        key = (row["task_id"], row["sample_id"], row["seed"], row["split"])
        baseline = row["baseline"]
        if baseline not in selected or key not in expected:
            raise ValueError("unregistered baseline or case")
        if key in selected[baseline]:
            raise ValueError("duplicate baseline/case row")
        selected[baseline][key] = row
        if row["status"] != "MEASURED":
            reasons.append("nonqualifying_row:" + baseline)
        if (
            row.get("evidence_kind") != "real"
            or row.get("evaluator_evidence_kind") != "real"
        ):
            reasons.append("nonreal_evidence:" + baseline)
        if row["group_id"] in training_groups:
            reasons.append("training_evaluation_group_overlap")
    for name, values in selected.items():
        if set(values) != expected:
            reasons.append("incomplete_baseline:" + name)
    binding_keys = (
        "manifest_sha256",
        "objective_sha256",
        "dataset_sha256",
        "evaluator_sha256",
        "budget_compute",
        "budget_seconds",
        "group_id",
    )
    case_groups = {}
    eligible_test_groups = set()
    for case in sorted(expected):
        paired = [v[case] for v in selected.values() if case in v]
        if paired:
            case_groups[case] = paired[0]["group_id"]
            matched = all(
                all(row[k] == paired[0][k] for k in binding_keys) for row in paired[1:]
            )
            if not matched:
                reasons.append("unmatched_case_bindings")
            if (
                case[3] == "test"
                and matched
                and len(paired) == len(required_baselines)
                and all(
                    row["status"] == "MEASURED"
                    and row["outcome"] is not None
                    and row.get("evidence_kind") == "real"
                    and row.get("evaluator_evidence_kind") == "real"
                    and row["group_id"] not in training_groups
                    for row in paired
                )
            ):
                eligible_test_groups.add(paired[0]["group_id"])
    if len(set(case_groups.values())) != len(case_groups):
        reasons.append("correlated_cases_require_clustered_estimator")
    if (
        minimum_independent_test_groups is not None
        and len(eligible_test_groups) < minimum_independent_test_groups
    ):
        reasons.append("insufficient_independent_test_task_groups")
    counts = {
        split: sum(case[3] == split for case in expected)
        for split in sorted({case[3] for case in expected})
    }
    summaries = {
        name: {
            split: _summary([r for r in values.values() if r["split"] == split], count)
            for split, count in counts.items()
        }
        for name, values in selected.items()
    }
    return {
        "status": "HOLD" if reasons else "COMPLETE_DESCRIPTIVE_PANEL",
        "reasons": sorted(set(reasons)),
        "expected_cases_per_baseline": len(expected),
        "expected_cases_per_split": counts,
        "minimum_independent_test_groups": minimum_independent_test_groups,
        "eligible_independent_test_groups": len(eligible_test_groups),
        "baselines": summaries,
        "ndu_necessity": "NOT_ESTABLISHED",
        "claim": "Preregistered paired efficacy and retention decisions are required; descriptive means are insufficient.",
    }

"""Bind recorded fixture checks and reconstruct the completed host control flow.

These are consistency checks on retained records, not signatures or independent
attestation of the SQLite state. Actual acceptance authority stays with the host.
"""

import re

from .model_protocol import digest, public_view


_REASONS = {
    "proved": {"finite_fixture_goal_and_owner_readback"},
    "refuted": {"goal_values_mismatch"},
    "unknown": {
        "state_frontier_mismatch",
        "incomplete_owner_intents",
        "missing_ack_requires_readback",
        "host_authorization_denied",
    },
}
_ASSUMPTIONS = [
    "controller_goal_is_trusted",
    "sqlite_transaction_is_exclusive",
    "fixture_owner_is_trusted",
]


def _report(report, goal, tick, mandatory):
    required = {
        "subject_sha256",
        "state_version",
        "property",
        "assumptions",
        "checker_id",
        "checker_version",
        "evidence_sha256",
        "checked_step",
        "verdict",
        "reason",
        "residual_obligations",
        "accepted",
        "production_authority",
    }
    if type(report) is not dict or set(report) != required:
        raise ValueError("incomplete checker report")
    if (
        report["subject_sha256"] != digest(goal)
        or report["property"] != "fixture_goal_and_owner_readback_at_snapshot"
    ):
        raise ValueError("checker subject or property mismatch")
    if (
        report["assumptions"] != _ASSUMPTIONS
        or report["checker_id"] != "verify1.sqlite.goal"
        or report["checker_version"] != "1"
        or report["production_authority"] != "NONE"
    ):
        raise ValueError("unknown checker contract")
    if type(report["checked_step"]) is not int or report["checked_step"] != tick:
        raise ValueError("checker frontier mismatch")
    if type(report["state_version"]) is not int or report["state_version"] != min(
        tick, 3
    ):
        raise ValueError("checker state version mismatch")
    evidence = report["evidence_sha256"]
    if type(evidence) is not str or re.fullmatch("[0-9a-f]{64}", evidence) is None:
        raise ValueError("invalid checker evidence digest")
    verdict, reason = report["verdict"], report["reason"]
    if verdict not in _REASONS or reason not in _REASONS[verdict]:
        raise ValueError("invalid checker verdict and reason")
    if report["residual_obligations"] != ([] if verdict == "proved" else [reason]):
        raise ValueError("checker residual obligation mismatch")
    if type(report["accepted"]) is not bool or report["accepted"] != (
        mandatory and verdict == "proved"
    ):
        raise ValueError("checker acceptance mismatch")
    return report


def readback_bindings(cases, settings, operations, rows, decisions, assessments):
    """Rebuild effects, optional checks, reconciliation and terminal acceptance.

    The loop never uses a row's claimed reached/detected/interrupted state to decide
    which events to require. Unknown missing-ACK optional checks reconcile once and
    continue; the reserved terminal check can read back once more after reconciliation.
    """
    kinds = {
        "host_effect",
        "optional_host_check",
        "mandatory_host_check",
        "host_reconcile_without_replay",
        "independent_outcome_label",
    }
    grouped = {key: [] for key in rows}
    for operation in operations:
        context = operation["context"]
        if operation["kind"] not in kinds or context.get("split") != "confirmation":
            continue
        key = context["case_id"], context["arm"]
        if key not in grouped or operation["status"] != "completed":
            return False
        grouped[key].append(operation)
    for key, row in rows.items():
        case, arm = key
        goal, events, cursor = cases[case]["goal"], grouped[key], 0

        def take(kind, tick=None):
            nonlocal cursor
            operation = events[cursor]
            cursor += 1
            context = {"case_id": case, "arm": arm, "split": "confirmation"}
            if tick is not None:
                context["tick"] = tick
            if operation["kind"] != kind or digest(operation["context"]) != digest(
                context
            ):
                raise ValueError("host control-flow event mismatch")
            return operation["result"]

        def check(tick, mandatory):
            nonlocal detected
            report = _report(
                take(
                    "mandatory_host_check" if mandatory else "optional_host_check", tick
                ),
                goal,
                tick,
                mandatory,
            )
            if report["verdict"] != "proved" and detected is None:
                detected = tick
            if report["reason"] == "missing_ack_requires_readback":
                recovery = take("host_reconcile_without_replay", tick)
                if digest(recovery) != digest(
                    {
                        "resolved": True,
                        "effects_replayed": 0,
                        "reason": "actual_snapshot_readback",
                    }
                ):
                    raise ValueError(
                        "missing ACK recovery must reconcile without replay"
                    )
                if mandatory:
                    report = _report(
                        take("mandatory_host_check", tick), goal, tick, True
                    )
            return report

        detected, interrupted, accepted, acks = None, False, False, []
        for tick in (1, 2, 3):
            effect = take("host_effect", tick)
            if (
                type(effect) is not dict
                or set(effect) != {"operation_id", "ack", "replayed"}
                or effect["operation_id"] != f"{case}/step/{tick}"
                or effect["replayed"] is not False
                or type(effect["ack"]) is not bool
            ):
                return False
            acks.append(effect["ack"])
            if tick not in ((2,) if arm in settings else (2, 3)):
                continue
            decision = decisions[case, arm, tick]
            if assessments[decision["assessment_id"]]["view"] != public_view(acks):
                return False
            if decision["selection"] == "check":
                report = check(tick, False)
                if (
                    report["verdict"] != "proved"
                    and report["reason"] != "missing_ack_requires_readback"
                ):
                    interrupted = True
                    break
        if not interrupted:
            accepted = check(4, True)["accepted"]
        label = take("independent_outcome_label")
        if (
            cursor != len(events)
            or type(label) is not bool
            or row["outcome_error"] is not label
        ):
            return False
        if (
            type(row["accepted"]) is not bool
            or row["accepted"] != accepted
            or row["interrupted"] != interrupted
        ):
            return False
        if row["reached_step"] != tick or row["detected_step"] != detected:
            return False
        if row["detected_step"] is not None and type(row["detected_step"]) is not int:
            return False
    return True

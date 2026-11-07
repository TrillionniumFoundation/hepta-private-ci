"""Finite research outcomes mapped to existing native learning semantics.

This is a declaration/structure auditor, not a native receipt authenticator.
The native learning iteration already implements evaluated NoUpdate; #5192 adds
an independently authorized same-model next-task operation. Neither is synthesized
here. A conditional outcome never authorizes selection, adoption, a V5 zero delta,
or rewards. JSON declarations cannot make final evidence conclusive.
"""

from datetime import datetime
import math

from .factorial import COSTS
from .generation import checked_digest, digest

OUTCOMES = ("Adoptable", "NoUpdate", "Inconclusive", "Failed")
GATES = ("external_net_gain", "retention", "complete_cost", "data_eligibility")


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _fields(value, fields, name):
    _need(
        isinstance(value, dict) and set(value) == set(fields),
        name + ": exact fields required",
    )


def _ids(values, name):
    _need(
        isinstance(values, list)
        and len(values) <= 10000
        and all(isinstance(v, str) and v and len(v) <= 256 for v in values),
        name + ": bounded IDs required",
    )
    _need(len(values) == len(set(values)), name + ": duplicate ID")
    return set(values)


def _time(value):
    _need(isinstance(value, str), "timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid timestamp") from error
    _need(parsed.tzinfo is not None, "timestamp timezone required")
    return parsed


def _number(value):
    _need(
        type(value) in (int, float) and math.isfinite(value) and value >= 0,
        "finite nonnegative cost required",
    )
    return float(value)


def audit(contract, evidence, *, expected_contract_digest, next_task=None):
    """Classify a finite declared campaign; keep unauthenticated results HOLD.

    expected_contract_digest is a caller-owned prospective pin, not a field from
    the submitted evidence. It is not an attestation. expected_candidate_ids fixes every attempted or prospectively skipped slot.
    Each candidate retains all job IDs, including failures and cancelled work.
    Costs use one disjoint nine-category ledger across dataset/training/search/
    evaluation jobs, including an independent terminal evaluation meter. Candidate
    construction outputs and evaluation inputs bind the same artifact; evaluation
    follows all successful construction work. Null remains unknown. Missing material is Inconclusive;
    NoUpdate/no_eligible_data needs a complete bound zero-eligible admission.
    next_task is an optional declared same-model receipt checked separately: a
    terminal learning decision does not prove the incumbent was actually reused.
    See the adjacent adversarial tests for a complete synthetic schema example.
    """
    _fields(
        contract,
        (
            "schema",
            "operation_id",
            "source_task_id",
            "source_run_id",
            "incumbent_manifest_digest",
            "incumbent_checkpoint_digest",
            "objective_digest",
            "source_registry_digest",
            "source_bundle_digest",
            "evaluator_digest",
            "trainer_id",
            "evaluator_id",
            "registered_at",
            "deadline_at",
            "cost_unit",
            "maximum_cost",
            "expected_candidate_ids",
        ),
        "contract",
    )
    _need(
        contract["schema"] == "ndu-learning-outcome-contract-v1", "unsupported contract"
    )
    checked_digest(expected_contract_digest)
    _need(
        digest(contract) == expected_contract_digest,
        "externally pinned contract mismatch",
    )
    for field in (
        "operation_id",
        "source_task_id",
        "source_run_id",
        "trainer_id",
        "evaluator_id",
        "cost_unit",
    ):
        _ids([contract[field]], field)
    for field in (
        "incumbent_manifest_digest",
        "incumbent_checkpoint_digest",
        "objective_digest",
        "source_registry_digest",
        "source_bundle_digest",
        "evaluator_digest",
    ):
        checked_digest(contract[field])
    _need(
        contract["trainer_id"] != contract["evaluator_id"],
        "independent evaluator required",
    )
    registered, deadline = (
        _time(contract["registered_at"]),
        _time(contract["deadline_at"]),
    )
    _need(
        deadline > registered and _number(contract["maximum_cost"]) > 0,
        "positive prospective budget required",
    )
    expected = _ids(contract["expected_candidate_ids"], "expected candidates")
    _fields(
        evidence,
        (
            "schema",
            "operation_id",
            "contract_digest",
            "completed_at",
            "stop_reason",
            "data_admission",
            "candidates",
            "jobs",
            "terminal_evaluation",
            "failure_receipt_digest",
        ),
        "evidence",
    )
    _need(
        evidence["schema"] == "ndu-learning-outcome-evidence-v1", "unsupported evidence"
    )
    _need(
        evidence["operation_id"] == contract["operation_id"]
        and evidence["contract_digest"] == digest(contract),
        "contract binding mismatch",
    )
    completed = _time(evidence["completed_at"])
    _need(completed >= registered, "result precedes registration")
    _need(
        evidence["stop_reason"]
        in (
            "candidates_exhausted",
            "no_eligible_data",
            "budget_stop",
            "execution_failed",
        ),
        "unregistered stop reason",
    )
    reasons, failed, jobs, spent, unknown = [], False, {}, 0.0, []
    _need(
        isinstance(evidence["jobs"], list) and len(evidence["jobs"]) <= 10000,
        "bounded jobs required",
    )
    for row in evidence["jobs"]:
        _fields(
            row,
            (
                "job_id",
                "candidate_id",
                "phase",
                "status",
                "started_at",
                "ended_at",
                "receipt_digest",
                "artifact_digest",
                "costs",
            ),
            "job",
        )
        _ids([row["job_id"]], "job ID")
        _need(row["job_id"] not in jobs, "duplicate job")
        _need(
            row["candidate_id"] is None or row["candidate_id"] in expected,
            "unexpected job candidate",
        )
        _need(
            row["phase"] in ("dataset", "training", "search", "evaluation"),
            "invalid research phase",
        )
        _need(
            row["phase"] not in ("training", "search")
            or row["candidate_id"] is not None,
            "training/search work must belong to a registered candidate",
        )
        _need(
            row["status"] in ("succeeded", "failed", "cancelled", "unresolved"),
            "invalid job status",
        )
        if row["artifact_digest"] is not None:
            checked_digest(row["artifact_digest"])
        start, end = _time(row["started_at"]), _time(row["ended_at"])
        _need(registered <= start <= end <= completed, "job time binding mismatch")
        if end > deadline:
            failed = True
            reasons.append("deadline_overrun:" + row["job_id"])
        if row["receipt_digest"] is None or row["status"] == "unresolved":
            reasons.append("unreconciled_job:" + row["job_id"])
            unknown.append("job_meter:" + row["job_id"])
        else:
            checked_digest(row["receipt_digest"])
        _fields(row["costs"], COSTS, "job costs")
        for category, amount in row["costs"].items():
            if amount is None:
                unknown.append(row["job_id"] + ":" + category)
            else:
                spent += _number(amount)
        jobs[row["job_id"]] = row
    _need(math.isfinite(spent), "aggregate cost overflow")
    recorded_ledger_total = (
        None
        if any(
            value is None for row in jobs.values() for value in row["costs"].values()
        )
        else spent
    )
    if not jobs:
        reasons.append("missing_job_inventory")
        unknown.append("job_inventory:missing")
    if spent > contract["maximum_cost"]:
        failed = True
        reasons.append("budget_overrun")
    admission = evidence["data_admission"]
    eligible = None
    if admission is None:
        reasons.append("missing_data_admission")
    else:
        _fields(
            admission,
            (
                "source_registry_digest",
                "objective_digest",
                "receipt_digest",
                "scanned_rows",
                "eligible_rows",
                "excluded_rows",
                "complete",
                "job_id",
            ),
            "data admission",
        )
        _need(
            admission["source_registry_digest"] == contract["source_registry_digest"]
            and admission["objective_digest"] == contract["objective_digest"],
            "data admission binding mismatch",
        )
        checked_digest(admission["receipt_digest"])
        for field in ("scanned_rows", "eligible_rows", "excluded_rows"):
            _need(
                type(admission[field]) is int and 0 <= admission[field] <= 100000000,
                "invalid admission count",
            )
        _need(
            admission["eligible_rows"] + admission["excluded_rows"]
            == admission["scanned_rows"],
            "admission counts disagree",
        )
        _need(type(admission["complete"]) is bool, "admission completeness required")
        _need(
            admission["job_id"] in jobs
            and jobs[admission["job_id"]]["phase"] == "dataset",
            "data admission job missing",
        )
        _need(
            admission["receipt_digest"] == jobs[admission["job_id"]]["receipt_digest"],
            "admission receipt/job mismatch",
        )
        if (
            not admission["complete"]
            or jobs[admission["job_id"]]["status"] != "succeeded"
        ):
            reasons.append("incomplete_data_admission")
        else:
            eligible = admission["eligible_rows"]
    _need(
        isinstance(evidence["candidates"], list)
        and len(evidence["candidates"]) <= 10000,
        "bounded candidates required",
    )
    candidates, qualified, linked = {}, [], set()
    for row in evidence["candidates"]:
        _fields(
            row,
            (
                "candidate_id",
                "status",
                "manifest_digest",
                "objective_digest",
                "evaluator_id",
                "evaluation_receipt_digest",
                "gates",
                "job_ids",
            ),
            "candidate",
        )
        cid = row["candidate_id"]
        _need(
            cid in expected and cid not in candidates,
            "duplicate or unexpected candidate",
        )
        _need(
            row["objective_digest"] == contract["objective_digest"]
            and row["evaluator_id"] == contract["evaluator_id"],
            "candidate evaluator/objective mismatch",
        )
        _need(
            row["status"]
            in (
                "evaluated",
                "skipped_no_data",
                "skipped_budget",
                "failed",
                "unresolved",
            ),
            "invalid candidate status",
        )
        ids = _ids(row["job_ids"], "candidate jobs")
        _need(
            ids <= set(jobs)
            and not ids & linked
            and all(jobs[j]["candidate_id"] == cid for j in ids),
            "candidate job binding mismatch",
        )
        linked.update(ids)
        if row["manifest_digest"] is not None:
            checked_digest(row["manifest_digest"])
        _fields(row["gates"], GATES, "candidate gates")
        _need(
            all(g in ("PASS", "FAIL", "HOLD") for g in row["gates"].values()),
            "invalid candidate gate",
        )
        if row["status"] == "evaluated":
            checked_digest(row["manifest_digest"])
            _need(
                row["manifest_digest"] != contract["incumbent_manifest_digest"],
                "zero delta is not an update candidate",
            )
            checked_digest(row["evaluation_receipt_digest"])
            evaluations = [
                jobs[j]
                for j in ids
                if jobs[j]["phase"] == "evaluation"
                and jobs[j]["status"] == "succeeded"
                and jobs[j]["receipt_digest"] == row["evaluation_receipt_digest"]
            ]
            _need(
                len(evaluations) == 1,
                "evaluation job missing or receipt mismatched/ambiguous",
            )
            construction = [
                jobs[j]
                for j in ids
                if jobs[j]["phase"] in ("training", "search")
                and jobs[j]["status"] == "succeeded"
            ]
            _need(construction, "successful candidate construction job missing")
            _need(
                any(
                    job["artifact_digest"] == row["manifest_digest"]
                    for job in construction
                )
                and evaluations[0]["artifact_digest"] == row["manifest_digest"],
                "construction/evaluation artifact does not match candidate manifest",
            )
            _need(
                all(
                    _time(job["ended_at"]) <= _time(evaluations[0]["started_at"])
                    for job in construction
                ),
                "candidate evaluation precedes successful construction or later reconstruction",
            )
            if "HOLD" in row["gates"].values():
                reasons.append("candidate_evidence_incomplete:" + cid)
            elif all(g == "PASS" for g in row["gates"].values()):
                qualified.append(cid)
        else:
            _need(
                row["evaluation_receipt_digest"] is None
                and set(row["gates"].values()) == {"HOLD"},
                "unevaluated candidate has result",
            )
            if row["status"] == "unresolved":
                reasons.append("candidate_unresolved:" + cid)
            if row["status"] == "failed":
                _need(
                    any(jobs[j]["status"] == "failed" for j in ids),
                    "failed candidate has no failed job receipt",
                )
            if row["status"] in ("skipped_no_data", "skipped_budget"):
                _need(
                    row["manifest_digest"] is None and not ids,
                    "skipped slot contains executed work",
                )
        candidates[cid] = row
    if set(candidates) != expected:
        reasons.append("incomplete_candidate_inventory")
    _need(
        linked == {j for j, r in jobs.items() if r["candidate_id"] is not None},
        "unlisted candidate job",
    )
    reason = evidence["stop_reason"]
    if reason == "candidates_exhausted" and not any(
        r["status"] == "evaluated" for r in candidates.values()
    ):
        reasons.append("no_completed_candidate_evaluation")
    if reason == "no_eligible_data":
        if eligible != 0:
            reasons.append("no_eligible_data_not_established")
        _need(
            all(r["status"] == "skipped_no_data" for r in candidates.values()),
            "no-data stop has candidate execution",
        )
    else:
        if eligible is None or eligible <= 0:
            reasons.append("eligible_data_not_established")
        _need(
            all(r["status"] != "skipped_no_data" for r in candidates.values()),
            "inconsistent no-data skip",
        )
    if reason != "budget_stop":
        _need(
            all(r["status"] != "skipped_budget" for r in candidates.values()),
            "unregistered budget skip",
        )
    if (
        reason == "budget_stop"
        and completed < deadline
        and spent < contract["maximum_cost"]
    ):
        reasons.append("predeclared_budget_not_reached")
    terminal = evidence["terminal_evaluation"]
    if terminal is None:
        reasons.append("missing_independent_terminal_evaluation")
        unknown.append("terminal_evaluation:meter_binding")
    else:
        _fields(
            terminal,
            (
                "evaluator_id",
                "evaluator_digest",
                "objective_digest",
                "incumbent_manifest_digest",
                "data_admission_digest",
                "candidate_inventory_digest",
                "job_inventory_digest",
                "receipt_digest",
                "meter_job_id",
            ),
            "terminal evaluation",
        )
        for field in (
            "evaluator_id",
            "evaluator_digest",
            "objective_digest",
            "incumbent_manifest_digest",
        ):
            _need(
                terminal[field] == contract[field],
                "terminal evaluation binding mismatch",
            )
        for field, source in (
            ("data_admission_digest", "data_admission"),
            ("candidate_inventory_digest", "candidates"),
            ("job_inventory_digest", "jobs"),
        ):
            _need(
                terminal[field] == digest(evidence[source]),
                "terminal inventory binding mismatch",
            )
        checked_digest(terminal["receipt_digest"])
        meter_id = terminal["meter_job_id"]
        _ids([meter_id], "terminal meter job")
        if meter_id not in jobs:
            reasons.append("missing_terminal_evaluation_meter_job")
            unknown.append("terminal_meter:" + meter_id)
        else:
            meter = jobs[meter_id]
            _need(
                meter["phase"] == "evaluation" and meter["candidate_id"] is None,
                "terminal evaluation needs its own independent meter job",
            )
            _need(
                meter["artifact_digest"] is None,
                "terminal meter cannot bind the signed terminal artifact",
            )
            # The job receipt attests metering, not this signed terminal report:
            # terminal -> job inventory -> meter receipt has no self-hash cycle.
            _need(
                meter["receipt_digest"] != terminal["receipt_digest"],
                "terminal meter receipt must differ from signed terminal receipt",
            )
            _need(
                all(
                    _time(job["ended_at"]) <= _time(meter["started_at"])
                    for job_id, job in jobs.items()
                    if job_id != meter_id
                ),
                "terminal evaluation precedes retained job inventory",
            )
            if meter["status"] != "succeeded" or meter["receipt_digest"] is None:
                reasons.append("incomplete_terminal_evaluation_meter_job")
                unknown.append("terminal_meter:" + meter_id)
    if reason == "execution_failed":
        checked_digest(evidence["failure_receipt_digest"])
        failed = True
    else:
        _need(
            evidence["failure_receipt_digest"] is None,
            "campaign failure must use execution_failed",
        )
    if unknown:
        reasons.append("unknown_costs")
    conditional = (
        "Failed"
        if failed
        else "Inconclusive"
        if reasons
        else "Adoptable"
        if qualified
        else "NoUpdate"
    )
    continuation = {"status": "NOT_SUPPLIED", "verified": False}
    if next_task is not None:
        _fields(
            next_task,
            (
                "operation_id",
                "decision_evidence_digest",
                "prior_task_id",
                "prior_run_id",
                "task_id",
                "run_id",
                "manifest_digest",
                "source_checkpoint_digest",
                "checkpoint_digest",
                "committed_step_receipt_digest",
                "final_use_receipt_digest",
                "purpose",
            ),
            "next task",
        )
        _need(
            conditional == "NoUpdate",
            "incumbent continuation only maps a conditional NoUpdate",
        )
        _need(
            next_task["operation_id"] == contract["operation_id"]
            and next_task["decision_evidence_digest"] == digest(evidence)
            and next_task["prior_task_id"] == contract["source_task_id"]
            and next_task["prior_run_id"] == contract["source_run_id"]
            and next_task["manifest_digest"] == contract["incumbent_manifest_digest"]
            and next_task["source_checkpoint_digest"]
            == contract["incumbent_checkpoint_digest"],
            "incumbent continuation binding mismatch",
        )
        _ids([next_task["task_id"], next_task["prior_task_id"]], "different next task")
        _ids([next_task["run_id"], next_task["prior_run_id"]], "different next run")
        _need(
            next_task["purpose"] == "agentd.cell-generation.next-task-same-model",
            "wrong FinalUse purpose",
        )
        for field in (
            "checkpoint_digest",
            "committed_step_receipt_digest",
            "final_use_receipt_digest",
        ):
            checked_digest(next_task[field])
        _need(
            next_task["checkpoint_digest"] != next_task["source_checkpoint_digest"],
            "next task must produce a distinct owner checkpoint",
        )
        continuation = {
            "status": "STRUCTURE_CHECKED_NATIVE_AUTHENTICATION_REQUIRED",
            "verified": False,
            "receipt_digest": digest(next_task),
        }
    return {
        "schema": "ndu-learning-outcome-audit-v1",
        "operation_id": contract["operation_id"],
        "contract_digest": digest(contract),
        "evidence_digest": digest(evidence),
        "outcome": "Inconclusive",
        "conditional_outcome": conditional,
        "qualified_candidate_ids": sorted(qualified),
        "conditional_reason": reason,
        "reasons": sorted(set(reasons)),
        "status": "HOLD",
        "costs": {
            "known_subtotal": spent,
            "total": None if unknown else spent,
            "unknowns": unknown,
            "recorded_ledger_total": recorded_ledger_total,
            "coverage": "incomplete" if unknown else "declared_complete",
            "unit": contract["cost_unit"],
            "jobs": len(jobs),
        },
        "incumbent_continuation": continuation,
        "native_receipt_verification": {"verified": False, "status": "NOT_IMPLEMENTED"},
        "adoption_authorized": False,
        "chain_submission": None,
        "reward_eligible": False,
        "global_optimality_claim": False,
        "claim": "Conditional finite-decision arithmetic only; native evidence and actual incumbent reuse remain separately required.",
    }

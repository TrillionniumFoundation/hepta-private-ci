"""Fail-closed, read-only four-stage MemoryCell research outcome reconciliation.

This consumes SEALED original-result *metadata*, not model outputs or trusted
semantic judgments. It never trains, executes tasks, attests identities, chooses
an evaluation policy, or promotes production. Unavailable attempts remain in the
registered denominator. External source/authentication checks precede this audit.
"""

from collections import Counter
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = "hepta.memory-cell.four-stage-research.v1"
CONDITIONS = ("none", "retrieved", "reviewed", "ablated")
EXTRA = (
    "single_hop",
    "entity_time",
    "organized",
    "learned_policy",
    "knowledge",
    "module_only",
)
LEARNED = ("learned_policy", "knowledge", "module_only")
TASK_KINDS = ("new_fact", "updated_fact", "cross_experience", "program")
COST_PARTS = (
    "extract",
    "index",
    "train",
    "query",
    "maintenance",
    "revocation",
    "recovery",
)
HEX = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[a-zA-Z0-9_.-]{1,96}\Z")


def _sha(value):
    if not isinstance(value, str) or HEX.fullmatch(value) is None:
        raise ValueError("nonempty sha256 required")
    return value


def _identity(value):
    if not isinstance(value, str) or IDENT.fullmatch(value) is None:
        raise ValueError("bounded identity required")
    return value


def _int(value, minimum=0, maximum=10**9):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("bounded integer required")
    return value


def _number(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative cost required")
    return float(value)


def _census(plan):
    if (
        set(plan)
        != {"schema", "source_commit", "frozen_plan_sha256", "readers", "tasks"}
        or plan["schema"] != SCHEMA
    ):
        raise ValueError("registered schema fields required")
    if not re.fullmatch(r"[0-9a-f]{40}", plan["source_commit"]):
        raise ValueError("generating source commit required")
    _sha(plan["frozen_plan_sha256"])
    if set(plan["readers"]) != {"baseline", "reference"}:
        raise ValueError("both fixed readers required")
    for value in plan["readers"].values():
        if set(value) != {
            "weights",
            "prompt",
            "tool_acl",
            "input_limit",
            "output_limit",
        }:
            raise ValueError("reader protocol incomplete")
        for name in ("weights", "prompt", "tool_acl"):
            _sha(value[name])
        _int(value["input_limit"], 1, 100000)
        _int(value["output_limit"], 1, 4096)
    small, strong = plan["readers"]["baseline"], plan["readers"]["reference"]
    if small["weights"] == strong["weights"] or any(
        small[key] != strong[key]
        for key in ("prompt", "tool_acl", "input_limit", "output_limit")
    ):
        raise ValueError("reference changes more than reader capacity")
    tasks = plan["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 1000:
        raise ValueError("bounded fixed task census required")
    by_task = {}
    for item in tasks:
        if set(item) != {
            "id",
            "family",
            "kind",
            "source_cut",
            "write_frozen_at",
            "task_exposed_at",
            "pool_sha256",
            "frontier_sha256",
            "critical_evidence_id",
        }:
            raise ValueError("task freeze/exposure contract incomplete")
        qid = _identity(item["id"])
        _identity(item["family"])
        if item["kind"] not in TASK_KINDS or qid in by_task:
            raise ValueError("unknown task kind or duplicate task")
        _int(item["source_cut"])
        _int(item["write_frozen_at"])
        _int(item["task_exposed_at"])
        if not item["source_cut"] <= item["write_frozen_at"] < item["task_exposed_at"]:
            raise ValueError("learning was not frozen before task exposure")
        _sha(item["pool_sha256"])
        _sha(item["frontier_sha256"])
        _identity(item["critical_evidence_id"])
        by_task[qid] = item
    return by_task


def _record(row, task, reader, condition):
    required = {
        "id",
        "reader",
        "condition",
        "generating_commit",
        "frozen_plan_sha256",
        "reader_weights",
        "prompt",
        "tool_acl",
        "input_limit",
        "output_limit",
        "pool_sha256",
        "frontier_sha256",
        "evidence_ids",
        "evidence_sha256",
        "answer_sha256",
        "status",
        "task_success",
        "program_trace_sha256",
        "program_verified",
        "diagnostic_calls",
        "input_tokens",
        "cost_usd",
        "write_sha256",
    }
    if set(row) != required:
        raise ValueError("missing or extra original model receipt field")
    if any(
        row[field] != reader[name]
        for field, name in (
            ("reader_weights", "weights"),
            ("prompt", "prompt"),
            ("tool_acl", "tool_acl"),
            ("input_limit", "input_limit"),
            ("output_limit", "output_limit"),
        )
    ):
        raise ValueError("reader weights/prompt/budget/tools drift")
    if (
        row["pool_sha256"] != task["pool_sha256"]
        or row["frontier_sha256"] != task["frontier_sha256"]
    ):
        raise ValueError("source frontier or candidate pool drift")
    evid = row["evidence_ids"]
    if not isinstance(evid, list) or len(evid) > 32 or len(evid) != len(set(evid)):
        raise ValueError("bounded unique delivered evidence required")
    for item in evid:
        _identity(item)
    _sha(row["evidence_sha256"])
    if condition in ("none", "module_only") and evid:
        raise ValueError("no-evidence control received original evidence")
    if row["status"] not in ("succeeded", "failed", "unavailable"):
        raise ValueError("invalid attempt state")
    if row["status"] == "unavailable" and condition not in ("reviewed", "ablated"):
        raise ValueError("missing original execution is not an eligible oracle absence")
    success = row["status"] == "succeeded"
    if (
        type(row["task_success"]) is not bool
        if success
        else row["task_success"] is not None
    ):
        raise ValueError("success / missing outcome mismatch")
    if success:
        _sha(row["answer_sha256"])
    elif row["answer_sha256"] is not None:
        raise ValueError("absent generation cannot supply answer")
    _int(row["diagnostic_calls"], 0, 100000)
    _int(row["input_tokens"], 0, reader["input_limit"])
    _number(row["cost_usd"])
    if task["kind"] == "program" and success:
        _sha(row["program_trace_sha256"])
        if type(row["program_verified"]) is not bool or (
            row["task_success"] and not row["program_verified"]
        ):
            raise ValueError("program success requires original verified execution")
    elif row["program_trace_sha256"] is not None or row["program_verified"] is not None:
        raise ValueError("only executed program tasks may include procedure trace")
    if condition in LEARNED:
        _sha(row["write_sha256"])
    elif row["write_sha256"] is not None:
        raise ValueError("nonlearned comparison cannot claim a learned write")


def _contrast(rows, left, right):
    count = Counter()
    for by_arm in rows.values():
        a, b = by_arm[left], by_arm[right]
        if a["status"] != "succeeded" or b["status"] != "succeeded":
            count["missing"] += 1
        elif a["task_success"] and not b["task_success"]:
            count["wins"] += 1
        elif b["task_success"] and not a["task_success"]:
            count["losses"] += 1
        else:
            count["ties"] += 1
    total = len(rows)
    assert sum(count.values()) == total
    wins, losses, missing = (count[key] for key in ("wins", "losses", "missing"))
    return dict(
        planned=total,
        **{key: count[key] for key in ("wins", "losses", "ties", "missing")},
        all_planned_effect_bounds=[
            (wins - losses - missing) / total,
            (wins - losses + missing) / total,
        ],
    )


def _costs(ledger):
    if set(ledger) != {"unit", "queries_reused", "arms"} or ledger["unit"] != "usd":
        raise ValueError("single comparable monetary unit required")
    count = _int(ledger["queries_reused"], 1, 10**9)
    if set(ledger["arms"]) != {
        "retrieved",
        "organized",
        "learned_policy",
        "knowledge",
        "module_only",
    }:
        raise ValueError("cost must retain every relevant original/control arm")
    report = {}
    for arm, data in ledger["arms"].items():
        if set(data) != set(COST_PARTS) | {
            "retained_raw_evidence_bytes",
            "retained_index_bytes",
            "storage_included_in_maintenance",
        }:
            raise ValueError("missing extraction/index/storage or maintenance cost")
        costs = {k: _number(data[k]) for k in COST_PARTS}
        raw = _int(data["retained_raw_evidence_bytes"])
        index = _int(data["retained_index_bytes"])
        if type(data["storage_included_in_maintenance"]) is not bool:
            raise ValueError("storage charge attribution required")
        complete = (
            all(value is not None for value in costs.values())
            and data["storage_included_in_maintenance"]
        )
        total = (
            (sum(costs[k] for k in COST_PARTS if k != "query") + count * costs["query"])
            if complete
            else None
        )
        report[arm] = dict(
            complete=complete,
            observed_query_reuse=count,
            total_lifecycle_usd=total,
            retained_raw_evidence_bytes=raw,
            retained_index_bytes=index,
            unknown_cost_phases=[k for k in COST_PARTS if costs[k] is None],
            storage_accounted=data["storage_included_in_maintenance"],
        )
    return report


def audit(plan, attempts, ledger):
    """Only development triage; no per-task oracle wins or auto promotion."""
    tasks = _census(plan)
    if not isinstance(attempts, list) or len(attempts) != 14 * len(tasks):
        raise ValueError("all preregistered reader / memory controls required")
    seen = {}
    required = {
        (qid, reader, condition)
        for qid in tasks
        for reader in ("baseline", "reference")
        for condition in CONDITIONS
    } | {(qid, "baseline", condition) for qid in tasks for condition in EXTRA}
    for row in attempts:
        if not isinstance(row, dict):
            raise ValueError("receipt object required")
        key = row.get("id"), row.get("reader"), row.get("condition")
        if key not in required or key in seen:
            raise ValueError("unexpected, duplicate or task-missing attempt")
        qid, reader, condition = key
        if (
            row["generating_commit"] != plan["source_commit"]
            or row["frozen_plan_sha256"] != plan["frozen_plan_sha256"]
        ):
            raise ValueError("attempt source or pre-registered plan drift")
        _record(row, tasks[qid], plan["readers"][reader], condition)
        seen[key] = row
    if set(seen) != required:
        raise ValueError("missing frozen reader condition")
    baseline = {
        qid: {
            condition: seen[qid, "baseline", condition]
            for condition in CONDITIONS + EXTRA
        }
        for qid in tasks
    }
    reference = {
        qid: {condition: seen[qid, "reference", condition] for condition in CONDITIONS}
        for qid in tasks
    }
    for qid, task in tasks.items():
        small, large = baseline[qid], reference[qid]
        for condition in CONDITIONS:
            if (
                small[condition]["evidence_ids"] != large[condition]["evidence_ids"]
                or small[condition]["evidence_sha256"]
                != large[condition]["evidence_sha256"]
            ):
                raise ValueError("reference model saw different evidence")
        for group in (small, large):
            sufficient, removed = group["reviewed"], group["ablated"]
            if (sufficient["status"] == "unavailable") != (
                removed["status"] == "unavailable"
            ):
                raise ValueError("ablation requires available reviewed evidence")
            if sufficient["status"] != "unavailable":
                ids = sufficient["evidence_ids"]
                if task["critical_evidence_id"] not in ids or removed[
                    "evidence_ids"
                ] != [x for x in ids if x != task["critical_evidence_id"]]:
                    raise ValueError(
                        "ablation did not remove exactly the registered premise"
                    )
        if (
            small["organized"]["evidence_ids"] != small["knowledge"]["evidence_ids"]
            or small["organized"]["evidence_sha256"]
            != small["knowledge"]["evidence_sha256"]
        ):
            raise ValueError(
                "knowledge head comparison must use identical delivered evidence"
            )
        if (
            small["learned_policy"]["write_sha256"]
            == small["knowledge"]["write_sha256"]
        ):
            raise ValueError("separate policy and knowledge write identities required")
        if small["module_only"]["write_sha256"] != small["knowledge"]["write_sha256"]:
            raise ValueError(
                "parameter-only comparison must use the same knowledge module"
            )
    for arm in LEARNED:
        if len({baseline[qid][arm]["write_sha256"] for qid in tasks}) != 1:
            raise ValueError("candidate write drifted after pre-task freeze")
    diagnoses = Counter()
    for qid in tasks:
        b, r = baseline[qid], reference[qid]
        if b["reviewed"]["status"] != "succeeded":
            diagnoses["no_verified_sufficient_reader_trial"] += 1
        elif not b["reviewed"]["task_success"]:
            diagnoses["sufficient_context_still_wrong"] += 1
        elif (
            b["retrieved"]["status"] == "succeeded"
            and not b["retrieved"]["task_success"]
        ):
            diagnoses["retrieval_or_evidence_packaging_bottleneck"] += 1
        if (
            b["reviewed"]["status"] == b["ablated"]["status"] == "succeeded"
            and b["ablated"]["task_success"]
        ):
            diagnoses["premise_ablation_not_necessary"] += 1
        if (
            r["reviewed"]["status"] == b["reviewed"]["status"] == "succeeded"
            and r["reviewed"]["task_success"]
            and not b["reviewed"]["task_success"]
        ):
            diagnoses["reference_reader_capacity_only"] += 1
    paired = {
        "organization_over_strong_rag": _contrast(baseline, "organized", "retrieved"),
        "correction_graph_over_entity_time": _contrast(
            baseline, "organized", "entity_time"
        ),
        "learned_policy_over_organized": _contrast(
            baseline, "learned_policy", "organized"
        ),
        "learned_policy_over_strong_rag": _contrast(
            baseline, "learned_policy", "retrieved"
        ),
        "knowledge_over_same_evidence": _contrast(baseline, "knowledge", "organized"),
        "module_only_over_organized_diagnostic": _contrast(
            baseline, "module_only", "organized"
        ),
    }
    decisions = {}
    for name, comparisons in {
        "learned_policy": (
            "learned_policy_over_organized",
            "learned_policy_over_strong_rag",
        ),
        "knowledge": ("knowledge_over_same_evidence",),
    }.items():
        values = [paired[key] for key in comparisons]
        if any(row["missing"] for row in values):
            outcome = "incomplete_reject_promotion"
        elif any(row["losses"] for row in values):
            outcome = "reject_observed_regressions"
        elif any(row["wins"] <= row["losses"] for row in values):
            outcome = "reject_no_independent_task_gain"
        else:
            outcome = "new_prospective_evaluation_required"
        decisions[name] = outcome
    return dict(
        schema=SCHEMA,
        planned_tasks=len(tasks),
        planned_model_calls=len(required),
        actual_successful_calls=sum(
            row["status"] == "succeeded" for row in seen.values()
        ),
        task_kinds=dict(Counter(item["kind"] for item in tasks.values())),
        source_families=len({item["family"] for item in tasks.values()}),
        capacity_diagnoses=dict(diagnoses),
        paired_contrasts=paired,
        learning_disposition=decisions,
        parameter_only_disposition="compression_boundary_only",
        lifecycle_cost=_costs(ledger),
        original_execution_authenticated_by_this_tool=False,
        independent_sufficient_evidence_verified_by_this_tool=False,
        independent_semantic_citation_judgment=False,
        prospective_future_windows_observed=False,
        current_cross_node_withdrawal_observed=False,
        allow_parametric_promotion=False,
        production_accepted=False,
    )


def strict_file(path, sha256):
    path = Path(path)
    _sha(sha256)
    if (
        path.is_symlink()
        or any(parent.is_symlink() for parent in path.parents)
        or not path.is_file()
        or path.stat().st_size > 16 * 1024 * 1024
    ):
        raise ValueError("bounded regular externally pinned input required")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError("external input pin mismatch")

    def unique(pairs):
        obj = {}
        for key, val in pairs:
            if key in obj:
                raise ValueError("duplicate JSON field")
            obj[key] = val
        return obj

    def invalid(_):
        raise ValueError("nonfinite JSON")

    return json.loads(content, object_pairs_hook=unique, parse_constant=invalid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for label in ("plan", "attempts", "ledger"):
        parser.add_argument(label, type=Path)
        parser.add_argument("--" + label + "-sha256", required=True)
    args = parser.parse_args()
    data = [
        strict_file(getattr(args, name), getattr(args, name + "_sha256"))
        for name in ("plan", "attempts", "ledger")
    ]
    print(json.dumps(audit(*data), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

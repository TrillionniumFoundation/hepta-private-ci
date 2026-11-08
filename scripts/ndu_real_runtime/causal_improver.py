"""E registry accounting and paired improver comparison; no attempt dispatch."""

from ._causal_checks import (
    COST_STAGES,
    COST_UNITS,
    _fields,
    _number,
    _pin,
    _require,
    _sha,
    _text,
)


def _reported_costs(ledger, *, unresolved=False):
    """Sum disjoint accounted work; missing measurements remain lower bounds."""
    known = {unit: 0.0 for unit in COST_UNITS}
    complete = {unit: ledger is not None and not unresolved for unit in COST_UNITS}
    if ledger is not None:
        _fields(ledger, COST_STAGES, "E_COST_SCOPE_INCOMPLETE")
        for cell in ledger.values():
            _fields(cell, ("status", "values", "evidence"), "E_COST_CELL_FIELDS")
            _require(
                _text(cell["status"])
                and cell["status"] in {"measured", "not_applicable", "unknown"}
                and _text(cell["evidence"]),
                "E_COST_BASIS_REQUIRED",
            )
            if cell["status"] == "not_applicable":
                _require(cell["values"] == {}, "E_NOT_APPLICABLE_IS_NOT_A_MEASUREMENT")
                continue
            _fields(cell["values"], COST_UNITS, "E_COST_UNITS")
            for unit, value in cell["values"].items():
                _require(value is None or _number(value, minimum=0), "E_INVALID_COST")
                if value is not None:
                    known[unit] += value
                    _require(_number(known[unit]), "E_COST_SUM_OVERFLOW")
                if value is None or cell["status"] == "unknown":
                    complete[unit] = False
    return {
        "known_lower_bounds": known,
        "totals": {
            unit: known[unit] if complete[unit] else None for unit in COST_UNITS
        },
    }


def _improver_runs(plan):
    _fields(plan, ("schema", "improvers", "runs", "cost_penalty"), "E_PLAN_FIELDS")
    _require(plan["schema"] == "ndu.causal.improver-comparison.v1", "E_PLAN_SCHEMA")
    _fields(plan["improvers"], ("parent", "child"), "E_IMPROVER_ROLES")
    for value in plan["improvers"].values():
        _fields(value, ("artifact_digest", "parent_digest"), "E_IMPROVER_BINDING")
        _require(_pin(value["artifact_digest"]), "E_IMPROVER_ARTIFACT")
    parent, child = (plan["improvers"][role] for role in ("parent", "child"))
    _require(
        parent["parent_digest"] is None
        and child["parent_digest"] == parent["artifact_digest"]
        and child["artifact_digest"] != parent["artifact_digest"],
        "E_IMPROVER_LINEAGE",
    )
    penalty = plan["cost_penalty"]
    _fields(penalty, ("unit", "per_unit"), "E_COST_PENALTY_FIELDS")
    _require(
        penalty["unit"] in COST_UNITS and _number(penalty["per_unit"], minimum=0),
        "E_COST_PENALTY_UNIT",
    )
    runs, pairs = {}, {}
    _require(isinstance(plan["runs"], list) and plan["runs"], "E_RUNS_REQUIRED")
    for run in plan["runs"]:
        _fields(
            run,
            (
                "run_id",
                "pair_id",
                "role",
                "improver_digest",
                "producer_owner",
                "evaluator_owner",
                "common_start",
                "full_budget_contract",
                "acceptance_profile",
                "holdout_profile",
            ),
            "E_RUN_FIELDS",
        )
        _require(
            all(
                _text(run[key])
                for key in ("run_id", "pair_id", "producer_owner", "evaluator_owner")
            )
            and run["run_id"] not in runs
            and _text(run["role"])
            and run["role"] in {"parent", "child"},
            "E_RUN_IDENTITY",
        )
        _require(
            run["improver_digest"] == plan["improvers"][run["role"]]["artifact_digest"]
            and all(_pin(run[key]) for key in ("acceptance_profile", "holdout_profile"))
            and run["acceptance_profile"] != run["holdout_profile"],
            "E_RUN_PINS",
        )
        start = run["common_start"]
        split_keys = (
            "training_data",
            "development_data",
            "acceptance_data",
            "holdout_data",
        )
        _fields(
            start,
            (
                "initial_bundle",
                "seed",
                "source_cluster",
                *split_keys,
                "training_families",
                "holdout_family",
            ),
            "E_START_FIELDS",
        )
        _require(
            _pin(start["initial_bundle"])
            and all(_pin(start[key]) for key in split_keys)
            and len({start[key] for key in split_keys}) == len(split_keys)
            and type(start["seed"]) is int
            and 0 <= start["seed"] < 2**63
            and _text(start["source_cluster"])
            and _text(start["holdout_family"])
            and isinstance(start["training_families"], list)
            and start["training_families"]
            and all(_text(item) for item in start["training_families"])
            and len(start["training_families"]) == len(set(start["training_families"]))
            and start["holdout_family"] not in start["training_families"],
            "E_COMMON_START_OR_HELDOUT_LEAKAGE",
        )
        budget = run["full_budget_contract"]
        _fields(budget, ("scope", "limits", "candidate_attempts"), "E_BUDGET_FIELDS")
        _require(
            budget["scope"] == list(COST_STAGES)
            and isinstance(budget["limits"], dict)
            and budget["limits"]
            and set(budget["limits"]) <= set(COST_UNITS)
            and all(_number(value, minimum=0) for value in budget["limits"].values())
            and type(budget["candidate_attempts"]) is int
            and 0 < budget["candidate_attempts"] <= 100000,
            "E_FULL_BUDGET_REQUIRED",
        )
        pair = pairs.setdefault(run["pair_id"], {})
        _require(run["role"] not in pair, "E_DUPLICATE_PAIR_ROLE")
        pair[run["role"]] = run
        runs[run["run_id"]] = run
    _require(
        not {run["producer_owner"] for run in runs.values()}.intersection(
            run["evaluator_owner"] for run in runs.values()
        ),
        "E_EVALUATOR_NOT_INDEPENDENT",
    )
    starts = set()
    for pair in pairs.values():
        _require(set(pair) == {"parent", "child"}, "E_UNPAIRED_IMPROVER")
        parent, child = pair["parent"], pair["child"]
        _require(parent["common_start"] == child["common_start"], "E_UNMATCHED_START")
        _require(
            parent["full_budget_contract"] == child["full_budget_contract"],
            "E_UNMATCHED_FULL_BUDGET",
        )
        _require(
            all(
                parent[key] == child[key]
                for key in ("acceptance_profile", "holdout_profile", "evaluator_owner")
            ),
            "E_UNMATCHED_EVALUATION",
        )
        identity = _sha(parent["common_start"])
        _require(identity not in starts, "E_DUPLICATED_PAIR_NOT_INDEPENDENT")
        starts.add(identity)
    return runs, pairs


def _evaluation(kind, reference, run, candidate, read_evaluation, verify_evaluation):
    if (
        reference is None
        or not callable(read_evaluation)
        or not callable(verify_evaluation)
    ):
        return None
    record = read_evaluation(kind, reference)
    if record is None:
        return None
    _require(
        isinstance(record, dict)
        and verify_evaluation(kind, record, run["evaluator_owner"]) is True,
        "E_EVALUATION_AUTHENTICATION_REJECTED",
    )
    final = kind == "heldout_final"
    _require(
        record.get("kind") == kind
        and record.get("run_id") == run["run_id"]
        and record.get("actor_id") == run["evaluator_owner"]
        and record.get("candidate_bundle") == candidate
        and record.get("baseline_bundle") == run["common_start"]["initial_bundle"]
        and record.get("evaluation_profile")
        == run["holdout_profile" if final else "acceptance_profile"]
        and record.get("data_digest")
        == run["common_start"]["holdout_data" if final else "acceptance_data"]
        and _pin(record.get("evidence_digest"))
        and type(record.get("observed_unix_seconds")) is int
        and 0 < record["observed_unix_seconds"] < 2**63
        and all(
            _number(record.get(key))
            for key in ("baseline_utility", "candidate_utility")
        ),
        "E_EVALUATION_BINDING",
    )
    _require(
        _number(record["candidate_utility"] - record["baseline_utility"]),
        "E_UTILITY_OVERFLOW",
    )
    return record


def compare_improvers(
    plan, attempt_registry, attempts, *, read_evaluation=None, verify_evaluation=None
):
    """Compare registered parent/child attempts without dropping unsuccessful work.

    Registry entries are actual admitted improvement invocations, not scheduled
    episodes. Reconciliation reads reuse their attempt ID. Missing outcomes stay
    UNKNOWN; fresh retries of an unresolved operation are refused. run_overheads
    must account for improver construction and costs outside individual attempts.
    Cost ledgers cover every stage, with explicit measured/unknown/not_applicable
    entries and separate units. Their provenance is checked by the host meter.

    Acceptance and final heldout results are only counted through independently
    authenticated evaluator ports. Final records must bind a selection committed
    before evaluation. Results are descriptive; replication/power and raw meter
    qualification belong to the common protocol, not this counting function.
    """
    runs, pairs = _improver_runs(plan)
    _fields(
        attempt_registry,
        ("schema", "sealed", "entries", "run_overheads", "finals"),
        "E_REGISTRY_FIELDS",
    )
    _require(
        attempt_registry["schema"] == "ndu.causal.improver-attempt-registry.v1"
        and type(attempt_registry["sealed"]) is bool
        and isinstance(attempt_registry["entries"], list)
        and isinstance(attempts, list),
        "E_REGISTRY_SCHEMA",
    )
    for key in ("run_overheads", "finals"):
        _require(
            isinstance(attempt_registry[key], dict)
            and set(attempt_registry[key]) <= set(runs),
            "E_UNKNOWN_RUN_ACCOUNTING",
        )
    entries, operations = {}, set()
    for entry in attempt_registry["entries"]:
        _fields(
            entry,
            (
                "attempt_id",
                "run_id",
                "operation_id",
                "request_sha256",
                "retry_of",
                "original_attempt_reference",
            ),
            "E_REGISTRY_ENTRY_FIELDS",
        )
        _require(
            all(
                _text(entry[key])
                for key in (
                    "attempt_id",
                    "run_id",
                    "operation_id",
                    "original_attempt_reference",
                )
            )
            and _pin(entry["request_sha256"])
            and entry["run_id"] in runs
            and entry["attempt_id"] not in entries
            and entry["operation_id"] not in operations,
            "E_DUPLICATE_OR_UNBOUND_ATTEMPT",
        )
        retry = entry["retry_of"]
        _require(
            retry is None
            or _text(retry)
            and retry in entries
            and entries[retry]["run_id"] == entry["run_id"],
            "E_INVALID_RETRY_LINEAGE",
        )
        entries[entry["attempt_id"]] = entry
        operations.add(entry["operation_id"])
    rows = {}
    for row in attempts:
        _fields(
            row,
            (
                "attempt_id",
                "run_id",
                "operation_id",
                "request_sha256",
                "terminal_status",
                "candidate_digest",
                "validity",
                "evaluation_reference",
                "rolled_back",
                "rollback_reference",
                "costs",
            ),
            "E_ATTEMPT_FIELDS",
        )
        _require(
            _text(row["attempt_id"])
            and row["attempt_id"] in entries
            and row["attempt_id"] not in rows,
            "E_UNREGISTERED_OR_DUPLICATE_RESULT",
        )
        entry = entries[row["attempt_id"]]
        _require(
            all(
                row[key] == entry[key]
                for key in ("run_id", "operation_id", "request_sha256")
            ),
            "E_ATTEMPT_BINDING_MISMATCH",
        )
        _require(
            _text(row["terminal_status"])
            and _text(row["validity"])
            and row["terminal_status"]
            in {"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"}
            and row["validity"] in {"VALID", "INVALID", "UNKNOWN"}
            and (row["candidate_digest"] is None or _pin(row["candidate_digest"]))
            and (row["validity"] != "VALID" or _pin(row["candidate_digest"]))
            and (
                row["evaluation_reference"] is None
                or row["validity"] == "VALID"
                and _pin(row["evaluation_reference"])
            )
            and (type(row["rolled_back"]) is bool or row["rolled_back"] is None)
            and (
                _pin(row["rollback_reference"])
                if row["rolled_back"] is True
                else row["rollback_reference"] is None
            ),
            "E_ATTEMPT_OUTCOME",
        )
        rows[row["attempt_id"]] = row
    for entry in entries.values():
        if entry["retry_of"] is not None:
            original = rows.get(entry["retry_of"])
            _require(
                original is not None and original["terminal_status"] != "UNKNOWN",
                "E_RETRY_OF_UNRESOLVED_OPERATION",
            )
    reports, accepted_by_id, final_records = {}, {}, {}
    for run_id, run in runs.items():
        ids = [key for key, value in entries.items() if value["run_id"] == run_id]
        budget = run["full_budget_contract"]
        _require(len(ids) <= budget["candidate_attempts"], "E_ATTEMPT_BUDGET_EXCEEDED")
        counts = dict.fromkeys(
            (
                "valid",
                "invalid",
                "unknown_validity",
                "accepted",
                "rejected",
                "unresolved_evaluation",
                "reported_rollbacks",
                "unknown_rollback",
            ),
            0,
        )
        terminal = dict.fromkeys(("SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"), 0)
        costs = [_reported_costs(attempt_registry["run_overheads"].get(run_id))]
        for attempt_id in ids:
            entry, row = entries[attempt_id], rows.get(attempt_id)
            if row is None:
                terminal["UNKNOWN"] += 1
                counts["unknown_validity"] += 1
                counts["unknown_rollback"] += 1
                costs.append(_reported_costs(None))
                continue
            terminal[row["terminal_status"]] += 1
            counts[
                {"VALID": "valid", "INVALID": "invalid", "UNKNOWN": "unknown_validity"}[
                    row["validity"]
                ]
            ] += 1
            counts["reported_rollbacks"] += row["rolled_back"] is True
            counts["unknown_rollback"] += (
                row["rolled_back"] is None
                or row["terminal_status"] == "UNKNOWN"
                and row["rolled_back"] is not True
            )
            costs.append(
                _reported_costs(
                    row["costs"], unresolved=row["terminal_status"] == "UNKNOWN"
                )
            )
            if row["validity"] != "VALID":
                continue
            evaluation = _evaluation(
                "acceptance",
                row["evaluation_reference"],
                run,
                row["candidate_digest"],
                read_evaluation,
                verify_evaluation,
            )
            if evaluation is None:
                counts["unresolved_evaluation"] += 1
                continue
            _require(
                evaluation.get("attempt_id") == attempt_id
                and evaluation.get("operation_id") == entry["operation_id"]
                and type(evaluation.get("accepted")) is bool,
                "E_ACCEPTANCE_BINDING",
            )
            accepted_by_id[attempt_id] = evaluation["accepted"]
            counts["accepted" if evaluation["accepted"] else "rejected"] += 1
        known = {
            unit: sum(cost["known_lower_bounds"][unit] for cost in costs)
            for unit in COST_UNITS
        }
        totals = {
            unit: known[unit]
            if all(cost["totals"][unit] is not None for cost in costs)
            else None
            for unit in COST_UNITS
        }
        _require(all(_number(value) for value in known.values()), "E_COST_SUM_OVERFLOW")
        _require(
            all(known[unit] <= limit for unit, limit in budget["limits"].items()),
            "E_RESOURCE_BUDGET_EXCEEDED",
        )
        n = len(ids)
        valid_resolved = counts["accepted"] + counts["rejected"]
        uncertain_acceptance = (
            counts["unknown_validity"] + counts["unresolved_evaluation"]
        )
        reports[run_id] = {
            "pair_id": run["pair_id"],
            "role": run["role"],
            "attempted": n,
            **counts,
            "terminal_counts": terminal,
            "valid_per_attempt": counts["valid"] / n if n else None,
            "valid_per_attempt_is_lower_bound": counts["unknown_validity"] > 0,
            "valid_probability_bounds": [
                counts["valid"] / n,
                (counts["valid"] + counts["unknown_validity"]) / n,
            ]
            if n
            else None,
            "accepted_per_attempt": counts["accepted"] / n if n else None,
            "accepted_per_attempt_is_lower_bound": uncertain_acceptance > 0,
            "acceptance_probability_bounds": [
                counts["accepted"] / n,
                (counts["accepted"] + uncertain_acceptance) / n,
            ]
            if n
            else None,
            "accepted_per_valid_resolved": counts["accepted"] / valid_resolved
            if valid_resolved
            else None,
            "reported_rollback_per_attempt": counts["reported_rollbacks"] / n
            if n
            else None,
            "reported_rollback_bounds": [
                counts["reported_rollbacks"] / n,
                (counts["reported_rollbacks"] + counts["unknown_rollback"]) / n,
            ]
            if n
            else None,
            "cost_totals": totals,
            "cost_known_lower_bounds": known,
            "reported_cost_coverage_complete": all(
                value is not None for value in totals.values()
            ),
            "heldout_delta": None,
            "net_improvement": None,
        }
        final = attempt_registry["finals"].get(run_id)
        if final is None:
            continue
        _fields(
            final,
            (
                "attempt_id",
                "candidate_bundle",
                "selection_digest",
                "evaluation_reference",
            ),
            "E_FINAL_FIELDS",
        )
        _require(
            all(
                _pin(final[key])
                for key in (
                    "candidate_bundle",
                    "selection_digest",
                    "evaluation_reference",
                )
            ),
            "E_FINAL_PINS",
        )
        chosen = final["attempt_id"]
        if chosen is None:
            _require(
                final["candidate_bundle"] == run["common_start"]["initial_bundle"],
                "E_RETAINED_BUNDLE_MISMATCH",
            )
        else:
            _require(
                _text(chosen)
                and chosen in ids
                and chosen in rows
                and rows[chosen]["candidate_digest"] == final["candidate_bundle"],
                "E_FINAL_CANDIDATE_NOT_FROM_RUN",
            )
            _require(
                rows[chosen]["rolled_back"] is not True,
                "E_FINAL_CANDIDATE_WAS_ROLLED_BACK",
            )
            if rows[chosen]["rolled_back"] is None:
                continue
            if accepted_by_id.get(chosen) is not True:
                continue
        record = _evaluation(
            "heldout_final",
            final["evaluation_reference"],
            run,
            final["candidate_bundle"],
            read_evaluation,
            verify_evaluation,
        )
        if record is None:
            continue
        _require(
            record.get("selection_digest") == final["selection_digest"]
            and type(record.get("selection_committed_unix_seconds")) is int
            and 0
            < record["selection_committed_unix_seconds"]
            < record["observed_unix_seconds"]
            and record.get("task_family") == run["common_start"]["holdout_family"],
            "E_HOLDOUT_BEFORE_SELECTION_OR_LEAKAGE",
        )
        delta = record["candidate_utility"] - record["baseline_utility"]
        reports[run_id]["heldout_delta"] = delta
        penalty_cost = totals[plan["cost_penalty"]["unit"]]
        if penalty_cost is not None:
            net = delta - penalty_cost * plan["cost_penalty"]["per_unit"]
            _require(_number(net), "E_NET_IMPROVEMENT_OVERFLOW")
            reports[run_id]["net_improvement"] = net
        final_records[run_id] = record
    contrasts = []
    for pair_id, pair in pairs.items():
        parent_id, child_id = (pair[role]["run_id"] for role in ("parent", "child"))
        if parent_id in final_records and child_id in final_records:
            _require(
                final_records[parent_id]["baseline_utility"]
                == final_records[child_id]["baseline_utility"],
                "E_UNMATCHED_BASELINE_SCORE",
            )
        contrast = {"pair_id": pair_id, "parent_run": parent_id, "child_run": child_id}
        for key in ("heldout_delta", "net_improvement"):
            left, right = (reports[run_id][key] for run_id in (parent_id, child_id))
            difference = (
                right - left if left is not None and right is not None else None
            )
            _require(
                difference is None or _number(difference), "E_PAIRED_CONTRAST_OVERFLOW"
            )
            contrast[key + "_child_minus_parent"] = difference
        contrasts.append(contrast)
    complete = attempt_registry["sealed"] and all(
        report["attempted"]
        and not report["terminal_counts"]["UNKNOWN"]
        and not report["unknown_validity"]
        and not report["unresolved_evaluation"]
        and not report["unknown_rollback"]
        and report["reported_cost_coverage_complete"]
        and report["net_improvement"] is not None
        for report in reports.values()
    )
    return {
        "status": "DESCRIPTIVE_COMPLETE" if complete else "HOLD_INCOMPLETE_EVIDENCE",
        "registry_sha256": _sha(attempt_registry),
        "registry_closed": attempt_registry["sealed"],
        "registered_attempts": len(entries),
        "missing_results": sorted(set(entries) - set(rows)),
        "runs": reports,
        "paired_contrasts": contrasts,
        "statistics_unit": "preregistered_improver_run_pair_not_episode",
        "rates_with_unknowns_are_bounds": True,
        "cost_provenance_verified": False,
        "scientific_efficacy_qualified": False,
        "authority_granted": False,
    }

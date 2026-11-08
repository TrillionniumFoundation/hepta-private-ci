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



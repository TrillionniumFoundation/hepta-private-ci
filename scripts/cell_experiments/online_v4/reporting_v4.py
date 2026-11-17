"""Aggregate existing v4 receipts without importing model code or inferring zero cost."""

import hashlib
import json
import re

MODES = ("teacher", "shadow", "controlled")
ARMS = {"single", "fixed", "random_sparse", "learned_sparse"}
COSTS = ("model_calls", "input_tokens", "output_tokens", "verifier_calls",
         "business_executions", "format_rejections")
INFERENCE = COSTS[:4]
E2_SCHEMA = "hepta.current-policy-study.v1"


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "missing hash")
    return value


def count(value):
    require(type(value) is int and value >= 0, "missing/noninteger/negative count")
    return value


def receipt(value, schema, complete=True):
    require(isinstance(value, dict) and value.get("schema") == schema, "unknown/missing schema")
    if complete:
        require(value.get("status") == "COMPLETE", "receipt not COMPLETE")
    require(count(value.get("independent_sample_increment")) == 0, "independent N changed")


def sums(rows, keys):
    return {key: sum(row[key] for row in rows)
            if rows and all(row.get(key) is not None for row in rows) else None for key in keys}


def e2_cost(pack, mode):
    freeze, result = pack["freeze"], pack["result"]
    receipt(freeze, E2_SCHEMA, False)
    receipt(result, E2_SCHEMA)
    require(result["freeze_digest"] == digest(freeze), "FREEZE binding differs")
    require(freeze["collection_mode"] == result["collection_mode"] == mode, "arm differs")
    require(count(freeze["rounds"]) == 2 and count(freeze["steps_per_round"]) == 64
            and count(result["optimizer_steps"]) == 128, "expected 2 x 64 steps")
    require(freeze["optimizer_initialization"] == "fresh_AdamW_each_round"
            and freeze["weight_initialization"] == "previous_candidate_adapter"
            and freeze["retention"] == "latest_round_only"
            and 1 <= count(freeze["maximum_attempts"]) <= 4, "optimizer/weight/budget policy differs")
    require(freeze["final_evaluation"] == "same_exposed_A_after_last_update"
            and result["scientific_confirmation_qualified"] is False, "scope changed")
    require(len(result["rounds"]) == 2, "round coverage incomplete")
    previous = sha(freeze["initial_model_digest"])
    for index, row in enumerate(result["rounds"]):
        require(count(row["round_index"]) == index and row["current_model_digest"] == previous,
                "candidate chain differs")
        previous = sha(row["candidate_model_digest"])
        sha(row["training_digest"])
    require(previous == result["final_model_digest"] == digest(result["final_manifest"]),
            "final candidate differs")
    return {**{key: count(result[key]) for key in INFERENCE[:3]},
            "verifier_calls": count(result["student_verifier_calls"])}


def training_cost(pack):
    result, training = pack["result"], pack.get("training")
    require(isinstance(training, list) and len(training) == 2, "two actual TRAINING receipts unavailable")
    values = []
    for summary, item in zip(result["rounds"], training):
        receipt(item, "hepta.current-policy-sft-training.v1")
        require(digest(item) == summary["training_digest"], "TRAINING binding differs")
        require(count(item["steps"]) == 64 and item["optimizer_resume"] is False
                and item["optimizer_initialization"] == "fresh_AdamW_each_round"
                and item["warm_start"] is True and item["warm_start_matched"] is True,
                "training step/optimizer/warm-start differs")
        require(item["candidate_model_digest"] == summary["candidate_model_digest"]
                and item["previous_model_digest"] == summary["current_model_digest"]
                and item["parameter_before"] == summary["parameter_before"] == item["previous_parameter_after"]
                and item["parameter_after"] == summary["parameter_after"], "training continuity differs")
        values.append({key: count(item["cost"][key]) for key in
                       ("input_tokens_consumed", "supervised_tokens", "padded_training_token_positions")})
    return sums(values, values[0])


def aggregate(e2, search, studies, *, search_plan=None, study_plans=None):
    """e2[mode]={freeze,result,training?}; studies/plans map A,B to existing JSON.

    Training is an optional list of the two actual TRAINING.json objects. Missing
    evidence yields null, never zero. Plans are the producers' actual PLAN.json.
    Returned verifier subtotals include E2 student checks only; reference checks
    and full system cost remain unknown. This is not provenance authentication.
    """
    issues, ledger, training, seen = [], {}, {}, set()
    study_plans = study_plans or {}

    def checked(label, callback):
        try:
            return callback()
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
            issues.append({"component": label, "error": str(error)})
            return None

    def add(label, callback):
        value = checked(label, callback)
        ledger[label] = value if value is not None else {key: None for key in INFERENCE}
        return value

    def common():
        require(set(e2) == set(MODES), "all three E2 arms required")
        keys = ("initial_model_digest", "context_digest", "A_records_digest", "source_inventory",
                "rounds", "steps_per_round", "maximum_attempts", "optimizer_initialization", "retention")
        for key in keys:
            values = [e2[mode]["freeze"][key] for mode in MODES]
            require(all(value == values[0] for value in values), "E2 arms differ: " + key)
        for key in keys[:3]:
            sha(e2[MODES[0]]["freeze"][key])
        return True

    shared = checked("E2.common", common)
    for mode in MODES:
        add("E2." + mode, lambda mode=mode: e2_cost(e2[mode], mode))
        training[mode] = checked("E2.training." + mode, lambda mode=mode: training_cost(e2[mode]))

    def budgets():
        require(search_plan["schema"] == "hepta.graph-search-plan.v4"
                and search["plan_digest"] == digest(search_plan), "SEARCH PLAN binding differs")
        contracts = search_plan["contracts"]
        require(isinstance(contracts, list) and contracts, "search contracts missing")
        budget, cells = contracts[0]["budget"], contracts[0]["cells"]
        require(count(budget["model_calls"]) == 2, "two call opportunities required")
        for key in ("max_input_tokens_per_call", "max_output_tokens_per_call", "max_relay_bytes"):
            require(count(budget[key]) > 0, "invalid budget cap")
        for contract in contracts:
            require(contract["schema"] == "hepta.online-message-circuit.contract.v4"
                    and contract["budget"] == budget and contract["cells"] == cells, "search contracts differ")
        require(set(studies) == set(study_plans) == {"A", "B"}, "A/B studies and plans required")
        for panel in ("A", "B"):
            plan = study_plans[panel]
            require(plan["schema"] == "hepta.graph-evaluation-plan.v4"
                    and studies[panel]["plan_digest"] == digest(plan), "evaluation PLAN binding differs")
            require(plan["budget"] == budget and plan["execution_binding_digest"] ==
                    search_plan["plan"]["execution_binding_digest"], "execution budget/binding differs")
            require(set(plan["cell_interventions"]) == set(cells)
                    and plan["selection_on_this_panel"] is False, "intervention/selection plan differs")
        return budget

    budget = checked("E4.budget_binding", budgets)

    def rows_cost(rows):
        require(isinstance(rows, list) and rows, "missing execution rows")
        identities = [sha(row["result_digest"]) for row in rows]
        require(len(set(identities)) == len(identities) and not set(identities) & seen,
                "duplicate execution receipt; do not double count")
        costs = []
        for row in rows:
            require(row["success"] is None or type(row["success"]) is bool, "unknown outcome encoding")
            require(row["cost"]["call_and_token_count_complete"] is True, "incomplete execution cost")
            costs.append({key: count(row["cost"][key]) for key in COSTS})
            if budget is not None:
                calls = costs[-1]["model_calls"]
                require(calls <= budget["model_calls"] and
                        costs[-1]["input_tokens"] <= calls * budget["max_input_tokens_per_call"] and
                        costs[-1]["output_tokens"] <= calls * budget["max_output_tokens_per_call"], "budget exceeded")
        seen.update(identities)
        return sums(costs, COSTS)

    def search_cost():
        receipt(search, "hepta.graph-search-result.v4")
        require(search["scientific_qualification"] is False, "search scope changed")
        require(all(type(row["success"]) is bool for row in search["observations"]), "unknown search labels")
        value = rows_cost(search["observations"])
        for key in INFERENCE:
            require(count(search["search_" + key]) == value[key], "search cost summary differs")
        return value

    add("E4.search", search_cost)
    for panel in ("A", "B"):
        def panel_header():
            study = studies[panel]
            receipt(study, "hepta.online-circuit-study.v4")
            require(study["router_digest"] == search["router_digest"]
                    and study["scientific_qualification"] is False, "router/scope differs")
            require(set(study["arms"]) == ARMS, "four arms required")
            plan = study_plans[panel]
            expected = {"edge-answer", "edge-feedback"} | {"cell-" + name for name in plan["cell_interventions"]}
            require(set(study["interventions"]) == expected, "ablation coverage differs")
            groups = {**study["arms"], **study["interventions"]}
            tasks = [row["task_id"] for row in groups["single"]]
            require(tasks and len(set(tasks)) == len(tasks), "duplicate/missing panel tasks")
            for rows in groups.values():
                require(len(rows) == len(tasks) and {row["task_id"] for row in rows} == set(tasks), "paired panel differs")
            require(len(plan["record_digests"]) == len(tasks), "planned panel size differs")
            return groups

        groups = checked("E4." + panel + ".coverage", panel_header)
        if groups is None:
            ledger["E4." + panel] = {key: None for key in COSTS}
            continue
        for name, rows in groups.items():
            add("E4." + panel + "." + name, lambda rows=rows: rows_cost(rows))
        def panel_totals():
            value = sums([ledger["E4." + panel + "." + name] for name in groups], COSTS)
            for key in COSTS:
                require(value[key] is not None and count(studies[panel]["all_actual_execution_cost"][key]) == value[key],
                        "panel cost summary differs: " + key)
            return True
        checked("E4." + panel + ".totals", panel_totals)

    values = list(ledger.values())
    return {"schema": "hepta.development-cost-report.v4", "status": "INCOMPLETE",
            "input_validation": "CONSISTENT" if not issues else "INCOMPLETE", "issues": issues,
            "same_E2_initial_context_A": shared is True, "bound_E4_budget": budget,
            "components": ledger, "reported_scope_totals": sums(values, INFERENCE),
            "known_measured_subtotals": {key: sum(row[key] for row in values if row.get(key) is not None)
                if any(row.get(key) is not None for row in values) else None for key in INFERENCE},
            "training_by_arm": training,
            "training_totals": sums([value or {} for value in training.values()],
                ("input_tokens_consumed", "supervised_tokens", "padded_training_token_positions")),
            "reference_verifier_calls": None, "all_verifier_calls": None,
            "full_system_cost_known": False, "matched_actual_cost_claim": False,
            "scope": "Paid reported inference/search/ablation counts; E2 verifier subtotal is student-only. Training token positions are separate, nested wall/CPU scopes are not added.",
            "independent_sample_increment": 0, "scientific_qualification": False,
            "proof_of_useful_work_eligible": False, "native_adoption": False,
            "provenance_authenticated": False}

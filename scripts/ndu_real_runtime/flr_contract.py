"""Replay F/L/R research evidence without manufacturing native or RSI authority.

The fixed horizon permits one final D audit after sealing all generation rows.
An evidence verifier is required even for NoUpdate. These ports do not establish
independent custody; callers must separately qualify the actual native owners.
"""

from copy import deepcopy

from ._causal_checks import COST_UNITS, _fields, _number, _pin, _require, _sha, _text
from .causal_improver import _reported_costs
from .flr_plan import ARMS, source_mean, validate_plan


def summarize_campaign(plan, records, *, read_evidence=None, verify_evidence=None):
    """Check originals, lineage, fixed arms, query budgets and sealed audit order."""
    plan, records = deepcopy(plan), deepcopy(records)
    validate_plan(plan)
    _fields(
        records,
        ("schema", "plan_digest", "rounds", "seal", "audits", "publication_costs"),
        "FLR_RUN_FIELDS",
    )
    _require(
        records["schema"] == "hepta.flr.run.v1"
        and records["plan_digest"] == _sha(plan),
        "FLR_PLAN_BINDING",
    )
    _require(
        isinstance(records["rounds"], list)
        and len(records["rounds"]) <= 3 * plan["generations"],
        "FLR_ROUNDS",
    )
    _fields(records["audits"], ARMS, "FLR_AUDIT_ARMS")
    sequences, run_ids, attempt_ids, operation_ids = set(), set(), set(), set()

    def evidence(kind, reference, expected):
        _require(reference is None or _pin(reference), "FLR_EVIDENCE_REFERENCE")
        if (
            reference is None
            or not callable(read_evidence)
            or not callable(verify_evidence)
        ):
            return None
        value = deepcopy(read_evidence(kind, reference))
        if value is None:
            return None
        _require(
            isinstance(value, dict)
            and _sha(value) == reference
            and verify_evidence(kind, value, plan["evaluation_owner"]) is True,
            "FLR_EVIDENCE_AUTHENTICATION",
        )
        _require(
            value.get("kind") == kind
            and value.get("plan_digest") == records["plan_digest"]
            and value.get("actor_id") == plan["evaluation_owner"]
            and all(value.get(key) == item for key, item in expected.items()),
            "FLR_EVIDENCE_BINDING",
        )
        seq = value.get("sequence")
        _require(
            type(seq) is int and 0 < seq < 2**63 and seq not in sequences,
            "FLR_EVIDENCE_SEQUENCE",
        )
        sequences.add(seq)
        return value

    def scores(value, ids):
        if value is None:
            return None
        _fields(value.get("scores"), ids, "FLR_SCORE_DENOMINATOR")
        _require(
            all(_number(x, minimum=0) and x <= 1 for x in value["scores"].values()),
            "FLR_INVALID_SCORE",
        )
        return source_mean(value["scores"], plan["sources"])

    states = {arm: (plan["initial_model"], plan["initial_learner"]) for arm in ARMS}
    chain_complete = {arm: True for arm in ARMS}
    queries, costs, observed = {arm: 0 for arm in ARMS}, {arm: [] for arm in ARMS}, {}
    searches = {arm: 0 for arm in ARMS}
    previous_generation, generation_arms, latest_sequence = 0, set(), 0
    for row in records["rounds"]:
        _fields(
            row,
            (
                "run_id",
                "arm",
                "generation",
                "information",
                "model_before",
                "learner_before",
                "learner_search",
                "attempts",
                "decision",
                "use_ref",
                "costs",
            ),
            "FLR_ROUND_FIELDS",
        )
        arm, generation, run_id = (row[key] for key in ("arm", "generation", "run_id"))
        _require(
            arm in ARMS
            and type(generation) is int
            and 0 <= generation < plan["generations"],
            "FLR_ROUND_IDENTITY",
        )
        if generation != previous_generation:
            _require(
                generation == previous_generation + 1 and generation_arms == set(ARMS),
                "FLR_GENERATION_ORDER",
            )
            previous_generation, generation_arms = generation, set()
        _require(
            arm not in generation_arms and _text(run_id) and run_id not in run_ids,
            "FLR_REUSED_EXECUTION",
        )
        generation_arms.add(arm)
        run_ids.add(run_id)
        _require(row["information"] == plan["information"], "FLR_UNMATCHED_INFORMATION")
        before = (row["model_before"], row["learner_before"])
        _require(before == states[arm], "FLR_BROKEN_INHERITANCE")
        attempts = row["attempts"]
        _require(
            isinstance(attempts, list)
            and len(attempts) <= plan["budget"]["candidate_attempts"]
            and (arm != "F" or not attempts),
            "FLR_ATTEMPT_BUDGET",
        )
        trials = row["learner_search"]
        _require(
            isinstance(trials, list)
            and len(trials) <= plan["budget"]["learner_trials"]
            and (arm == "R" or not trials),
            "FLR_LEARNER_SEARCH_BUDGET",
        )
        resolved, accepted, b_sequences, baselines = True, [], [], set()
        successful_trials = 0
        for trial in trials:
            _fields(
                trial,
                (
                    "trial_id",
                    "operation_id",
                    "training_sources",
                    "training_model",
                    "training_learner",
                    "status",
                    "result_model",
                    "utility",
                ),
                "FLR_LEARNER_TRIAL_FIELDS",
            )
            for key, identities in (
                ("trial_id", attempt_ids),
                ("operation_id", operation_ids),
            ):
                _require(
                    _text(trial[key]) and trial[key] not in identities,
                    "FLR_REUSED_EXECUTION",
                )
                identities.add(trial[key])
            _require(
                trial["training_sources"] == plan["schedule"][generation]["A"]
                and (trial["training_model"], trial["training_learner"]) == before,
                "FLR_TRAINING_BINDING",
            )
            _require(
                trial["status"] in ("SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"),
                "FLR_LEARNER_TRIAL_STATUS",
            )
            if trial["status"] == "SUCCEEDED":
                _require(
                    _pin(trial["result_model"])
                    and _number(trial["utility"], minimum=0)
                    and trial["utility"] <= 1,
                    "FLR_LEARNER_TRIAL_RESULT",
                )
                successful_trials += 1
            else:
                _require(
                    trial["result_model"] is None and trial["utility"] is None,
                    "FLR_LEARNER_TRIAL_RESULT",
                )
            resolved = resolved and trial["status"] != "UNKNOWN"
        searches[arm] += len(trials)
        for attempt in attempts:
            _fields(
                attempt,
                (
                    "attempt_id",
                    "operation_id",
                    "candidate_model",
                    "training_sources",
                    "training_model",
                    "training_learner",
                    "candidate_learner",
                    "status",
                    "b_queries",
                    "evaluation_ref",
                ),
                "FLR_ATTEMPT_FIELDS",
            )
            for key, identities in (
                ("attempt_id", attempt_ids),
                ("operation_id", operation_ids),
            ):
                _require(
                    _text(attempt[key]) and attempt[key] not in identities,
                    "FLR_REUSED_EXECUTION",
                )
                identities.add(attempt[key])
            _require(
                all(
                    _pin(attempt[key])
                    for key in ("candidate_model", "candidate_learner")
                ),
                "FLR_CANDIDATE_PINS",
            )
            _require(
                attempt["training_sources"] == plan["schedule"][generation]["A"]
                and (attempt["training_model"], attempt["training_learner"]) == before,
                "FLR_TRAINING_BINDING",
            )
            _require(
                arm != "L" or attempt["candidate_learner"] == plan["initial_learner"],
                "FLR_FIXED_LEARNER_CHANGED",
            )
            _require(
                attempt["candidate_learner"] == before[1] or successful_trials > 0,
                "FLR_LEARNER_CHANGED_WITHOUT_SEARCH",
            )
            status, count = attempt["status"], attempt["b_queries"]
            _require(
                status in ("SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN")
                and type(count) is int
                and count in (0, 1),
                "FLR_ATTEMPT_STATUS",
            )
            queries[arm] += count
            _require(queries[arm] <= plan["budget"]["b_queries"], "FLR_B_QUERY_BUDGET")
            if status != "SUCCEEDED":
                _require(attempt["evaluation_ref"] is None, "FLR_FAILED_EVALUATION")
                resolved = resolved and status != "UNKNOWN"
                continue
            _require(count > 0, "FLR_UNMETERED_B_QUERY")
            evaluation = evidence(
                "B",
                attempt["evaluation_ref"],
                {
                    "run_id": run_id,
                    "source_ids": plan["schedule"][generation]["B"],
                    "attempt_id": attempt["attempt_id"],
                    "operation_id": attempt["operation_id"],
                    "model": attempt["candidate_model"],
                    "learner": attempt["candidate_learner"],
                    "baseline_model": before[0],
                },
            )
            if evaluation is None:
                resolved = False
                continue
            _require(
                all(
                    _number(evaluation.get(key), minimum=0) and evaluation[key] <= 1
                    for key in ("utility", "baseline_utility")
                ),
                "FLR_B_UTILITY",
            )
            _require(
                evaluation["sequence"] > latest_sequence,
                "FLR_GENERATION_FEEDBACK_ORDER",
            )
            baselines.add(evaluation["baseline_utility"])
            b_sequences.append(evaluation["sequence"])
            gain = evaluation["utility"] - evaluation["baseline_utility"]
            if gain > 0 and gain >= plan["minimum_gain"]:
                accepted.append((evaluation["utility"], attempt))
        _require(len(baselines) <= 1, "FLR_BASELINE_CHANGED_DURING_SELECTION")
        decision = row["decision"]
        _fields(
            decision,
            (
                "kind",
                "selected_attempt",
                "model_after",
                "learner_after",
                "evidence_ref",
            ),
            "FLR_DECISION_FIELDS",
        )
        after = (decision["model_after"], decision["learner_after"])
        _require(all(_pin(x) for x in after), "FLR_SELECTED_PINS")
        kind = decision["kind"]
        _require(
            kind in ("ADOPT", "NO_UPDATE", "UNAVAILABLE", "FROZEN_CONTROL"),
            "FLR_DECISION_KIND",
        )
        if kind == "ADOPT":
            chosen = next(
                (
                    x
                    for x in attempts
                    if x["attempt_id"] == decision["selected_attempt"]
                ),
                None,
            )
            _require(
                chosen is not None
                and chosen["status"] == "SUCCEEDED"
                and after == (chosen["candidate_model"], chosen["candidate_learner"])
                and after != before,
                "FLR_SELECTION_BINDING",
            )
        else:
            _require(
                decision["selected_attempt"] is None and after == before,
                "FLR_RETAINED_STATE_CHANGED",
            )
        _require((arm == "F") == (kind == "FROZEN_CONTROL"), "FLR_FIXED_SYSTEM_CHANGED")
        _require(
            arm != "L" or after[1] == plan["initial_learner"],
            "FLR_FIXED_LEARNER_CHANGED",
        )
        complete_b = arm == "F" or (resolved and bool(b_sequences))
        if complete_b and kind != "UNAVAILABLE":
            best = max(accepted, key=lambda item: item[0])[1] if accepted else None
            expected_kind = (
                "FROZEN_CONTROL" if arm == "F" else "ADOPT" if best else "NO_UPDATE"
            )
            _require(
                kind == expected_kind
                and decision["selected_attempt"]
                == (best["attempt_id"] if best else None),
                "FLR_SELECTION_RULE",
            )
        selection = evidence(
            "selection",
            decision["evidence_ref"],
            {
                "run_id": run_id,
                "attempts_digest": _sha(attempts),
                "decision": kind,
                "learner_search_digest": _sha(trials),
                "selected_attempt": decision["selected_attempt"],
                "model": after[0],
                "learner": after[1],
            },
        )
        if selection is not None:
            _require(
                selection["sequence"] > max([latest_sequence, *b_sequences]),
                "FLR_SELECTION_BEFORE_B",
            )
        complete = (
            chain_complete[arm]
            and complete_b
            and kind != "UNAVAILABLE"
            and selection is not None
        )
        use = (
            evidence(
                "C",
                row["use_ref"],
                {
                    "run_id": run_id,
                    "source_ids": plan["schedule"][generation]["C"],
                    "model": after[0],
                    "learner": after[1],
                    "entrypoint": plan["ordinary_entrypoint"],
                },
            )
            if complete
            else None
        )
        if use is not None:
            _require(
                use["sequence"] > selection["sequence"], "FLR_USE_BEFORE_SELECTION"
            )
            latest_sequence = use["sequence"]
        complete = complete and use is not None
        chain_complete[arm] = complete
        value = scores(use, plan["schedule"][generation]["C"])
        observed[(generation, arm)] = {
            "decision": kind if complete else "UNAVAILABLE",
            "complete": complete,
            "future_utility": value,
        }
        states[arm] = after
        costs[arm].append(_reported_costs(row["costs"], unresolved=not resolved))
    sealed, seal = False, records["seal"]
    if seal is not None:
        _fields(seal, ("rounds_digest", "sequence"), "FLR_SEAL_FIELDS")
        _require(
            len(observed) == 3 * plan["generations"]
            and seal["rounds_digest"] == _sha(records["rounds"])
            and type(seal["sequence"]) is int
            and max(sequences, default=0) < seal["sequence"] < 2**63,
            "FLR_SEARCH_NOT_SEALED",
        )
        sealed = True
    _require(
        sealed or all(ref is None for ref in records["audits"].values()),
        "FLR_D_BEFORE_SEAL",
    )
    complete = len(observed) == 3 * plan["generations"] and all(
        x["complete"] for x in observed.values()
    )
    audits = {}
    for arm in ARMS:
        record = (
            evidence(
                "D",
                records["audits"][arm],
                {
                    "run_id": plan["campaign_id"] + "/" + arm,
                    "source_ids": plan["audit_sources"],
                    "model": states[arm][0],
                    "learner": states[arm][1],
                },
            )
            if sealed and complete
            else None
        )
        if record is not None:
            _require(record["sequence"] > seal["sequence"], "FLR_D_BEFORE_SEAL")
        audits[arm] = scores(record, plan["audit_sources"])
    shared = _reported_costs(records["publication_costs"])
    standalone = {}
    for arm in ARMS:
        items = [*costs[arm], shared]
        known = {
            unit: sum(x["known_lower_bounds"][unit] for x in items)
            for unit in COST_UNITS
        }
        _require(
            all(_number(x, minimum=0) for x in known.values()), "FLR_COST_OVERFLOW"
        )
        _require(
            all(known[unit] <= plan["budget"]["limits"][unit] for unit in COST_UNITS),
            "FLR_TOTAL_BUDGET_EXCEEDED",
        )
        standalone[arm] = {
            "known_lower_bounds": known,
            "totals": {
                unit: known[unit]
                if len(costs[arm]) == plan["generations"]
                and all(x["totals"][unit] is not None for x in items)
                else None
                for unit in COST_UNITS
            },
        }
    generations = []
    for generation in range(plan["generations"]):
        values = {
            arm: observed.get((generation, arm), {}).get("future_utility")
            for arm in ARMS
        }
        generations.append(
            {
                "generation": generation,
                **values,
                **{
                    right + "_minus_" + left: values[right] - values[left]
                    if values[right] is not None and values[left] is not None
                    else None
                    for left, right in (("F", "L"), ("L", "R"))
                },
            }
        )
    return {
        "schema": "hepta.flr.summary.v1",
        "status": "DESCRIPTIVE_PROTOCOL_COMPLETE"
        if complete and sealed and all(value is not None for value in audits.values())
        else "HOLD_INCOMPLETE_EVIDENCE",
        "registered_rounds": 3 * plan["generations"],
        "complete_rounds": sum(x["complete"] for x in observed.values()),
        "unresolved_rounds": 3 * plan["generations"]
        - sum(x["complete"] for x in observed.values()),
        "decisions": {
            arm: [
                observed.get((g, arm), {}).get("decision", "UNAVAILABLE")
                for g in range(plan["generations"])
            ]
            for arm in ARMS
        },
        "future_generations": generations,
        "final_audit": audits,
        "b_queries": queries,
        "learner_trials": searches,
        "costs": {
            "standalone_by_arm": standalone,
            "shared_publication": shared,
            "shared_cost_policy": "full standalone charge per arm; do not sum standalone totals",
        },
        "statistics_unit": "declared_source_group_not_seed_replay_or_template_variant",
        "declared_audit_source_groups": len(
            {plan["sources"][x]["group"] for x in plan["audit_sources"]}
        ),
        "independent_real_sources_verified": 0,
        "source_provenance_verified": False,
        "independent_external_audit_verified": False,
        "cost_provenance_verified": False,
        "same_solver_improver_transfer_required": True,
        "scientific_efficacy_qualified": False,
        "recursive_self_improvement_qualified": False,
        "production_adoption_qualified": False,
        "authority_granted": False,
    }

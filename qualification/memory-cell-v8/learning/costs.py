"""A frozen measured-cost proxy and explicit incomplete full-cost gate.

Whole child lifecycle wall already contains fitting, reading, wake/load, IPC,
publication, replay of the retention cohort, fsync and shutdown. Nested timers
are diagnostics; summing them again would double-charge the same time.
"""

from evidence import integer, require


FIXED = tuple(f"fixed-{count}" for count in range(1, 9))
ADAPTIVE = ("lightweight-prefix-selector", "learned-coaccess")
ROLES = (*FIXED, *ADAPTIVE, "direct-owner")
WEIGHTS = {"wrong_future_decision": 1_000_000_000, "wall_ns": 1,
           "retained_logical_byte": 100, "application_transport_byte": 10, "process_peak_rss_byte": 1}
RESOURCES = tuple(name for name in WEIGHTS if name != "wrong_future_decision")
UNMEASURED = ("storage_byte_time_integral", "simultaneous_process_rss_byte_time_integral",
              "coordinator_total_bookkeeping_and_final_report_write_wall_ns", "post_observation_host_and_worker_tail_peak_rss_bytes")


def complete_matrix(arms):
    require(isinstance(arms, list) and len(arms) == len(ROLES), "incomplete actual arm matrix")
    ids = [arm["id"] for arm in arms]
    require(len(ids) == len(set(ids)) and set(ids) == set(ROLES), "missing/duplicate actual arm")
    return {arm["id"]: arm for arm in arms}


def add_observed(values):
    if any(value is None for value in values):
        return None
    return sum(integer(value, "observed cost") for value in values)


def resources(arm, fits, execution_bytes):
    execution = arm["parent_execution"]
    host_rss = arm["host_peak_rss_bytes"]
    worker_rss = [fit["receipt"]["process_peak_rss_bytes"] for fit in fits]
    processes = [fit["measurement"] for fit in fits]
    transport = [arm["traffic"][field] for field in ("transmitted_bytes", "received_bytes")]
    transport.extend(execution[field] for field in ("stdout_bytes", "stderr_bytes"))
    transport.extend(process[field] for process in processes for field in ("request_bytes", "response_bytes", "stderr_bytes"))
    stocks = [arm["source_ledger_logical_bytes"], arm["artifact_owner_logical_bytes"],
              arm["materialized_trial_logical_bytes"], execution_bytes, arm.get("direct_owner_cache_logical_bytes", 0)]
    return {"wall_ns": integer(execution["lifecycle_wall_ns"], "fresh process lifecycle wall", 1),
            "retained_logical_byte": add_observed(stocks), "application_transport_byte": add_observed(transport),
            "process_peak_rss_byte": add_observed([host_rss, *worker_rss])}, {
        "host_observed_peak_rss_bytes": host_rss, "worker_observed_peak_rss_bytes": worker_rss,
        "peak_rss_policy": "sum of per-process observed HWM; not a measured simultaneous peak or memory-time integral",
        "rss_sampling_boundary": "host before report construction/serialization; worker before final response serialization; exit rusage and later tail are unmeasured",
        "separate_training_process_wall_ns": [process["whole_training_process_wall_ns"] for process in processes],
        "training_fit_calls": sum(fit["receipt"]["fit_calls"] for fit in fits),
        "parameter_payload_bytes_across_fits": sum(fit["parameters_bytes"] for fit in fits),
        "explicit_catalog_payload_bytes_across_fits": sum(fit["catalog_bytes"] for fit in fits),
        "payload_diagnostics_added_to_file_stock_again": False,
        "source_ledger_logical_bytes": arm["source_ledger_logical_bytes"],
        "artifact_owner_logical_bytes": arm["artifact_owner_logical_bytes"],
        "raw_trial_evidence_logical_bytes": arm["materialized_trial_logical_bytes"],
        "parent_execution_evidence_logical_bytes": execution_bytes,
        "direct_owner_cache_logical_bytes": arm.get("direct_owner_cache_logical_bytes"),
        "socket_rpc_attempts": arm["traffic"]["rpc_attempts"],
        "socket_transmitted_bytes": arm["traffic"]["transmitted_bytes"],
        "socket_received_bytes": arm["traffic"]["received_bytes"],
        "exclusive_communication_wall_ns": None,
        "communication_wall_already_in_lifecycle_wall": True,
        "kernel_wire_bytes_or_cross_machine_cost_measured": False,
        "unmeasured_dimensions": {name: None for name in UNMEASURED},
    }


def weighted(resources_value, weights):
    return add_observed([None if resources_value[name] is None else resources_value[name] * weights[name]
                         for name in RESOURCES])


def compare(arms, weights, common_bytes, selector_wall_ns):
    require(weights == WEIGHTS, "cost policy differs from frozen positive weights")
    for name, value in weights.items():
        integer(value, f"positive weight {name}", 1)
    inventory = complete_matrix(arms)
    search = {name: add_observed([inventory[role]["resources"][name] for role in FIXED]) for name in RESOURCES}
    search["wall_ns"] = add_observed([search["wall_ns"], integer(selector_wall_ns, "actual selector wall")])
    common_bytes = integer(common_bytes, "common experiment evidence bytes")
    policies = {}
    for role in ROLES:
        arm = inventory[role]
        policy = dict(arm["resources"])
        for name in RESOURCES:
            policy[name] = add_observed([policy[name], search[name] if role in ADAPTIVE else 0])
        policy["retained_logical_byte"] = add_observed([policy["retained_logical_byte"], common_bytes])
        error_penalty = arm["future"]["decision_errors"] * weights["wrong_future_decision"]
        partial = weighted(policy, weights)
        policies[role] = {"own_resource_score": weighted(arm["resources"], weights),
            "search_resource_score": weighted(search, weights) if role in ADAPTIVE else 0,
            "common_evidence_material_score": common_bytes * weights["retained_logical_byte"],
            "future_decision_error_penalty": error_penalty,
            "measured_proxy_score": None if partial is None else partial + error_penalty,
            "charged_resource_vector": policy, "search_trials_charged": list(FIXED) if role in ADAPTIVE else [],
            "missing_weighted_components": [name for name in RESOURCES if policy[name] is None],
            "retention_no_observed_regression": arm["retention"]["read_error_delta"] <= 0
                and arm["retention"]["decision_error_delta"] <= 0}
    fixed_scores = [policies[role]["measured_proxy_score"] for role in FIXED]
    best_fixed = None if any(score is None for score in fixed_scores) else min(FIXED, key=lambda role: (policies[role]["measured_proxy_score"], role))
    learned = policies["learned-coaccess"]["measured_proxy_score"]
    gains = {}
    for label, reference in (("hindsight_fixed_inventory_oracle", best_fixed),
                             ("same_information_lightweight_selector", ADAPTIVE[0]), ("direct_owner", "direct-owner")):
        comparator = None if reference is None else policies[reference]["measured_proxy_score"]
        gains[label] = {"arm": reference, "comparator_minus_learned_proxy_score":
                       None if comparator is None or learned is None else comparator - learned}
    return {"weights": weights, "unit": "frozen arbitrary weighted proxy units; not money or measured lifetime cost",
        "policies": policies, "learned_comparisons": gains,
        "fixed_oracle_policy": "hindsight best of the frozen eight; pays only its own trial and common evidence, no search; conservative fixed hurdle",
        "same_information_policy": "lightweight and learned both pay all eight completed search trials and the same selector",
        "search_cost_scope": "complete actual trials, including their future/retention diagnostics; conservative experiment account, not deployment-required prefix selection cost",
        "search_quality_penalty_policy": "search trials contribute resource cost; only the deployed arm contributes future decision loss",
        "direct_owner_policy": "predeclared exact owner cache with registered opcode execution; no model fitting or model search",
        "common_evidence_logical_bytes": common_bytes,
        "full_cost_gate": {"decision": "NoChange", "missing_dimensions": {name: None for name in UNMEASURED},
                           "exclusive_communication_attribution_required_separately": False,
                           "reason": "the measured proxy cannot establish complete lifetime cost; independent acceptance and publication remain required"},
        "rust_budget_proposal_bridge_executed": False, "autonomous_release_authority": False}

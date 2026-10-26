"""Every saved physical step, every attempted forecast and every retained cut."""

import numpy as np

from remaining_audit_core_v8 import (WEIGHTS, array_hash, check_portfolio, digest,
    errors, independent_response, load_policy_record, panel_values, read, require)


def close(actual, expected, reason, *, rtol=2e-8, atol=1e-11):
    actual, expected = np.asarray(actual), np.asarray(expected)
    require(actual.shape == expected.shape and np.isfinite(actual).all() and np.isfinite(expected).all()
        and np.allclose(actual, expected, rtol=rtol, atol=atol), reason)
    return float(np.max(np.abs(actual-expected), initial=0.))


def inspect_case(directory, origin, train, panels, method, protocol_sha, source_sha, *, compressed=False):
    from cell_field_state import CellTrainingState, dataset_digest
    record = load_policy_record(directory, compressed)
    require(record["method"] == method and record["scientific_acceptance"] is False
        and record["production_authority"] is False and record["policy_call_cpu_ns"] > 0
        and record["policy_call_wall_ns"] > 0, "registered method, denied authority and paid caller required")
    if record["status"] == "actual_error":
        require(record["error"] and record["completed_steps"] is None
            and record["retained_prefix_available"] is False and record.get("common_J32") is None
            and record.get("parameter_action_penalty") is None, "unavailable error prefix remains unavailable")
        return {"available": False, "completed": False, "status": record["status"],
            "actual_errors": [record["error"]], "known_replayed_steps": 0, "proposal_checks": 0,
            "record": record, "scope": "error slot retained; no claim to replay an unavailable prefix"}
    with np.load(directory/"trajectory.npz", allow_pickle=False) as archive:
        require(set(archive.files) == {"states", "actions", "old_losses"}, "exact trace array census")
        vectors, actions, saved_losses = (archive[k] for k in ("states", "actions", "old_losses"))
    p, n = origin.parameter_count, len(actions)
    require(0 <= n <= 32 and actions.shape == (n, p) and vectors.shape == (n+1, 3*p)
        and saved_losses.shape == (n+1, 4) and np.isfinite(actions).all()
        and np.all(np.abs(actions) <= 4./np.sqrt(p)) and record["completed_steps"] == n
        and record["registered_steps"] == 32 and record["status"] in
            ("completed", "not_executed_rejected", "not_executed_unresolved")
        and (record["status"] != "completed" or n == 32), "complete or explicitly stopped32-step trace")
    anchors = panel_values(origin, panels[4:])
    contract = {"schema": "hepta.remaining-terminal-contract.v8", "method": method,
        "controller_protocol_sha256": protocol_sha, "controller_source_sha256": source_sha,
        "warmup_state_sha256": origin.digest(), "optimizer_origin_bindings": origin.bindings,
        "optimizer_origin_protocol": origin.protocol, "training_sha256": dataset_digest(*train),
        "current_panel_sha256": [dataset_digest(*v) for v in panels[:4]],
        "old_panel_sha256": [dataset_digest(*v) for v in panels[4:]],
        "original_old_anchors": anchors.tolist(), "registered_steps": 32, "commit_stride": 1,
        "dt": .02, "effort_price": .03, "action_bound": 4., "old_mean_weight": .25,
        "current_mean_weight": 1., "current_dispersion": 0., "production_authority": False}
    require(record["contract"] == contract and record["contract_sha256"] == digest(contract)
        and record["initial_state_sha256"] == origin.digest() and len(record["receipts"]) == n
        and len(record["state_sha256"]) == n+1, "exact new control identity and original complete warmup")
    current, states, maximum = origin.clone(), [origin.clone()], None
    for k in range(n+1):
        if k:
            receipt = current.advance(*train, intervention=.02*actions[k-1])
            require(receipt == record["receipts"][k-1], "exact actual transition receipt")
            states.append(current.clone())
        values = panel_values(current, panels[4:])
        require(np.array_equal(values, saved_losses[k]) and np.array_equal(current.vector(), vectors[k])
            and current.digest() == record["state_sha256"][k], "all full states and old losses replay exactly")
        if k:
            require(np.all(values <= anchors), "every committed old inequality has zero slack")
            excess = float(np.max(values-anchors))
            maximum = excess if maximum is None else max(maximum, excess)
    require(current.digest() == record["terminal_state_sha256"], "actual retained terminal identity")
    cuts = sorted({k for k in (0, 16, 17, 32, n) if k <= n})
    require(record["checkpoint_cuts"] == cuts and record["terminal_checkpoint"] == "checkpoints/"+str(n)
        and {p.name for p in (directory/"checkpoints").iterdir()} == {str(k) for k in cuts}, "all required cut and terminal preimages")
    for k in cuts:
        restored = CellTrainingState.load(directory/"checkpoints"/str(k), origin.bindings,
            origin.protocol, origin.contexts, states[k].digest())
        require(np.array_equal(restored.vector(), states[k].vector()), "complete checkpoint cut restores exact bits")
    with np.load(directory/"plans.npz", allow_pickle=False) as archive:
        require(set(archive.files) == {"proposed_actions", "first_action_maps", "reference_terminal_states",
            "reference_terminal_panels", "initial_field_observations"}, "exact attempted proposal arrays")
        arrays = {k: archive[k] for k in archive.files}
    planned_rows = [r for r in record["steps"] if "proposal" in r]
    count = len(planned_rows)
    require(record["saved_plan_count"] == count and n <= count <= min(n+1, 32)
        and [r["at_step"] for r in planned_rows] == list(range(count)), "all attempted causal proposals retained")
    for key, shape in {"proposed_actions": (count, p), "first_action_maps": (count, 8, p),
        "reference_terminal_states": (count, 3*p), "reference_terminal_panels": (count, 8),
        "initial_field_observations": (count if method == "terminal_field8_remaining" else 0, 8, 3*p)}.items():
        require(arrays[key].shape == shape and np.isfinite(arrays[key]).all(), "bounded proposal payload: "+key)
    workload, nominal_updates, jvps, heads, map_error, field_error = [], 0, 0, 0, 0., 0.
    for k, row in enumerate(planned_rows):
        proposal = row["proposal"]
        h = 1 if method == "myopic_h1" else 32-k
        require(proposal["method"] == method and proposal["status"] == "qualified"
            and proposal["remaining_physical_steps"] == 32-k and proposal["proposal_horizon"] == h
            and proposal["initial_state_sha256"] == states[k].digest()
            and proposal["panel_sha256"] == [dataset_digest(*v) for v in panels]
            and proposal["reference_optimizer_updates"] == h
            and proposal["planning_panel_head_evaluations"] == (8*h if method == "loss2_remaining" else 8)
            and proposal["analytic_adam_derivatives"] == (h if method == "terminal_field8_remaining" else h-1)
            and proposal["training_head_gradient_evaluations_from_fixed_calls"] == (2*h if method == "terminal_field8_remaining" else 2*h-1),
            "declared causal horizon, original panels and actual construction workload")
        derived = independent_response(states[k], train, panels, method, 32-k)
        require(np.array_equal(arrays["reference_terminal_states"][k], derived["terminal"])
            and np.array_equal(arrays["reference_terminal_panels"][k], derived["panels"]), "actual zero-tail nominal endpoint")
        matrix = arrays["first_action_maps"][k]
        map_error = max(map_error, close(matrix, derived["map"], "independent first-action response"))
        if method == "terminal_field8_remaining":
            field_error = max(field_error, close(arrays["initial_field_observations"][k],
                derived["field"], "independent arbitrary-initial-state terminal observable", atol=1e-9))
        linear, action = WEIGHTS@matrix, arrays["proposed_actions"][k]
        close(action, np.clip(-linear/(.02*.03), -4./np.sqrt(p), 4./np.sqrt(p)), "absolute-action box optimum", rtol=1e-12, atol=1e-13)
        require(np.all(np.abs(action) <= 4./np.sqrt(p)), "intended action within exact original box")
        close(proposal["baseline_terminal_panels"], derived["panels"], "declared nominal losses", rtol=0., atol=0.)
        close(proposal["predicted_terminal_panels"], derived["panels"]+matrix@action, "same intended-action forecast", rtol=1e-12, atol=1e-13)
        close(proposal["predicted_priced_change"], linear@action+.5*.02*.03*np.square(action).sum(), "tangent loss plus physical effort")
        nominal_updates += derived["nominal_updates"]
        jvps += derived["jvp_steps"]
        heads += derived["panel_head_evaluations"]
        if k < n:
            require("repair" in row and not errors(row["repair"]), "every committed step retains its complete error-free paid safety certificate")
        if "repair" in row:
            workload.append(check_portfolio(row["repair"], states[k], action, anchors, panels[4:],
                actions[k] if k < n else None, states[k+1] if k < n else None))
        if k < n:
            require(row["status"] == "committed_certified" and row["committed_steps"] == 1
                and row["resolved_action_sha256"] == array_hash(actions[k]), "only a complete certified step was adopted")
            close(row["predicted_zero_tail_panels_on_resolved_action"], derived["panels"]+matrix@actions[k],
                "forecast applies to the actual resolved action, not another action")
        else:
            require(row["committed_steps"] == 0, "failed attempt cannot advance a partial checkpoint")
    penalty = float(.5*.02*.03*np.square(actions).sum())
    require(record["parameter_action_penalty"] == penalty, "all actual physical effort charged")
    terminal = panel_values(current, panels)
    actual_errors = errors(record)
    if record["terminal_planning_panels"] is None:
        require(actual_errors and record["common_J32"] is None, "unavailable terminal measurement retains its actual error")
    else:
        close(record["terminal_planning_panels"], terminal, "retained terminal planning losses", rtol=0., atol=0.)
    if n == 32 and record["terminal_planning_panels"] is not None:
        close(record["common_J32"], WEIGHTS@terminal+penalty, "actual common32 objective", atol=1e-12)
    else:
        require(record["common_J32"] is None, "stopped-prefix risk is not a32-step outcome")
    inner_cpu = sum(r["proposal"]["cpu_ns"]+r.get("repair", {}).get("cpu_ns", 0) for r in planned_rows)
    require(record["policy_call_cpu_ns"] >= record["cpu_ns"] >= inner_cpu >= 0 and record["cpu_ns"] > 0
        and record["policy_call_wall_ns"] >= record["wall_ns"] > 0, "whole caller, core and all paid attempts")
    require(record["status"] != "completed" or not actual_errors, "completed run cannot contain paid actual errors")
    return {"available": True, "completed": record["status"] == "completed", "status": record["status"],
        "actual_errors": actual_errors, "known_replayed_steps": n, "checkpoint_cuts": cuts,
        "proposal_checks": count, "audit_nominal_updates": nominal_updates, "audit_jvp_steps": jvps,
        "audit_nominal_panel_evaluations": heads, "max_map_absolute_error": map_error,
        "max_initial_field_absolute_error": field_error, "maximum_old_panel_excess": maximum,
        "portfolio_workload": workload, "terminal_state_sha256": current.digest(), "record": record,
        "actions": actions, "states": vectors}

"""Independent stdlib replay of V9 optimizer receipts and fixed observations."""
import math

from collections import Counter
from binding_review import _check, _cost, _digest, _id, audit_scores
from grounding_review import ARMS, audit_auxiliary, audit_graph_trace
from retention_v7_review import STREAMS, audit_plan, replay_losses, same


def state_checks(row, reset):
    for prefix, width in (("hop", 3), ("graph", 2)):
        gradients, maxima = row[prefix + "_state_gradient_l2"], row[prefix + "_state_max_abs"]
        fractions = row[prefix + "_state_saturation_fraction"]
        _check(len(gradients) == len(maxima) == len(fractions) == width, "complete old/graph state observations required")
        for index, value in enumerate(gradients):
            _check(value is None and prefix == "graph" and reset and index == 0
                   or type(value) in (int, float) and math.isfinite(value) and value >= 0,
                   "unregistered absent or nonfinite state gradient")
        _check(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1.000001 for v in maxima)
               and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in fractions),
               "old/graph state bounds violated")
    grouped = row["graph_grouped_counts"]
    _check(grouped["input_rows"] == 16 and type(grouped["unique_fact_groups"]) is int
           and 1 <= grouped["unique_fact_groups"] <= 16
           and grouped["reused_rows"] == 16 - grouped["unique_fact_groups"], "within-call public fact grouping count mismatch")


def audit_observation(observation, target, rows, reset):
    indices = list(range(16))
    _check(observation["indices"] == indices and observation["case_ids"] == [_id(row) for row in rows[:16]]
           and observation["depth"] == 3 and observation["graph_depth"] == 2 and observation["graph_reset"] is reset
           and observation["physical_forward_calls"] == 1 and observation["candidate_observations"] == 16
           and observation["labels_or_annotations_entered_forward"] is False, "fixed complete first16 auxiliary observation changed")
    result = audit_auxiliary(observation, target, indices, full=True)
    replay_losses(observation["logits"], rows[:16])
    _check(len(observation["probabilities"]) == 16, "complete observation class probabilities required")
    for z, p in zip(observation["logits"], observation["probabilities"]):
        probability = math.exp(-max(0., z[0] - z[1])) / (1. + math.exp(-abs(z[0] - z[1])))
        same(p, probability, "observation saved class probability differs from raw binary logits", atol=2e-6, rtol=2e-5)
    _check(len(observation["graph_states"]) == len(observation["graph_fact_attentions"])
           == len(observation["graph_readouts"]) == 2, "complete two-hop graph observation required")
    for states in observation["graph_states"]:
        _check(len(states) == 16 and all(len(state) == 32 and all(type(v) in (int, float) and math.isfinite(v)
               and abs(v) <= 1.000001 for v in state) for state in states), "finite bounded full graph frontiers required")
    return dict(**result, **audit_graph_trace(observation, target, indices), cost_once=_cost(observation),
                physical_forward_calls=1, candidate_observations=16)


def audit_training(receipt, plan, targets, parts, initial, arm, *, updates=500):
    natural, old, augmentation = parts["natural_train"], parts["reader_train"], parts["augmentation"]
    audit_plan(plan, natural, old, augmentation, updates=updates)
    reset, grounded = arm.endswith("_reset"), arm.startswith("grounded_")
    target_shas = {k: _digest(v) for k, v in targets.items()}
    _check(arm in ARMS and receipt["schema"] == "hepta.grounding.continuation.v9" and receipt["arm"] == arm
           and receipt["status"] == "completed" and receipt["completed_steps"] == receipt["requested_logical_updates"] == updates
           and receipt["seed"] == plan["seed"] == initial["seed"] and receipt["plan_sha256"] == plan["plan_sha256"]
           and receipt["initial_model_sha256"] == initial["training_parameter_sha256"], "completed model/plan/initial identity mismatch")
    _check(receipt["optimizer"] == "Adam_foreach_false" and receipt["learning_rate"] == .001
           and receipt["depth"] == 3 and receipt["graph_depth"] == 2 and receipt["graph_reset"] is reset
           and receipt["batch_size"] == 16 and receipt["stream_order"] == list(STREAMS)
           and receipt["stopping_rule"] == "fixed_budget_diagnostics_do_not_select"
           and receipt["teacher_calls"] == receipt["anchor_weight"] == 0 and receipt["auxiliary_temperature"] == .1
           and receipt["latent_computes_auxiliary_diagnostics"] is True and receipt["annotations_enter_forward"] is False
           and receipt["auxiliary_targets_sha256"] == target_shas,
           "registered common optimizer/graph/auxiliary policy changed")
    for prefix in ("natural", "binding", "augmentation"):
        _check(receipt[prefix + "_sequence_sha256"] == _digest(plan[prefix + "_batches"]), "common sampling sequence SHA changed")
    _check(len(receipt["updates"]) == updates * 3, "missing or extra optimizer updates")
    exposures, nested = {s: Counter() for s in STREAMS}, dict(cpu_ns=0, wall_ns=0)
    errors, controlled_mentions = dict(CE=0., pair=0., total=0.), 0
    for index, row in enumerate(receipt["updates"]):
        cycle, stream = index // 3, STREAMS[index % 3]
        role = {"natural": "natural", "transfer": "augmentation", "retention": "binding"}[stream]
        indices = plan[role + "_batches"][cycle]
        rows = [dict(natural=natural, binding=old, augmentation=augmentation)[role][i] for i in indices]
        ids = [_id(r) for r in rows]
        _check(row["step"] == index + 1 and row["logical_step"] == cycle + 1 and row["stream"] == stream
               and row["data_role"] == role and row["indices"] == indices and row["case_ids"] == ids
               and row["sample_sha256"] == _digest(ids) and row["exposures"] == 16, "actual sample/order differs from immutable three-stream plan")
        losses = replay_losses(row["logits"], rows, paired=stream != "natural")
        auxiliary = audit_auxiliary(row["auxiliary"], targets[role] if role != "natural" else None, indices,
                                    target_sha256=target_shas.get(role))
        controlled_mentions += auxiliary["span_mentions"]
        pair_weight = 0. if stream == "natural" else .5
        span_weight, identity_weight = (1., .1) if grounded and stream != "natural" else (0., 0.)
        _check(row["pair_weight"] == pair_weight and row["span_weight"] == span_weight
               and row["identity_weight"] == identity_weight, "2x2 grounding supervision factor or class pair weights changed")
        for field, short in (("binary_cross_entropy", "CE"), ("pair_loss", "pair")):
            same(row[field], losses[field], "class raw-logit loss mismatch: " + field)
            errors[short] = max(errors[short], abs(row[field] - losses[field]))
        total = losses["binary_cross_entropy"] + pair_weight * losses["pair_loss"] + span_weight * auxiliary["span_loss"] + identity_weight * auxiliary["contrastive_loss"]
        same(row["total_loss"], total, "combined classification/span/entity objective mismatch")
        errors["total"] = max(errors["total"], abs(row["total_loss"] - total))
        _check(row["depth"] == 3 and row["graph_depth"] == 2 and row["graph_reset"] is reset
               and row["inference_feature_arguments"] == 6 and row["finite_gradients"] is True
               and row["finite_parameters_after_update"] is True
               and type(row["parameter_gradient_l2"]) in (int, float) and math.isfinite(row["parameter_gradient_l2"])
               and row["parameter_gradient_l2"] >= 0, "public input/depth/finite-gradient boundary changed")
        state_checks(row, reset)
        exposures[stream].update(ids)
        for axis, value in _cost(row).items():
            nested[axis] += value
    grid = list(range(0, updates + 1, 100))
    if grid[-1] != updates:
        grid.append(updates)
    _check([d["logical_step"] for d in receipt["diagnostics"]] == grid, "fixed diagnostic grid changed")
    full_reports = []
    for diagnostic in receipt["diagnostics"]:
        _check(diagnostic["optimizer_steps"] == diagnostic["logical_step"] * 3
               and diagnostic["auxiliary_subset_fixed_before_training"] is True
               and diagnostic["diagnostic_used_for_selection"] is False, "fixed nonselective diagnostic position changed")
        for role, rows in (("binding", old), ("augmentation", augmentation)):
            audit_scores(rows, diagnostic[role]["probabilities"], diagnostic[role])
            full = diagnostic["auxiliary_" + role]
            observed = audit_observation(full, targets[role], rows, reset)
            _check(full["probabilities"] == diagnostic[role]["probabilities"][:16], "auxiliary and ordinary diagnostic class predictions differ")
            full_reports.append(dict(logical_step=diagnostic["logical_step"], role=role, **observed))
            for item in (_cost(diagnostic[role]), observed["cost_once"]):
                for axis in nested:
                    nested[axis] += item[axis]
    for stream in STREAMS:
        _check(receipt["completed_" + stream + "_updates"] == updates and receipt["actual_" + stream + "_exposures"] == updates * 16
               and receipt["case_exposures"][stream] == dict(exposures[stream]), "actual per-stream exposure count mismatch")
    sources = set(initial["training_source_groups"]) | {r["source_hash"] for r in natural + old + augmentation}
    _check(receipt["actual_total_exposures"] == updates * 48 and receipt["parameter_count"] == initial["parameter_count"] == 44884
           and receipt["parameter_bytes"] == 44884 * 4 and receipt["frozen"] is True and receipt["original_model_unchanged"] is True
           and receipt["training_source_groups"] == sorted(sources) and receipt["raw_step_logits_recorded"] is True
           and receipt["actual_auxiliary_diagnostic_forwards"] == len(full_reports)
           and receipt["actual_auxiliary_diagnostic_candidates"] == len(full_reports) * 16
           and receipt["full_auxiliary_trace_scope"] == "fixed_first16_old_and_augmentation_every_diagnostic"
           and receipt["final_evaluation_authorized"] is False, "frozen source/parameter/full diagnostic coverage mismatch")
    outer = _cost(receipt)
    _check(all(outer[k] >= nested[k] for k in nested) and receipt["formula_flops"] is None and receipt["nested_costs_additive"] is False,
           "outer fit cost omits or double-counts nested work")
    return dict(passed=True, arm=arm, optimizer_updates=updates * 3, candidate_exposures=updates * 48,
        raw_class_logits_updates_replayed=updates * 3, auxiliary_controlled_update_reductions_replayed=updates * 2,
        natural_no_auxiliary_checks=updates, selected_span_mentions_replayed=controlled_mentions,
        fully_recomputed_auxiliary_observations=len(full_reports), full_observations=full_reports,
        full_observation_cases_are_fixed_repeated_not_random_samples=True, replay_max_absolute_errors=errors,
        shared_fit_cost_once=outer, nested_decomposition_not_added=nested,
        every_update_contrastive_dot_products_recomputed=False, independent_neural_execution=False)

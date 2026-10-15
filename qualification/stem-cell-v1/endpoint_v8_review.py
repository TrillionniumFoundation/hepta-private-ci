"""Independent V8 numerical and receipt review; stdlib, without neural reruns.

Uses the frozen independent grammar/loss definitions, not a trainer or runtime
scorer. Recorded gradient norms and clocks receive consistency checks only.
"""
from collections import Counter
from hashlib import sha256
import math
from pathlib import Path
import struct

from binding_review import _check, _cost, _digest, _groups, _id, audit_panel, audit_scores
from retention_v7_review import STREAMS, audit_plan, replay_losses, same

ARMS = ("bridge", "endpoint", "broken", "local")


def audit_binding_panel(rows, panel, model, *, depth=3, deleted=False, reset=False):
    _check(panel["depth"] == depth and panel["deleted"] is deleted and panel["reset"] is reset,
           "registered depth/evidence/state intervention changed")
    _check(len(panel["batches"]) == (len(rows) + 15) // 16,
           "complete fixed-size physical panel batches required")
    ids = [_id(row) for row in rows]
    for index, batch in enumerate(panel["batches"]):
        _check(batch["case_ids"] == ids[index * 16:(index + 1) * 16], "panel physical batch geometry changed")
    return audit_panel(rows, panel, model)


def audit_start_predictions(panels):
    _check(set(panels) == set(ARMS), "all four actual initial panels required")
    reference = panels["bridge"]["probabilities"]
    ids = panels["bridge"]["case_ids"]
    _check(all(p["probabilities"] == reference and p["case_ids"] == ids for p in panels.values()),
           "same-seed initial probabilities must be exactly equal")
    _check(len(reference) == 128, "full old-training initial probability panel required")
    return dict(passed=True, panels=4, candidates_per_panel=128, probabilities_exactly_equal=True,
        shared_observation=False, physical_candidate_observations=512,
        predictions_independently_neurally_reexecuted=False)


def audit_support_transform(transform, rows):
    _groups(rows)  # Independent grammar rederives truth and both support sentences.
    expected_rows = []
    for row in rows:
        positions = [i for i, sentence in enumerate(row["sentence_ids"]) if sentence in row["evidence_sentence_indices"]]
        _check(len(positions) == 2, "exactly two independently verified supports required")
        public = "\n".join(("[QUESTION]", row["question"], "[CANDIDATE]", row["candidate"], "[PASSAGE]", *row["facts"]))
        expected_rows.append(dict(case_id=_id(row), public_source_sha256=sha256(public.encode()).hexdigest(),
            support_sentence_ids=row["evidence_sentence_indices"], deleted_fact_positions=positions))
    expected = dict(schema="hepta.endpoint.support-delete.v8", cases=expected_rows,
        case_ids=[_id(row) for row in rows], transform_sha256=_digest(expected_rows),
        kind="zero_verified_support_fact_rows_and_masks_keep_positions", exactly_two_support_facts=True,
        labels_unchanged=True, annotations_enter_forward=False, missing_evidence_can_make_task_unanswerable=True,
        diagnostic_only=True)
    _check(transform == expected, "support-only deletion grammar/source transform changed")
    return dict(passed=True, transform_sha256=transform["transform_sha256"], cases=len(rows), supports_per_case=2)


def audit_deleted_panel(rows, panel, model, transform, tokens):
    _check(panel["depth"] == 3 and panel["reset"] is False and panel["deleted_support_only"] is True
           and panel["all_evidence_deleted"] is False and panel["used_for_gate_or_selection"] is False
           and panel["support_transform_sha256"] == transform["transform_sha256"], "support-only diagnostic boundary changed")
    report = audit_panel(rows, panel, model)
    observations = panel["transform_observations"]
    _check(len(observations) == len(panel["batches"]) == (len(rows) + 15) // 16, "support deletion physical transforms missing/duplicated")
    for index, observation in enumerate(observations):
        selected = rows[index * 16:(index + 1) * 16]
        _check(observation["case_ids"] == [_id(row) for row in selected] == panel["batches"][index]["case_ids"]
               and observation["labels_and_order_unchanged"] is True, "support transform row identity changed")
        layouts = [[(min(62, len(tokens[text]) - start), sentence)
                    for sentence, text in enumerate(row["facts"]) for start in range(0, len(tokens[text]), 62)] for row in selected]
        facts, width = max(map(len, layouts)), max(n for layout in layouts for n, _ in layout)
        positions = [[i for i, (_, sentence) in enumerate(layout) if sentence in transform["cases"][index * 16 + row]["deleted_fact_positions"]]
                     for row, layout in enumerate(layouts)]
        _check(observation["deleted_chunk_positions"] == positions, "support sentence-to-token-chunk mapping changed")
        before, after = bytearray(), bytearray()
        for layout, removed in zip(layouts, positions):
            for fact in range(facts):
                length = layout[fact][0] if fact < len(layout) else 0
                before.extend(bytes([1]) * length + bytes(width - length))
                after.extend(bytes(width) if fact in removed else bytes([1]) * length + bytes(width - length))
        original, changed = observation["original_feature_sha256"], observation["transformed_feature_sha256"]
        _check(len(original) == len(changed) == len(observation["feature_shapes"]) == 6
               and all(isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v) for v in original + changed)
               and original[3] == sha256(before).hexdigest() and changed[3] == sha256(after).hexdigest()
               and all(original[i] == changed[i] for i in (1, 2, 4, 5)) and original[0] != changed[0],
               "deleted masks not independently reproducible or other public roles changed")
        _check(observation["feature_shapes"][0] == [len(selected), facts, width, 384]
               and observation["feature_shapes"][3] == [len(selected), facts, width], "deleted public feature geometry changed")
    return dict(**report, support_masks_independently_reconstructed=True,
        unchanged_other_public_roles_sha_bound=True, transformed_fact_values_independently_decoded=False,
        scope="old_training_support_sensitivity_not_fresh_or_causal_identification")


def audit_fit(receipt, plan, teacher, natural, old, augmentation, initial, arm, *, updates=500):
    """Replay each natural→augmentation→old logit objective and sample identity."""
    audit_plan(plan, natural, old, augmentation, updates=updates)
    count = 42562 if arm == "bridge" else 46722
    _check(arm in ARMS and receipt["model_arm"] == arm and receipt["recipe"] == "diverse"
           and receipt["arm"] == "diverse" and receipt["schema"] == "hepta.retention.continuation.v7"
           and receipt["status"] == "completed" and receipt["completed_steps"] == updates
           and receipt["requested_logical_updates"] == updates and receipt["seed"] == initial["seed"] == plan["seed"]
           and receipt["plan_sha256"] == plan["plan_sha256"], "complete V8 arm/diverse recipe/plan identity changed")
    _check(initial["parameter_count"] == count and receipt["initial_model_sha256"] == initial["training_parameter_sha256"]
           and receipt["optimizer"] == "Adam_foreach_false" and receipt["learning_rate"] == .001
           and receipt["pair_weight"] == .5 and receipt["anchor_weight"] == 0.
           and receipt["depth"] == 3 and receipt["batch_size"] == 16 and receipt["stream_order"] == list(STREAMS)
           and receipt["stopping_rule"] == "fixed_budget_diagnostics_do_not_select", "registered common optimizer/loss/depth/start changed")
    raw = b"".join(struct.pack("<2f", *row) for row in teacher)
    _check(receipt["teacher_logits_sha256"] == sha256(raw).hexdigest()
           and receipt["teacher_logits_shape"] == [len(old), 2] and receipt["teacher_logits_dtype"] == "torch.float32"
           and receipt["teacher_calls_inside_fit"] == 0 and receipt["teacher_logits_unchanged"] is True
           and receipt["anchor_applies_only_to"] == "retention" and receipt["raw_step_logits_recorded"] is True,
           "unused historical teacher compatibility argument changed or executed")
    prefixes = dict(natural=natural, augmentation=augmentation, binding=old)
    for prefix in prefixes:
        _check(receipt[prefix + "_sequence_sha256"] == _digest(plan[prefix + "_batches"]), "common stream sequence changed")
    _check(receipt["transfer_sequence_sha256"] == _digest(plan["augmentation_batches"])
           and receipt["transfer_data_role"] == "augmentation" and len(receipt["updates"]) == updates * 3,
           "all arms must use the complete same diverse stream recipe")
    exposures = {stream: Counter() for stream in STREAMS}
    costs, errors = dict(cpu_ns=0, wall_ns=0), dict(CE=0., pair=0., total=0.)
    for index, row in enumerate(receipt["updates"]):
        cycle, stream = index // 3, STREAMS[index % 3]
        prefix = {"natural": "natural", "transfer": "augmentation", "retention": "binding"}[stream]
        indices = plan[prefix + "_batches"][cycle]
        selected = [prefixes[prefix][i] for i in indices]
        ids = [_id(r) for r in selected]
        _check(row["step"] == index + 1 and row["logical_step"] == cycle + 1 and row["stream"] == stream
               and row["data_role"] == prefix and row["indices"] == indices and row["case_ids"] == ids
               and row["sample_sha256"] == _digest(ids) and row["exposures"] == 16, "actual optimizer sample/order differs from common plan")
        expected = replay_losses(row["logits"], selected, paired=stream != "natural")
        pair_weight = 0. if stream == "natural" else .5
        for field, short in (("binary_cross_entropy", "CE"), ("pair_loss", "pair")):
            same(row[field], expected[field], "raw-logit objective replay mismatch: " + field)
            errors[short] = max(errors[short], abs(row[field] - expected[field]))
        total = expected["binary_cross_entropy"] + pair_weight * expected["pair_loss"]
        same(row["total_loss"], total, "raw-logit total objective mismatch")
        errors["total"] = max(errors["total"], abs(row["total_loss"] - total))
        _check(row["pair_weight"] == pair_weight and row["anchor_weight"] == row["anchor_mse"] == 0.
               and row["depth"] == 3 and row["inference_feature_arguments"] == 6
               and row["finite_gradients"] is True and row["finite_parameters_after_update"] is True,
               "anchor introduced or public/gradient boundary changed")
        for key in ("hop_state_gradient_l2", "hop_state_saturation_fraction", "hop_state_max_abs"):
            _check(len(row[key]) == 3 and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in row[key]),
                   "complete finite recurrent gradient/state observations required")
        _check(all(v <= 1. for v in row["hop_state_saturation_fraction"])
               and all(v <= 1.000001 for v in row["hop_state_max_abs"])
               and type(row["parameter_gradient_l2"]) in (int, float)
               and math.isfinite(row["parameter_gradient_l2"]) and row["parameter_gradient_l2"] >= 0,
               "recorded recurrent state bounds/parameter gradient invalid")
        for axis, value in _cost(row).items():
            costs[axis] += value
        exposures[stream].update(ids)
    grid = list(range(0, updates + 1, 100))
    if grid[-1] != updates:
        grid.append(updates)
    _check([d["logical_step"] for d in receipt["diagnostics"]] == grid, "fixed final diagnostic grid changed")
    for diagnostic in receipt["diagnostics"]:
        _check(diagnostic["optimizer_steps"] == diagnostic["logical_step"] * 3, "diagnostic update position changed")
        for role, rows in (("binding", old), ("augmentation", augmentation)):
            observed = diagnostic[role]
            audit_scores(rows, observed["probabilities"], observed)
            for axis, value in _cost(observed).items():
                costs[axis] += value
    for stream in STREAMS:
        _check(receipt["completed_" + stream + "_updates"] == updates
               and receipt["actual_" + stream + "_exposures"] == updates * 16
               and receipt["case_exposures"][stream] == dict(exposures[stream]), "stream exposure counts differ from actual update rows")
    sources = set(initial["training_source_groups"]) | {r["source_hash"] for r in natural + old + augmentation}
    _check(receipt["training_source_groups"] == sorted(sources) and receipt["actual_total_exposures"] == updates * 48
           and receipt["parameter_count"] == count and receipt["parameter_bytes"] == count * 4
           and receipt["frozen"] is True and receipt["original_model_unchanged"] is True
           and receipt["planned_stream_update_budgets_equal"] is True and receipt["actual_stream_update_counts_equal"] is True
           and receipt["strict_equal_compute"] is False and receipt["final_evaluation_authorized"] is False,
           "final freeze/architecture/actual training source scope changed")
    outer = _cost(receipt)
    _check(all(outer[k] >= costs[k] for k in costs) and receipt["formula_flops"] is None
           and receipt["nested_costs_additive"] is False, "fit timing omitted or double-counted nested work")
    return dict(passed=True, model_arm=arm, recipe="diverse", optimizer_updates=updates * 3,
        total_exposures=updates * 48, shared_fit_cost_once=outer, nested_costs_not_added=costs,
        replay_max_absolute_errors=errors, parameter_count=count, anchor_used=False, teacher_calls=0,
        teacher_is_unused_historical_API_argument=True, independent_neural_execution=False,
        numerical_replay_tolerance=dict(absolute=2e-6, relative=2e-5))


def review_completed(run, previous, code, design, parts, initial, transform, load, bind):
    from binding_review import audit_checkpoint
    from endpoint_v8_checkpoint_review import (audit_identity, audit_learning_change, checkpoint_tensors,
        parameter_shapes, tensor_summary)
    from retention_v7_checkpoint_review import file_sha, natural_panel
    from retention_v7_review import audit_teacher, joint_gate
    completion, started, frozen = (load(run / name) for name in ("training-completion.json", "training-start.json", "all-models-frozen.json"))
    _check(completion["runtime_source_sha256"] == frozen["runtime_source_sha256"] == design["runtime_source_sha256"]
           and completion["actual_optimizer_updates"] == 18000 and completion["actual_training_exposures"] == 288000
           and completion["new_encoder_forward_batches"] == completion["new_teacher_forward_calls"] == 0
           and all(completion[k] is False for k in ("feedback_authorized", "fresh_authorized", "automatic_downstream_opening"))
           and frozen["feedback_authorized"] is frozen["fresh_authorized"] is False
           and started["retries_authorized"] is False and started["started_ns"] < frozen["frozen_ns"] <= completion["completed_ns"],
           "complete fixed-budget freeze/cost/downstream scope changed")
    expected_models = {f"seed-{seed}/{arm}/final-model.json" for seed in (41, 47, 53) for arm in ARMS}
    _check(set(frozen["manifests"]) == expected_models
           and not any((run / name).exists() for name in ("feedback-start.json", "feedback-completion.json", "evaluation-start.json", "completion.json")),
           "exact twelve frozen models and unconditional downstream closure required")
    cache = load(previous / "features/metadata.json")
    reports, gates, costs = [], {}, dict(cpu_ns=0, wall_ns=0)
    for seed in (41, 47, 53):
        plan = load(run / f"seed-{seed}/training-plan.json")
        historical_folder = previous / f"seed-{seed}"
        warmup_folder = Path(design["historical"]["warmups"][str(seed)]["folder"])
        core = load(warmup_folder / "warmup-model.json")
        teacher_record = load(historical_folder / "teacher.json")
        bind(historical_folder / "teacher-logits.bin")
        teacher, _ = audit_teacher(historical_folder, teacher_record, parts["reader_train"], core, design["reused_cache_files_sha256"])
        start = load(historical_folder / "start-natural-train.json")["metrics"]
        baseline = load(warmup_folder / "warmup-binding-train.json")["metrics"]
        gates[str(seed)], arm_reports, times = {}, [], []
        for arm in design["order"][str(seed)]:
            folder = run / f"seed-{seed}" / arm
            init_record, init_tensors = initial[seed][arm]
            receipt, model = load(folder / "final-training.json"), load(folder / "final-model.json")
            fit = audit_fit(receipt, plan, teacher, parts["natural_train"], parts["reader_train"], parts["augmentation"], init_record, arm)
            _check(receipt["campaign_schema"] == "hepta.endpoint.campaign.v8" and receipt["teacher_reference_reused"] is True
                   and receipt["active_teacher_distillation"] is False and receipt["new_teacher_forward_calls"] == 0,
                   "historical teacher compatibility reference misrepresented as active training")
            _check(file_sha(folder / "final-model.json") == frozen["manifests"][str((folder / "final-model.json").relative_to(run))], "global model manifest freeze changed")
            audit_identity(model["architecture"], arm)
            _check(model["file"] == "final.pt" and model["training_receipt_file"] == "final-training.json"
                   and model["seed"] == seed and started["started_ns"] < model["frozen_ns"] <= frozen["frozen_ns"], "final checkpoint arm/file/time changed")
            final_tensors = checkpoint_tensors(bind(folder / "final.pt"), parameter_shapes(arm))
            decoded = tensor_summary(final_tensors)
            _check(all(model[k] == decoded[k] for k in ("training_parameter_sha256", "execution_parameter_sha256", "parameter_count")), "final checkpoint decoded digest/count differs")
            audit_checkpoint(folder / "final.pt", model, receipt, init_record)
            change = audit_learning_change(load(folder / "learning-change.json"), init_tensors, final_tensors, arm, init_record, model)
            panels = {}
            for suffix, rows in (("binding-train", parts["reader_train"]), ("binding-internal", parts["internal_tune"]), ("augmentation-train", parts["augmentation"])):
                recorded = load(folder / f"final-{suffix}.json")
                panels[suffix] = audit_binding_panel(rows, recorded, model)
                if suffix != "binding-internal":
                    diagnostic = receipt["diagnostics"][-1]["binding" if suffix == "binding-train" else "augmentation"]["probabilities"]
                    _check(len(diagnostic) == len(recorded["probabilities"]), "final diagnostic/panel length mismatch")
                    for a, b in zip(diagnostic, recorded["probabilities"]):
                        same(b, a, "final frozen panel differs from final training diagnostic", atol=1e-7, rtol=1e-7)
            for suffix, role, scope in (("natural-train", "natural_train", "complete_natural_training_partition"),
                ("natural-internal", "natural_internal", "previously_exposed_descriptive_not_fresh")):
                panels[suffix] = natural_panel(parts[role], load(folder / f"final-{suffix}.json"), model, scope)
            gate = joint_gate(panels["binding-train"]["metrics"], baseline, panels["binding-internal"]["metrics"],
                              panels["natural-train"]["metrics"], start, design["natural_constants"])
            _check(load(folder / "final-gate.json") == gate, "reported qualification differs from independent complete panels")
            gates[str(seed)][arm] = gate
            qualification = _cost(load(folder / "qualification-cost.json"))
            panel_cost = {axis: sum(p.get("cost", p.get("costs"))[axis] for p in panels.values()) for axis in costs}
            _check(all(qualification[k] >= panel_cost[k] for k in costs), "qualification outer cost omits physical panels")
            diagnostics = dict(deleted3=audit_deleted_panel(parts["reader_train"], load(folder / "diagnostics/deleted3.json"), model, transform, cache["tokens"]),
                reset3=audit_binding_panel(parts["reader_train"], load(folder / "diagnostics/reset3.json"), model, reset=True),
                full1=audit_binding_panel(parts["reader_train"], load(folder / "diagnostics/full1.json"), model, depth=1))
            diagnostic_receipt = load(folder / "diagnostics/receipt.json")
            _check(diagnostic_receipt["full3_reused_file"] == "../final-binding-train.json"
                   and diagnostic_receipt["full3_reused_sha256"] == file_sha(folder / "final-binding-train.json")
                   and diagnostic_receipt["new_candidate_observations"] == 384
                   and diagnostic_receipt["diagnostics_used_for_gate_or_selection"] is False,
                   "diagnostic reference reuse/candidate accounting changed")
            diagnostic_cost = _cost(diagnostic_receipt["phase_cost"])
            _check(all(diagnostic_cost[k] >= sum(p["costs"][k] for p in diagnostics.values()) for k in costs), "diagnostic outer cost omits physical work")
            for item in (fit["shared_fit_cost_once"], change["cost_once"], qualification, diagnostic_cost):
                for axis in costs:
                    costs[axis] += item[axis]
            times.append(model["frozen_ns"])
            arm_reports.append(dict(arm=arm, fit=fit, final_checkpoint=decoded, learning_change=change,
                panels=panels, gate=gate, diagnostics=diagnostics, qualification_cost_once=qualification,
                diagnostics_cost_once=diagnostic_cost))
        _check(times == sorted(times), "actual model freeze order differs from registered order")
        reports.append(dict(seed=seed, arms=arm_reports))
    primary = all(gates[str(seed)]["endpoint"]["passed"] for seed in (41, 47, 53))
    _check(completion["gates"] == gates and completion["primary_all_passed"] is primary, "global endpoint qualification differs from three-seed conjunction")
    outer = _cost(completion["phase_cost"])
    _check(all(outer[k] >= costs[k] for k in costs), "training phase outer cost omits disjoint work")
    return dict(training_audited=True, training=reports, optimizer_updates=18000, completed_fits=12,
        decoded_new_checkpoints=12, all_models_frozen=True, downstream_markers_absent=True,
        qualification=dict(gates=gates, primary_all_passed=primary, controls_cannot_replace_primary=True,
                           feedback_authorized=False, fresh_authorized=False),
        training_cost=dict(outer_phase_once=outer, disjoint_nested_decomposition_not_added=costs,
            fit_diagnostics_not_added=True, full3_reference_not_recharged=True,
            historical_teacher_and_natural_start_not_recharged=True))

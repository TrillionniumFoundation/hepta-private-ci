"""Independent V9 prepare/training/fresh orchestration; never imports Torch."""
import json
from pathlib import Path
import time

from binding_review import _check, _cost, audit_checkpoint, audit_source_inventory
from bridge_feedback_review import audit_manifest
from endpoint_v8_checkpoint_review import BRIDGE_SHAPES, checkpoint_tensors, tensor_summary
from endpoint_v8_checkpoint_review import review as review_v8
from endpoint_v8_review import audit_binding_panel
from grounding_checkpoint_review import SHAPES, audit_identity, audit_initialization, audit_learning_change
from grounding_fresh_review import audit_fresh_cases, review_fresh
from grounding_review import ARMS, audit_auxiliary
from grounding_span_review import audit_span_targets
from grounding_training_review import audit_training
from retention_v7_checkpoint_review import file_sha, natural_panel
from retention_v7_review import audit_plan, joint_gate, same

SEEDS = (41, 47, 53)
NEW_RUNTIME = {"grounding_reader.py", "grounding_spans.py", "grounding_protocol.py", "grounding_training.py",
               "grounding_campaign_utils.py", "grounding_campaign.py", "grounding_evaluation.py"}
AUDITORS = ("binding_review.py", "bridge_feedback_review.py", "bridge_review.py", "bridge_revision_review.py",
    "retention_v7_review.py", "retention_v7_checkpoint_review.py", "endpoint_v8_review.py", "endpoint_v8_checkpoint_review.py",
    "grounding_span_review.py", "grounding_review.py", "grounding_training_review.py", "grounding_checkpoint_review.py",
    "grounding_run_review.py", "grounding_fresh_review.py")


def review(run, code, natural_cases, *, stage="prepare"):
    started = time.perf_counter_ns(), time.process_time_ns()
    run, code = Path(run), Path(code)
    _check(stage in ("prepare", "training", "fresh"), "explicit V9 audit stage required")
    guarded = {}

    def bind(path):
        path = Path(path).resolve()
        digest = file_sha(path)
        _check(str(path) not in guarded or guarded[str(path)] == digest, "audit input changed between reads")
        guarded[str(path)] = digest
        return path

    def load(path):
        return json.loads(bind(path).read_text())

    for name in AUDITORS:
        bind(code / name)
    design, parts = load(run / "design.json"), load(run / "all-cases.json")
    _check(design["schema"] == "hepta.grounding.campaign.v9" and design["primary"] == "grounded_chain"
           and design["arms"] == list(ARMS) and design["order"] == {str(s): list(ARMS[i:] + ARMS[:i]) for i, s in enumerate(SEEDS)}, "registered 2x2 V9 arms/order changed")
    _check(design["training"] == dict(logical_updates=500, streams=["natural", "transfer", "retention"], batch_size=16,
        legacy_depth=3, graph_depth=2, learning_rate=.001, pair_weight=.5, span_weight=1., contrastive_weight=.1,
        contrastive_temperature=.1, diagnostic_interval=100, optimizer_updates_per_model=1500,
        candidate_exposures_per_model=24000, stop_rule="fixed_final_no_selection", teacher_calls=0, teacher_distillation=False)
        and design["factors"] == dict(grounded="training_only_span_and_cross_context_entity_losses", chain="carry_graph_address_across_two_hops"), "registered training budget/factors changed")
    _check(all(design[k] is False for k in ("feedback_authorized", "original_V5_fresh_authorized", "official_validation_read", "hosted_ci_consulted", "production_authorized"))
           and design["fresh_authorized"] is design["fresh_requires_all_twelve_frozen"] is design["fresh_independent_of_old_qualification"] is True
           and design["initial_actual_candidate_observations"] == 1536, "frozen V9 evaluation scope changed")
    previous = run.parent / "reader-v8-endpoint"
    prior_design, prior_complete, prior_freeze = (load(previous / name) for name in ("design.json", "training-completion.json", "all-models-frozen.json"))
    _check(file_sha(previous / "design.json") == design["previous_v8_design_sha256"]
           and file_sha(previous / "training-completion.json") == design["previous_v8_completion_sha256"]
           and prior_complete["runtime_source_sha256"] == prior_design["runtime_source_sha256"]
           and prior_complete["actual_optimizer_updates"] == 18000 and prior_complete["actual_training_exposures"] == 288000
           and len(prior_freeze["manifests"]) == 12, "actual complete V8 lineage changed")
    for name, digest in prior_freeze["manifests"].items():
        _check(file_sha(bind(previous / name)) == digest, "historical V8 selection changed")
    prior = review_v8(previous, code, natural_cases, stage="prepare")
    for path, digest in prior["inputs_sha256"].items():
        _check(file_sha(bind(path)) == digest, "independent historical preparation chain changed")
    inventory = design["runtime_source_sha256"]
    _check(len(inventory) == 68 and set(inventory) == set(prior_design["runtime_source_sha256"]) | NEW_RUNTIME
           and all(inventory[n] == sha for n, sha in prior_design["runtime_source_sha256"].items()), "old 61 bytes or new seven-file runtime inventory changed")
    for name in inventory:
        bind(code / name)
    sources = audit_source_inventory(code, inventory)
    _check(file_sha(bind(code / "GROUNDING_V9_PROTOCOL.md")) == design["protocol_sha256"], "frozen V9 protocol changed")
    old_parts = load(previous / "all-cases.json")
    _check(set(parts) == set(old_parts) | {"fresh_combinations", "fresh_vocabulary"}
           and all(parts[role] == rows for role, rows in old_parts.items())
           and design["historical"] == prior_design["historical"] and design["natural_constants"] == prior_design["natural_constants"]
           and design["old_gates"] == prior_design["gates"] and design["reused_cache_files_sha256"] == prior_design["reused_cache_files_sha256"], "training data/natural baseline/cache/warmup reuse changed")
    prior_v7_roots = {Path(r["folder"]).parent for r in design["historical"]["observations"].values()}
    _check(len(prior_v7_roots) == 1, "one V7 historical data/cache root required")
    prior_v7 = next(iter(prior_v7_roots))
    history = load(prior_v7 / "all-cases.json")
    final_cases = load(run.parent / "reader-v4-main/seed-41/binding/controlled-cases.json")
    fresh_cases = audit_fresh_cases({r: parts[r] for r in ("fresh_combinations", "fresh_vocabulary")}, design["fresh"],
        {r: rows for r, rows in history.items() if r != "augmentation"}, parts["augmentation"], final_cases)
    cache = load(prior_v7 / "features/metadata.json")
    targets = load(run / "auxiliary-targets.json")
    _check(set(targets) == {"binding", "augmentation"}, "exact old/augmentation immutable auxiliary target tables required")
    span_reports = {role: audit_span_targets(parts["reader_train" if role == "binding" else role], target, cache["tokens"])
                    for role, target in targets.items()}
    expected_files = {"all-cases.json", "auxiliary-targets.json"} | {f"seed-{s}/training-plan.json" for s in SEEDS} | {
        f"seed-{s}/{arm}/initialization.{suffix}" for s in SEEDS for arm in ARMS for suffix in ("json", "pt", "bin")}
    _check(set(design["prepared_files_sha256"]) == expected_files, "complete 41-file prepared input inventory required")
    for name, digest in design["prepared_files_sha256"].items():
        _check(file_sha(bind(run / name)) == digest, "prepared V9 input changed")
    prep = load(run / "preparation-completion.json")
    panel_names = {f"seed-{s}/{arm}/initial-binding-train.json" for s in SEEDS for arm in ARMS}
    _check(prep["design_sha256"] == file_sha(run / "design.json") and prep["actual_initial_candidate_observations"] == 1536
           and prep["exact_initial_probability_equality"] == {str(s): True for s in SEEDS} and set(prep["initial_panels_sha256"]) == panel_names
           and prep["new_encoder_forward_batches"] == 0 and prep["completed_ns"] > design["created_ns"], "actual complete initial observation evidence changed")
    initial, reports, panel_cost = {}, [], dict(cpu_ns=0, wall_ns=0)
    for seed in SEEDS:
        core_folder = Path(design["historical"]["warmups"][str(seed)]["folder"])
        core = audit_manifest(core_folder / "warmup-model.json", expected_arm="bridge")
        warmup = checkpoint_tensors(bind(core_folder / "warmup.pt"), BRIDGE_SHAPES)
        baseline = load(core_folder / "warmup-binding-train.json")
        plan = load(run / f"seed-{seed}/training-plan.json")
        _check(plan == load(prior_v7 / f"seed-{seed}/training-plan.json"), "actual V7/V8 sample sequence changed")
        audit_plan(plan, parts["natural_train"], parts["reader_train"], parts["augmentation"])
        initial[seed], arm_reports, reference = {}, [], None
        for arm in ARMS:
            folder = run / f"seed-{seed}" / arm
            record = load(folder / "initialization.json")
            tensors, decoded = audit_initialization(folder, record, warmup, core, arm, seed)
            panel_path = folder / "initial-binding-train.json"
            _check(file_sha(bind(panel_path)) == prep["initial_panels_sha256"][str(panel_path.relative_to(run))], "initial actual panel bytes changed")
            panel = load(panel_path)
            checked = audit_binding_panel(parts["reader_train"], panel, record)
            _check(panel["probabilities"] == baseline["probabilities"] and (reference is None or reference == tensors), "four complete initial tensors/predictions must equal common V6 starts")
            reference = tensors
            for axis, value in checked["costs"].items():
                panel_cost[axis] += value
            initial[seed][arm] = (record, tensors)
            arm_reports.append(dict(arm=arm, checkpoint=decoded, panel=checked))
        reports.append(dict(seed=seed, arms=arm_reports, four_arm_tensor_bytes_equal=True, actual_probability_equality=True))
    _check(all(_cost(prep["phase_cost"])[axis] >= value for axis, value in panel_cost.items()), "prepare outer cost omits initial panels")
    result = dict(schema="hepta.grounding.independent-review.v9", passed=True, stage=stage, source_inventory_count=68,
        sources=sources, old_runtime_61_unchanged=True, prepared_input_files=41, previous_v8_prepare_audit_passed=True,
        fresh_membership=fresh_cases, span_targets=span_reports, initializations=reports,
        initial_candidate_observations=1536, preparation_cost=dict(outer_phase_once=_cost(prep["phase_cost"]), initial_panels_nested_not_added=panel_cost),
        training_audited=False, fresh_audited=False, feedback_audited=False, torch_imported=False, independent_neural_execution=False)
    if stage != "prepare":
        training, models = review_training(run, prior_v7, design, parts, targets, initial, load, bind)
        result.update(training)
        if stage == "fresh":
            result["fresh"] = review_fresh(run, design, parts, models, load, bind, audit_aux=audit_auxiliary)
            result["fresh_audited"] = True
    _check(all(file_sha(path) == digest for path, digest in guarded.items()), "independent audit inputs changed during review")
    result.update(immutable_inputs_unchanged=True, inputs_sha256=guarded, auditor_source_sha256={name: file_sha(code / name) for name in AUDITORS},
        audit_cost=dict(cpu_ns=time.process_time_ns() - started[1], wall_ns=time.perf_counter_ns() - started[0],
            scope="stdlib_parse_hash_decode_replay_excludes_process_startup_output_serialization"),
        limitations=["No neural or tokenizer rerun; recorded clocks and gradient observations receive consistency checks.",
                     "Every update class logits, selected span CE and scalar contrastive reductions replayed; full metric dots only fixed saved observations."])
    return result


def review_training(run, prior_v7, design, parts, targets, initial, load, bind):
    complete, started, frozen = (load(run / n) for n in ("training-completion.json", "training-start.json", "all-models-frozen.json"))
    names = {f"seed-{s}/{a}/final-model.json" for s in SEEDS for a in ARMS}
    _check(set(frozen["manifests"]) == names and complete["runtime_source_sha256"] == frozen["runtime_source_sha256"] == design["runtime_source_sha256"]
           and complete["actual_optimizer_updates"] == 18000 and complete["actual_training_exposures"] == 288000
           and complete["new_encoder_forward_batches"] == complete["new_teacher_forward_calls"] == 0
           and complete["feedback_authorized"] is False and complete["fresh_authorized"] is True and frozen["feedback_authorized"] is False
           and frozen["fresh_started"] is False and started["retries_authorized"] is False
           and started["started_ns"] < frozen["frozen_ns"] <= complete["completed_ns"], "complete twelve-model freeze/training budget changed")
    _check(not any((run / n).exists() for n in ("feedback-start.json", "feedback-completion.json")), "V9 feedback remains unauthorized")
    models, reports, gates, costs = {}, [], {}, dict(cpu_ns=0, wall_ns=0)
    for seed in SEEDS:
        plan = load(run / f"seed-{seed}/training-plan.json")
        core_folder = Path(design["historical"]["warmups"][str(seed)]["folder"])
        baseline = load(core_folder / "warmup-binding-train.json")["metrics"]
        start = load(prior_v7 / f"seed-{seed}/start-natural-train.json")["metrics"]
        gates[str(seed)], arm_reports, times = {}, [], []
        for arm in design["order"][str(seed)]:
            folder = run / f"seed-{seed}" / arm
            before, initial_tensors = initial[seed][arm]
            receipt, model = load(folder / "final-training.json"), load(folder / "final-model.json")
            fit = audit_training(receipt, plan, targets, parts, before, arm)
            _check(file_sha(folder / "final-model.json") == frozen["manifests"][str((folder / "final-model.json").relative_to(run))], "global final manifest changed")
            audit_identity(model["architecture"], arm)
            _check(model["file"] == "final.pt" and model["training_receipt_file"] == "final-training.json" and model["seed"] == seed
                   and started["started_ns"] < model["frozen_ns"] <= frozen["frozen_ns"], "final model file/seed/freeze time changed")
            final_tensors = checkpoint_tensors(bind(folder / "final.pt"), SHAPES)
            decoded = tensor_summary(final_tensors)
            _check(all(model[k] == decoded[k] for k in ("training_parameter_sha256", "execution_parameter_sha256", "parameter_count")), "final decoded checkpoint digest/count mismatch")
            audit_checkpoint(folder / "final.pt", model, receipt, before)
            drift = audit_learning_change(load(folder / "learning-change.json"), initial_tensors, final_tensors, before, model)
            panels = {}
            for suffix, role in (("binding-train", "reader_train"), ("binding-internal", "internal_tune"), ("augmentation-train", "augmentation")):
                panel = load(folder / f"final-{suffix}.json")
                panels[suffix] = audit_binding_panel(parts[role], panel, model)
                if suffix != "binding-internal":
                    previous = receipt["diagnostics"][-1]["binding" if suffix == "binding-train" else "augmentation"]["probabilities"]
                    _check(len(previous) == len(panel["probabilities"]), "final diagnostic/panel coverage changed")
                    for a, b in zip(previous, panel["probabilities"]):
                        same(b, a, "final panel differs from last diagnostic", atol=1e-7, rtol=1e-7)
            for suffix, role, scope in (("natural-train", "natural_train", "complete_natural_training_partition"),
                ("natural-internal", "natural_internal", "previously_exposed_descriptive_not_fresh")):
                panels[suffix] = natural_panel(parts[role], load(folder / f"final-{suffix}.json"), model, scope)
            gate = joint_gate(panels["binding-train"]["metrics"], baseline, panels["binding-internal"]["metrics"], panels["natural-train"]["metrics"], start, design["natural_constants"])
            _check(load(folder / "final-legacy-gate.json") == gate, "legacy qualification differs from independently rescored panels")
            qualification = _cost(load(folder / "qualification-cost.json"))
            _check(all(qualification[k] >= sum(p.get("cost", p.get("costs"))[k] for p in panels.values()) for k in costs), "qualification outer cost omits panels")
            for item in (fit["shared_fit_cost_once"], drift["cost_once"], qualification):
                for axis in costs:
                    costs[axis] += item[axis]
            gates[str(seed)][arm], models[(seed, arm)] = gate, model
            times.append(model["frozen_ns"])
            arm_reports.append(dict(arm=arm, fit=fit, checkpoint=decoded, learning_change=drift, panels=panels, legacy_gate=gate, qualification_cost_once=qualification))
        _check(times == sorted(times), "registered actual model execution/freeze order changed")
        reports.append(dict(seed=seed, arms=arm_reports))
    primary = all(gates[str(s)]["grounded_chain"]["passed"] for s in SEEDS)
    _check(complete["legacy_gates"] == gates and complete["legacy_primary_all_passed"] is primary, "legacy primary conjunction changed")
    outer = _cost(complete["phase_cost"])
    _check(all(outer[k] >= costs[k] for k in costs), "training outer cost omits disjoint work")
    return dict(training_audited=True, training=reports, optimizer_updates=18000, completed_fits=12, decoded_new_checkpoints=12,
        all_models_frozen=True, legacy_qualification=dict(gates=gates, primary_all_passed=primary, fresh_selection_authorized=False),
        auxiliary_replay_coverage=dict(controlled_update_reductions=12000, natural_no_auxiliary_checks=6000,
            fixed_full_observations=144, all_update_contrastive_dots_recomputed=False),
        training_cost=dict(outer_phase_once=outer, disjoint_nested_decomposition_not_added=costs)), models

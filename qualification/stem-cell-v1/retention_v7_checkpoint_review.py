"""Independent V7 prepare/completed-fit orchestration; stdlib only.

No fresh probabilities or incomplete fits are opened. Checkpoint tensor bytes
are decoded with the frozen bounded decoder, never with torch.load.
"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import time

from binding_review import (_check, _cost, _digest, _groups, _id, _semantic,
    audit_checkpoint, audit_panel, audit_scores, audit_source_inventory)
from bridge_feedback_review import audit_manifest
from retention_v7_review import (ARMS, STREAMS, audit_plan, audit_teacher,
    audit_training, constants, joint_gate, natural_metrics, same)

SEEDS = (41, 47, 53)
NEW_RUNTIME = {"retention_data.py", "retention_v7_training.py", "retention_campaign_utils.py",
               "retention_campaign.py", "retention_evaluation.py", "retention_feedback.py"}


def read(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare_metrics(reported, expected):
    _check(set(reported) == set(expected), "complete metric fields changed")
    for key, value in expected.items():
        same(reported[key], value, "independent metric mismatch: " + key, atol=1e-9, rtol=1e-9)


def audit_data(parts, membership, augmentation, old_final):
    """Reconstruct grammar and exclusions without importing any generator."""
    _check(set(parts) == set(membership["roles"]) | {"augmentation"}, "complete six-role data required")
    role_reports = {}
    for role, bound in membership["roles"].items():
        rows, groups = _groups(parts[role])
        _check(bound["case_ids"] == [_id(r) for r in rows]
               and bound["complete_labeled_cases_sha256"] == _digest(rows)
               and bound["semantic_tasks_sha256"] == _digest(sorted(_semantic(r) for r in rows))
               and bound["source_hashes"] == sorted({r["source_hash"] for r in rows})
               and bound["cases"] == len(rows) and bound["groups"] == len(groups)
               and bound["paired_candidates"] == len(groups) * 2, "historical role data changed: " + role)
        role_reports[role] = dict(cases=len(rows), groups=len(groups), labeled_sha256=_digest(rows))
    old = parts["reader_train"] + parts["internal_tune"] + old_final
    _check(len(old_final) == 128 and _digest(sorted(_semantic(r) for r in old))
           == membership["old_v4_exclusions_sha256"], "independently reconstructed historical exclusion changed")
    excluded = old + [r for role, rows in parts.items() if role != "augmentation" for r in rows]
    task_keys, source_keys = {_semantic(r) for r in excluded}, {_semantic(r, True) for r in excluded}
    rows, groups = _groups(parts["augmentation"])
    _check(len(rows) == 1024 and len(groups) == 256 and all(r["source_split"] == "train" for r in rows)
           and not task_keys & {_semantic(r) for r in rows}
           and not source_keys & {_semantic(r, True) for r in rows}, "augmentation size/split or exclusion failed")
    shard_counts = Counter()
    for prefix, members in groups.items():
        match = re.fullmatch(r"binding-v5/retention-v7-augmentation-([0-7])/1701/(\d+)", prefix)
        _check(match is not None and 0 <= int(match[2]) < 32, "augmentation shard/group identity changed")
        shard_counts[match[1]] += 1
        for _, row, _, owners, stores in members:
            _check(set(owners) <= set("coin bead token key button marble shell stamp".split())
                   and set(stores) <= set("Ada Ben Cleo Drew Esme Finn Gina Hugo".split())
                   and set(stores.values()) <= set("copper silver golden blue green violet".split()),
                   "augmentation crossed registered old-training vocabulary")
    _check(shard_counts == {str(i): 32 for i in range(8)}, "complete eight augmentation shards required")
    expected = dict(cases=1024, groups=256, paired_candidates=512,
        semantic_tasks_sha256=_digest(sorted(_semantic(r) for r in rows)), independent_grammar_verified=True,
        complete_labeled_cases_sha256=_digest(rows), excluded_tasks_sha256=_digest(sorted(task_keys)),
        excluded_sources_sha256=_digest(sorted(source_keys)), labels_reconstructed_by_grammar=True,
        fresh_scores_used=False, vocabulary="same_generator_people_objects_colors_as_old_train",
        chain_structure="two_hop_ownership_storage", longer_chain=False)
    _check(augmentation == expected, "augmentation independent grammar/exclusion manifest mismatch")
    return dict(passed=True, historical_roles=role_reports, augmentation=expected,
                exclusion_tasks=len(task_keys), exclusion_sources=len(source_keys), generator_imported=False,
                old_final_metadata_only=True, fresh_predictions_read=False)


def audit_natural_material(path, design, v6, v5):
    path = Path(path)
    material, provenance = read(path), read(path.parent / "material-provenance.json")
    _check(set(material) == {"train", "tune"} and file_sha(path) == provenance["natural_cases_file_sha256"]
           and provenance["design_sha256"] == file_sha(v5 / "design.json")
           == v6["previous_v5_design_sha256"], "natural material/V5 design chain changed")
    old = read(v5 / "design.json")
    _check(provenance["official_train_sha256"] == old["train_file_sha256"], "natural official-training source binding changed")
    reports = {}
    for role, count, questions, paragraphs in (("train", 3909, 722, 64), ("tune", 827, 194, 16)):
        rows = material[role]
        _check(len(rows) == count and all(r["source_split"] == "train" and type(r["label"]) is int
               and r["label"] in (0, 1) for r in rows) and len({_id(r) for r in rows}) == count
               and [_id(r) for r in rows] == design["natural_case_ids"][role] == v6["natural_case_ids"][role],
               "natural exact row identity/split/labels changed")
        score = natural_metrics(rows, [.5] * len(rows))
        _check(score["questions"] == questions and score["paragraphs"] == paragraphs, "complete natural question grouping changed")
        reports[role] = dict(cases=count, questions=questions, paragraphs=paragraphs,
                             case_ids_sha256=_digest([_id(r) for r in rows]))
    _check({r["source_hash"] for r in material["train"]}.isdisjoint(r["source_hash"] for r in material["tune"]),
           "natural training/internal paragraph overlap")
    baseline = constants(material["train"])
    _check(sum(r["label"] for r in material["train"]) == 1696, "natural training class count changed")
    _check(design["natural_constants"].keys() == baseline.keys(), "constant baseline structure changed")
    for key in ("always_positive", "always_negative"):
        compare_metrics(design["natural_constants"][key], baseline[key])
    for key in ("positive_prior", "prior_constant_CE", "majority_class"):
        same(design["natural_constants"][key], baseline[key], "natural prior baseline mismatch")
    _check(design["natural_constants"]["training_only"] is True
           and design["natural_constants"]["threshold_selected"] is False, "constant baseline scope changed")
    return material, dict(passed=True, partitions=reports, constants=baseline,
        material_file_sha256=file_sha(path), raw_official_training_reparsed=False, official_validation_read=False)


def audit_design(design):
    _check(design["schema"] == "hepta.retention.campaign.v7" and design["primary"] == "anchored"
           and design["arms"] == list(ARMS), "registered V7 primary/arms changed")
    _check(design["order"] == {"41": list(ARMS), "47": list(ARMS[1:] + ARMS[:1]),
                              "53": list(ARMS[2:] + ARMS[:2])}, "registered arm execution order changed")
    _check(design["training"] == dict(logical_updates=500, streams=list(STREAMS), batch_size=16, depth=3,
        learning_rate=.001, low_learning_rate=.0001, pair_weight=.5, anchor_weight=1., diagnostic_interval=100,
        wall_time_ns=1_800_000_000_000, stop_rule="fixed_final_no_selection", transfer_repeat="old_binding",
        transfer_other="augmentation", anchor_stream="retention_only", teacher="frozen_V6_warmup_centered_logits"),
        "fixed training recipe changed")
    _check(design["gates"] == dict(retention_candidate=.95, retention_pairs=.95, maximum_retention_drop=.05,
        internal_relation_candidate=.75, internal_relation_pairs=.50, natural_F1m_gain_over_best_constant=.05,
        natural_F1a_gain_over_start=.05, natural_EM=.05, natural_CE_ratio_to_prior=.95,
        every_primary_seed_required=True), "registered joint gates changed")
    _check(design["new_parameters"] == 0 and design["teacher_inference_at_serving"] is False
           and design["same_parameter_count_is_same_compute"] is False and design["equal_exposures_is_equal_compute"] is False
           and design["old_internal_is_unseen_generalization"] is False and design["official_validation_read"] is False
           and design["hosted_ci_consulted"] is False and design["production_authorized"] is False,
           "scope or compute claim changed")


def natural_panel(rows, panel, model, scope):
    _check(panel["case_ids"] == [_id(r) for r in rows] and panel["scope"] == scope
           and panel["threshold_selected"] is False and panel["labels_entered_model"] is False
           and panel["model_execution_parameter_sha256"] == model["execution_parameter_sha256"],
           "natural panel source/model/public-boundary binding changed")
    metrics = natural_metrics(rows, panel["probabilities"])
    compare_metrics(panel["metrics"], metrics)
    ids, batches, cost = panel["case_ids"], panel["batches"], dict(cpu_ns=0, wall_ns=0)
    _check(len(batches) == (len(rows) + 15) // 16 and len({r["batch_id"] for r in batches}) == len(batches),
           "natural physical batches missing/duplicated")
    for index, batch in enumerate(batches):
        _check(batch["case_ids"] == ids[index * 16:(index + 1) * 16] and batch["steps"] == 3
               and batch["proposal_steps"] == 3 * len(batch["case_ids"]), "natural physical case/call accounting changed")
        for axis, value in _cost(batch).items():
            cost[axis] += value
    return dict(passed=True, metrics=metrics, cost=cost, physical_batches=len(batches))


def binding_panel(rows, panel, model):
    _check(panel["depth"] == 3 and len(panel["batches"]) == (len(rows) + 15) // 16,
           "binding fixed-depth physical batches changed")
    ids = [_id(row) for row in rows]
    for index, batch in enumerate(panel["batches"]):
        _check(batch["case_ids"] == ids[index * 16:(index + 1) * 16], "binding physical batch geometry changed")
    return audit_panel(rows, panel, model)


def review(run, code, natural_cases, *, stage="prepare"):
    started = time.perf_counter_ns(), time.process_time_ns()
    run, code = Path(run), Path(code)
    _check(stage in ("prepare", "training"), "explicit prepare/training audit stage required")
    guarded = {}

    def bind(path):
        path = Path(path).resolve()
        digest = file_sha(path)
        _check(str(path) not in guarded or guarded[str(path)] == digest, "audit input changed between reads")
        guarded[str(path)] = digest
        return path

    def load(path):
        return read(bind(path))

    auditor_names = ("retention_v7_checkpoint_review.py", "retention_v7_review.py", "binding_review.py",
                     "bridge_feedback_review.py", "bridge_review.py", "bridge_revision_review.py")
    for name in auditor_names:
        bind(code / name)
    design, parts = load(run / "design.json"), load(run / "all-cases.json")
    audit_design(design)
    roots = {Path(r["folder"]).parent.parent for r in design["historical_warmups"].values()}
    _check(len(roots) == 1 and set(design["historical_warmups"]) == {str(s) for s in SEEDS}, "three shared historical warmups required")
    previous = next(iter(roots))
    v6, completed = load(previous / "design.json"), load(previous / "warmup-completion.json")
    _check(file_sha(previous / "design.json") == design["previous_v6_design_sha256"]
           and file_sha(previous / "warmup-completion.json") == design["previous_v6_warmup_completion_sha256"]
           and completed["primary_all_passed"] is True, "qualified historical V6 design chain changed")
    declared = design["runtime_source_sha256"]
    _check(len(v6["runtime_source_sha256"]) == 52 and len(declared) == 58
           and set(declared) == set(v6["runtime_source_sha256"]) | NEW_RUNTIME
           and all(declared[n] == value for n, value in v6["runtime_source_sha256"].items()), "old 52 runtime bytes or new six-file inventory changed")
    for name in declared:
        bind(code / name)
    sources = audit_source_inventory(code, declared)
    _check(file_sha(bind(code / "RETENTION_V7_PROTOCOL.md")) == design["protocol_sha256"], "registered V7 protocol bytes changed")
    final_path = run.parent / "reader-v4-main" / "seed-41" / "binding" / "controlled-cases.json"
    data = audit_data(parts, v6["membership"], design["augmentation"], load(final_path))
    v5_roots = {Path(r["folder"]).parent for r in v6["historical_baselines"].values()}
    _check(len(v5_roots) == 1, "one historical V5 design required")
    v5 = next(iter(v5_roots))
    bind(v5 / "design.json")
    bind(natural_cases)
    bind(Path(natural_cases).parent / "material-provenance.json")
    natural, natural_report = audit_natural_material(natural_cases, design, v6, v5)
    for name, digest in design["extended_cache_files_sha256"].items():
        _check(name in ("metadata.json", "tokens.pt") and file_sha(bind(run / "features" / name)) == digest, "extended feature cache bytes changed")
    _check(set(design["extended_cache_files_sha256"]) == {"metadata.json", "tokens.pt"}, "complete cache inventory required")
    cache = load(run / "features" / "metadata.json")
    _check(cache["file_sha256"] == design["extended_cache_files_sha256"]["tokens.pt"], "cache metadata token file binding mismatch")
    encoder, preparation = load(run / "augmentation-encoder.json"), load(run / "preparation-cost.json")
    incremental = _cost(encoder["incremental_encoding"])
    _check(encoder["historical_cache_generation_not_additive"] is True
           and all(_cost(preparation)[k] >= incremental[k] for k in incremental)
           and encoder["incremental_encoding"]["batches"] == 2 and encoder["incremental_encoding"]["sequences"] == 18,
           "actual augmentation encoder preparation/cost accounting changed")
    history, cores, historical_cost = [], {}, dict(cpu_ns=0, wall_ns=0)
    required = {"warmup.pt", "warmup-model.json", "warmup-training.json", "warmup-binding-train.json", "warmup-natural-internal.json", "warmup-gate.json"}
    for seed in SEEDS:
        record = design["historical_warmups"][str(seed)]
        folder = Path(record["folder"])
        _check(set(record["files_sha256"]) == required and record["newly_trained"] is False
               and record["historical_not_free"] is True, "historical warmup scope/inventory changed")
        for name, digest in record["files_sha256"].items():
            _check(file_sha(bind(folder / name)) == digest, "historical warmup file changed")
        core = audit_manifest(folder / "warmup-model.json", expected_arm="bridge")
        receipt = load(folder / "warmup-training.json")
        _check(core["seed"] == seed and core["execution_parameter_sha256"] == record["execution_parameter_sha256"]
               and core["training_parameter_sha256"] == receipt["model_sha256"], "historical warmup dual digest binding changed")
        baseline = binding_panel(parts["reader_train"], load(folder / "warmup-binding-train.json"), core)
        _check(baseline["metrics"]["accuracy"] == baseline["metrics"]["both_worlds_correct"]
               == baseline["metrics"]["all_four_correct"] == 1. and baseline["metrics"]["probability_CE"] <= .10
               and load(folder / "warmup-gate.json")["passed"] is True, "historical actual baseline not fully qualified")
        _check(receipt["cpu_ns"] == record["historical_fit_cpu_ns"] and receipt["wall_ns"] == record["historical_fit_wall_ns"], "historical fit cost changed")
        for axis, value in _cost(receipt).items():
            historical_cost[axis] += value
        history.append(dict(seed=seed, parameter_count=core["parameter_count"], tensors=22,
            finite_FP32_tensors_decoded=True, training_parameter_sha256=core["training_parameter_sha256"],
            execution_parameter_sha256=core["execution_parameter_sha256"], old_training_recharged=False))
        cores[seed] = core
    result = dict(schema="hepta.retention.independent-review.v7", passed=True, stage=stage,
        source_inventory_count=58, sources=sources, data=data, natural=natural_report, historical_warmups=history,
        preparation=dict(outer_cost_once=_cost(preparation), incremental_encoder_nested_not_added=incremental,
                         historical_warmup_fit_costs_not_added=historical_cost, cache_tensor_values_decoded=False),
        training_audited=False, feedback_audited=False, fresh_audited=False,
        torch_imported=False, independent_neural_execution=False, official_validation_read=False)
    if stage == "training":
        result.update(review_completed(run, parts, natural, design, cores, load, bind))
    _check(all(file_sha(path) == digest for path, digest in guarded.items()), "audit inputs changed during independent review")
    result.update(immutable_inputs_unchanged=True, inputs_sha256=guarded,
        auditor_source_sha256={name: file_sha(code / name) for name in auditor_names},
        audit_cost=dict(cpu_ns=time.process_time_ns() - started[1], wall_ns=time.perf_counter_ns() - started[0],
                       scope="stdlib_parse_hash_decode_replay_excludes_process_startup_output_serialization"),
        limitations=["Recorded clocks and gradient observations are consistency checked, not independently authenticated.",
                     "No neural reexecution, fresh scoring or official validation access."])
    return result


def review_completed(run, parts, natural, design, cores, load, bind):
    completion = load(run / "training-completion.json")
    _check(completion["runtime_source_sha256"] == design["runtime_source_sha256"]
           and completion["fresh_scoring_authorized"] is False, "completion runtime/fresh authorization changed")
    training_start = load(run / "training-start.json")
    _check(training_start["retries_authorized"] is False and training_start["started_ns"] < completion["completed_ns"], "single completed fixed training phase required")
    reports, gates, costs = [], {}, dict(cpu_ns=0, wall_ns=0)
    fits, updates, checkpoints = 0, 0, 0
    for seed in SEEDS:
        folder, core = run / f"seed-{seed}", cores[seed]
        teacher_record = load(folder / "teacher.json")
        bind(folder / "teacher-logits.bin")
        teacher, shared = audit_teacher(folder, teacher_record, parts["reader_train"], core, design["extended_cache_files_sha256"])
        plan = load(folder / "training-plan.json")
        audit_plan(plan, natural["train"], parts["reader_train"], parts["augmentation"])
        start = natural_panel(natural["train"], load(folder / "start-natural-train.json"), core,
                              "complete_natural_training_partition_before_updates")
        for item in (shared["preparation_cost_once"], start["cost"]):
            for axis in costs:
                costs[axis] += item[axis]
        baseline = load(Path(design["historical_warmups"][str(seed)]["folder"]) / "warmup-binding-train.json")["metrics"]
        gates[str(seed)] = {}
        arm_reports, frozen_times = [], []
        for arm in design["order"][str(seed)]:
            receipt = load(folder / f"{arm}-training.json")
            fit = audit_training(receipt, plan, teacher, natural["train"], parts["reader_train"], parts["augmentation"], core, arm)
            model = load(folder / f"{arm}-model.json")
            bind(folder / model["file"])
            audit_manifest(folder / f"{arm}-model.json", expected_arm="bridge")
            audit_checkpoint(folder / model["file"], model, receipt, core)
            _check(model["seed"] == seed and model["frozen_ns"] <= completion["completed_ns"], "final model seed/freeze time changed")
            frozen_times.append(model["frozen_ns"])
            panels = {}
            for suffix, rows in (("binding-train", parts["reader_train"]), ("binding-internal", parts["internal_tune"]), ("augmentation-train", parts["augmentation"])):
                recorded = load(folder / f"{arm}-{suffix}.json")
                panels[suffix] = binding_panel(rows, recorded, model)
                if suffix != "binding-internal":
                    role = "binding" if suffix == "binding-train" else "augmentation"
                    diagnostic = receipt["diagnostics"][-1][role]["probabilities"]
                    _check(len(diagnostic) == len(recorded["probabilities"]), "final diagnostic/panel length mismatch")
                    for old_p, new_p in zip(diagnostic, recorded["probabilities"]):
                        same(new_p, old_p, "final frozen panel differs from last diagnostic", atol=1e-7, rtol=1e-7)
            for suffix, rows, scope in (("natural-train", natural["train"], "complete_natural_training_partition"),
                ("natural-internal", natural["tune"], "previously_exposed_training_source_internal_tune_not_fresh")):
                panels[suffix] = natural_panel(rows, load(folder / f"{arm}-{suffix}.json"), model, scope)
            gate = joint_gate(panels["binding-train"]["metrics"], baseline, panels["binding-internal"]["metrics"],
                              panels["natural-train"]["metrics"], start["metrics"], design["natural_constants"])
            _check(load(folder / f"{arm}-gate.json") == gate, "reported joint qualification differs from independent metrics")
            gates[str(seed)][arm] = gate
            for item in (fit["shared_fit_cost_once"], *[p.get("cost", p.get("costs")) for p in panels.values()]):
                for axis in costs:
                    costs[axis] += item[axis]
            fits += 1
            updates += fit["optimizer_updates"]
            checkpoints += 1
            arm_reports.append(dict(arm=arm, fit=fit, gate=gate, panels=panels,
                checkpoint=dict(parameter_count=model["parameter_count"], tensors=22, finite_FP32_tensors_decoded=True,
                    training_parameter_sha256=model["training_parameter_sha256"], execution_parameter_sha256=model["execution_parameter_sha256"])))
        _check(frozen_times == sorted(frozen_times) and min(frozen_times) > training_start["started_ns"], "actual arm execution/freeze order changed")
        reports.append(dict(seed=seed, teacher=shared, starting_natural=start, arms=arm_reports))
    primary = all(gates[str(seed)]["anchored"]["passed"] for seed in SEEDS)
    _check(completion["gates"] == gates and completion["primary_all_passed"] is primary,
           "global primary gate differs from independent three-seed conjunction")
    phase = _cost(completion["phase_cost"])
    _check(all(phase[k] >= costs[k] for k in costs), "training phase omits disjoint teacher/start/fit/qualification costs")
    forbidden = ("feedback-start.json", "feedback-completion.json", "all-models-frozen.json", "evaluation-start.json", "completion.json")
    if not primary:
        _check(not any((run / name).exists() for name in forbidden), "failed primary gate executed dependent feedback/fresh work")
    return dict(training_audited=True, training=reports, optimizer_updates=updates,
        completed_fits=fits, decoded_new_checkpoints=checkpoints, qualification=dict(gates=gates, primary_all_passed=primary,
            controls_cannot_replace_primary=True, feedback_authorized=primary, fresh_authorized_by_training_alone=False),
        training_cost=dict(outer_phase_once=phase, disjoint_nested_decomposition_not_added=costs,
            teacher_preparation_charged_once_per_seed=True, nested_fit_diagnostics_not_added=True),
        dependent_outputs_absent_if_gate_failed=not primary,
        future_feedback_and_18_model_freeze_support_only=True)

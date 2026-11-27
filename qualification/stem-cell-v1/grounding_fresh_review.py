"""Independent stdlib V9 held-out membership, execution-order and cost audit.

No producer generator/scorer/model or Torch is imported. Saved predictions,
vectors and clocks are consistency evidence, not independently rerun inference.
"""
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import statistics

from binding_review import (_check, _cost, _digest, _groups, _id, _rows, _semantic,
    audit_scores)
from endpoint_v8_review import audit_deleted_panel, audit_support_transform
from grounding_span_review import audit_span_targets, grammar_roles

ARMS = ("latent_chain", "grounded_chain", "grounded_reset", "latent_reset")
ROLES = ("fresh_combinations", "fresh_vocabulary")
SEEDS = (41, 47, 53)
DIAGNOSTICS = ("graph_one", "graph_reset", "reverse_facts", "support_deleted", "broken_payload")
WORDS = (("Ada Ben Cleo Drew Esme Finn Gina Hugo".split(), "coin bead token key button marble shell stamp".split()),
         ("Alden Briar Cassia Dorian Elian Freya Galen Hazel".split(),
          "anchor lantern ribbon pebble locket whistle prism thimble".split()))


def same(value, expected, message, *, tolerance=1e-10):
    _check(type(value) in (int, float) and math.isfinite(value)
           and math.isclose(value, expected, abs_tol=tolerance, rel_tol=tolerance), message)


def _legacy_v4_id(row):
    fields = ("source_split", "paragraph_id", "question_id", "answer_id")
    if all(k in row for k in fields):
        return _id(row)
    _check(not any(k in row for k in ("source_split", "question_id", "answer_id"))
           and re.fullmatch(r"binding-v4/final/41/([0-9]|[12][0-9]|3[01])/world-[01]", row["paragraph_id"])
           and isinstance(row.get("case_id"), str), "explicit legacy V4 final identity required")
    try:
        identity = json.loads(row["case_id"])
    except (ValueError, TypeError) as error:
        raise ValueError("invalid legacy V4 stored case identity") from error
    _check(isinstance(identity, list) and len(identity) == 4 and all(isinstance(v, str) for v in identity)
           and identity[:3] == ["validation", row["paragraph_id"], "0"] and identity[3] in ("0", "1"),
           "legacy V4 stored case identity differs from registered public row")
    return json.dumps(identity, separators=(",", ":"))


def audit_fresh_cases(parts, manifest, historical_parts, augmentation, old_v4_final):
    """Verify independent grammar, both lexical domains and every exclusion hash."""
    _check(set(parts) == set(ROLES), "exact two new held-out panels required")
    regular = [r for rows in historical_parts.values() for r in _rows(rows)] + _rows(augmentation)
    legacy = _rows(old_v4_final)
    old = regular + legacy
    _check(old and manifest["schema"] == "hepta.grounding.protocol.v9" and manifest["data_seed"] == 2901,
           "registered immutable V9 data identity required")
    excluded_tasks, excluded_sources = {_semantic(r) for r in old}, {_semantic(r, True) for r in old}
    _check(manifest["excluded_semantic_tasks_sha256"] == _digest(sorted(excluded_tasks))
           and manifest["excluded_source_keys_sha256"] == _digest(sorted(excluded_sources)), "historical exclusions changed")
    identifiers = {_id(r) for r in regular} | {_legacy_v4_id(r) for r in legacy}
    seen, sources, reports = set(excluded_tasks), set(excluded_sources), {}
    _check(set(manifest["roles"]) == set(ROLES), "exact two frozen manifest roles required")
    for role, (names, objects) in zip(ROLES, WORDS):
        rows, groups = _groups(parts[role])
        tasks, current_sources = {_semantic(r) for r in rows}, {_semantic(r, True) for r in rows}
        _check(len(rows) == 128 and len(groups) == 32 and not tasks & seen and not current_sources & sources,
               "new worlds overlap historical/reserved/other sources or have wrong counts")
        for row in rows:
            match = re.fullmatch(r"binding-v5/" + role + r"/2901/([0-9]|[12][0-9]|3[01])/world-[01]", row["paragraph_id"])
            _check(match is not None and row["source_split"] == "validation" and _id(row) not in identifiers,
                   "new frozen role/seed/case identity changed")
            fact_roles, question, candidate = grammar_roles(row)
            entities = [key for pair in fact_roles for key, _ in pair] + [question[0], candidate[0]]
            for key in entities:
                kind, word = key.split(":")
                allowed = names if kind == "person" else objects if kind == "object" else "copper silver golden blue green violet".split()
                _check(word in allowed, "declared controlled vocabulary changed")
        bound = manifest["roles"][role]
        _check(bound["cases"] == 128 and bound["groups"] == 32 and bound["paired_candidates"] == 64
               and bound["case_ids"] == [_id(r) for r in rows]
               and bound["complete_labeled_cases_sha256"] == _digest(rows)
               and bound["source_keys_sha256"] == _digest(sorted(current_sources))
               and bound["semantic_tasks_sha256"] == _digest(sorted(tasks)), "frozen domain membership/hash mismatch")
        seen.update(tasks); sources.update(current_sources); identifiers.update(_id(r) for r in rows)
        reports[role] = dict(cases=128, groups=32, independent_grammar=True, disjoint_worlds=True)
    _check(manifest["longer_chains"] is False and manifest["original_V5_reserved_domains_scored"] is False
           and manifest["predictions_read"] is False and manifest["official_validation_read"] is False,
           "new-data scope differs from frozen two-hop protocol")
    return dict(passed=True, panels=reports, original_reserved_domains_not_scored=True,
        unseen_atomic_joins_not_established=True, vocabulary_novelty_is_controlled_only=True)


def seed_gate(metrics):
    _check(set(metrics) == set(ROLES), "exact complete final panels required")
    panels, reasons = {}, []
    for role in ROLES:
        m = metrics[role]
        _check((m["cases"], m["groups"], m["paired_candidates"]) == (128, 32, 64), "complete fresh metrics required")
        for key, count in (("accuracy", 128), ("both_worlds_correct", 64)):
            value = m[key]
            _check(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
                   and abs(value*count-round(value*count)) <= 1e-9, "integer raw probability counts required")
        _check(m["both_worlds_correct"] <= m["accuracy"], "paired count exceeds candidate accuracy")
        candidate, pairs = round(m["accuracy"]*128), round(m["both_worlds_correct"]*64)
        failures = []
        if candidate < 109: failures.append("candidate_accuracy_below_0.85")
        if pairs < 48: failures.append("paired_accuracy_below_0.75")
        panels[role] = dict(passed=not failures, reasons=failures, candidate_correct=candidate, paired_correct=pairs)
        reasons.extend(role+":"+v for v in failures)
    return dict(passed=not reasons, reasons=reasons, panels=panels,
        thresholds=dict(candidate=.85, paired=.75, minimum_candidates=109, minimum_pairs=48),
        legacy_joint_gate_is_separate=True, model_or_threshold_selection=False, automatic_downstream_authorized=False)


def chronology(frozen, start, encoder, raw, target_start, target_end, complete, models):
    expected = {f"seed-{s}/{a}/final-model.json" for s in SEEDS for a in ARMS}
    _check(set(frozen["manifests"]) == expected and set(models) == {(s, a) for s in SEEDS for a in ARMS},
           "all twelve frozen model selections required")
    times = [frozen["frozen_ns"], start["started_ns"], encoder["encoding_started_ns"], encoder["encoding_completed_ns"],
             raw["completed_ns"], target_start["started_ns"], target_end["completed_ns"], complete["completed_ns"]]
    _check(all(type(t) is int and t > 0 for t in times) and times == sorted(times) and times[0] < times[1]
           and times[4] < times[5] < times[6]
           and max(m["frozen_ns"] for m in models.values()) <= times[0], "fresh encoding/raw/annotation chronology violated")
    _check(raw["actual_candidate_observations"] == 3072 and raw["diagnostic_annotations_constructed"] is False
           and raw["selected_models_changed"] is False and start["retries_authorized"] is False
           and start["original_V5_fresh_opened"] is False, "raw prediction phase boundary changed")
    return dict(passed=True, times_ns=times, recorded_order_consistent=True, clock_authenticity_independently_established=False)


def _panel(rows, panel, model, *, raw=False):
    ids = [_id(r) for r in rows]
    _check(panel["case_ids"] == ids and panel["model_execution_parameter_sha256"] == model["execution_parameter_sha256"],
           "fresh panel row/model binding changed")
    metrics = audit_scores(rows, panel["probabilities"], panel["metrics"])
    _check(set(metrics) <= set(panel["metrics"]), "complete independently recomputed metrics required")
    if raw:
        _check(panel["depth"] == 3 and panel["deleted"] is False and panel["reset"] is False
               and panel["labels_entered_model"] is False, "raw original inference boundary changed")
    batches = panel["batches"]
    _check(len(batches) == 8 and len({b["batch_id"] for b in batches}) == 8
           and [i for b in batches for i in b["case_ids"]] == ids, "eight complete physical batches required")
    costs = dict(cpu_ns=0, wall_ns=0)
    for b in batches:
        _check(len(b["case_ids"]) == 16 and b["steps"] == 3 and b["proposal_steps"] == 48, "fixed batch16/depth3 required")
        for k, v in _cost(b).items(): costs[k] += v
    return dict(metrics=metrics, costs=costs, physical_batches=8)


def audit_latency(record, rows, model):
    _check(record["schema"] == "hepta.grounding.cached-latency.v9" and record["case_ids"] == [_id(r) for r in rows[:2]]
           and rows[0]["facts"] == rows[1]["facts"] and rows[0]["question"] == rows[1]["question"], "fixed first-two public cases required")
    _check(record["model_execution_parameter_sha256"] == model["execution_parameter_sha256"]
           and record["warmup_forwards_per_geometry"] == 3 and record["timed_forwards_per_geometry"] == 20
           and record["extra_trace_forwards"] == record["separate_validation_forwards"] == 2
           and record["total_model_forwards"] == 2*(3+20)+2+2 == 50
           and record["device"] == "cpu" and record["dtype"] == "torch.float32" and record["thread_count"] == 1
           and record["legacy_depth"] == 3 and record["graph_depth"] == 2
           and record["encoder_included_in_timed_scope"] is False and record["end_to_end_product_latency"] is False
           and record["timed_scope"] == "forward_only_cached_features_including_graph_public_dedup"
           and record["warmup_and_validation_included_in_complete_evaluation_process"] is True
           and record["same_parameters_implies_equal_cost"] is False,
           "cached Head latency execution/count/scope changed")
    timed = dict(cpu_ns=0, wall_ns=0)
    _check(set(record["results"]) == {"batch1", "batch2"}, "both latency geometries required")
    for name, count in (("batch1", 1), ("batch2", 2)):
        value = record["results"][name]; samples = value["raw_measurements"]
        _check(value["candidate_count"] == count and len(samples) == 20
               and value["trace_group_work"] == dict(input_rows=count, unique_fact_groups=1, reused_rows=count-1),
               "latency sampler geometry or actual fact dedup changed")
        _check(len(value["probabilities"]) == count and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1
               for p in value["probabilities"]), "finite latency probabilities required")
        for kind in timed:
            ordered = sorted(_cost(r)[kind] for r in samples)
            same(value["summary"][kind]["median_ns"], statistics.median(ordered), "latency median mismatch")
            same(value["summary"][kind]["p95_ns"], .95*ordered[18]+.05*ordered[19], "inclusive latency p95 mismatch")
            timed[kind] += sum(ordered)
    separate = record["separate_probabilities"]
    _check(len(separate) == 2 and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in separate),
           "two independently executed validation probabilities required")
    same(record["batch_vs_separate_max_probability_delta"], max(abs(a-b) for a, b in zip(separate, record["results"]["batch2"]["probabilities"])),
         "batch/separate probability delta mismatch")
    outer, frontend = _cost(record["phase_cost"]), _cost(record["frontend_cost"])
    _check(all(outer[k] >= frontend[k]+timed[k] for k in timed), "latency outer cost omits disjoint frontend/timed work")
    return dict(passed=True, model_forwards=50, timed_forward_calls=40, phase_cost_once=outer,
        frontend_and_timed_nested_not_added=True, warmup_or_validation_clocks_not_independently_reexecuted=True)


def _auxiliary(rows, record, raw, target, arm, audit_aux, audit_graph=None):
    _check(record["exact_probabilities_equal_raw"] is True and record["used_for_training_or_selection"] is False
           and record["model_execution_parameter_sha256"] == raw["model_execution_parameter_sha256"], "auxiliary scorer model/scope changed")
    observations = record["observations"]
    _check(len(observations) == 8 and [p for o in observations for p in o["probabilities"]] == raw["probabilities"],
           "all auxiliary observations must exactly reproduce all raw predictions")
    costs = dict(cpu_ns=0, wall_ns=0); reports = []
    for batch, o in enumerate(observations):
        indices = list(range(16*batch, 16*(batch+1)))
        _check(o["indices"] == indices and o["case_ids"] == [_id(rows[i]) for i in indices]
               and o["depth"] == 3 and o["graph_depth"] == 2 and o["graph_reset"] is arm.endswith("_reset")
               and o["physical_forward_calls"] == 1 and o["candidate_observations"] == 16
               and o["labels_or_annotations_entered_forward"] is False, "complete frozen batch16 auxiliary boundary changed")
        _check(len(o["logits"]) == 16 and all(len(z) == 2 and all(type(v) in (int, float) and math.isfinite(v) for v in z) for z in o["logits"]),
               "complete auxiliary class logits required")
        for logits, p in zip(o["logits"], o["probabilities"]):
            expected = 1/(1+math.exp(max(-700., min(700., logits[0]-logits[1]))))
            same(p, expected, "saved auxiliary class probability mismatch", tolerance=2e-6)
        replay = audit_aux(o, target, indices, full=True)
        if audit_graph is not None:
            replay = dict(replay, graph_walk=audit_graph(o, target, indices))
        reports.append(replay)
        for k, v in _cost(o).items(): costs[k] += v
    return dict(passed=True, physical_forwards=8, candidate_observations=128, costs=costs,
        full_auxiliary_replay=reports, annotation_did_not_change_saved_predictions=True)


def review_fresh(run, design, parts, models, load, bind, *, audit_aux=None, audit_graph=None):
    """Called by the parent after source/weights and membership have been audited."""
    if audit_aux is None:
        from grounding_review import audit_auxiliary
        audit_aux = audit_auxiliary
    if audit_graph is None:
        from grounding_review import audit_graph_trace
        audit_graph = audit_graph_trace
    run = Path(run)
    frozen, start, encoder, raw, target_start, target_end, complete = [load(run/n) for n in (
        "all-models-frozen.json", "evaluation-start.json", "fresh-encoder.json", "raw-predictions-complete.json",
        "diagnostic-annotations-start.json", "diagnostic-annotations-complete.json", "evaluation-completion.json")]
    report = chronology(frozen, start, encoder, raw, target_start, target_end, complete, models)
    digest = lambda p: sha256(Path(bind(p)).read_bytes()).hexdigest()
    _check(start["frozen_sha256"] == digest(run/"all-models-frozen.json")
           and target_start["raw_predictions_complete_sha256"] == digest(run/"raw-predictions-complete.json")
           and target_end["targets_sha256"] == digest(run/"frozen-diagnostic-targets.json"), "phase byte bindings changed")
    _check(frozen["runtime_source_sha256"] == complete["runtime_source_sha256"] == design["runtime_source_sha256"], "frozen fresh source changed")
    expected = {f"seed-{s}/{a}/fresh/{r}.json" for s in SEEDS for a in ARMS for r in ROLES}
    _check(set(raw["panels_sha256"]) == expected, "all twenty-four raw prediction panels required before annotations")
    for name, wanted in {**frozen["manifests"], **raw["panels_sha256"]}.items():
        _check(digest(run/name) == wanted, "frozen model/raw prediction file changed")
    _check(set(encoder["cache_files_sha256"]) == {"metadata.json", "tokens.pt"}, "complete bounded new feature cache required")
    for name, wanted in encoder["cache_files_sha256"].items():
        _check(Path(name).name == name and digest(run/"evaluation-features"/name) == wanted, "new feature cache bytes changed")
    tokens = load(run/"evaluation-features/metadata.json")["tokens"]
    targets = load(run/"frozen-diagnostic-targets.json")
    _check(set(targets) == set(ROLES) and encoder["encoding_after_all_models_frozen"] is True
           and encoder["prior_cache_generation_cost_not_additive"] is True, "post-freeze annotation/cache scope changed")
    span_reports = {r: audit_span_targets(parts[r], targets[r], tokens, role="frozen_diagnostic") for r in ROLES}
    metrics, reports = {}, []; costs = dict(cpu_ns=0, wall_ns=0)
    for seed in SEEDS:
        metrics[str(seed)] = {}
        for arm in ARMS:
            model, folder = models[(seed, arm)], run/f"seed-{seed}"/arm
            metrics[str(seed)][arm] = {}; checked = {}
            for role in ROLES:
                rows = _rows(parts[role]); panel = load(folder/f"fresh/{role}.json")
                checked[role] = _panel(rows, panel, model, raw=True)
                metrics[str(seed)][arm][role] = checked[role]["metrics"]
                aux = load(folder/f"fresh/{role}-auxiliary.json")
                checked[role]["auxiliary"] = _auxiliary(rows, aux, panel, targets[role], arm, audit_aux, audit_graph)
                for k in costs: costs[k] += checked[role]["costs"][k]+checked[role]["auxiliary"]["costs"][k]
                if arm == "grounded_chain":
                    diagnostics = {}
                    for kind in DIAGNOSTICS:
                        d = load(folder/f"diagnostics/{role}-{kind}.json")
                        _check(d["transform"] == kind and d["used_for_training_or_selection"] is False
                               and d["labels_unchanged"] is True, "predeclared diagnostic identity/scope changed")
                        value = _panel(rows, d, model)
                        same(d["mean_absolute_probability_delta"], sum(abs(a-b) for a, b in zip(d["probabilities"], panel["probabilities"]))/128,
                             "diagnostic probability delta mismatch")
                        if kind == "support_deleted":
                            audit_support_transform(d["support_transform"], rows)
                            shim = dict(d, depth=3, reset=False, deleted_support_only=True, all_evidence_deleted=False,
                                used_for_gate_or_selection=False, labels_entered_model=False,
                                support_transform_sha256=d["support_transform"]["transform_sha256"])
                            audit_deleted_panel(rows, shim, model, d["support_transform"], tokens)
                            value["annotation_assisted_diagnostic_not_label_blind"] = True
                        diagnostics[kind] = value
                        for k in costs: costs[k] += value["costs"][k]
                    checked[role]["diagnostics"] = diagnostics
            latency = audit_latency(load(folder/"cached-latency.json"), _rows(parts["reader_train"]), model)
            for k in costs: costs[k] += latency["phase_cost_once"][k]
            reports.append(dict(seed=seed, arm=arm, panels=checked, latency=latency))
    gates = {}
    for arm in ARMS:
        per_seed = {str(s): seed_gate(metrics[str(s)][arm]) for s in SEEDS}
        gates[arm] = dict(primary_all_passed=all(g["passed"] for g in per_seed.values()), gates=per_seed,
            every_seed_and_both_panels_required=True, selection_authorized=False, automatic_downstream_authorized=False)
    _check(complete["gates"] == gates and complete["primary_all_passed"] is gates["grounded_chain"]["primary_all_passed"],
           "fresh qualification differs from independently scored probabilities")
    _check(set(complete["metrics"]) == set(map(str, SEEDS)) and all(set(m) == set(ARMS)
           and all(set(v) == set(ROLES) for v in m.values()) for m in complete["metrics"].values()),
           "exact twelve models/two complete metric panels required")
    for seed in map(str, SEEDS):
        for arm in ARMS:
            for role in ROLES:
                audit_scores(parts[role], load(run/f"seed-{seed}/{arm}/fresh/{role}.json")["probabilities"], complete["metrics"][seed][arm][role])
    _check(complete["raw_prediction_candidate_observations"] == complete["auxiliary_trace_candidate_observations"] == 3072
           and complete["intervention_candidate_observations"] == 3840 and complete["cached_latency_model_forwards"] == 600
           and complete["new_teacher_forward_calls"] == 0 and complete["fresh_used_for_selection"] is False
           and complete["feedback_executed"] is False and complete["original_V5_fresh_opened"] is False
           and complete["official_validation_read"] is False and complete["production_authorized"] is False
           and complete["NDU_benefit_established"] is False, "fresh work/scope totals changed")
    for key in ("new_encoder_forward_batches", "new_encoded_sequences"):
        _check(type(complete[key]) is int and complete[key] >= 0, "finite nonnegative new encoding counts required")
    _check(complete["new_encoder_forward_batches"] == encoder["new_forward_batches"]
           and complete["new_encoded_sequences"] == encoder["new_encoded_sequences"], "encoding counts disagree")
    for key in costs:
        value = encoder["incremental_register_"+key]
        _check(type(value) is int and value >= 0, "nonnegative incremental register cost required")
        costs[key] += value
    outer = _cost(complete["phase_cost"])
    _check(all(outer[k] >= costs[k] for k in costs), "evaluation outer cost omits disjoint physical work")
    return dict(fresh_audited=True, chronology=report, span_targets=span_reports, models=reports,
        qualification=gates, primary_all_passed=gates["grounded_chain"]["primary_all_passed"],
        raw_candidate_observations=3072, extra_auxiliary_candidate_observations=3072,
        intervention_candidate_observations=3840, latency_model_forwards=600,
        evaluation_cost=dict(outer_phase_once=outer, disjoint_nested_lower_bound_not_added=costs),
        independent_neural_execution=False, no_oracle_inference_established_by_frozen_source_and_recorded_boundary=True,
        actual_tensor_forward_or_clock_authenticity_independently_reexecuted=False,
        original_V5_reserved_scored=False, official_validation_read=False)

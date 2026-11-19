"""One frozen-family V9 evaluation, public interventions and cached CPU latency."""
import copy
import json
import statistics
import time

import torch
from torch import nn

from binding_campaign_utils import binding_panel
from binding_protocol import score_binding_probabilities
from endpoint_campaign_utils import SupportDeletedBank, support_transform
from endpoint_reader import public_value_permutation
from grounding_campaign_utils import (ARMS, SEEDS, checked_design, frozen_selections, load_bank,
    load_model, phase_cost, source_inventory, typed_digest, write)
from grounding_protocol import build_grounding_protocol, grounding_campaign_gate
from grounding_spans import grounding_from_bank
from grounding_training import auxiliary_panel
from group_encoder import file_digest
from token_campaign_utils import infer


DIAGNOSTICS = ("graph_one", "graph_reset", "reverse_facts", "support_deleted", "broken_payload")


class DiagnosticReader(nn.Module):
    """Apply a frozen, named public-input/state intervention; never select weights."""
    def __init__(self, model, kind):
        super().__init__()
        if kind not in DIAGNOSTICS:
            raise ValueError("registered V9 diagnostic required")
        self.model, self.kind, self.max_hops = model, kind, model.max_hops

    def forward(self, facts, question, candidate, fact_mask, question_mask, candidate_mask,
                *, steps=3, reset_state=False):
        kwargs = {}
        if self.kind == "graph_one":
            kwargs["graph_depth"] = 1
        elif self.kind == "graph_reset":
            kwargs["graph_reset"] = True
        elif self.kind == "reverse_facts":
            facts, fact_mask = facts.flip(1), fact_mask.flip(1)
        elif self.kind == "broken_payload":
            kwargs["value_permutation"] = public_value_permutation(facts, fact_mask)
        return self.model(facts, question, candidate, fact_mask, question_mask, candidate_mask,
                          steps=steps, reset_state=reset_state, **kwargs)


def benchmark(model, cases, bank):
    """Time a cached Head forward separately from public batch construction."""
    if len(cases) < 2 or cases[0].facts != cases[1].facts:
        raise ValueError("two preregistered candidates over identical public facts required")
    started = time.perf_counter_ns(), time.process_time_ns()
    frontend = time.perf_counter_ns(), time.process_time_ns()
    single, paired = bank.batch(cases[:1]), bank.batch(cases[:2])
    frontend_cost = phase_cost(frontend)
    frontend_cost["includes"] = "cache_lookup_and_padding_for_batch1_and_batch2"
    result = {}
    with torch.no_grad():
        for name, batch in (("batch1", single), ("batch2", paired)):
            features = batch.features()
            for _ in range(3):
                model(*features, steps=3)
            rows = []
            for _ in range(20):
                wall, cpu = time.perf_counter_ns(), time.process_time_ns()
                model(*features, steps=3)
                rows.append(dict(cpu_ns=time.process_time_ns()-cpu, wall_ns=time.perf_counter_ns()-wall))
            trace = model(*features, steps=3, return_attention=True)
            summary = {kind: dict(median_ns=statistics.median(r[kind] for r in rows),
                p95_ns=statistics.quantiles([r[kind] for r in rows], n=20, method="inclusive")[18])
                for kind in ("cpu_ns", "wall_ns")}
            result[name] = dict(raw_measurements=rows, summary=summary,
                candidate_count=len(batch.targets), trace_group_work=trace["graph_grouped_counts"],
                probabilities=trace["logits"].softmax(-1)[:, 1].tolist())
        singles = torch.cat([model(*bank.batch([case]).features(), steps=3).softmax(-1)[:, 1] for case in cases[:2]])
    return dict(schema="hepta.grounding.cached-latency.v9", results=result,
        separate_probabilities=singles.tolist(),
        batch_vs_separate_max_probability_delta=max(abs(a-b) for a, b in zip(singles.tolist(), result["batch2"]["probabilities"])),
        case_ids=[c.case_id for c in cases[:2]], warmup_forwards_per_geometry=3,
        timed_forwards_per_geometry=20, extra_trace_forwards=2, separate_validation_forwards=2,
        total_model_forwards=50, timed_scope="forward_only_cached_features_including_graph_public_dedup",
        frontend_cost=frontend_cost, phase_cost=phase_cost(started), encoder_included_in_timed_scope=False,
        thread_count=torch.get_num_threads(), device="cpu", dtype="torch.float32",
        legacy_depth=3, graph_depth=2, model_execution_parameter_sha256=typed_digest(model),
        warmup_and_validation_included_in_complete_evaluation_process=True,
        end_to_end_product_latency=False, same_parameters_implies_equal_cost=False)


def evaluate(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    design, parts, _, augmentation = checked_design(args)
    frozen = frozen_selections(args, design)
    fresh = build_grounding_protocol(parts, augmentation)
    saved = json.loads((args.output/"all-cases.json").read_text())
    from dataclasses import asdict
    if any(saved[role] != json.loads(json.dumps([asdict(c) for c in cases])) for role, cases in fresh.items()):
        raise ValueError("new-domain cases differ from the pre-observation membership")
    # Every model, source, case and prepared artifact is checked before this marker.
    with (args.output/"evaluation-start.json").open("x") as f:
        json.dump(dict(started_ns=time.time_ns(), frozen_sha256=file_digest(args.output/"all-models-frozen.json"),
            retries_authorized=False, original_V5_fresh_opened=False), f)
    bank = load_bank(args)
    before = bank.forward_batches, bank.encoded_sequences, bank.cpu_ns, bank.wall_ns
    encoding_started_ns = time.time_ns()
    bank.register(tuple(c for cases in fresh.values() for c in cases))
    encoding_completed_ns = time.time_ns()
    after = bank.forward_batches, bank.encoded_sequences, bank.cpu_ns, bank.wall_ns
    # Persist only the bounded new-domain subset as a local intermediate cache.
    subset = copy.copy(bank)
    texts = {t for cases in fresh.values() for c in cases for t in (*c.facts, c.question, c.candidate)}
    subset.tokens = {t: bank.tokens[t] for t in texts}
    subset.values = {t: bank.values[t] for t in texts}
    subset.bindings = {c.case_id: bank.bindings[c.case_id] for cases in fresh.values() for c in cases}
    subset.save_local(args.output/"evaluation-features")
    write(args.output, "fresh-encoder.json", dict(new_forward_batches=after[0]-before[0],
        encoding_started_ns=encoding_started_ns, encoding_completed_ns=encoding_completed_ns,
        new_encoded_sequences=after[1]-before[1], incremental_register_cpu_ns=after[2]-before[2],
        incremental_register_wall_ns=after[3]-before[3], full_bank_report=bank.report(),
        prior_cache_generation_cost_not_additive=True, encoding_after_all_models_frozen=True,
        cache_files_sha256={p.name: file_digest(p) for p in (args.output/"evaluation-features").iterdir()}))
    metrics, panels = {}, {}
    for seed in SEEDS:
        metrics[str(seed)] = {}
        for arm in ARMS:
            folder = args.output/f"seed-{seed}"/arm
            model, _ = load_model(folder)
            metrics[str(seed)][arm] = {}
            for role, cases in fresh.items():
                name = "fresh/"+role
                metrics[str(seed)][arm][role] = binding_panel(folder, name, model, cases, bank)
                path = folder/(name+".json")
                panels[str(path.relative_to(args.output))] = file_digest(path)
    write(args.output, "raw-predictions-complete.json", dict(completed_ns=time.time_ns(),
        panels_sha256=panels, actual_candidate_observations=12*256,
        diagnostic_annotations_constructed=False, selected_models_changed=False))
    # Labels/spans are scorer-only and constructed after every raw answer is saved.
    with (args.output/"diagnostic-annotations-start.json").open("x") as f:
        json.dump(dict(started_ns=time.time_ns(),
            raw_predictions_complete_sha256=file_digest(args.output/"raw-predictions-complete.json")), f)
    targets = {role: grounding_from_bank(cases, bank, role="frozen_diagnostic") for role, cases in fresh.items()}
    write(args.output, "frozen-diagnostic-targets.json", targets)
    write(args.output, "diagnostic-annotations-complete.json", dict(completed_ns=time.time_ns(),
        targets_sha256=file_digest(args.output/"frozen-diagnostic-targets.json")))
    auxiliary_observations = 0
    for seed in SEEDS:
        for arm in ARMS:
            folder = args.output/f"seed-{seed}"/arm
            model, record = load_model(folder)
            for role, cases in fresh.items():
                auxiliary = auxiliary_panel(model, cases, bank, targets[role])
                observations, probabilities = auxiliary["observations"], auxiliary["probabilities"]
                auxiliary_observations += len(probabilities)
                raw = json.loads((folder/f"fresh/{role}.json").read_text())
                if probabilities != raw["probabilities"]:
                    raise ValueError("scoring-only annotations changed a frozen raw prediction")
                write(folder, f"fresh/{role}-auxiliary.json", dict(observations=observations,
                    exact_probabilities_equal_raw=True, used_for_training_or_selection=False,
                    model_execution_parameter_sha256=record["execution_parameter_sha256"]))
            write(folder, "cached-latency.json", benchmark(model, parts["reader_train"], bank))
            if arm != "grounded_chain":
                continue
            for role, cases in fresh.items():
                transform = support_transform(cases)
                for kind in DIAGNOSTICS:
                    wrapper = DiagnosticReader(model, kind).eval().requires_grad_(False)
                    selected_bank = SupportDeletedBank(bank, transform) if kind == "support_deleted" else bank
                    probabilities, batches = infer(wrapper, cases, selected_bank, depth=3, batch_size=16,
                        prefix=f"{role}/{kind}")
                    raw = json.loads((folder/f"fresh/{role}.json").read_text())
                    value = dict(case_ids=[c.case_id for c in cases], probabilities=probabilities,
                        metrics=score_binding_probabilities(cases, probabilities), batches=batches, transform=kind,
                        model_execution_parameter_sha256=record["execution_parameter_sha256"],
                        mean_absolute_probability_delta=sum(abs(a-b) for a, b in zip(probabilities, raw["probabilities"]))/len(cases),
                        used_for_training_or_selection=False, labels_unchanged=True)
                    if kind == "support_deleted":
                        value.update(support_transform=transform, transform_observations=selected_bank.observations,
                            missing_evidence_can_make_task_unanswerable=True)
                    write(folder, f"diagnostics/{role}-{kind}.json", value)
    if source_inventory() != design["runtime_source_sha256"] or frozen_selections(args, design) != frozen:
        raise ValueError("runtime or frozen weights changed during evaluation")
    gates = {arm: grounding_campaign_gate({str(seed): metrics[str(seed)][arm] for seed in SEEDS}) for arm in ARMS}
    write(args.output, "evaluation-completion.json", dict(completed_ns=time.time_ns(), metrics=metrics, gates=gates,
        primary_all_passed=gates["grounded_chain"]["primary_all_passed"], runtime_source_sha256=source_inventory(),
        raw_prediction_candidate_observations=3072, auxiliary_trace_candidate_observations=auxiliary_observations,
        intervention_candidate_observations=3*256*len(DIAGNOSTICS), cached_latency_model_forwards=12*50,
        new_encoder_forward_batches=after[0]-before[0], new_encoded_sequences=after[1]-before[1],
        new_teacher_forward_calls=0, phase_cost=phase_cost(started), fresh_used_for_selection=False,
        feedback_executed=False, original_V5_fresh_opened=False, official_validation_read=False,
        production_authorized=False, NDU_benefit_established=False))


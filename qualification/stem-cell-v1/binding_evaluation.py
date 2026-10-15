"""One frozen V5 generated holdout; physical batches and public revision traces."""
import json
import random
import time

from binding_campaign_utils import (SEEDS, binding_panel, checked_design, load_bank,
    load_model, load_verifier, phase_cost, source_inventory, write)
from binding_protocol import score_binding_probabilities
from group_encoder import digest_json, file_digest
from revision_execution import execute_revision
from token_campaign_utils import model_inputs

CORE_MODELS = ("warmup", "natural_only", "replay", "contrastive")
REVISION_MODES = ("real", "zero", "shuffle", "reset", "late_fusion", "verifier_only",
                  "cheap_fixed1", "cheap_verifier")
FRESH = ("fresh_combinations", "fresh_vocabulary")


def public_permutation(case_ids, seed):
    """A public-ID derangement; it never reads targets or probabilities."""
    if len(case_ids) < 2:
        raise ValueError("shuffle requires at least two public cases")
    rng = random.Random(digest_json(dict(case_ids=list(case_ids), seed=seed, version="v5-feedback-shuffle")))
    indices = list(range(len(case_ids)))
    for _ in range(10000):
        rng.shuffle(indices)
        if all(index != value for index, value in enumerate(indices)):
            return indices
    raise ValueError("bounded public derangement construction failed")


def _transitions(cases, initial, predictions):
    if len(initial) != len(cases) or len(predictions) != len(cases):
        raise ValueError("aligned initial and final decisions required")
    wrong = sum(p != c.label for p, c in zip(initial, cases))
    corrected = sum(a != c.label and b == c.label for a, b, c in zip(initial, predictions, cases))
    damaged = sum(a == c.label and b != c.label for a, b, c in zip(initial, predictions, cases))
    return dict(initial_wrong=wrong, initial_correct=len(cases) - wrong,
        corrected=corrected, damaged=damaged, net_corrected=corrected - damaged,
        wrong_to_correct_rate=corrected / wrong if wrong else None,
        initially_correct_retained_rate=(len(cases) - wrong - damaged) / (len(cases) - wrong)
            if len(cases) != wrong else None)


def revision_panel(root, prefix, model, verifier, provenance, cases, bank, mode, seed):
    probabilities, predictions, initial, physical = [], [], [], []
    for start in range(0, len(cases), 16):
        selected = cases[start:start + 16]
        ids = [c.case_id for c in selected]
        prep = time.perf_counter_ns(), time.process_time_ns()
        batch = bank.batch(selected)
        permutation = public_permutation(ids, seed) if mode == "shuffle" else None
        prep_cost = dict(cpu_ns=time.process_time_ns() - prep[1], wall_ns=time.perf_counter_ns() - prep[0])
        result = execute_revision(model_inputs(batch), model, verifier, mode=mode,
            verifier_provenance=provenance, case_ids=ids, source_sha256s=[c.source_hash for c in selected],
            shuffle_indices=permutation)
        p = [row[1] for row in result["probabilities"]]
        if result["predictions"] != [int(value > .5) for value in p]:
            raise ValueError("saved probabilities differ from the common prediction rule")
        probabilities.extend(p)
        predictions.extend(result["predictions"])
        if result["initial_proposals"]:
            initial.extend(row["prediction"] for row in result["initial_proposals"])
        record = dict(batch_id=f"{prefix}/{start // 16}", case_ids=ids,
            feature_preparation=prep_cost, shuffle_indices=permutation, execution=result)
        physical.append(record)
    metrics = score_binding_probabilities(cases, probabilities)
    costs = dict(cpu_ns=sum(row["feature_preparation"]["cpu_ns"] + row["execution"]["cost"]["cpu_ns"] for row in physical),
        wall_ns=sum(row["feature_preparation"]["wall_ns"] + row["execution"]["cost"]["wall_ns"] for row in physical),
        scope="physical_batch_public_feature_and_control_preparation_plus_execution_once", batch_count=len(physical),
        callback_costs_are_nested=True, formula_flops=None, individually_measured_case_latency=False)
    result = dict(metrics=metrics, probabilities=probabilities, predictions=predictions,
        initial_predictions=initial, case_ids=[c.case_id for c in cases], physical_batches=physical,
        transitions=_transitions(cases, initial, predictions) if initial else None,
        costs=costs, mode=mode, labels_entered_model=False,
        reader_model_sha256=physical[0]["execution"]["reader_model_sha256"],
        verifier_model_sha256=physical[0]["execution"]["verifier_model_sha256"])
    write(root, prefix + ".json", result)
    return dict(metrics=metrics, transitions=result["transitions"], costs=costs)


def evaluate(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    design, parts, natural = checked_design(args)
    frozen_path = args.output / "all-models-frozen.json"
    frozen = json.loads(frozen_path.read_text())
    retained = json.loads((args.output / "continuation-completion.json").read_text())
    warmups = json.loads((args.output / "warmup-completion.json").read_text())
    if (not warmups["all_passed"] or not retained["contrastive_all_passed"]
            or frozen["runtime_source_sha256"] != source_inventory()):
        raise ValueError("full learning/retention/frozen-source gate closed")
    start_record = dict(schema="hepta.binding.fresh-evaluation-start.v1", started_ns=time.time_ns(),
        all_models_frozen_ns=frozen["frozen_ns"], all_models_frozen_sha256=file_digest(frozen_path),
        model_manifests=frozen["manifests"], fresh_roles=list(FRESH), model_selection_authorized=False,
        original_v4_official_final_used=False)
    if not start_record["all_models_frozen_ns"] < start_record["started_ns"]:
        raise ValueError("models must freeze before the first fresh evaluation")
    with (args.output / "evaluation-start.json").open("x") as stream:
        json.dump(start_record, stream, sort_keys=True, indent=2)
    for seed in SEEDS:
        for name, expected in frozen["manifests"][str(seed)].items():
            if file_digest(args.output / f"seed-{seed}" / (name + "-model.json")) != expected:
                raise ValueError("a selected model manifest changed after freezing")
    for name, expected in frozen["gate_evidence_sha256"].items():
        if file_digest(args.output / name) != expected:
            raise ValueError("learning gate evidence changed after freezing")
    bank = load_bank(args)
    before = dict(cpu_ns=bank.cpu_ns, wall_ns=bank.wall_ns, batches=bank.forward_batches,
                  sequences=bank.encoded_sequences)
    for role in FRESH:
        bank.register(parts[role])
    write(args.output, "fresh-encoder.json", dict(report=bank.report(),
        incremental_encoding={k: getattr(bank, attr) - before[k] for k, attr in (
            ("cpu_ns", "cpu_ns"), ("wall_ns", "wall_ns"), ("batches", "forward_batches"),
            ("sequences", "encoded_sequences"))}, old_origin_generation_cost_is_not_additive=True))
    summaries = {}
    for seed in SEEDS:
        folder = args.output / f"seed-{seed}"
        output = folder / "fresh"
        output.mkdir(exist_ok=False)
        seed_results = {}
        for name in CORE_MODELS:
            model, _ = load_model(folder, name)
            for role in FRESH:
                for control, kwargs in (("full3", {}), ("deleted3", dict(deleted=True)),
                                        ("full1", dict(depth=1)), ("reset3", dict(reset=True))):
                    prefix = f"{role}/{name}/{control}"
                    seed_results[prefix] = binding_panel(output, prefix, model, parts[role], bank, **kwargs)
        verifier, provenance = load_verifier(args, seed, natural["train"], parts["reader_train"])
        for trained_arm in ("real", "zero"):
            model, _ = load_model(folder, "revision-" + trained_arm)
            for role in FRESH:
                for mode in REVISION_MODES:
                    prefix = f"{role}/revision-{trained_arm}/{mode}"
                    seed_results[prefix] = revision_panel(output, prefix, model, verifier, provenance,
                                                         parts[role], bank, mode, seed)
        summaries[str(seed)] = seed_results
        print(json.dumps(dict(seed=seed, phase="fresh", panels=len(seed_results))), flush=True)
    if source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("runtime changed during fresh evaluation")
    write(args.output, "completion.json", dict(schema="hepta.binding.fresh-completion.v5",
        completed_ns=time.time_ns(), phase_cost=phase_cost(started), summaries=summaries,
        runtime_source_sha256=source_inventory(), model_freeze_sha256=file_digest(frozen_path),
        repeated_seeds_are_independent_examples=False, official_validation_used=False,
        all_source_and_prediction_records_retained=True, equal_actual_compute=False,
        production_authorized=False, hosted_ci_consulted=False))

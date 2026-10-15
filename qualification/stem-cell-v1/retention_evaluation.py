"""V7 fresh scoring opens only after all joint and actual feedback gates pass."""
import json
import time

from binding_campaign_utils import binding_panel
from binding_evaluation import FRESH, REVISION_MODES, revision_panel
from retention_campaign_utils import (ARMS, SEEDS, checked_design, load_bank, load_model,
    load_verifier, phase_cost, selected_models, source_inventory, write)
from group_encoder import file_digest


def preflight(args, natural):
    """Validate exact models, transitive bytes and gates before creating a fresh marker."""
    for name in ("training-completion.json", "feedback-completion.json"):
        if not json.loads((args.output / name).read_text())["primary_all_passed"]:
            raise ValueError("all V7 joint gates must pass before held-out scoring")
    frozen = json.loads((args.output / "all-models-frozen.json").read_text())
    if frozen["runtime_source_sha256"] != source_inventory() or set(frozen["manifests"]) != set(selected_models()):
        raise ValueError("exact frozen V7 model family and runtime required")
    for name, expected in {**frozen["manifests"], **frozen["gate_evidence_sha256"]}.items():
        if file_digest(args.output / name) != expected:
            raise ValueError("selected model or qualification evidence changed")
    for path, name in selected_models().items():
        load_model((args.output / path).parent, name, expected_arm="bridge")
    for seed in SEEDS:
        load_model(args.previous_v6 / f"seed-{seed}" / "bridge", "warmup", expected_arm="bridge")
        load_verifier(args, seed, natural, ())
    if frozen["frozen_ns"] >= time.time_ns():
        raise ValueError("all models must freeze before fresh encoding")
    return frozen


def evaluate(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    design, parts, natural, augmentation = checked_design(args)
    frozen = preflight(args, (*natural["train"], *parts["reader_train"], *augmentation))
    with (args.output / "evaluation-start.json").open("x") as stream:
        json.dump(dict(started_ns=time.time_ns(), frozen_ns=frozen["frozen_ns"],
            all_models_frozen_sha256=file_digest(args.output / "all-models-frozen.json"),
            fresh_selection_authorized=False), stream)
    bank = load_bank(args)
    before = dict(cpu_ns=bank.cpu_ns, wall_ns=bank.wall_ns,
                  batches=bank.forward_batches, sequences=bank.encoded_sequences)
    for role in FRESH:
        bank.register(parts[role])
    write(args.output, "fresh-encoder.json", dict(report=bank.report(),
        incremental_encoding={k: getattr(bank, attr)-before[k] for k, attr in (
            ("cpu_ns", "cpu_ns"), ("wall_ns", "wall_ns"),
            ("batches", "forward_batches"), ("sequences", "encoded_sequences"))},
        historical_cache_generation_not_additive=True))
    results = {}
    for seed in SEEDS:
        folder = args.output / f"seed-{seed}"
        models = {arm: load_model(folder, arm, expected_arm="bridge")[0] for arm in ARMS}
        models["historical-warmup"] = load_model(
            args.previous_v6 / f"seed-{seed}" / "bridge", "warmup", expected_arm="bridge")[0]
        summaries = {}
        for name, model in models.items():
            for role in FRESH:
                for control, kwargs in (("full3", {}), ("deleted3", dict(deleted=True)),
                                        ("full1", dict(depth=1)), ("reset3", dict(reset=True))):
                    key = f"{role}/{name}/{control}"
                    summaries[key] = binding_panel(folder / "fresh", key, model, parts[role], bank, **kwargs)
        verifier, provenance = load_verifier(args, seed, natural["train"], (*parts["reader_train"], *augmentation))
        for arm in ("real", "zero"):
            model, _ = load_model(folder, "revision-"+arm, expected_arm="bridge")
            for role in FRESH:
                for mode in REVISION_MODES:
                    key = f"{role}/revision-{arm}/{mode}"
                    summaries[key] = revision_panel(folder / "fresh", key, model, verifier,
                        provenance, parts[role], bank, mode, seed)
        results[str(seed)] = summaries
        print(json.dumps(dict(seed=seed, phase="fresh", panels=len(summaries))), flush=True)
    if source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("runtime changed during fresh scoring")
    write(args.output, "completion.json", dict(schema="hepta.retention.fresh.v7", summaries=results,
        completed_ns=time.time_ns(), phase_cost=phase_cost(started),
        runtime_source_sha256=source_inventory(), repeated_seeds_are_new_examples=False,
        official_validation_read=False, longer_chains_evaluated=False, multimodal_evaluated=False,
        NDU_causal_gain_established=False, production_authorized=False))

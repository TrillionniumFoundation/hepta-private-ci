"""Once-only V6 holdout: separate warmup, continuation and revision comparisons."""
import json
import time

from binding_campaign_utils import binding_panel, load_model as load_v5_model, natural_panel
from binding_evaluation import FRESH, REVISION_MODES, revision_panel
from bridge_campaign_utils import (SEEDS, checked_design, load_bank, load_model,
    load_verifier, phase_cost, selected_model_paths, source_inventory, write)
from group_encoder import file_digest


def evaluate(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    design, parts, natural = checked_design(args)
    warmups = json.loads((args.output / "warmup-completion.json").read_text())
    retention = json.loads((args.output / "continuation-completion.json").read_text())
    frozen_path = args.output / "all-models-frozen.json"
    frozen = json.loads(frozen_path.read_text())
    if (not warmups["primary_all_passed"] or not retention["contrastive_all_passed"]
            or frozen["runtime_source_sha256"] != source_inventory()):
        raise ValueError("primary fit, retention or source-freeze gate closed")
    expected_models = selected_model_paths()
    if set(frozen["manifests"]) != set(expected_models):
        raise ValueError("all six warmups, nine continuations and six revision models must freeze")
    for name, expected in {**frozen["manifests"], **frozen["gate_evidence_sha256"]}.items():
        if file_digest(args.output / name) != expected:
            raise ValueError("selected model or gate evidence changed")
    # Validate transitive artifact bytes before opening even fresh encoding.
    for name, selection in expected_models.items():
        load_model((args.output / name).parent, selection["name"], expected_arm=selection["arm"])
    for seed in SEEDS:
        load_verifier(args, seed, natural["train"], parts["reader_train"])
    now = time.time_ns()
    if frozen["frozen_ns"] >= now:
        raise ValueError("all models must freeze before fresh encoding or scoring")
    with (args.output / "evaluation-start.json").open("x") as stream:
        json.dump(dict(started_ns=now, frozen_ns=frozen["frozen_ns"],
            all_models_frozen_sha256=file_digest(frozen_path), fresh_selection_authorized=False,
            reused_baselines_bound_by_design=True), stream, sort_keys=True, indent=2)
    bank = load_bank(args)
    before = dict(cpu_ns=bank.cpu_ns, wall_ns=bank.wall_ns,
                  batches=bank.forward_batches, sequences=bank.encoded_sequences)
    for role in FRESH:
        bank.register(parts[role])
    write(args.output, "fresh-encoder.json", dict(report=bank.report(),
        incremental_encoding={k: getattr(bank, attr) - before[k] for k, attr in (
            ("cpu_ns", "cpu_ns"), ("wall_ns", "wall_ns"),
            ("batches", "forward_batches"), ("sequences", "encoded_sequences"))},
        historical_cache_generation_not_additive=True))
    summaries = {}
    for seed in SEEDS:
        root = args.output / f"seed-{seed}"
        output = root / "fresh"
        output.mkdir(exist_ok=False)
        models = {"base-warmup": load_v5_model(args.previous_v5 / f"seed-{seed}", "warmup")[0]}
        models.update({arm + "-warmup": load_model(root / arm, "warmup", expected_arm=arm)[0]
                       for arm in ("bridge", "wide")})
        models.update({"bridge-" + arm: load_model(root / "bridge", arm, expected_arm="bridge")[0]
                       for arm in ("natural_only", "replay", "contrastive")})
        result = {}
        for name, model in models.items():
            for role in FRESH:
                for control, kwargs in (("full3", {}), ("deleted3", dict(deleted=True)),
                                        ("full1", dict(depth=1)), ("reset3", dict(reset=True))):
                    prefix = f"{role}/{name}/{control}"
                    result[prefix] = binding_panel(output, prefix, model, parts[role], bank, **kwargs)
        verifier, provenance = load_verifier(args, seed, natural["train"], parts["reader_train"])
        for arm in ("real", "zero"):
            model, _ = load_model(root / "bridge", "revision-" + arm, expected_arm="bridge")
            for role in FRESH:
                for mode in REVISION_MODES:
                    prefix = f"{role}/revision-{arm}/{mode}"
                    result[prefix] = revision_panel(output, prefix, model, verifier, provenance,
                                                    parts[role], bank, mode, seed)
        summaries[str(seed)] = result
        print(json.dumps(dict(seed=seed, phase="fresh", panels=len(result))), flush=True)
    if source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("runtime changed during evaluation")
    write(args.output, "completion.json", dict(schema="hepta.bridge.fresh-completion.v6",
        completed_ns=time.time_ns(), summaries=summaries, phase_cost=phase_cost(started),
        source_sha256=source_inventory(), all_models_frozen_sha256=file_digest(frozen_path),
        warmup_cross_variant_controls=True, cross_stage_budgets_equal=False,
        wide_natural_transfer_control_available=False, official_validation_scored=False,
        repeated_seeds_are_new_examples=False, hosted_ci_consulted=False, production_authorized=False))

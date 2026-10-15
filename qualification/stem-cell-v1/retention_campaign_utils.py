"""V7 pins V6 inputs and models while using a separate extended training cache."""
import copy
from dataclasses import asdict
import json
import time
from pathlib import Path

from bridge_campaign_utils import (SEEDS, checked_design as checked_v6, load_bank as old_bank,
    load_model, load_verifier, phase_cost, save_model, source_inventory as v6_inventory,
    typed_digest, write)
from group_encoder import file_digest
from retention_data import build_augmentation
from token_features import TokenBank

ARMS = ("repeat", "diverse", "anchored", "low_lr")
ORDER = {41: ARMS, 47: ARMS[1:] + ARMS[:1], 53: ARMS[2:] + ARMS[:2]}
RUNTIME = ("retention_data.py", "retention_v7_training.py", "retention_campaign_utils.py",
           "retention_campaign.py", "retention_evaluation.py", "retention_feedback.py")


def source_inventory():
    code = Path(__file__).parent
    return {**v6_inventory(), **{n: file_digest(code / n) for n in RUNTIME}}


def old_inputs(args):
    previous = copy.copy(args)
    previous.output = args.previous_v6
    design, parts, natural = checked_v6(previous)
    if any((args.previous_v6 / name).exists() for name in ("evaluation-start.json", "completion.json")):
        raise ValueError("the reused V6 fresh domains have already been scored")
    completed = json.loads((args.previous_v6 / "warmup-completion.json").read_text())
    if not completed["primary_all_passed"]:
        raise ValueError("all three V6 bridge warmups must already qualify")
    augmentation, report = build_augmentation(parts)
    return design, parts, natural, augmentation, report


def historical_models(args):
    """Bind actual warmups, including full input bytes and past costs, never retrain."""
    result = {}
    for seed in SEEDS:
        folder = args.previous_v6 / f"seed-{seed}" / "bridge"
        _, manifest = load_model(folder, "warmup", expected_arm="bridge")
        names = ("warmup.pt", "warmup-model.json", "warmup-training.json",
                 "warmup-binding-train.json", "warmup-natural-internal.json", "warmup-gate.json")
        receipt = json.loads((folder / "warmup-training.json").read_text())
        result[str(seed)] = dict(folder=str(folder.resolve()),
            files_sha256={n: file_digest(folder / n) for n in names},
            execution_parameter_sha256=manifest["execution_parameter_sha256"],
            historical_fit_cpu_ns=receipt["cpu_ns"], historical_fit_wall_ns=receipt["wall_ns"],
            newly_trained=False, historical_not_free=True)
    return result


def checked_design(args):
    design = json.loads((args.output / "design.json").read_text())
    _, parts, natural, augmentation, report = old_inputs(args)
    if (source_inventory() != design["runtime_source_sha256"]
            or file_digest(Path(__file__).parent / "RETENTION_V7_PROTOCOL.md") != design["protocol_sha256"]
            or file_digest(args.previous_v6 / "design.json") != design["previous_v6_design_sha256"]
            or file_digest(args.previous_v6 / "warmup-completion.json") != design["previous_v6_warmup_completion_sha256"]
            or report != design["augmentation"]):
        raise ValueError("V7 frozen runtime, previous evidence or augmentation changed")
    actual = {**parts, "augmentation": augmentation}
    saved = json.loads((args.output / "all-cases.json").read_text())
    if saved != {role: [json.loads(json.dumps(asdict(c))) for c in cases] for role, cases in actual.items()}:
        raise ValueError("V7 complete case identities changed")
    for record in design["historical_warmups"].values():
        for name, expected in record["files_sha256"].items():
            if file_digest(Path(record["folder"]) / name) != expected:
                raise ValueError("historical warmup material changed")
    for name, expected in design["extended_cache_files_sha256"].items():
        if file_digest(args.output / "features" / name) != expected:
            raise ValueError("extended training token cache changed")
    return design, parts, natural, augmentation


def load_bank(args):
    bank = TokenBank.from_snapshot(args.snapshot, batch_size=16, chunk_tokens=64)
    bank.restore_local(args.output / "features")
    return bank


def selected_models():
    return {f"seed-{seed}/{name}-model.json": name for seed in SEEDS
            for name in (*ARMS, "revision-real", "revision-zero")}


def freeze_models(args, gates):
    """Bind exact transitive selections before any held-out encoding."""
    expected = selected_models()
    found = {str(p.relative_to(args.output)): file_digest(p)
             for p in args.output.glob("seed-*/*-model.json")}
    if set(found) != set(expected):
        raise ValueError("exact twelve continuations and six revisions must freeze")
    for path, name in expected.items():
        load_model((args.output / path).parent, name, expected_arm="bridge")
    write(args.output, "all-models-frozen.json", dict(manifests=found,
        gate_evidence_sha256={n: file_digest(args.output / n) for n in gates},
        runtime_source_sha256=source_inventory(), fresh_started=False,
        frozen_ns=time.time_ns()))

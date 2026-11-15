"""Freeze V4 source membership, encode nonfinal text and pass a tiny fitting gate."""
import argparse
import json
from pathlib import Path
import time

import torch

from group_encoder import file_digest
from multirc_data import load_jsonl, score_multirc
from reader_campaign import DATA_HASHES
from reader_campaign_utils import gate_cases, write_json
from token_campaign_utils import infer
from token_features import TokenBank
from token_protocol import build_binding_cases, make_partitions, protocol_manifest, score_binding
from token_reader import TokenReader
from token_reader_training import fit_token_reader


def sources(source, previous_design):
    train = load_jsonl(Path(source) / "train.jsonl", "train")
    validation = load_jsonl(Path(source) / "val.jsonl", "validation")
    if (train.sha256, validation.sha256) != (DATA_HASHES["train"], DATA_HASHES["validation"]):
        raise ValueError("pinned official dataset bytes changed")
    prior = json.loads(Path(previous_design).read_text())
    parts = make_partitions(train.cases, validation.cases, prior)
    return parts, protocol_manifest(parts,
        dataset_files_sha256={"train.jsonl": train.sha256, "val.jsonl": validation.sha256},
        previous_design_sha256=file_digest(previous_design))


def prepare(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    parts, design = sources(args.source, args.previous_design)
    design.update(membership_frozen_ns=time.time_ns(), official_validation_used_for_selection=False,
        synthetic_groups=dict(train=32, tune=16, final=32), synthetic_seed=41)
    write_json(root, "membership.json", design)
    bank = TokenBank.from_snapshot(args.snapshot, batch_size=16, chunk_tokens=64)
    for name in ("train", "tune", "verifier_fit", "critic_fit", "critic_calibration"):
        bank.register(parts[name])
        print(json.dumps(dict(encoded=name, cases=len(parts[name]), sequences=bank.encoded_sequences)), flush=True)
    for name in ("train", "tune"):
        bank.register(build_binding_cases(name, groups=design["synthetic_groups"][name], seed=41))
    bank.save_local(root / "features")
    write_json(root, "encoder.json", bank.report())
    write_json(root, "phase-cost.json", dict(cpu_ns=time.process_time_ns() - started[1],
        wall_ns=time.perf_counter_ns() - started[0], includes="load_tokenize_encode_serialize_verify",
        nested_costs_additive=False, hosted_ci_consulted=False))


def gate(args):
    started = time.perf_counter_ns(), time.process_time_ns()
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    parts, _ = sources(args.source, args.previous_design)
    bank = TokenBank.from_snapshot(args.snapshot, batch_size=16, chunk_tokens=64)
    bank.restore_local(args.prepared / "features")
    natural = gate_cases(parts["train"], questions=8)
    synthetic = build_binding_cases("train", groups=32, seed=41)[:16]
    protocol = dict(schema="hepta.token-reader.learnability-gate.v1", seed=41,
        natural_case_ids=[case.case_id for case in natural],
        synthetic_case_ids=[case.case_id for case in synthetic],
        prepared_membership_sha256=file_digest(args.prepared / "membership.json"),
        model_source_sha256={name: file_digest(Path(__file__).parent / name) for name in
                            ("token_reader.py", "token_reader_training.py", "token_features.py")},
        hidden_dim=32, learning_rate=.001, steps=args.steps, depth=3,
        training_recipe="alternating_natural_and_synthetic_minibatches", intervention_probability=.5,
        official_validation_evaluated=False, gate_scope="tiny_train_fit_only")
    write_json(root, "protocol.json", protocol)
    torch.manual_seed(41)
    model, training = fit_token_reader(TokenReader(384, 32), bank.dataset(natural),
        steps=args.steps, seed=41, batch_size=16, max_depth=3, learning_rate=.001,
        counterfactual_train=bank.dataset(synthetic), counterfactual_fraction=.5,
        evidence_weight=.2, diagnostic_interval=args.steps, wall_time_ns=900_000_000_000,
        failure_receipt_fn=lambda receipt: write_json(root, "failed-training.json", receipt))
    write_json(root, "training.json", training)
    natural_p, natural_cost = infer(model, natural, bank, depth=3, prefix="tiny-natural")
    binding_p, binding_cost = infer(model, synthetic, bank, depth=3, prefix="tiny-binding")
    deleted_p, deleted_cost = infer(model, synthetic, bank, depth=3, deleted=True, prefix="tiny-deleted")
    natural_metrics = score_multirc(natural, [int(p > .5) for p in natural_p])
    binding_metrics = score_binding(synthetic, [int(p > .5) for p in binding_p])
    report = dict(natural=natural_metrics, binding=binding_metrics,
        binding_deleted=score_binding(synthetic, [int(p > .5) for p in deleted_p]),
        passed=training["completed_steps"] == args.steps and natural_metrics["accuracy"] >= .95
               and binding_metrics["both_worlds_correct"] >= .95,
        completed_steps=training["completed_steps"], official_validation_evaluated=False,
        generalization_established=False, inference_batches=natural_cost + binding_cost + deleted_cost)
    write_json(root, "report.json", report)
    write_json(root, "encoder.json", bank.report())
    write_json(root, "phase-cost.json", dict(cpu_ns=time.process_time_ns() - started[1],
        wall_ns=time.perf_counter_ns() - started[0], includes="setup_restore_fit_infer_verify",
        nested_costs_additive=False, hosted_ci_consulted=False))
    print(json.dumps({key: value for key, value in report.items() if key != "inference_batches"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "gate"))
    for name in ("source", "snapshot", "previous-design", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--steps", type=int, default=1000)
    args = parser.parse_args()
    torch.set_num_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        (prepare if args.phase == "prepare" else gate)(args)
    except Exception as error:
        if args.output.is_dir():
            write_json(args.output, "failed-phase-cost.json", dict(error_type=type(error).__name__,
                message=str(error), cpu_ns=time.process_time_ns() - cpu,
                wall_ns=time.perf_counter_ns() - wall, completed=False))
        raise


if __name__ == "__main__":
    main()

"""Training trace/reuse contracts using old validation data, never primary labels."""

import argparse
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from unittest import mock

import torch

from ..v6.data import SourceCorpus, make_batch
from ..field_bridge_20261027.run import setup, write_json, digest
from ..field_bridge_20261027.adapters import local_hash
from . import primary_training as training
from .learning import make_model, new_optimizer, optimizer_hash
from .primary_common import load_checkpoint


def check(args):
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    corpus, observers, originals, identities = setup(args)
    seed, original = 17, originals[17]
    recipe = training.P["recipe"]
    initial = make_model(original, seed, recipe)
    initial_opt = new_optimizer(initial, recipe)
    bank = json.loads((Path(args.parent_bank) / "fit-17/BANK.json").read_text())
    for trajectory in range(4):
        rows = training.constant_path(bank, trajectory, seed, recipe,
                                      local_hash(initial), optimizer_hash(initial_opt))
        path = Path(args.parent_bank) / f"fit-17/trajectory-{trajectory}-terminal.pt"
        model, optimizer, _ = load_checkpoint(path, original, seed, recipe)
        assert local_hash(model) == rows[-1]["branches"][trajectory]["model_sha256"]
        assert optimizer_hash(optimizer) == rows[-1]["branches"][trajectory]["optimizer_sha256"]
    rejected = []
    for key, value in (("schedule_sha256", "bad"), ("optimizer_sha256", "bad"), ("trajectory_action", 3)):
        corrupt = deepcopy(bank)
        corrupt["records"][0][key] = value
        try:
            training.constant_path(corrupt, 0, seed, recipe, local_hash(initial), optimizer_hash(initial_opt))
        except ValueError:
            rejected.append(key)
        else:
            raise AssertionError(f"Changed {key} was accepted for endpoint reuse")
    source = corpus.splits["validation"]
    source = replace(source, images=source.images[1400:1408], labels=source.labels[1400:1408],
                     ids=source.ids[1400:1408], pixel_hashes=source.pixel_hashes[1400:1408])
    data = SourceCorpus({"train": source}, corpus.manifest)
    response = [("heavy_noise", make_batch(corpus, "validation", 4, 271027, offset=700, corruption="heavy_noise"))]
    clean = [("clean", make_batch(corpus, "validation", 4, 271027, offset=700, corruption="clean"))]
    mini_recipe = {**recipe, "steps": 16}
    directory = out / "training/17"
    directory.mkdir(parents=True)
    starts, original_train = [], training.train_steps

    def tracked_train(*positional):
        stream = directory / "field-decisions-before-updates.jsonl"
        committed = [json.loads(line) for line in stream.read_text().splitlines()]
        start, count, multiplier = positional[8:11]
        assert len(committed) == len(starts) + 1
        assert committed[-1]["step"] == start and committed[-1]["multiplier"] == multiplier
        assert positional[7] == 0 and count == 8
        starts.append({"step": start, "multiplier": multiplier, "committed_before_update": True})
        return original_train(*positional)

    args.seed = seed
    with mock.patch.object(training, "gradient_corpus", return_value=data), \
            mock.patch.object(training, "panel", side_effect=[response, clean]), \
            mock.patch.object(training, "predict", side_effect=[[1., 0., 0., 0.], [0., 0., 1., 0.]]), \
            mock.patch.object(training, "train_steps", side_effect=tracked_train):
        receipt = training.closed_loop(args, "field", {"contract": "forced zero then unit"}, corpus,
            observers["reward"], original, identities[seed], mini_recipe, 0, {}, out, directory)
    trace = json.loads((directory / "field.json").read_text())
    first, second = trace["records"]
    assert first["after"]["local_sha256"] == first["local_sha256"]
    assert first["after"]["optimizer_sha256"] == first["optimizer_sha256"]
    assert second["after"]["local_sha256"] != second["local_sha256"]
    assert second["after"]["optimizer_sha256"] != second["optimizer_sha256"]
    assert all(row["committed_monotonic_ns"] < row["completed_monotonic_ns"] for row in trace["records"])
    model, optimizer, record = load_checkpoint(out / receipt["checkpoint"], original, seed, mini_recipe)
    assert record["local_sha256"] == second["after"]["local_sha256"]
    assert record["optimizer_sha256"] == second["after"]["optimizer_sha256"]
    assert optimizer.state and all("momentum_buffer" in state for state in optimizer.state.values())
    assert trace["resources"]["gradient_forward_calls"] == 16
    assert trace["resources"]["optimizer_steps"] == 8
    assert trace["resources"]["teacher_forced_field_probe_examples"] == 16
    assert trace["resources"]["hard_value_and_margin_observer_digit_examples"] == 32
    report = {"schema": "hepta.field-bridge.v2.primary-training-contract.1", "status": "pass",
        "source_sha256": digest(Path(training.__file__)), "protocol_sha256": digest(Path(training.__file__).with_name("PRIMARY_PROTOCOL.json")),
        "reused_constant_paths_checked": 4, "complete_sgd_terminal_states_checked": 4,
        "reuse_rejects_changes": rejected, "before_update_commits": starts,
        "zero_block_holds_complete_state": True, "unit_block_changes_both_weights_and_momentum": True,
        "checkpoint_complete_state_readback": True, "common_schedule_id": 0,
        "actual_gradient_calls": 16, "actual_gradient_examples": 1024,
        "existing_validation_source_ids": list(source.ids), "audit_observer_loaded": False,
        "primary_or_retention_outputs_scored": False,
        "scope": "Controller choice is forced only inside this isolated behavioral contract; no training efficacy or policy selection is inferred."}
    write_json(out / "PRIMARY_TRAINING_CONTRACT.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--parent-bank", required=True)
    parser.add_argument("--out", required=True)
    print(json.dumps(check(parser.parse_args()), sort_keys=True))

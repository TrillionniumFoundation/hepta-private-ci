"""Actual short branch contracts on existing validation sources, not efficacy."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest import mock

import numpy as np
import torch

from ..v6.data import SourceCorpus, make_batch
from ..field_bridge_20261027.run import setup, object_hash
from ..field_bridge_20261027.adapters import local_hash, frozen_base_hash
from . import learning
from .field_bank import B, margin_features


def batch_hash(batch):
    digest = hashlib.sha256()
    for value in (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens,
                  batch.target.pixels, batch.target.text_tokens, batch.target.labels):
        digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def check(args):
    root = Path(args.out).resolve()
    if root.is_relative_to(Path(__file__).resolve().parent):
        raise ValueError("Contract artifacts must be outside the source package")
    root.mkdir(parents=True, exist_ok=False)
    corpus, observers, originals, _ = setup(args)
    source = corpus.splits["validation"]
    source = replace(source, images=source.images[1400:1408], labels=source.labels[1400:1408],
                     ids=source.ids[1400:1408], pixel_hashes=source.pixel_hashes[1400:1408])
    data = SourceCorpus({"train": source}, corpus.manifest)
    batch = make_batch(corpus, "validation", 4, 271027, offset=700, corruption="heavy_noise")
    clean = make_batch(corpus, "validation", 4, 271027, offset=700, corruption="clean")
    response, clean_panel = [("heavy_noise", batch)], [("clean", clean)]
    recipe = next(x for x in learning.P["candidates"] if x["name"] == B["selected_recipe"])
    original, observer = originals[17], observers["reward"]
    model = learning.make_model(original, 17, recipe)
    optimizer = learning.new_optimizer(model, recipe)
    learning.update(model, original, optimizer, batch, 0, 1., 111, recipe)
    learning.update(model, original, optimizer, batch, 0, 1., 112, recipe)
    initial_model, initial_optimizer = local_hash(model), learning.optimizer_hash(optimizer)
    frozen = frozen_base_hash(model)
    initial = learning.hard_outputs(model, response, observer, 0)
    state = learning.observe_field(model, optimizer, recipe, response, clean_panel, 0, 0, initial["value"])
    state += margin_features(model, response, observer, 0)
    assert len(state) == 25 and np.isfinite(state).all()
    all_runs, schedules = [], []
    actual_make_batch, actual_update = learning.make_batch, learning.update
    for order in ([0, 1, 2, 3], [3, 2, 1, 0]):
        outcomes = {}
        for index in order:
            branch, branch_optimizer = learning.clone_optimizer_model(model, optimizer, recipe)
            assert local_hash(branch) == initial_model
            assert learning.optimizer_hash(branch_optimizer) == initial_optimizer
            schedule = []

            def tracked_batch(*positional, **keywords):
                observed = actual_make_batch(*positional, **keywords)
                schedule.append({"batch_seed": positional[3], "condition": keywords["corruption"],
                                 "actual_batch_sha256": batch_hash(observed)})
                return observed

            def tracked_update(*positional, **keywords):
                schedule[-1]["noise_seed"] = positional[6]
                return actual_update(*positional, **keywords)

            with mock.patch.object(learning, "make_batch", side_effect=tracked_batch), \
                    mock.patch.object(learning, "update", side_effect=tracked_update):
                learning.train_steps(branch, original, branch_optimizer, data, 0, recipe,
                                     17, 8, 0, B["macro_steps"], B["multipliers"][index])
            assert len(schedule) == B["macro_steps"] == 8
            assert all(row["noise_seed"] == 107 + step for step, row in enumerate(schedule))
            schedules.append(schedule)
            value = learning.hard_outputs(branch, response, observer, 0)
            outcomes[str(index)] = {"local_sha256": local_hash(branch),
                "optimizer_sha256": learning.optimizer_hash(branch_optimizer),
                "hard_outputs_sha256": object_hash(value), "value": value["value"]}
            assert local_hash(model) == initial_model
            assert learning.optimizer_hash(optimizer) == initial_optimizer
            assert frozen_base_hash(branch) == frozen
            if index == 0:
                assert value == initial
                assert outcomes[str(index)]["local_sha256"] == initial_model
                assert outcomes[str(index)]["optimizer_sha256"] == initial_optimizer
            else:
                assert outcomes[str(index)]["local_sha256"] != initial_model
        all_runs.append(outcomes)
    assert all(schedule == schedules[0] for schedule in schedules)
    assert all_runs[0] == all_runs[1]
    assert len({row["local_sha256"] for row in all_runs[0].values()}) == 4
    report = {"schema": "hepta.field-bridge.v2.complete-branch-contract.1", "status": "pass",
        "scope": "Production branch helpers on eight existing validation sources at offset700; one eight-step branch block, two branch orderings; no efficacy selection",
        "source_ids": list(source.ids), "rich_field_width": len(state),
        "actual_gradient_calls": len(schedules) * B["macro_steps"],
        "actual_gradient_examples": len(schedules) * B["macro_steps"] * learning.P["batch_size"],
        "all_four_branches_start_from_identical_complete_optimizer_state": True,
        "actual_minibatches_and_noise_marks_match_across_all_branches": True,
        "no_update_eight_steps_preserve_parameters_momentum_and_hard_outputs": True,
        "all_nonzero_actions_produce_distinct_parameter_states": True,
        "branch_execution_order_reversal_is_exact": True,
        "unselected_branches_cannot_mutate_origin": True,
        "frozen_base_unchanged_for_every_branch": True,
        "audit_observer_loaded": False, "test_retention_scored": False,
        "chronology_scope": "Full field_bank.main chronology is reviewed statically and must be audited on its actual prediction/output records; this helper test does not substitute for that audit",
        "actual_shared_schedule": schedules[0], "branch_results": all_runs[0],
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "bank_protocol_sha256": hashlib.sha256(Path(__file__).with_name("BANK_PROTOCOL.json").read_bytes()).hexdigest()}
    (root / "FIELD_BANK_CONTRACT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", required=True)
    report = check(parser.parse_args())
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"source_ids", "actual_shared_schedule", "branch_results"}}))


if __name__ == "__main__":
    main()

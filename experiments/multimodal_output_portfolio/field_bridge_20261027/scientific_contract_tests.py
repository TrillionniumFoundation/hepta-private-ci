"""Smoke contracts using validation offset 700 only, without efficacy comparisons.

Run as a module with --assets pointing to the recovered archive directory and
--out pointing to a fresh directory outside this source package. This program
does not access test/retention examples or select scientific hyperparameters.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import torch

from .run import setup
from .adapters import (make_model, local_state, save_adapter, load_adapter, frozen_base_hash)
from .adaptation import new_optimizer, update, hard_value
from .task import ACTIONS, prepare_episode, finish_episode
from .protocol import P
from ..v6.data import make_batch
from ..v6.observer import observe_tensors


def equal_tree(first, second):
    if isinstance(first, torch.Tensor):
        return isinstance(second, torch.Tensor) and torch.equal(first, second)
    if isinstance(first, dict):
        return set(first) == set(second) and all(equal_tree(first[k], second[k]) for k in first)
    if isinstance(first, (list, tuple)):
        return len(first) == len(second) and all(equal_tree(a, b) for a, b in zip(first, second, strict=True))
    return first == second


def check_contracts(args):
    destination = Path(args.out).resolve()
    if destination.is_relative_to(Path(__file__).resolve().parent):
        raise ValueError("Smoke artifacts must be outside the scientific source package")
    destination.mkdir(parents=True, exist_ok=False)
    corpus, observers, originals, identities = setup(args)
    original = originals[17]
    batch = make_batch(corpus, "validation", 4, 271027, offset=700, corruption="clean")
    model = make_model(original, 17)
    optimizer = new_optimizer(model)
    initial, base = local_state(model), frozen_base_hash(model)
    update(model, original, optimizer, batch, 0, 1.0, 111)
    update(model, original, optimizer, batch, 0, 1.0, 112)
    assert all(not torch.equal(value, local_state(model)[name]) for name, value in initial.items()), \
        "At least one low-rank factor did not receive an actual parameter update"
    checkpoint = destination / "adapter.pt"
    save_adapter(checkpoint, model, optimizer, base_file_sha256=identities[17]["file_sha256"],
                 metadata={"scope": "validation-offset700-only; no-efficacy"})
    resumed, record = load_adapter(checkpoint, original, 17, identities[17]["file_sha256"])
    resumed_optimizer = new_optimizer(resumed)
    resumed_optimizer.load_state_dict(record["optimizer_state"])
    reset, _ = load_adapter(checkpoint, original, 17, identities[17]["file_sha256"])
    reset_optimizer = new_optimizer(reset)
    for candidate, state in ((model, optimizer), (resumed, resumed_optimizer), (reset, reset_optimizer)):
        update(candidate, original, state, batch, 0, .25, 113)
    assert equal_tree(local_state(model), local_state(resumed)), "Restored optimizer did not reproduce the next parameters"
    assert equal_tree(optimizer.state_dict(), resumed_optimizer.state_dict()), "Restored optimizer state diverged"
    assert not equal_tree(local_state(model), local_state(reset)), "Negative control failed to detect discarded momentum"
    before_parameters, before_optimizer = local_state(resumed), deepcopy(resumed_optimizer.state_dict())
    update(resumed, original, resumed_optimizer, batch, 0, 0.0, 114)
    assert equal_tree(before_parameters, local_state(resumed)), "Zero intervention changed adapter parameters"
    assert equal_tree(before_optimizer, resumed_optimizer.state_dict()), "Zero intervention advanced hidden optimizer state"
    assert base == frozen_base_hash(model) == frozen_base_hash(resumed) == frozen_base_hash(reset)
    discrepancies = []
    for action in range(len(ACTIONS)):
        prepared = prepare_episode(resumed, batch.observation, observers["reward"], noise_seed=991,
                                   output_root=destination / f"action-{action}",
                                   case_ids=[f"smoke-{i}" for i in range(len(batch.source_ids))])
        final = finish_episode(resumed, prepared, [action] * len(batch.source_ids))
        scores = observe_tensors(observers["reward"], final.pixels_u8.float() / 255, final.captions,
                                 batch.target.pixels, batch.target.labels)
        delivered_value = sum(score["utility"] for score in scores) / len(scores)
        delivered_value -= P["refinement_charge"] * (1 + (action != 0))
        discrepancy = abs(delivered_value - hard_value(resumed, batch, observers["reward"], action))
        assert discrepancy < 1e-12, "Training value differs from exact deployed hard output score"
        discrepancies.append(discrepancy)
    report = {"status": "pass", "scope": "four validation source pairs at offset700; seed17; no efficacy comparison",
              "both_factors_updated": True, "complete_optimizer_continuation_exact": True,
              "discarded_momentum_negative_control_detected": True,
              "zero_action_holds_parameters_and_optimizer": True,
              "frozen_base_preserved": True,
              "all_five_hard_value_delivery_checks_pass": True,
              "max_hard_value_delivery_discrepancy": max(discrepancies),
              "source_image_ids": batch.source_ids,
              "test_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (destination / "SCIENTIFIC_CONTRACT_SMOKE.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, help="Recovered archive with RESTORATION.json")
    parser.add_argument("--out", required=True, help="Fresh artifact directory outside this source package")
    report = check_contracts(parser.parse_args())
    print(json.dumps({key: value for key, value in report.items() if key != "source_image_ids"}))


if __name__ == "__main__":
    main()

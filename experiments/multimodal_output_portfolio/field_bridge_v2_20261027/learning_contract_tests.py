"""Executed learning contracts; validation offset 700, no efficacy selection."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ..v6.data import make_batch
from ..v6.neural import parameter_hash
from ..v6.observer import observe_tensors, read_bundle
from ..field_bridge_20261027.run import setup
from ..field_bridge_20261027.adapters import frozen_base_hash, local_state, local_hash
from ..field_bridge_20261027.scientific_contract_tests import equal_tree
from ..field_bridge_20261027.task import ACTIONS, prepare_episode, finish_episode
from .learning import (P, make_model, new_optimizer, hard_outputs, update,
                       optimizer_hash, clone_optimizer_model, save_model)


def check(args):
    root = Path(args.out).resolve()
    if root.is_relative_to(Path(__file__).resolve().parent):
        raise ValueError("Contract output must be outside the source package")
    root.mkdir(parents=True, exist_ok=False)
    corpus, observers, originals, identities = setup(args)
    original, observer = originals[17], observers["reward"]
    original_hash, observer_hash = parameter_hash(original), parameter_hash(observer)
    batch = make_batch(corpus, "validation", 4, 271027, offset=700, corruption="heavy_noise")
    batches = [("heavy_noise", batch)]
    reports = []
    for recipe in (P["candidates"][0], P["candidates"][3]):
        directory = root / recipe["name"]
        directory.mkdir()
        model = make_model(original, 17, recipe)
        optimizer = new_optimizer(model, recipe)
        initial, frozen = local_state(model), frozen_base_hash(model)
        assert hard_outputs(model, batches, observer, 0) == hard_outputs(original, batches, observer, 0)
        for noise_seed in (111, 112):
            update(model, original, optimizer, batch, 0, 1., noise_seed, recipe)
        changes = {name: not torch.equal(value, local_state(model)[name]) for name, value in initial.items()}
        assert all(changes.values()), "An adapter factor did not learn after two updates"

        copied, copied_optimizer = clone_optimizer_model(model, optimizer, recipe)
        checkpoint = directory / "adapter.pt"
        save_model(checkpoint, model, optimizer, recipe,
                   {"scope": "validation offset700 contracts", "base_identity": identities[17]})
        stored = torch.load(checkpoint, map_location="cpu", weights_only=True)
        restored = make_model(original, 17, recipe)
        parameters = dict(restored.named_parameters())
        assert set(stored["parameters"]) == set(local_state(restored))
        with torch.no_grad():
            for name, value in stored["parameters"].items():
                parameters[name].copy_(value)
        restored_optimizer = new_optimizer(restored, recipe)
        restored_optimizer.load_state_dict(deepcopy(stored["optimizer"]))
        assert stored["local_sha256"] == local_hash(restored)
        assert stored["optimizer_sha256"] == optimizer_hash(restored_optimizer)
        reset = deepcopy(restored)
        reset_optimizer = new_optimizer(reset, recipe)
        for candidate, state in ((model, optimizer), (copied, copied_optimizer),
                                 (restored, restored_optimizer), (reset, reset_optimizer)):
            update(candidate, original, state, batch, 0, .25, 113, recipe)
        for candidate, state in ((copied, copied_optimizer), (restored, restored_optimizer)):
            assert equal_tree(local_state(model), local_state(candidate))
            assert equal_tree(optimizer.state_dict(), state.state_dict())
        assert not equal_tree(local_state(model), local_state(reset)), "Dropped-momentum negative control was insensitive"

        before_parameters = local_state(restored)
        before_optimizer = deepcopy(restored_optimizer.state_dict())
        before_value = hard_outputs(restored, batches, observer, 0)
        update(restored, original, restored_optimizer, batch, 0, 0., 114, recipe)
        assert equal_tree(before_parameters, local_state(restored))
        assert equal_tree(before_optimizer, restored_optimizer.state_dict())
        assert before_value == hard_outputs(restored, batches, observer, 0)
        assert all(frozen_base_hash(x) == frozen for x in (model, copied, restored, reset))

        discrepancies = []
        for action in range(len(ACTIONS)):
            prepared = prepare_episode(restored, batch.observation, observer, noise_seed=91027,
                output_root=directory / f"action-{action}", case_ids=[f"case-{i}" for i in range(4)])
            final = finish_episode(restored, prepared, [action] * 4)
            read_pixels, captions = [], []
            for i in range(4):
                artifact = directory / f"action-{action}" / f"case-{i}" / "final"
                pixels, caption, _ = read_bundle({"image": artifact / "image.png", "text": artifact / "caption.txt"})
                read_pixels.append(pixels)
                captions.append(caption)
            reread = torch.cat(read_pixels)
            assert torch.equal((reread * 255).round().to(torch.uint8), final.pixels_u8)
            assert tuple(captions) == final.captions
            scores = observe_tensors(observer, reread, captions, batch.target.pixels, batch.target.labels)
            delivered = [row["utility"] - P["charge"] * (1 + (action != 0)) for row in scores]
            predicted = hard_outputs(restored, batches, observer, action)
            difference = float(np.max(np.abs(np.asarray(delivered) - np.asarray(predicted["values"]))))
            assert difference < 1e-12, "Hard panel value differs from real PNG/UTF8 readback"
            assert predicted["decisions"] == [[captions[i], *scores[i]["image_digits"]] for i in range(4)]
            discrepancies.append(difference)
        reports.append({"recipe": recipe["name"], "all_adapter_factors_changed": changes,
            "complete_optimizer_clone_continuation_exact": True,
            "serialized_optimizer_continuation_exact": True,
            "discarded_momentum_negative_control_detected": True,
            "zero_action_preserves_parameters_momentum_and_hard_outputs": True,
            "base_parameters_preserved": True,
            "all_five_actions_raw_png_utf8_parity": True,
            "maximum_value_discrepancy": max(discrepancies)})
    assert parameter_hash(original) == original_hash
    assert parameter_hash(observer) == observer_hash
    report = {"schema": "hepta.field-bridge.v2.learning-contracts.1", "status": "pass",
        "scope": "seed17, four existing validation source pairs at offset700; no efficacy selection",
        "source_ids": batch.source_ids, "audit_observer_loaded": False,
        "test_retention_scored": False, "recipes": reports,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256(Path(__file__).with_name("PILOT_PROTOCOL.json").read_bytes()).hexdigest()}
    (root / "LEARNING_CONTRACTS.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", required=True)
    report = check(parser.parse_args())
    print(json.dumps({"status": report["status"], "recipes": report["recipes"]}))


if __name__ == "__main__":
    main()

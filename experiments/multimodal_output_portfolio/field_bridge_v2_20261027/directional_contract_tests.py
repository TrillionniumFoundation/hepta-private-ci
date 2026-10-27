"""Independent derivative/state contracts on existing validation examples only."""

import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest import mock

import numpy as np
import torch

from ..v6.data import SourceCorpus, make_batch
from ..field_bridge_20261027.run import setup
from ..field_bridge_20261027.adapters import local_parameters, local_hash, frozen_base_hash
from . import learning
from . import directional_features as df


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unchanged(model, optimizer, snapshot):
    parameters, moments, frozen, gradients, references, rng = snapshot
    assert local_hash(model) == parameters
    assert learning.optimizer_hash(optimizer) == moments
    assert frozen_base_hash(model) == frozen
    assert all(parameter.grad is reference for parameter, reference in zip(local_parameters(model), references, strict=True))
    assert all((value is None and parameter.grad is None) or torch.equal(value, parameter.grad)
               for parameter, value in zip(local_parameters(model), gradients, strict=True))
    assert torch.equal(torch.get_rng_state(), rng)


def snapshot(model, optimizer):
    references = [parameter.grad for parameter in local_parameters(model)]
    return (local_hash(model), learning.optimizer_hash(optimizer), frozen_base_hash(model),
            [None if gradient is None else gradient.clone() for gradient in references], references,
            torch.get_rng_state().clone())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Refusing to overwrite directional contract evidence")
    args.out.mkdir(parents=True)
    corpus, observers, originals, _ = setup(args)
    source = corpus.splits["validation"]
    source = replace(source, images=source.images[1400:1408], labels=source.labels[1400:1408],
        ids=source.ids[1400:1408], pixel_hashes=source.pixel_hashes[1400:1408])
    data = SourceCorpus({"train": source}, corpus.manifest)
    response = [(condition, make_batch(corpus, "validation", 4, 271027 + index, offset=700, corruption=condition))
                for index, condition in enumerate(("heavy_noise", "occlusion"))]
    clean = [("clean", make_batch(corpus, "validation", 4, 271027, offset=700, corruption="clean"))]
    recipe = next(x for x in learning.P["candidates"] if x["name"] == "upstream_r8_288_lr02")
    original = originals[17]
    model = learning.make_model(original, 17, recipe)
    optimizer = learning.new_optimizer(model, recipe)
    for index in range(2):
        learning.update(model, original, optimizer, response[0][1], 0, 1., 111 + index, recipe)
    for index, parameter in enumerate(local_parameters(model)):
        parameter.grad = None if index % 2 else torch.full_like(parameter, (index + 1) * .001)
    saved = snapshot(model, optimizer)
    seed, schedule_id, step = 17, 8, 8
    call = (model, original, optimizer, data, recipe, seed, schedule_id, step, response, clean, 0)
    features, receipt = df.measure_directional(*call)
    unchanged(model, optimizer, saved)
    with torch.no_grad():
        repeated, _ = df.measure_directional(*call)
    assert features == repeated
    unchanged(model, optimizer, saved)

    # Derive g and the proposed buffer from a separate exact optimizer clone.
    copied, copied_optimizer = learning.clone_optimizer_model(model, optimizer, recipe)
    batch_seed = seed * 100003 + 600000 + schedule_id * 1009 + step
    batch = make_batch(data, "train", learning.P["batch_size"], batch_seed,
                       corruption=learning.P["conditions"][step % 4])
    assert receipt["batch_seed"] == batch_seed and receipt["noise_seed"] == 107 + step
    assert receipt["next_batch_source_ids"] == [list(pair) for pair in batch.source_ids]
    learning.update(copied, original, copied_optimizer, batch, 0, 0., 107 + step, recipe)
    gradient, momentum, direction = [], [], []
    for parameter in local_parameters(copied):
        g = parameter.grad.detach().clone()
        m = copied_optimizer.state.get(parameter, {}).get("momentum_buffer", torch.zeros_like(parameter))
        gradient.append(g)
        momentum.append(m.clone())
        direction.append(m.clone().mul_(learning.P["momentum"]).add_(g))
    g = np.concatenate([value.numpy().reshape(-1).astype(np.float64) for value in gradient])
    m = np.concatenate([value.numpy().reshape(-1).astype(np.float64) for value in momentum])
    expected = [float(np.sqrt(np.mean(g * g))), float((g @ m) / (np.linalg.norm(g) * np.linalg.norm(m)))]
    np.testing.assert_allclose(features[:2], expected, rtol=1e-12, atol=1e-12)
    assert receipt["measured"]["gradient_sha256"] == df._tensor_hash(gradient)
    assert receipt["measured"]["momentum_sha256"] == df._tensor_hash(momentum)
    assert receipt["measured"]["direction_sha256"] == df._tensor_hash(direction)

    # Compare the direction to an actual optimizer step, including rounding.
    actual, actual_optimizer = learning.clone_optimizer_model(model, optimizer, recipe)
    before = [parameter.detach().clone() for parameter in local_parameters(actual)]
    learning.update(actual, original, actual_optimizer, batch, 0, .25, 107 + step, recipe)
    for parameter, previous, v in zip(local_parameters(actual), before, direction, strict=True):
        assert torch.equal(parameter.detach(), previous.add(v, alpha=-recipe["learning_rate"] * .25))
        assert torch.equal(actual_optimizer.state[parameter]["momentum_buffer"], v)

    observed = learning.observe_field(model, optimizer, recipe, response, clean, 0, step, .5)
    np.testing.assert_allclose(receipt["measured"]["probe_values"], observed[1:4], rtol=0, atol=2e-7)
    epsilon = .002
    losses = []
    for sign in (1, -1):
        perturbed = deepcopy(model)
        with torch.no_grad():
            for parameter, v in zip(local_parameters(perturbed), direction, strict=True):
                parameter.add_(v, alpha=sign * epsilon)
            losses.append([float(value) for value in df.probe_losses(perturbed, response, clean, 0)])
    central = (np.asarray(losses[0]) - np.asarray(losses[1])) / (2 * epsilon)
    dots = np.asarray(features[2:])
    errors = np.abs(central - dots)
    tolerances = 2e-5 + .05 * np.abs(dots)
    assert np.all(errors <= tolerances), (central.tolist(), dots.tolist(), errors.tolist())
    assert np.max(np.abs(dots)) > 1e-4, "Derivative fixture is too flat to test sign/scale"

    fresh = learning.make_model(original, 17, recipe)
    fresh_optimizer = learning.new_optimizer(fresh, recipe)
    fresh_snapshot = snapshot(fresh, fresh_optimizer)
    no_momentum, initial_receipt = df.measure_directional(fresh, original, fresh_optimizer,
        data, recipe, seed, schedule_id, step, response, clean, 0)
    assert no_momentum[1] == 0 and initial_receipt["measured"]["momentum_l2"] == 0
    unchanged(fresh, fresh_optimizer, fresh_snapshot)

    # A probe failure must also restore incoming gradients and optimizer state.
    with mock.patch.object(df, "probe_losses", side_effect=RuntimeError("contract injected probe failure")):
        try:
            df.measure_directional(*call)
        except RuntimeError as error:
            assert str(error) == "contract injected probe failure"
        else:
            raise AssertionError("Injected probe failure was swallowed")
    unchanged(model, optimizer, saved)
    rejected = 0
    try:
        with torch.inference_mode():
            df.measure_directional(*call)
    except ValueError:
        rejected += 1
    bad_optimizer = torch.optim.SGD(local_parameters(model), lr=.2, momentum=.9, weight_decay=.01)
    try:
        df.measure_directional(model, original, bad_optimizer, *call[3:])
    except ValueError:
        rejected += 1
    assert rejected == 2
    unchanged(model, optimizer, saved)
    result = {"schema": "hepta.field-bridge.v2.directional-contract.1", "status": "pass",
        "scope": "Eight existing validation sources at offset700; seed17; no efficacy comparison or heldout access",
        "source_ids": source.ids, "actual_next_minibatch_identity_matches": True,
        "clipped_gradient_and_carried_direction_hashes_match_separate_clone": True,
        "direction_predicts_actual_first_sgd_step_bit_exact": True,
        "probe_values_match_original_H7_observables": True,
        "parameters_optimizer_base_grad_object_values_and_rng_preserved": True,
        "no_grad_context_supported": True, "zero_initial_momentum_cosine_zero": True,
        "exception_path_restores_incoming_gradients": True,
        "unsupported_weight_decay_and_inference_mode_rejected": True,
        "features": features, "central_difference_epsilon": epsilon, "central_difference_values": central.tolist(),
        "central_difference_absolute_errors": errors.tolist(), "central_difference_tolerances": tolerances.tolist(),
        "receipt": receipt, "source_sha256": sha(__file__), "helper_sha256": sha(df.__file__),
        "test_retention_scored": False, "audit_observer_loaded": False}
    (args.out / "DIRECTIONAL_CONTRACT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"receipt", "source_ids"}}))


if __name__ == "__main__":
    main()

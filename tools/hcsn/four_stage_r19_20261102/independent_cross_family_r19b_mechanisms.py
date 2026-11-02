"""Independent finite sequence, masked proper-loss and READ audit. No owner worlds."""

import hashlib
import itertools
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.optimize import minimize as real_minimize

from experiments.hcsn_cross_family_r19b_20261102 import classes, masked_fit
from experiments.hcsn_cross_family_r19b_20261102.posterior import infer
from .independent_cross_family_mechanisms import (
    completions, encode, hand_model, hand_probability, marginals,
)


HERE = Path(__file__).resolve().parent
MODULE = HERE.parents[2] / "experiments/hcsn_cross_family_r19b_20261102"


def run():
    source = {name: hashlib.sha256((MODULE / name).read_bytes()).hexdigest()
              for name in ("classes.py", "masked_fit.py", "posterior.py", "protocol.json")}
    model = hand_model()
    sequences = list(itertools.product(range(4), repeat=6))
    raw = np.array([hand_probability(sequence, model) for sequence in sequences])
    raw_error = float(np.max(abs(classes.raw_likelihood(np.array(sequences), model) - raw)))
    key_mass = raw.sum(0)
    full = [(2, i % 4, (i + 1) % 4) for i in range(14)]
    for index, key, value in zip((0, 2, 4, 6, 9, 12), (0, 1, 2, 3, 1, 3), (0, 1, 1, 2, 3, 0), strict=True):
        full[index] = (0, key, value)
    masks = ((2, 10), (9, 12), (4, 6, 10))
    examples = []
    for key, missing in enumerate(masks):
        mask = np.ones(14, dtype=bool)
        mask[list(missing)] = False
        actual = np.stack([encode(event) for event in full])
        prefix = actual.copy()
        prefix[~mask] = 0
        target = [event[2] for event in full if event[0] == 0 and event[1] == key][-1]
        examples.append(dict(prefix=prefix, mask=mask, full=actual, key=key, target=target))

    max_temperature = max_mass = max_posterior = max_loss = max_gradient = 0.
    views_checked = read_choices = replay_checks = gradient_checks = 0
    optimizer_attempts = []
    prior = np.array([.5, .3, .2])
    for beta in masked_fit.BETAS:
        conditional = raw / key_mass[None]
        powered = np.exp(beta * np.log(conditional))
        manual = key_mass[None] * powered / powered.sum(0)[None]
        table = classes.tempered_table(model, beta)
        max_temperature = max(max_temperature, float(np.max(abs(table - manual))))
        max_mass = max(max_mass, float(np.max(abs(table.sum(0) - key_mass))))
        runtime = dict(model, sequence_table=table)
        lookup = dict(zip(sequences, manual, strict=True))
        cache = masked_fit.cache(examples, runtime)
        manual_probabilities = []
        for example, missing in zip(examples, masks, strict=True):
            events, finals, mass = completions(full, missing, lookup, prior)
            posterior = infer(example["prefix"], example["mask"], runtime, prior)
            weights = mass.sum(1) / mass.sum()
            max_posterior = max(max_posterior, float(np.max(abs(
                marginals(finals, weights) - np.stack([posterior.probability(k) for k in range(4)])))))
            kept_views = [np.ones(len(events), dtype=bool)]
            for index in missing:
                keep = np.all(events[:, index] == np.array(full[index]), axis=1)
                kept_views.append(keep)
                acquired = posterior.acquire(index, encode(full[index]))
                max_posterior = max(max_posterior, float(np.max(abs(
                    marginals(finals[keep], weights[keep] / weights[keep].sum()) -
                    np.stack([acquired.probability(k) for k in range(4)])))))
                assert acquired.acquire(index, encode(full[index])) is acquired
                replay_checks += 1
            for keep in kept_views:
                numerator = mass[keep & (finals[:, example["key"]] == example["target"])].sum()
                denominator = mass[keep].sum()
                manual_probabilities.append((numerator / denominator, 1 / len(kept_views) / len(examples)))
                views_checked += 1
            for destination in np.eye(3):
                updated = posterior.reprior(destination)
                fresh = infer(example["prefix"], example["mask"], runtime, destination)
                max_posterior = max(max_posterior, abs(updated.surprise - fresh.surprise),
                    float(np.max(abs(updated.class_masses - fresh.class_masses))))
            for key, price, threshold, cutoff in itertools.product(range(4), (.02, .12), (.8, .95), (.5, 1.)):
                if posterior.broad_mass > cutoff:
                    continue
                p = marginals(finals, weights)[key]
                best, value = None, 2 * p.max() - 1 if p.max() >= threshold else 0.
                for index in missing:
                    expected = -price
                    for event in np.unique(events[:, index], axis=0):
                        keep = np.all(events[:, index] == event, axis=1)
                        probability = weights[keep].sum()
                        branch = marginals(finals[keep], weights[keep] / probability)[key]
                        broad = mass[keep, 2].sum() / mass[keep].sum()
                        if branch.max() >= threshold and broad <= cutoff + 1e-12:
                            expected += probability * (2 * branch.max() - 1)
                    if expected > value + 1e-12:
                        best, value = index, expected
                assert posterior.choose(key, price, threshold, cutoff)[0] == best
                read_choices += 1
        a, b, weight = cache
        cached_probabilities = (a @ prior) / (b @ prior)
        expected = np.array([p for p, _ in manual_probabilities])
        max_loss = max(max_loss, float(np.max(abs(cached_probabilities - expected))),
                       abs(masked_fit.loss(cache, prior) + sum(w * np.log(p) for p, w in manual_probabilities)))
        assert np.max(abs(weight - np.array([w for _, w in manual_probabilities]))) < 2e-15
        assert abs(weight.sum() - 1) < 2e-15

        def checked_optimizer(objective, initial, **kwargs):
            nonlocal max_gradient, gradient_checks
            for theta in (np.array(initial), np.array([.3, -.7]), np.array([-3., 2.])):
                value, gradient = objective(theta)
                step = 2e-6
                fd = np.array([(objective(theta + step * np.eye(2)[i])[0] -
                                objective(theta - step * np.eye(2)[i])[0]) / (2 * step) for i in range(2)])
                max_gradient = max(max_gradient, float(np.max(abs(gradient - fd))))
                soft = np.exp(np.r_[theta, 0.] - max(*theta, 0.))
                transformed = .9 * soft / soft.sum() + np.array([0., 0., .1])
                max_value = abs(value - masked_fit.loss(cache, transformed))
                assert max_value < 2e-14
                gradient_checks += 2
            result = real_minimize(objective, initial, **kwargs)
            optimizer_attempts.append(dict(beta=beta, success=bool(result.success), value=float(result.fun)))
            return result

        with patch.object(masked_fit, "minimize", checked_optimizer):
            fitted, receipt = masked_fit.learn_prior(cache)
        assert receipt["success"] and abs(fitted.sum() - 1) < 2e-15 and fitted[2] >= .1

    degenerate = hand_model()
    degenerate["mean_q"] = 1.
    for particle in degenerate["particles"]:
        particle["q"] = 1.
    for beta in masked_fit.BETAS:
        table = classes.tempered_table(degenerate, beta)
        assert np.isfinite(table).all() and np.array_equal(table[:, :, 0], np.zeros((4096, 3)))
        assert np.max(abs(table.sum(0)[:, 1] - 1 / 12)) < 2e-14
    assert raw_error < 2e-14 and max_temperature < 2e-14 and max_mass < 2e-14
    assert max_posterior < 2e-12 and max_loss < 2e-12 and max_gradient < 2e-8
    assert source == {name: hashlib.sha256((MODULE / name).read_bytes()).hexdigest() for name in source}
    return dict(schema="hcsn-r19b-independent-mechanisms-v1", source_sha256=source,
        scope="Manual finite fixtures only; no world/owner/campaign imports or formal data opened",
        all_checks_passed=True, complete_sequences=4096, betas=list(masked_fit.BETAS),
        maximum_raw_sequence_error=raw_error, maximum_temperature_error=max_temperature,
        maximum_key_mass_drift=max_mass, maximum_posterior_read_reprior_error=max_posterior,
        maximum_conditional_cache_loss_error=max_loss, maximum_optimizer_gradient_fd_error=max_gradient,
        equal_world_pre_and_each_actual_read_views=views_checked, indexed_replay_checks=replay_checks,
        guarded_read_choices=read_choices, gradient_components_checked=gradient_checks,
        optimizer_attempts=optimizer_attempts, zero_key_mass_preserved=True,
        source_review=["Temperature normalizes each entire sequence conditional on class/repeat category and retains original key mass",
            "Public supervision derives target from complete observed final WRITE; class learning receives no owner/family field",
            "Conditional cache common normalization cancels in (a@prior)/(b@prior); weights average views within worlds then worlds",
            "Strong static searches all12class/beta options on same proper validation loss; independent beta triggers fresh runtime inference",
            "Ordinary reprior is reused only for equal beta, with common key marginal, before actual READ"],
        limits=["Finite six-WRITE/four-value model only; no calibration or unknown-family efficacy claim",
                "Optimizer checks verify analytic conditional-loss gradient and finite convergence, not global nonconvex optimum"])


if __name__ == "__main__":
    report = run()
    with (HERE / "independent_cross_family_r19b_mechanisms.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: value for key, value in report.items() if key not in ("source_review", "optimizer_attempts", "source_sha256")}))

"""Manual Polya-urn/reference enumeration; never opens registered owner worlds."""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

from experiments.hcsn_cross_family_r19_20261102.classes import likelihood
from experiments.hcsn_cross_family_r19_20261102.posterior import infer


HERE = Path(__file__).resolve().parent
MODULE = HERE.parents[2] / "experiments/hcsn_cross_family_r19_20261102"


def hand_model():
    rotor = np.full((4, 4), .05)
    rotor[np.arange(4), (np.arange(4) + 1) % 4] = .85
    return dict(particles=[dict(pi=[.1, .2, .3, .4], transition=(.6 * np.eye(4) + .1).tolist(), q=.2),
                           dict(pi=[.4, .3, .2, .1], transition=rotor.tolist(), q=.8)],
                mean_q=.5, pooled=[.2, .3, .1, .4], start=[.4, .1, .3, .2],
                pooled_transition=[[.7, .1, .1, .1], [.1, .6, .2, .1],
                                   [.2, .2, .4, .2], [.15, .25, .35, .25]])


def urn(sequence, alpha):
    counts = np.zeros(4)
    probability = 1.
    for value in sequence:
        probability *= (counts[value] + alpha[value]) / (counts.sum() + alpha.sum())
        counts[value] += 1
    return probability


def hand_probability(sequence, model):
    result = np.zeros((3, 2))
    for particle in model["particles"]:
        value = particle["pi"][sequence[0]]
        for a, b in zip(sequence, sequence[1:]):
            value *= particle["transition"][a][b]
        q = particle["q"]
        result[0] += value * np.array([(1 - q) / 16, (1 - q) / 16 + q / 12]) / len(model["particles"])
    q = model["mean_q"]
    key_weight = np.array([(1 - q) / 16, (1 - q) / 16 + q / 12])
    for strength in (.1, .5, 2., 8.):
        result[1] += urn(sequence, np.array(model["pooled"]) * strength) * key_weight / 4
        alpha = np.array(model["pooled_transition"]) * strength
        counts = np.zeros((4, 4))
        value = model["start"][sequence[0]]
        for a, b in zip(sequence, sequence[1:]):
            value *= (alpha[a, b] + counts[a, b]) / (alpha[a].sum() + counts[a].sum())
            counts[a, b] += 1
        result[2] += value * key_weight / 4
    return result


def encode(event):
    kind, key, value = event
    x = np.zeros(24, dtype=np.int8)
    x[[key, 4 + value, 12 + kind, 16]] = 1
    return x


def completions(full, missing, class_probabilities, prior):
    options = list(itertools.product((0, 2), range(4), range(4)))
    events, finals, masses = [], [], []
    for replacements in itertools.product(options, repeat=len(missing)):
        candidate = list(full)
        for index, event in zip(missing, replacements, strict=True):
            candidate[index] = event
        writes = [event for event in candidate if event[0] == 0]
        if len(writes) != 6 or sorted(event[1] for event in writes[:4]) != list(range(4)):
            continue
        sequence = tuple(event[2] for event in writes)
        category = int(writes[-1][1] != writes[-2][1])
        weights = class_probabilities[sequence][:, category] * prior
        final = np.zeros(4, dtype=int)
        for _, key, value in writes:
            final[key] = value
        events.append(candidate)
        finals.append(final)
        masses.append(weights)
    return np.array(events), np.array(finals), np.array(masses)


def marginals(finals, weights):
    return np.stack([np.bincount(finals[:, key], weights=weights, minlength=4) for key in range(4)])


def run():
    sources = {name: hashlib.sha256((MODULE / name).read_bytes()).hexdigest()
               for name in ("classes.py", "posterior.py")}
    model, sequences = hand_model(), list(itertools.product(range(4), repeat=6))
    actual = likelihood(np.array(sequences), model)
    manual = np.array([hand_probability(sequence, model) for sequence in sequences])
    sequence_error = float(np.max(abs(actual - manual)))
    normalization = actual.sum(0) @ np.array([4., 12.])
    assert sequence_error < 2e-14 and np.max(abs(normalization - 1)) < 2e-12
    lookup = dict(zip(sequences, manual, strict=True))
    full = [(2, i % 4, (i + 1) % 4) for i in range(14)]
    for index, key, value in zip((0, 2, 4, 6, 9, 12), (0, 1, 2, 3, 1, 3), (0, 1, 1, 2, 3, 0), strict=True):
        full[index] = (0, key, value)
    prior = np.array([.5, .3, .2])
    posterior_errors, broad_errors, read_errors, reprior_errors = [], [], [], []
    choice_checks = completion_rows = 0
    for missing in ((2, 10), (9, 12), (4, 6, 10)):
        mask = np.ones(14, dtype=bool)
        mask[list(missing)] = False
        prefix = np.stack([encode(event) for event in full])
        prefix[~mask] = 0
        result = infer(prefix, mask, model, prior)
        events, finals, mass = completions(full, missing, lookup, prior)
        completion_rows += len(events)
        weights = mass.sum(1) / mass.sum()
        posterior_errors.append(float(np.max(abs(marginals(finals, weights) - np.stack([result.probability(k) for k in range(4)])))))
        broad_errors.append(abs(float(mass[:, 2].sum() / mass.sum()) - result.broad_mass))
        for index in missing:
            keep = np.all(events[:, index] == np.array(full[index]), axis=1)
            expected = marginals(finals[keep], weights[keep] / weights[keep].sum())
            conditioned = result.acquire(index, encode(full[index]))
            read_errors.append(float(np.max(abs(expected - np.stack([conditioned.probability(k) for k in range(4)])))))
            broad_errors.append(abs(float(mass[keep, 2].sum() / mass[keep].sum()) - conditioned.broad_mass))
            assert conditioned.acquire(index, encode(full[index])) is conditioned
            changed = (full[index][0], full[index][1], (full[index][2] + 1) % 4)
            try:
                conditioned.acquire(index, encode(changed))
            except ValueError:
                pass
            else:
                raise AssertionError("Conflicting indexed READ replay was accepted")
        for destination in np.eye(3):
            reweighted, fresh = result.reprior(destination), infer(prefix, mask, model, destination)
            reprior_errors.append(abs(reweighted.surprise - fresh.surprise))
            for key in range(4):
                reprior_errors.append(float(np.max(abs(reweighted.probability(key) - fresh.probability(key)))))
        for key, price, threshold, cutoff in itertools.product(range(4), (.02, .12), (.65, .85, .95), (.5, 1.)):
            if result.broad_mass > cutoff:
                continue
            p = marginals(finals, weights)[key]
            best, best_value = None, (2 * p.max() - 1 if p.max() >= threshold else 0.)
            for index in missing:
                expected = -price
                for event in np.unique(events[:, index], axis=0):
                    keep = np.all(events[:, index] == event, axis=1)
                    probability = weights[keep].sum()
                    branch = marginals(finals[keep], weights[keep] / probability)[key]
                    broad = mass[keep, 2].sum() / mass[keep].sum()
                    if branch.max() >= threshold and broad <= cutoff + 1e-12:
                        expected += probability * (2 * branch.max() - 1)
                if expected > best_value + 1e-12:
                    best, best_value = index, expected
            assert result.choose(key, price, threshold, cutoff)[0] == best
            choice_checks += 1
    maximum = max(posterior_errors + broad_errors + read_errors + reprior_errors)
    assert maximum < 2e-12
    assert sources == {name: hashlib.sha256((MODULE / name).read_bytes()).hexdigest() for name in sources}
    return dict(schema="hcsn-r19-independent-class-mechanism-audit-v1", source_sha256=sources,
                scope="Hand-defined models, Polya-urn sequence likelihoods and complete raw-token enumeration; no registered owner-world imports or outcomes",
                complete_value_sequences=4096, sequence_entries_checked=int(actual.size),
                maximum_sequence_probability_error=sequence_error, class_joint_normalization=normalization.tolist(),
                complete_event_rows_enumerated=completion_rows, mask_cases=3,
                guarded_read_choice_checks=choice_checks, maximum_posterior_read_reprior_error=maximum,
                all_checks_passed=True,
                limits=["Finite four-value/six-WRITE profile only", "No calibration or cross-family efficacy result",
                        "Surprise reprior identity uses the fitted common key marginal"])


if __name__ == "__main__":
    report = run()
    target = HERE / "independent_cross_family_mechanisms.json"
    with target.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("complete_value_sequences", "sequence_entries_checked",
                                                   "complete_event_rows_enumerated", "guarded_read_choice_checks",
                                                   "maximum_posterior_read_reprior_error", "all_checks_passed")}))

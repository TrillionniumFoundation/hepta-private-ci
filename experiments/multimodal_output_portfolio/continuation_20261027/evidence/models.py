"""Measured source pooling with explicit shrinkage assumptions and unknown support."""

import hashlib
import numpy as np

from ...repair_20261026.evidence.joint import JointObservationLaw


FAMILIES = ("independent", "paired", "speaker_mixture")
CUES = ("uniform", "plus1", "plus3", "plus7")


def measured_pairs(observations):
    lookup = {(row["speaker"], row["target"], row["index"]): row for row in observations}
    speakers = sorted({row["speaker"] for row in observations})
    rows = []
    for speaker in speakers:
        for left in range(10):
            for right in range(10):
                for index in range(20):
                    a = lookup.get((speaker, left, index))
                    b = lookup.get((speaker, right, index if left == right else (7 * index + 11) % 20))
                    if a is None or b is None:
                        continue
                    sample = hashlib.sha256(f"{speaker}/{left}/{right}/{index}".encode()).hexdigest()
                    rows.append({"sample_id": sample, "speaker": speaker, "target": 10 * left + right,
                                 "index": index, "event_ids": [a["event_id"], b["event_id"]],
                                 "values": [a["observation"], b["observation"]]})
    return rows


def event_index(event_ids, values):
    if len(event_ids) != 2 or len(values) != 2:
        raise ValueError("Two observed placements are required")
    if any(not isinstance(value, int) or not 0 <= value < 10 for value in values):
        raise ValueError("Invalid public observer value")
    if any(not isinstance(event, str) or not event for event in event_ids):
        raise ValueError("Missing physical event identity")
    if event_ids[0] == event_ids[1]:
        if values[0] != values[1]:
            raise ValueError("Same actual event has contradictory labels")
        return values[0]
    return 10 + 10 * values[0] + values[1]


def project_marginals(table, left, right):
    """Positive-table information projection; dependence changes, marginals do not."""
    result = table.copy()
    for _ in range(2000):
        result *= (left / result.sum(axis=1))[:, None]
        result *= (right / result.sum(axis=0))[None, :]
        if max(np.abs(result.sum(1) - left).max(), np.abs(result.sum(0) - right).max()) < 1e-12:
            return result
    raise ArithmeticError("Joint marginal projection did not converge")


def fit_law(observations, family, strength, excluded_speakers=(), marginal_strength=.5):
    if family not in FAMILIES or strength <= 0:
        raise ValueError("Declare a supported family and positive pseudocount")
    speakers = sorted({row["speaker"] for row in observations})
    if set(speakers) & set(excluded_speakers):
        raise ValueError("Reserved sources entered likelihood fitting")
    position = {speaker: index for index, speaker in enumerate(speakers)}
    counts = np.zeros((len(speakers), 10, 10))
    events = {}
    for row in observations:
        identity = (row["speaker"], row["target"], row["observation"])
        if row["event_id"] in events and events[row["event_id"]] != identity:
            raise ValueError("Physical event has conflicting fitted metadata")
        if row["event_id"] not in events:
            counts[position[row["speaker"]], row["observation"], row["target"]] += 1
        events[row["event_id"]] = identity
    pairs = measured_pairs(observations)
    paired_counts = np.zeros((110, 100))
    for row in pairs:
        paired_counts[event_index(row["event_ids"], row["values"]), row["target"]] += 1
    matrix = np.full((110, 100), np.nan)
    pooled = counts.sum(0)
    base = (pooled + marginal_strength / 10) / (pooled.sum(0) + marginal_strength)
    single = (pooled + strength / 10) / (pooled.sum(0) + strength)
    conditional = (counts + strength * base[None]) / (counts.sum(1)[:, None] + strength)
    for target in range(100):
        n = paired_counts[:, target].sum()
        if not n:
            continue
        left, right = divmod(target, 10)
        matrix[:, target] = 0.
        if left == right:
            matrix[:10, target] = single[:, left] if family == "independent" else base[:, left]
        elif family == "independent":
            matrix[10:, target] = np.outer(single[:, left], single[:, right]).ravel()
        elif family == "paired":
            prior = np.outer(base[:, left], base[:, right]).ravel()
            joint = ((paired_counts[10:, target] + strength * prior) / (n + strength)).reshape(10, 10)
            matrix[10:, target] = project_marginals(joint, base[:, left], base[:, right]).ravel()
        else:
            joint = np.einsum("si,sj->ij", conditional[:, :, left], conditional[:, :, right]) / len(speakers)
            matrix[10:, target] = project_marginals(joint, base[:, left], base[:, right]).ravel()
    return JointObservationLaw(matrix, {"origin": "measured AudioMNIST source pooling",
        "family": family, "pseudocount": strength, "source_groups": speakers,
        "marginal_pseudocount": strength if family == "independent" else marginal_strength,
        "joint_marginals_projected": family != "independent",
        "unique_waveforms": len(events), "derived_pairs": len(pairs),
        "assumptions": {"independent": "explicit pooled conditional independence",
                        "paired": "measured paired law shrunk toward explicit pooled product",
                        "speaker_mixture": "conditional independence within a latent source, source-mixture dependence"}[family],
        "unobserved_columns": "unknown; no marginal-only completion"})


def posterior(law, event_ids, values, prior):
    prior = np.asarray(prior, dtype=np.float64)
    if (prior.shape != (100,) or not np.isfinite(prior).all() or (prior < 0).any()
            or abs(prior.sum() - 1) > 1e-10):
        raise ValueError("Normalized target prior required")
    active = prior > 0
    if not law.known_targets[active].all():
        raise ValueError("Unidentified coupling has positive target prior")
    likelihood = law.likelihood[event_index(event_ids, values)].copy()
    weighted = np.zeros(100)
    weighted[active] = likelihood[active] * prior[active]
    if weighted.sum() <= 0:
        raise ValueError("Actual observation outside frozen support")
    return weighted / weighted.sum(), likelihood


def metrics(law, rows, prior=None):
    prior = np.full(100, .01) if prior is None else prior
    collected = []
    for row in rows:
        probability, likelihood = posterior(law, row["event_ids"], row["values"], prior)
        target, selected = row["target"], int(probability.argmax())
        collected.append((-np.log(likelihood[target]), -np.log(probability[target]),
                          float(selected == target), float(probability.max())))
    return np.asarray(collected)


def target_distribution(cue):
    if cue not in CUES:
        raise ValueError("Unknown public task cue")
    distribution = np.full((10, 10), .01 if cue == "uniform" else .003)
    if cue != "uniform":
        offset = int(cue[4:])
        for digit in range(10):
            distribution[digit, (digit + offset) % 10] += .07
    return distribution.ravel()


def prior_cases(observations, seed):
    lookup = {(row["speaker"], row["target"], row["index"]): row for row in observations}
    result = []
    for speaker in sorted({row["speaker"] for row in observations}):
        for cue_index, cue in enumerate(CUES):
            rng = np.random.default_rng(seed + int(speaker) * 101 + cue_index * 10007)
            for index, target in enumerate(rng.choice(100, 300, p=target_distribution(cue))):
                left, right = divmod(int(target), 10)
                trial = int(rng.integers(20))
                a = lookup[speaker, left, trial]
                b = lookup[speaker, right, trial if left == right else (7 * trial + 11) % 20]
                sample = hashlib.sha256(f"prior/{speaker}/{cue}/{index}".encode()).hexdigest()
                result.append({"sample_id": sample, "speaker": speaker, "cue": cue,
                               "target": int(target), "event_ids": [a["event_id"], b["event_id"]],
                               "values": [a["observation"], b["observation"]]})
    return result


def fit_prior(rows, cue, family, strength):
    counts = np.bincount([row["target"] for row in rows if row["cue"] == cue], minlength=100)
    joint = (counts + strength / 100) / (counts.sum() + strength)
    if family == "joint":
        return joint
    if family != "factorized":
        raise ValueError("Unsupported target prior family")
    marginal = counts.reshape(10, 10)
    left = (marginal.sum(1) + strength / 10) / (counts.sum() + strength)
    right = (marginal.sum(0) + strength / 10) / (counts.sum() + strength)
    return np.outer(left, right).ravel()

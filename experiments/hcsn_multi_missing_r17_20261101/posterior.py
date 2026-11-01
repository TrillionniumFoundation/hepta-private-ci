"""Exact finite prefix posterior; no labels, hidden targets or fit IDs are inputs.

Initial phase: shuffled one WRITE per key and one distractor per key count.
Selective phase: two distinct overwrite keys. WRITE values are either independent
uniform draws or ordered draws without replacement. Missing positions are chosen
independently of event contents; a missing token reveals no kind/key/value.
"""

from dataclasses import dataclass
from itertools import combinations, permutations, product
from math import comb, factorial, perm

import numpy as np


@dataclass(frozen=True)
class Profile:
    keys: int = 4
    values: int = 8
    overwrites: int = 2


def decode(event, profile):
    event = np.asarray(event)
    if event.shape != (24,) or not np.isin(event, [0, 1]).all():
        raise ValueError("Expected one binary raw token")
    if event[:4].sum() != 1 or event[4:12].sum() != 1 or event[12:16].sum() != 1:
        raise ValueError("Expected one typed key/value event")
    key, value, kind = int(event[:4].argmax()), int(event[4:12].argmax()), int(event[12:16].argmax())
    if key >= profile.keys or value >= profile.values or kind not in (0, 2):
        raise ValueError("Event lies outside the declared profile")
    expected = encode(kind, key, value)
    if not np.array_equal(expected, event):
        raise ValueError("Unexpected token fields")
    return kind, key, value


def encode(kind, key, value):
    result = np.zeros(24, dtype=np.int8)
    result[key] = result[4 + value] = result[12 + kind] = result[16] = 1
    return result


@dataclass(frozen=True)
class Posterior:
    worlds: np.ndarray
    hidden: np.ndarray
    missing: tuple
    evidence: float
    profile: Profile
    receipts: tuple = ()

    def marginals(self):
        return np.eye(self.profile.values)[self.worlds].mean(0)

    def gain(self, index):
        """Expected improvement in mean key accuracy from retrieving this token."""
        column = self.missing.index(index)
        before, after = self.marginals().max(1).mean(), 0.
        for code in np.unique(self.hidden[:, column]):
            keep = self.hidden[:, column] == code
            after += keep.mean() * np.eye(self.profile.values)[self.worlds[keep]].mean(0).max(1).mean()
        return float(after - before)

    def acquire(self, index, raw_token):
        """Condition on the retrieved raw token at its original causal position."""
        kind, key, value = decode(raw_token, self.profile)
        revealed = (kind, key, value)
        previous = dict(self.receipts)
        if index in previous:
            if previous[index] != revealed:
                raise ValueError("Conflicting replay of an already acquired raw token")
            return self
        column = self.missing.index(index)
        code = key * self.profile.values + value if kind == 0 else -1
        keep = self.hidden[:, column] == code
        if not keep.any():
            raise ValueError("Actual READ has zero likelihood under this declared model")
        likelihood = keep.mean() / (self.profile.keys * self.profile.values if kind == 2 else 1)
        return Posterior(self.worlds[keep], self.hidden[keep], self.missing,
                         self.evidence * likelihood, self.profile, self.receipts + ((index, revealed),))


def infer(prefix, observed, generator, profile=Profile()):
    """Enumerate the exact conditional latent assignments for a fixed finite law.

    The return retains correlations between missing events and final content.
    Missing distractor key/value draws are analytically marginalized, not filled
    with WRITE hypotheses. Full prefix likelihood is returned for model checks.
    """
    if generator not in ("without_replacement", "with_replacement"):
        raise ValueError("Unknown generator; an explicit finite law is required")
    k, v, u = profile.keys, profile.values, profile.overwrites
    if not (1 <= k <= 4 and 1 <= v <= 8 and 0 <= u <= k and k + u <= v):
        raise ValueError("Unsupported finite profile")
    x, mask = np.asarray(prefix), np.asarray(observed)
    if (x.shape != (2 * k + u, 24) or mask.shape != (len(x),) or mask.dtype != bool
            or not np.isfinite(x).all() or np.any(x[~mask])):
        raise ValueError("Expected raw finite prelude and boolean observation mask")
    known = {i: decode(x[i], profile) for i in np.flatnonzero(mask)}
    initial = {i: event for i, event in known.items() if i < 2 * k and event[0] == 0}
    overwrite = {i: event for i, event in known.items() if i >= 2 * k}
    if any(event[0] != 0 for event in overwrite.values()):
        raise ValueError("The overwrite phase contains a non-WRITE")
    initial_keys = [event[1] for event in initial.values()]
    update_keys = [event[1] for event in overwrite.values()]
    if len(set(initial_keys)) != len(initial_keys) or len(set(update_keys)) != len(update_keys):
        raise ValueError("Repeated keys contradict the declared key schedule")
    seen_values = [event[2] for event in list(initial.values()) + list(overwrite.values())]
    if generator == "without_replacement" and len(set(seen_values)) != len(seen_values):
        raise ValueError("Duplicate WRITE values have zero likelihood without replacement")
    missing = tuple(map(int, np.flatnonzero(~mask)))
    initial_missing = [i for i in missing if i < 2 * k]
    update_missing = [i for i in missing if i >= 2 * k]
    needed = k - len(initial)
    if needed < 0 or needed > len(initial_missing):
        raise ValueError("Observed event kinds contradict the initial schedule")
    final_rows, hidden_rows = [], []
    unseen_keys = sorted(set(range(k)) - set(initial_keys))
    available_update_keys = sorted(set(range(k)) - set(update_keys))
    for slots in combinations(initial_missing, needed):
        write_slots = tuple(slots) + tuple(update_missing)
        for first_keys in permutations(unseen_keys):
            for later_keys in permutations(available_update_keys, len(update_missing)):
                keys = first_keys + later_keys
                choices = (permutations(sorted(set(range(v)) - set(seen_values)), len(write_slots))
                           if generator == "without_replacement" else product(range(v), repeat=len(write_slots)))
                for values in choices:
                    writes = {i: (event[1], event[2]) for i, event in {**initial, **overwrite}.items()}
                    writes.update({i: (key, value) for i, key, value in zip(write_slots, keys, values, strict=True)})
                    final = np.zeros(k, dtype=np.int8)
                    for i in sorted(writes):
                        key, value = writes[i]
                        final[key] = value
                    final_rows.append(final)
                    hidden_rows.append([writes[i][0] * v + writes[i][1] if i in writes else -1 for i in missing])
    if not final_rows:
        raise ValueError("Prefix has zero likelihood")
    observed_distractors = sum(event[0] == 2 for event in known.values())
    likelihood_per_row = (1 / (comb(2 * k, k) * factorial(k)) / perm(k, u)
                          / (perm(v, k + u) if generator == "without_replacement" else v ** (k + u))
                          / (k * v) ** observed_distractors)
    return Posterior(np.asarray(final_rows), np.asarray(hidden_rows, dtype=np.int16).reshape(len(final_rows), len(missing)),
                     missing, len(final_rows) * likelihood_per_row, profile)

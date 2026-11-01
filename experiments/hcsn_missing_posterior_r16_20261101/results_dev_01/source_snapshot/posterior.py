"""Exact ordinary reference for the frozen typed four-address task.

Only task identity and raw observed prefixes enter inference. The reference
knows the published without-replacement generator; it is an additional shared
structural prior, not learned semantic memory or an analytical-cell benefit.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Posterior:
    worlds: np.ndarray
    missing_events: np.ndarray
    aliases: np.ndarray

    def by_address(self):
        return np.eye(8)[self.worlds].mean(0)

    def query(self, event):
        if event.shape != (24,) or event[13] != 1:
            raise ValueError("Expected one raw query")
        if event[19:23].sum() == 1:
            key = int(self.aliases[event[19:23].argmax()])
        elif event[:4].sum() == 1:
            key = int(event[:4].argmax())
        else:
            raise ValueError("Query must contain one observed address")
        if key < 0:
            raise ValueError("Alias relation was not observed")
        return self.by_address()[key]

    def acquire(self, raw_write):
        """Condition on the actual retrieved missing event, with no true label."""
        if (raw_write.shape != (24,) or raw_write[12] != 1
                or raw_write[:4].sum() != 1 or raw_write[4:12].sum() != 1):
            raise ValueError("Expected an acquired raw WRITE")
        pair = np.array([raw_write[:4].argmax(), raw_write[4:12].argmax()])
        keep = (self.missing_events == pair).all(1)
        if not keep.any():
            raise ValueError("Retrieved event has zero likelihood under this profile")
        return Posterior(self.worlds[keep], self.missing_events[keep], self.aliases)

    def value_of_read(self):
        """Gain in expected mean four-query accuracy for this exact READ."""
        before = self.by_address().max(1).mean()
        after = 0.
        for event in np.unique(self.missing_events, axis=0):
            keep = (self.missing_events == event).all(1)
            after += keep.mean() * np.eye(8)[self.worlds[keep]].mean(0).max(1).mean()
        return float(after - before)


def infer(task, prefix, observed):
    """Infer final content before a query, for base or single-WRITE erasure.

    The fixed prelude has eight shuffled initial events, two subsequent
    overwrites in Selective, and four preceding bridges in Binding. Erased
    tokens carry no address or value. Other schedules are rejected.
    """
    lengths = {"mqar": 8, "selective": 10, "binding": 12}
    if task not in lengths:
        raise ValueError("Unknown task")
    x, mask = np.asarray(prefix), np.asarray(observed)
    if (x.shape != (lengths[task], 24) or mask.shape != (len(x),)
            or mask.dtype != bool or not np.isfinite(x).all()
            or not np.isin(x, [0, 1]).all() or np.any(x[~mask])):
        raise ValueError("Expected the exact raw prelude and boolean observation mask")
    if (~mask).sum() > 1:
        raise ValueError("Only the registered single-WRITE erasure is supported")
    aliases = np.full(4, -1, dtype=int)
    offset = 4 if task == "binding" else 0
    if offset:
        for event in x[:4]:
            if event[15] != 1 or event[:4].sum() != 1 or event[19:23].sum() != 1:
                raise ValueError("All four bridge observations are required")
            aliases[event[19:23].argmax()] = event[:4].argmax()
        if sorted(aliases.tolist()) != list(range(4)):
            raise ValueError("The binding map must be a permutation")
    initial = np.full(4, -1, dtype=int)
    updates = []
    values = []
    for index, event in enumerate(x):
        if not mask[index] or index < offset:
            continue
        kind = event[12:16]
        if kind.sum() != 1:
            raise ValueError("Observed event kind is not one-hot")
        if event[12] == 1:
            if event[:4].sum() != 1 or event[4:12].sum() != 1:
                raise ValueError("Malformed WRITE")
            key, value = int(event[:4].argmax()), int(event[4:12].argmax())
            values.append(value)
            if index < offset + 8:
                if initial[key] != -1:
                    raise ValueError("Repeated initial key")
                initial[key] = value
            else:
                updates.append((key, value))
        elif event[14] != 1:
            raise ValueError("Unexpected event in content prelude")
    if len(values) != len(set(values)):
        raise ValueError("Observed WRITE values violate sampling without replacement")
    unseen = sorted(set(range(8)) - set(values))
    absent = np.flatnonzero(~mask)
    worlds, events = [], []
    if not len(absent):
        if np.any(initial < 0) or len(updates) != (2 if task == "selective" else 0):
            raise ValueError("Incomplete unmasked history")
        final = initial.copy()
        for key, value in updates:
            final[key] = value
        return Posterior(final[None], np.full((1, 2), -1), aliases)
    if absent[0] < offset + 8:
        keys = np.flatnonzero(initial < 0)
        if len(keys) != 1 or len(updates) != (2 if task == "selective" else 0):
            raise ValueError("Erasure is not one initial WRITE")
    else:
        if task != "selective" or np.any(initial < 0) or len(updates) != 1:
            raise ValueError("Erasure is not one final overwrite")
        keys = [key for key in range(4) if key != updates[0][0]]
    for key in keys:
        for value in unseen:
            final = initial.copy()
            final[key] = value
            for known_key, known_value in updates:
                final[known_key] = known_value
            worlds.append(final)
            events.append((key, value))
    return Posterior(np.asarray(worlds), np.asarray(events), aliases)


def calibrate(task, x, observed, probabilities):
    """Replace only uncertain predictions with the shared causal posterior.

    Already observed targets retain their original learned probabilities. This
    function does not receive labels, target availability, clocks or fit IDs.
    """
    result = np.asarray(probabilities, dtype=float).copy()
    if x.ndim != 3 or x.shape[:2] != observed.shape or result.shape != (*observed.shape, 8):
        raise ValueError("Incompatible batch dimensions")
    for row in range(len(x)):
        queries = np.flatnonzero((x[row, :, 13] == 1) & observed[row])
        if len(queries) != 4:
            raise ValueError("Exactly four observed queries required")
        first = int(queries[0])
        posterior = infer(task, x[row, :first], observed[row, :first])
        for index in queries:
            p = posterior.query(x[row, index])
            if p.max() < 1:
                result[row, index] = p
    return result

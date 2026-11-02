"""Streaming finite-law posterior using only visible typed events.

This is an explicit ordinary task-law prior. It bypasses the neural content
readout and cannot establish a Flow contribution. Task is a constructor-level
domain declaration shared by both cores. Inference accepts only x/dt/observed;
no target, availability flag, hidden dependency, or world identifier is used.
The source law has four distinct initial values and (Selective) two distinct
new-value updates to distinct keys. Only that frozen law is supported.
"""

import hashlib
import numpy as np


CERTAIN, INITIAL_UNKNOWN, FINAL_AMBIGUOUS = 0, 1, 2
SALT = b"hcsn-r2-fixed-quarter-20261101"


class VisiblePosterior:
    def __init__(self, task, retained_probability=2/3):
        if task not in ("mqar", "selective", "binding"):
            raise ValueError("Unsupported declared task law")
        if not .5 < retained_probability < 1:
            raise ValueError("Retained mixture must be between half and one")
        self.task = task
        self.q = float(retained_probability)

    @staticmethod
    def _index(field):
        if np.count_nonzero(field) != 1 or not np.all((field == 0) | (field == 1)):
            raise ValueError("Exactly one visible typed address/value required")
        return int(field.argmax())

    def forward(self, x, dt, observed):
        if (x.ndim != 3 or x.shape[-1] != 24 or dt.shape != x.shape[:2]
                or observed.shape != dt.shape or observed.dtype != bool
                or not np.isfinite(x).all() or not np.isfinite(dt).all() or (dt < 0).any()):
            raise ValueError("Raw finite x[B,T,24], dt[B,T], boolean observed required")
        n, steps, _ = x.shape
        probability = np.full((n, steps, 8), 1/8, np.float64)
        group = np.full((n, steps), -1, np.int8)
        accepted = np.zeros((n, steps), bool)
        visible_old = np.full((n, steps), -1, np.int8)
        initial_start = 4 if self.task == "binding" else 0
        initial_end = initial_start + 8
        prelude_end = initial_end + (2 if self.task == "selective" else 0)
        for row in range(n):
            initial = np.full(4, -1, np.int8)
            updates = np.full(4, -1, np.int8)
            aliases = np.full(4, -1, np.int8)
            missing_initial = missing_final = 0
            for t in range(steps):
                event = x[row, t]
                if not observed[row, t]:
                    if np.any(event): raise ValueError("Hidden payload in missing slot")
                    if initial_start <= t < initial_end: missing_initial += 1
                    elif self.task == "selective" and initial_end <= t < prelude_end: missing_final += 1
                    else: raise ValueError("Missing slot outside registered one-erasure law")
                    if missing_initial + missing_final > 1: raise ValueError("Only one erased raw write supported")
                    continue
                kind = self._index(event[12:16])
                if kind == 1:
                    if t < prelude_end: raise ValueError("Query before complete registered prelude")
                    if np.any(event[4:12]): raise ValueError("Query carries a raw answer value")
                    old_values=initial[initial >= 0].tolist();new_values=updates[updates >= 0].tolist()
                    if len(set(old_values)) != len(old_values) or len(set(new_values)) != len(new_values) or set(old_values)&set(new_values):
                        raise ValueError("Distinct original/fresh-value law violated")
                    if self.task == "binding":
                        if sorted(aliases.tolist()) != list(range(4)): raise ValueError("Visible bridge law must be bijective")
                        alias = self._index(event[19:23]); key = int(aliases[alias])
                        if key < 0 or np.any(event[:4]): raise ValueError("Unresolved visible B alias")
                    else:
                        key = self._index(event[:4])
                    missing_keys = np.flatnonzero(initial < 0)
                    if len(missing_keys) != missing_initial: raise ValueError("Observed initial-write contract mismatch")
                    if missing_final:
                        if self.task != "selective" or np.count_nonzero(updates >= 0) != 1:
                            raise ValueError("Expected exactly one observed final update")
                        if updates[key] >= 0:
                            p = np.eye(8)[updates[key]]; g = CERTAIN
                        else:
                            excluded = set(initial.tolist()) | set(updates[updates >= 0].tolist())
                            unseen = sorted(set(range(8)) - excluded)
                            if len(unseen) != 3: raise ValueError("Fresh-update distinctness contract mismatch")
                            p = np.zeros(8); p[unseen] = (1-self.q)/3; p[initial[key]] = self.q
                            g = FINAL_AMBIGUOUS; visible_old[row,t] = initial[key]
                    elif updates[key] >= 0 or initial[key] >= 0:
                        label = updates[key] if updates[key] >= 0 else initial[key]
                        p = np.eye(8)[label]; g = CERTAIN
                    else:
                        excluded = set(initial[initial >= 0].tolist()) | set(updates[updates >= 0].tolist())
                        unseen = sorted(set(range(8)) - excluded)
                        expected = 3 if self.task == "selective" else 5
                        if len(unseen) != expected: raise ValueError("Initial-erasure exchangeability contract mismatch")
                        p = np.zeros(8); p[unseen] = 1/len(unseen); g = INITIAL_UNKNOWN
                    probability[row,t] = p; group[row,t] = g
                    # Quarter selection depends only on visible semantic state and current query.
                    # Ignore clocks/filler so equivalent interference preserves the policy.
                    state = bytes(initial.astype(np.uint8)) + bytes(updates.astype(np.uint8))
                    state += bytes(aliases.astype(np.uint8)) + bytes([key, missing_initial, missing_final])
                    coin = int.from_bytes(hashlib.blake2b(SALT+self.task.encode()+state,digest_size=8).digest(), "big")
                    accepted[row,t] = g == CERTAIN or (g == FINAL_AMBIGUOUS and coin < 2**62)
                    continue
                if kind == 2: continue  # Explicit shared distractor type prior.
                key = self._index(event[:4])
                if kind == 3:
                    if self.task != "binding" or t >= initial_start:
                        raise ValueError("Bridge outside registered visible prefix")
                    alias=self._index(event[19:23])
                    if aliases[alias] >= 0 or np.any(event[4:12]): raise ValueError("Invalid bridge")
                    aliases[alias] = key
                else:
                    value = self._index(event[4:12])
                    if initial_start <= t < initial_end:
                        if initial[key] >= 0: raise ValueError("Repeated initial-write key")
                        initial[key] = value
                    elif self.task == "selective" and initial_end <= t < prelude_end:
                        if updates[key] >= 0: raise ValueError("Repeated final-update key")
                        updates[key] = value
                    else: raise ValueError("Write outside registered prelude")
        return dict(probabilities=probability, group=group, accepted=accepted, visible_old=visible_old)

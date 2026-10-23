"""Retain block-specific actual gradients, deltas and inactive state proofs."""

import hashlib

import numpy as np

from content_block.learning import HEADS
from independent.learning import CONTENT_PARAMETERS


def inactive_digest(model):
    digest = hashlib.sha256()
    for key in CONTENT_PARAMETERS[:2]:
        digest.update(model.params[key].tobytes())
        state = model._moments.get(key)
        if state is not None:
            digest.update(state[0].tobytes())
            digest.update(state[1].tobytes())
            digest.update(str(state[2]).encode())
    return digest.hexdigest()


class Evidence:
    def __init__(self, optimizer, ledger):
        self.optimizer, self.ledger = optimizer, ledger
        self.first, self.last, self.deltas, self.counts, self.skip = {}, {}, {}, {}, None

    def apply_gradients(self, model, gradients, lr):
        mode = "heads" if set(gradients) == set(HEADS) else "joint"
        first = mode not in self.first
        before = {k: model.params[k].copy() for k in gradients} if first else None
        skipped = inactive_digest(model) if first and mode == "heads" else None
        if first:
            self.first[mode] = {k:g.copy() for k,g in gradients.items()}
        self.optimizer.apply_gradients(model, gradients, lr)
        self.last[mode] = gradients
        self.counts[mode] = self.counts.get(mode,0)+1
        if first:
            self.ledger.charge_kernel("gradient_evidence", "first_actual_delta", scalar_ops=sum(v.size for v in before.values()))
            self.deltas[mode] = {k:model.params[k]-v for k,v in before.items()}
        if skipped is not None:
            self.skip = {"before_sha256": skipped, "after_sha256": inactive_digest(model)}
            if self.skip["before_sha256"] != self.skip["after_sha256"]:
                raise RuntimeError("heads step mutated encoder parameters/moments/clocks")

    def save(self, path, model, initial, losses):
        arrays = {"loss": np.asarray(losses)}
        for kind, modes in (("first_gradient", self.first), ("last_gradient", self.last), ("first_delta",self.deltas)):
            arrays.update({kind+"/"+mode+"/"+key:value for mode,groups in modes.items() for key,value in groups.items()})
        self.ledger.charge_kernel("gradient_evidence", "final_actual_delta", scalar_ops=sum(v.size for v in initial.values()))
        for key in CONTENT_PARAMETERS:
            arrays["final_delta/"+key] = model.params[key]-initial[key]
            m,v,clock = model._moments[key]
            arrays["first_moment/"+key], arrays["second_moment/"+key] = m,v
            arrays["clock/"+key] = np.array(clock)
        np.savez_compressed(path,**arrays)
        self.ledger.record("gradient_evidence",serialized_bytes=path.stat().st_size)

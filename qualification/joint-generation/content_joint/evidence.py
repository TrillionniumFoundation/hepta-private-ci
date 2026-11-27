"""Real gradient, displacement, clock and moment evidence paid in the ledger."""

import numpy as np

from content_joint.work import evidence_work


class Evidence:
    def __init__(self, model, keys, optimizer, ledger):
        self.keys, self.optimizer, self.ledger = keys, optimizer, ledger
        self.initial = {key: model.params[key].copy() for key in keys}
        self.first, self.first_delta, self.last = None, None, None
        self.norms, self.scales, self.group_norms = [], [], []

    def apply_gradients(self, model, grads, lr):
        elements = sum(g.size for g in grads.values())
        self.ledger.charge_kernel("gradient_evidence", "norm_trace", **evidence_work(elements))
        group = [float(np.sum(grads[key] * grads[key])) for key in self.keys]
        norm = float(np.sqrt(sum(group)))
        self.norms.append(norm)
        self.group_norms.append(group)
        self.scales.append(min(1., 5. / max(norm, 1e-300)))
        first = self.first is None
        if first:
            self.first = {key: grads[key].copy() for key in self.keys}
        self.optimizer.apply_gradients(model, grads, lr)
        self.last = grads
        if first:
            self.ledger.charge_kernel("gradient_evidence", "first_actual_delta", scalar_ops=elements)
            self.first_delta = {key: model.params[key] - self.initial[key] for key in self.keys}

    def save(self, path, model, losses, ce, utility):
        if self.first is None:
            raise RuntimeError("no real parameter update to retain")
        elements = sum(self.initial[key].size for key in self.keys)
        self.ledger.charge_kernel("gradient_evidence", "final_actual_delta", scalar_ops=elements)
        arrays = dict(loss=np.asarray(losses), ce=np.asarray(ce), utility=np.asarray(utility),
                      total_gradient_norm=np.asarray(self.norms), clip_scale=np.asarray(self.scales),
                      squared_gradient_norm_by_group=np.asarray(self.group_norms),
                      group_names=np.asarray(self.keys))
        for tag, values in (("first_gradient", self.first), ("last_gradient", self.last),
                            ("first_delta", self.first_delta)):
            arrays.update({tag + "/" + key: values[key] for key in self.keys})
        for key in self.keys:
            arrays["final_delta/" + key] = model.params[key] - self.initial[key]
            first, second, step = model._moments[key]
            arrays["moment1/" + key] = first
            arrays["moment2/" + key] = second
            arrays["clock/" + key] = np.asarray(step)
        np.savez_compressed(path, **arrays)
        self.ledger.record("gradient_evidence", serialized_bytes=path.stat().st_size)

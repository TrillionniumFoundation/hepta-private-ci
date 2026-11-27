"""One fixed pre-clip CE control variate; the existing NativeAdam remains unchanged."""

import numpy as np

from independent.learning import CONTENT_PARAMETERS
from ndu_training.cv_train_d2.budget import norm_work
from ndu_training.mechanism_readout.anchor_cv import correct, correction_work


class AnchorAdam:
    def __init__(self, native_adam, ledger, reference=None):
        self.native = native_adam
        self.ledger = ledger
        self.reference = reference
        self.pending = None
        self.trace = []

    def bind_batch(self, indices, weights, full, step):
        if self.pending is not None:
            raise RuntimeError("unconsumed optimizer minibatch")
        self.pending = (indices, weights, full, step)

    def norm(self, grads):
        elements = sum(grads[key].size for key in CONTENT_PARAMETERS)
        self.ledger.charge_kernel(
            "search_train", "observed_gradient_norm", **norm_work(elements)
        )
        return float(
            np.sqrt(sum(float(np.sum(value * value)) for value in grads.values()))
        )

    def apply_gradients(self, model, gradients, lr):
        if self.pending is None:
            raise RuntimeError("exact paired minibatch required before update")
        indices, weights, full, step = self.pending
        observe = step == 1 or step % 64 == 0
        raw_norm = self.norm(gradients) if observe else None
        corrected = gradients
        if self.reference is not None:
            self.ledger.charge_kernel(
                "search_train", "reference_index_map", scalar_ops=len(indices)
            )
            selected = indices + np.where(full, 0, len(self.reference.y) // 2)
            batch = self.reference.pull(selected, weights, self.ledger, "search_train")
            elements = sum(value.size for value in gradients.values())
            self.ledger.charge_kernel(
                "search_train", "fixed_anchor_CV", **correction_work(elements)
            )
            corrected = correct(gradients, self.reference.mean, batch)
        changed_norm = (
            self.norm(corrected) if observe and self.reference is not None else raw_norm
        )
        self.native.apply_gradients(model, corrected, lr)
        self.pending = None
        if observe:
            self.trace.append(
                {
                    "step": step,
                    "raw_preclip_norm": raw_norm,
                    "applied_preclip_norm": changed_norm,
                }
            )

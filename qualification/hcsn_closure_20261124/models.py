"""One signed communication path for all prospective factorial arms."""

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig, SmallHCSN


class SignedHCSN(SmallHCSN):
    def __init__(self, config):
        if config.message_mode != "flow":
            raise ValueError("prospective signed experiment requires flow mode")
        super().__init__(config)
        n = config.neurons
        self.synaptic_mask[:, n:2*n] = 0


def make_model(slot):
    return SignedHCSN(ModelConfig(neurons=slot["neurons"],
        boundary_mode=slot["boundary"], feature_bank=slot["features"],
        message_mode="flow", backend="uniformized", precision=slot["precision"]))


def parameter_accounting(model):
    total = sum(v.numel() for v in model.parameters())
    trainable = sum(v.numel() for v in model.parameters() if v.requires_grad)
    n = model.config.neurons
    effective_mask = model.synaptic_mask.detach().clone()
    effective_mask[:, :2*n] = 0
    masked = model.recurrent.weight.numel() - int(torch.count_nonzero(effective_mask))
    return {"total_parameters": total, "requires_grad_parameters": trainable,
            "structurally_active_recurrent_parameters": int(torch.count_nonzero(effective_mask)),
            "trainable_minus_masked_recurrent": trainable - masked,
            "scope": "Masks accounted exactly; this is not a functional rank or identifiability claim."}

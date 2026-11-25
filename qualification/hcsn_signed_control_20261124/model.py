"""Exactly suppress unsigned intercell flow, with a checkpoint-persistent mask."""
import torch
from qualification.hcsn_smallnet_20261124.model import SmallHCSN


def signed_mask(config, like):
    n, half = config.neurons, config.neurons // 2
    topology = torch.ones(n, n, dtype=like.dtype, device=like.device)
    topology[:half, half:] = 0
    mask = topology.repeat(1, 3)
    mask[:, n:2*n] = 0
    return mask


class SignedOnlySmallHCSN(SmallHCSN):
    """Flow config removes boundary; this buffer removes unsigned event flow."""
    def __init__(self, config):
        if config.message_mode != 'flow':
            raise ValueError('signed-only control requires the original flow configuration')
        super().__init__(config)
        with torch.no_grad():
            self.synaptic_mask.copy_(signed_mask(config, self.synaptic_mask))


def verify_state_mask(config, state):
    actual = state['synaptic_mask']
    if config.message_mode != 'flow' or not torch.equal(actual, signed_mask(config, actual)):
        raise ValueError('checkpoint does not have the exact signed-only topology')

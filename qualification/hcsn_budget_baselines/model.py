"""PyTorch GRU with the factorial study's exact frozen semantic interfaces."""

import copy

import torch
from torch import nn

from qualification.hcsn_boundary_factorial.run import FactorialModel, tensor_digest


class BudgetGRU(nn.Module):
    """GRU7 plus a charged trainable 7-to-9 projection, not a tuned strong baseline."""

    def __init__(self, seed, grid):
        super().__init__()
        self.configuration = dict(seed=seed, grid=dict(grid))
        reference = FactorialModel(seed, "c0_b0", width=4, grid=grid)
        self.frontend = copy.deepcopy(reference.frontend)
        self.readout = copy.deepcopy(reference.network.readout)
        self.reference_interfaces = {
            "frontend": tensor_digest(reference.frontend.state_dict()),
            "readout": tensor_digest(reference.network.readout.state_dict()),
        }
        content_names = ("write_gate", "content_proposal", "state_embedding")
        self.ceilings = dict(
            trainable_parameters=sum(p.numel() for name, p in reference.named_parameters()
                                     if any(part in name for part in content_names)
                                     or name.endswith("physics.raw_log_boundary")),
            total_parameters=sum(p.numel() for p in reference.parameters()),
            recurrent_payload_bytes=reference.network.layers[0].state_count * 5 * 8,
        )
        del reference
        with torch.random.fork_rng():
            torch.manual_seed(seed + 7000001)
            self.gru = nn.GRU(4, 7, batch_first=True).double()
            self.projection = nn.Linear(7, 9).double()
        self.frontend.requires_grad_(False)
        self.readout.requires_grad_(False)
        self.capacity = dict(trainable_parameters=sum(p.numel() for p in self.parameters() if p.requires_grad),
                             total_parameters=sum(p.numel() for p in self.parameters()),
                             recurrent_payload_bytes=7 * 8)
        if any(self.capacity[key] > self.ceilings[key] for key in self.capacity):
            raise ValueError("baseline exceeds a declared HCSN joint-arm ceiling")
        if self.interface_digests() != self.reference_interfaces:
            raise AssertionError("common interface bytes changed during copying")

    def interface_digests(self):
        return {"frontend": tensor_digest(self.frontend.state_dict()),
                "readout": tensor_digest(self.readout.state_dict())}

    def forward(self, x, valid):
        if x.ndim != 3 or x.shape[-1] != 21 or valid.shape != x.shape[:2] or valid.dtype != torch.bool:
            raise ValueError("expected 21-feature sequences with an explicit validity mask")
        lengths = valid.sum(1)
        expected = torch.arange(x.shape[1], device=x.device)[None] < lengths[:, None]
        if bool((lengths <= 0).any()) or not torch.equal(valid, expected):
            raise ValueError("only nonempty episodes followed by tail padding are supported")
        encoded = self.frontend(x)
        if bool(valid.all()):
            states, _ = self.gru(encoded)  # Omitted h0 is a new zero state for every episode.
        else:
            packed = nn.utils.rnn.pack_padded_sequence(encoded, lengths.cpu(), batch_first=True,
                                                       enforce_sorted=False)
            packed_states, _ = self.gru(packed)
            states, _ = nn.utils.rnn.pad_packed_sequence(packed_states, batch_first=True,
                                                       total_length=x.shape[1])
            index = torch.minimum(torch.arange(x.shape[1], device=x.device)[None], lengths[:, None] - 1)
            states = states.gather(1, index[..., None].expand(-1, -1, 7))
        logits = self.readout(self.projection(states))
        return torch.where(valid[..., None], logits, torch.zeros_like(logits)), states

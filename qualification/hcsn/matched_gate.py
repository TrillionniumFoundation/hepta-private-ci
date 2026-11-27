"""Parameter-matched ordinary features for the existing HX recurrent cell."""

import torch

from .cells import ValueKernelCell


class MatchedGateCell(ValueKernelCell):
    """Keep every memory/recovery map; replace HX with two learned sigmoid gates.

    The six coefficients per unit occupy the same parameter allocation as the
    six HX physical parameters. All are trainable. The initialized memory,
    readout and other maps therefore agree exactly with HX at a shared seed.
    These coefficients do not represent financial parameters or a free boundary.
    """

    def __init__(self, input_size, hidden_size):
        super().__init__(input_size, hidden_size)

    def _base_boundary(self, params):
        return torch.ones_like(params.principal)

    def _features(self, inputs, memory, params, base_boundary):
        value = 2.4 + 2 * torch.sigmoid(self.margin_input(inputs) + 0.2 * memory)
        shift = 0.25 * torch.tanh(self.boundary_input(inputs))
        x = value.log() - shift
        coefficients = self.raw_financial.reshape(2, 3, self.hidden_size)
        return torch.sigmoid(coefficients[:, 0, None] + coefficients[:, 1, None] * x
                             + coefficients[:, 2, None] * x.square())

"""Exact affine price evaluation at fixed margin atoms for a variable-principal HCSN.

The two price buffers are derived state. Rebuild them after recursive state loading;
copy_reference also preserves the Python law and derived constants absent from a
state_dict. Direct edits to the physical object require an explicit rebuild after
installing a coherent Published law/grid. Arbitrary .data writes are not tracked.
"""
import copy
import torch
from population import BoundaryPopulation


def _rebuild_after_load(module, _incompatible_keys):
    module.rebuild_price_cache()


class AffineBoundaryPopulation(BoundaryPopulation):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.register_buffer('price_center', None)
        self.register_buffer('price_relative_slope', None)
        self.rebuild_price_cache()
        self.register_load_state_dict_post_hook(_rebuild_after_load)

    def rebuild_price_cache(self):
        """Derive prices from the current, coherently installed law and grid."""
        p0 = self.prices.p.P0
        with torch.no_grad():
            prices = self.grid.new_tensor([[.75*p0, p0, 1.25*p0]])
            E, L = super().priced_channels(prices)
            self.price_center = torch.stack([E[0, 1], L[0, 1]], dim=-1)
            self.price_relative_slope = torch.stack(
                [(E[0, 2]-E[0, 0])*2, (L[0, 2]-L[0, 0])*2], dim=-1)

    def priced_channels(self, principal):
        value = self.price_center + (principal/self.prices.p.P0-1)[..., None, None]*self.price_relative_slope
        return value[..., 0], value[..., 1]


def copy_reference(ref):
    n = AffineBoundaryPopulation(
        ref.sender.in_features, ref.width, len(ref.grid), dt=ref.dt,
        reset=float((ref.grid*ref.reset_weights).sum()),
        probe_horizons=ref.probe_horizons)
    # state_dict alone omits Law and Published's derived Python scalars.
    n.prices = copy.deepcopy(ref.prices)
    n.to(ref.grid)
    missing, extra = n.load_state_dict(ref.state_dict(), strict=False)
    assert set(missing) == {'price_center', 'price_relative_slope'} and not extra
    return n

"""Exact affine price evaluation at fixed margin atoms for a variable-principal HCSN."""
import torch
from population import BoundaryPopulation
class AffineBoundaryPopulation(BoundaryPopulation):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        p0=self.prices.p.P0
        with torch.no_grad():
            prices=self.grid.new_tensor([[.75*p0,p0,1.25*p0]])
            E,L=super().priced_channels(prices)
            self.register_buffer('price_center',torch.stack([E[0,1],L[0,1]],dim=-1))
            self.register_buffer('price_relative_slope',torch.stack([(E[0,2]-E[0,0])*2,(L[0,2]-L[0,0])*2],dim=-1))
    def priced_channels(self,principal):
        value=self.price_center+(principal/self.prices.p.P0-1)[...,None,None]*self.price_relative_slope
        return value[...,0],value[...,1]
def copy_reference(ref):
    n=AffineBoundaryPopulation(ref.sender.in_features,ref.width,len(ref.grid),dt=ref.dt,reset=float((ref.grid*ref.reset_weights).sum()),probe_horizons=ref.probe_horizons)
    n.to(ref.grid);missing,extra=n.load_state_dict(ref.state_dict(),strict=False)
    assert set(missing)=={'price_center','price_relative_slope'} and not extra
    return n

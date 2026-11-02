"""FP64 differentiable asset map of the fixed-parameter HX financial equations.

No financial parameter is trained. The neuronal reset is defined elsewhere,
not supplied by HX. This port admits only the declared noncoalescent domain.
"""

import math
import torch
from torch import nn
from experiments.hcsn_hx_unified_v3 import hx


class FinancialMap(nn.Module):
    def __init__(self, parameters=None):
        super().__init__()
        self.p = hx.HX() if parameters is None else parameters
        p = self.p
        if min(abs(p.z-p.a), abs(p.z+p.a), abs(p.z-p.zhat)) < .05:
            raise ValueError("Port excludes coalescent financial parameter regimes")
        self.register_buffer("boundary", torch.tensor(hx.boundary(p), dtype=torch.float64))

    @staticmethod
    def exp_cdf(exponent, argument):
        return torch.exp(exponent + torch.special.log_ndtr(argument))

    def K(self, v, y, beta):
        p = self.p
        u = p.volatility*math.sqrt(p.maturity)
        s = .5*((beta-p.a)**2-y*y)*u*u
        return (torch.exp(-beta*v)*float(hx.ndtr(y*u))
                - self.exp_cdf(s-beta*v, v.new_tensor((beta-p.a)*u))
                + self.exp_cdf(s-beta*v, (-v+(beta-p.a)*u*u)/u)
                - self.exp_cdf(-(p.a+y)*v, (-v+y*u*u)/u))

    def k(self, v, y):
        p = self.p
        beta = -p.eta
        u = p.volatility*math.sqrt(p.maturity)
        s = .5*((beta-p.a)**2-y*y)*u*u
        return (self.exp_cdf(s-beta*v, (-v+(beta-p.a)*u*u)/u)
                - self.exp_cdf(-(p.a+y)*v, (-v+y*u*u)/u))

    def A(self, v, y):
        p = self.p
        return ((self.K(v, y, p.gamma)+self.k(v, -y))/(p.z-y)
                + (self.K(v, -y, p.gamma)+self.k(v, y))/(p.z+y))

    def channels(self, asset, tau=None):
        """Return equity,F,G,bond with source endpoint order and asset gradients."""
        p, boundary = self.p, self.boundary
        if asset.dtype != torch.float64 or not torch.isfinite(asset).all() or (asset <= 0).any():
            raise ValueError("Financial map requires positive finite FP64 assets")
        tau = asset.new_full(asset.shape, p.maturity) if tau is None else torch.broadcast_to(tau, asset.shape)
        if not torch.isfinite(tau).all() or (tau < 0).any() or (tau > p.maturity).any():
            raise ValueError("Financial horizon outside [0,maturity]")
        alive = asset > boundary
        v = torch.clamp(torch.log(asset/boundary), min=0)
        safe_tau = torch.where(tau > 0, tau, torch.ones_like(tau))
        u = p.volatility*torch.sqrt(safe_tau)
        F = torch.special.ndtr((-v-p.a*u*u)/u) + self.exp_cdf(-2*p.a*v, (-v+p.a*u*u)/u)
        G = (self.exp_cdf((-p.a+p.zhat)*v, (-v-p.zhat*u*u)/u)
             + self.exp_cdf((-p.a-p.zhat)*v, (-v+p.zhat*u*u)/u))
        F = torch.where(alive, torch.where(tau > 0, F, torch.zeros_like(F)), torch.ones_like(F))
        G = torch.where(alive, torch.where(tau > 0, G, torch.zeros_like(G)), torch.ones_like(G))
        recovery, base = p.recovery*boundary/p.maturity, p.per_bond_coupon/p.q
        bond = base + torch.exp(-p.q*tau)*(p.per_bond_principal-base)*(1-F) + (recovery-base)*G
        off = p.per_bond_principal-p.per_bond_coupon/p.q
        cash = (1-p.tax_shield)*p.coupon + (-math.expm1(-p.q*p.maturity))*off
        equity = (asset - p.payout*boundary/(p.z*p.volatility**2)*torch.exp(-p.gamma*v)/(p.gamma+1)
                  - cash/(p.z*p.volatility**2)*(1/p.eta+(-torch.expm1(-p.gamma*v))/p.gamma)
                  + (math.exp(-p.q*p.maturity)*off*self.A(v, p.a)
                     - (p.recovery*boundary/p.maturity-p.per_bond_coupon/p.q)*self.A(v, p.zhat))
                  / (p.z*p.volatility**2))
        equity = torch.where(alive, equity, torch.zeros_like(equity))
        result = torch.stack((equity, F, G, bond), -1)
        if not torch.isfinite(result).all() or (equity < -1e-8).any():
            raise ArithmeticError("Financial continuation channel failed its admitted domain")
        return result

    def forward(self, log_asset):
        asset = torch.exp(log_asset)
        E, F, G, debt = self.channels(asset).unbind(-1)
        return torch.stack((log_asset-torch.log(self.boundary), E/asset, F, G,
                            (debt-self.p.per_bond_principal)/self.p.per_bond_principal), -1)

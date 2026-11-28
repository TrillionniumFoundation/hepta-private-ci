"""Run with python -m unittest -v in this directory; no downloaded data required."""
from dataclasses import replace
import math
import unittest

from scipy.integrate import quad
from scipy.stats import norm
import torch

from hepta_spiking import Contract, HeptaContinuousSpikingNetwork, PopulationCell, Prices


class ReferenceChecks(unittest.TestCase):
    def test_financial_contact_and_linear_interpolation(self):
        for premium in (0., .01, .05):
            contract = Contract(premium=premium)
            prices = Prices(contract)
            cell = PopulationCell(2, 3, law=contract)
            self.assertAlmostEqual(prices.equity(0), 0, 12)
            self.assertAlmostEqual(prices.bond(-.2), contract.recovery*prices.boundary*math.exp(-.2)/contract.maturity, 12)
            self.assertLess(abs(prices.equity(1e-6)/1e-6), .001)
            for pfrac in (-.21, -.07, .15, .27):
                actual = Prices(replace(contract, principal=(1+pfrac)*contract.principal))
                self.assertAlmostEqual(math.log(actual.boundary/prices.boundary),
                                       math.log1p(cell.log_wall_gain*pfrac/.28), 13)
                weight = (pfrac/.28+1)/2
                for quotes,fn in ((cell.equity_quotes,actual.equity),(cell.loss_quotes,actual.credit_loss)):
                    expect = torch.tensor([fn(float(x)) for x in cell.grid],dtype=cell.grid.dtype)
                    torch.testing.assert_close(torch.lerp(quotes[0], quotes[1], weight), expect, atol=5e-12, rtol=0)

    def test_absorbed_distribution_against_quadrature(self):
        cell = PopulationCell(1,1,atoms=7)
        for mu in (-1.2,-.02,.8):
            for atom in (0,3,6):
                active=torch.zeros(1,1,7,dtype=torch.float64);active[0,0,atom]=1
                surv,hit=cell._transport(active,torch.full((1,1),mu,dtype=torch.float64))
                x=float(cell.grid[atom]);sd=cell.sigma*math.sqrt(cell.dt)
                def density(y):
                    ratio=-math.expm1(-2*x*y/(sd*sd))
                    return norm.pdf((y-x-mu*cell.dt)/sd)/sd*ratio
                bounds=[0.,*cell.cuts.tolist(),math.inf]
                expected=torch.tensor([quad(density,a,b,epsabs=2e-14,epsrel=1e-13)[0] for a,b in zip(bounds,bounds[1:])],dtype=torch.float64)
                torch.testing.assert_close(surv[0,0],expected,atol=3e-13,rtol=1e-11)
                self.assertLess(abs(hit.item()+expected.sum().item()-1),5e-13)

    def test_streaming_backward_and_wire_ablation(self):
        for dtype,tol in ((torch.float32,3e-6),(torch.float64,3e-13)):
            torch.manual_seed(71)
            model=HeptaContinuousSpikingNetwork(3,5,2,atoms=9,dtype=dtype)
            x=torch.randn(15,2,3,dtype=dtype,requires_grad=True)
            full,state=model(x)
            first,s0=model(x[:7]);second,split_state=model(x[7:],s0)
            torch.testing.assert_close(full,torch.cat((first,second)),rtol=0,atol=0)
            for a,b in zip(state,split_state):
                for v,w in zip(a,b):torch.testing.assert_close(v,w,rtol=0,atol=0)
                torch.testing.assert_close(a.active.sum(-1)+a.refractory,torch.ones_like(a.refractory),atol=tol,rtol=0)
            full[-1].square().sum().backward()
            for p in model.parameters():
                self.assertIsNotNone(p.grad)
                self.assertTrue(torch.isfinite(p.grad).all())
            self.assertGreater(x.grad[0].abs().max(),0.)
            self.assertGreater(model.cells[0].force_logits.grad.abs().max(),0.)
            def disconnect(_mod,args):
                return (torch.zeros_like(args[0]),)
            # Only the upper input projection receives the lower layer's wire.
            hook=model.cells[1].input_projection.register_forward_pre_hook(disconnect)
            a,_=model(x.detach());b,_=model(-x.detach())
            hook.remove()
            torch.testing.assert_close(a,b,rtol=0,atol=0)

    def test_ordinary_bp_and_early_input_derivative(self):
        torch.manual_seed(170)
        model=HeptaContinuousSpikingNetwork(2,3,2,atoms=7)
        x=torch.randn(7,2,2,dtype=torch.float64,requires_grad=True)
        def objective(inp):
            out,_=model(inp)
            return out[-1,1,0]
        g=torch.autograd.grad(objective(x),x)[0][1,1,0]
        delta=torch.zeros_like(x);delta[1,1,0]=1e-5
        with torch.no_grad():numeric=(objective(x+delta)-objective(x-delta))/(2e-5)
        self.assertAlmostEqual(g.item(),numeric.item(),8)
        opt=torch.optim.Adam(model.parameters(),lr=.001)
        before=model.cells[0].input_projection.weight.detach().clone()
        y,_=model(x)
        torch.nn.functional.cross_entropy(y[-1],torch.tensor([1,0])).backward()
        opt.step()
        self.assertGreater((model.cells[0].input_projection.weight-before).abs().max(),0.)


if __name__=="__main__":
    unittest.main()

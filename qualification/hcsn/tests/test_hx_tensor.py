"""HX tensor checks against independent FP64 integration and model identities."""

from dataclasses import asdict, fields, replace
import itertools
import math
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr, roots_laguerre

from qualification.hcsn import reference

try:
    import torch
except ModuleNotFoundError:
    torch = None

if torch is not None:
    from qualification.hcsn import tensor as hx


_FIELDS = tuple(field.name for field in fields(reference.HXParams))


def _params_from_vector(vector):
    return hx.HXParams(**dict(zip(_FIELDS, vector)))


def _reference_derivative(function, value, step):
    return (function(value-2*step)-8*function(value-step)+8*function(value+step)
            -function(value+2*step))/(12*step)


@unittest.skipIf(torch is None,"PyTorch is required; the CI job treats its absence as a failure")
class HXTorchTests(unittest.TestCase):
    def test_normal_tail_integral_and_zero_lambda_gradient(self):
        for dtype,tolerance in ((torch.float64,3e-11),(torch.float32,5e-6)):
            for lam,u,s in itertools.product((-2.0,-1e-8,0.0,1e-8,2.0),(-4.0,0.2,3.0),(0.3,)):
                tensor_lambda=torch.tensor(lam,dtype=dtype,requires_grad=True)
                actual=hx.normal_tail_integral(tensor_lambda,u,s)
                expected=quad(lambda y:math.exp(-lam*y)*ndtr(u*s-y/s),
                              0,8,epsabs=1e-13,epsrel=1e-12)[0]
                expected_derivative=-quad(lambda y:y*math.exp(-lam*y)*ndtr(u*s-y/s),
                                          0,8,epsabs=1e-13,epsrel=1e-12)[0]
                gradient=torch.autograd.grad(actual,tensor_lambda)[0]
                self.assertTrue(bool(torch.isfinite(gradient)))
                self.assertAlmostEqual(actual.item(),expected,delta=tolerance*(1+abs(expected)))
                self.assertAlmostEqual(gradient.item(),expected_derivative,
                                       delta=4*tolerance*(1+abs(expected_derivative)))

    def test_zero_lambda_deep_tail_has_finite_log_gradients(self):
        # Positive Laguerre integration is independent of the continued fraction.
        nodes,weights=roots_laguerre(64)
        for dtype,tolerance in ((torch.float64,2e-11),(torch.float32,3e-6)):
            for w,s in ((-5.0,0.3),(-20.0,0.1),(-100.0,0.001),(-1000.0,0.001)):
                lam=torch.tensor(0.0,dtype=dtype,requires_grad=True)
                u=torch.tensor(w/s,dtype=dtype,requires_grad=True)
                scale=torch.tensor(s,dtype=dtype,requires_grad=True)
                actual=hx._log_normal_tail_integral(lam,u,scale)
                a=-w
                integral=np.sum(weights*nodes*np.exp(-nodes*nodes/(2*a*a)))
                expected=math.log(s)-a*a/2-math.log(2*math.pi)/2-2*math.log(a)+math.log(integral)
                self.assertAlmostEqual(actual.item(),expected,delta=tolerance*(1+abs(expected)))
                for gradient in torch.autograd.grad(actual,(lam,u,scale)):
                    self.assertTrue(bool(torch.isfinite(gradient)))

    def test_elementary_q_derivatives_against_complex_contour(self):
        # Cauchy's integral formula extracts derivatives without copying the
        # implementation's Hermite recurrence or unstable high-order differences.
        theta=2*np.pi*np.arange(128)/128
        for a,u,s in ((0.4,-2.0,0.3),(0.4,-0.4,0.3),(0.4,0.4,0.3),
                      (0.4,2.0,0.3),(0.0,0.0,0.3)):
            radius=0.6/(1+abs(a+u)+1/s)
            points=radius*np.exp(1j*theta)
            function=np.exp(-(a+u)*points)*ndtr(u*s-points/s)
            expected=[math.factorial(n)/radius**n*np.mean(function*np.exp(-1j*n*theta)).real
                      for n in range(7)]
            for dtype,tolerance in ((torch.float64,3e-7),(torch.float32,4e-4)):
                inputs=[torch.tensor(value,dtype=dtype) for value in (u,a,s)]
                actual=hx._q_derivatives(*inputs)
                for got,target in zip(actual,expected):
                    self.assertAlmostEqual(got.item(),target,delta=tolerance*(1+abs(target)))

    def test_closed_values_against_independent_oracle_grid(self):
        baseline=reference.HXParams()
        margins=np.array([0.01,0.1,0.5,2.0])
        for sigma,maturity,ell in itertools.product((0.05,0.2,0.7),(0.05,1.0,10.0),
                                                   (0.0,1e-10,0.01,0.3)):
            par=replace(baseline,sigma=sigma,maturity=maturity,ell=ell)
            expected_boundary=reference.hx_boundary(par)
            expected=reference.hx_equity(margins,par)
            # This stress grid deliberately includes formal roots violating
            # limited liability. It is a numerical identity test, with explicit
            # opt-out of the economic guard for those diagnostic cases.
            feasibility=reference.parameter_feasibility(par)
            validate=feasibility["local_admissible"] and bool(np.all(expected>=0))
            for dtype,tolerance in ((torch.float64,3e-8),(torch.float32,5e-4)):
                vector=torch.tensor(list(asdict(par).values()),dtype=dtype)
                tensor_par=_params_from_vector(vector)
                boundary=hx.hx_boundary(tensor_par,validate=validate)
                actual=hx.hx_equity(torch.tensor(margins,dtype=dtype),tensor_par,validate=validate)
                self.assertEqual(actual.dtype,dtype)
                self.assertEqual(boundary.dtype,dtype)
                self.assertTrue(bool(torch.isfinite(actual).all()))
                self.assertAlmostEqual(boundary.item(),expected_boundary,
                                       delta=tolerance*(1+abs(expected_boundary)))
                np.testing.assert_allclose(actual.detach().cpu().numpy(),expected,
                                           atol=tolerance,rtol=tolerance)

    def test_boundary_and_equity_parameter_gradcheck(self):
        values=list(asdict(reference.HXParams()).values())
        parameters=torch.tensor(values,dtype=torch.float64,requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(
            lambda theta:hx.hx_boundary(_params_from_vector(theta)),(parameters,),
            eps=1e-6,atol=3e-6,rtol=4e-5))
        x=torch.tensor([0.003,0.3],dtype=torch.float64,requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(
            lambda margin,theta:hx.hx_equity(margin,_params_from_vector(theta)),(x,parameters),
            eps=1e-6,atol=5e-6,rtol=8e-5))

    def test_fp32_parameter_gradients_against_reference_finite_differences(self):
        baseline=reference.HXParams()
        values=list(asdict(baseline).values())
        for margin in (0.003,0.3):
            vector=torch.tensor(values,dtype=torch.float32,requires_grad=True)
            value=hx.hx_equity(torch.tensor(margin,dtype=torch.float32),_params_from_vector(vector))
            gradients=torch.autograd.grad(value,vector)[0]
            for name,parameter,gradient in zip(_FIELDS,values,gradients):
                step=max(abs(parameter),0.01)*1e-4
                expected=_reference_derivative(
                    lambda current:reference.hx_equity(margin,replace(baseline,**{name:current})),
                    parameter,step)
                self.assertTrue(bool(torch.isfinite(gradient)))
                self.assertAlmostEqual(gradient.item(),expected,delta=3e-3*(1+abs(expected)))

    def test_zero_liquidity_boundary_gradient(self):
        par=reference.HXParams(ell=0)
        step=1e-4
        values=[reference.hx_boundary(replace(par,ell=k*step)) for k in range(5)]
        expected=(-25*values[0]+48*values[1]-36*values[2]+16*values[3]-3*values[4])/(12*step)
        for dtype,tolerance in ((torch.float64,2e-6),(torch.float32,4e-4)):
            ell=torch.tensor(0.0,dtype=dtype,requires_grad=True)
            tensor_par=hx.HXParams(**dict(asdict(par),ell=ell))
            boundary=hx.hx_boundary(tensor_par)
            gradient=torch.autograd.grad(boundary,ell)[0]
            self.assertTrue(bool(torch.isfinite(gradient)))
            self.assertAlmostEqual(gradient.item(),expected,delta=tolerance*(1+abs(expected)))

    def test_boundary_value_slope_and_curvature(self):
        for par in (reference.HXParams(),reference.HXParams(ell=0),
                    reference.HXParams(delta=0.03,ell=0)):
            boundary=reference.hx_boundary(par)
            running=(par.delta*boundary-(1-par.tax)*par.coupon
                     +par.recovery*boundary/par.maturity-par.p)
            expected_curvature=-2*running/par.sigma**2
            for dtype,tolerance in ((torch.float64,3e-10),(torch.float32,3e-5)):
                x=torch.tensor(0.0,dtype=dtype,requires_grad=True)
                tensor_par=_params_from_vector(torch.tensor(list(asdict(par).values()),dtype=dtype))
                value=hx.hx_equity(x,tensor_par)
                slope=torch.autograd.grad(value,x,create_graph=True)[0]
                curvature=torch.autograd.grad(slope,x)[0]
                self.assertEqual(value.item(),0)
                self.assertEqual(slope.item(),0)
                self.assertAlmostEqual(curvature.item(),expected_curvature,
                                       delta=tolerance*(1+abs(expected_curvature)))

    def test_debt_pde_and_equity_ode_with_autograd(self):
        for par in (reference.HXParams(),reference.HXParams(ell=0),
                    reference.HXParams(delta=0.03,ell=0)):
            p=hx.HXParams(**asdict(par))
            boundary=reference.hx_boundary(par)
            for margin in (0.003,0.1,0.5):
                x=torch.tensor(margin,dtype=torch.float64,requires_grad=True)
                time=torch.tensor(0.7,dtype=torch.float64,requires_grad=True)
                debt=hx.hx_debt(x,time,p)
                debt_x,debt_t=torch.autograd.grad(debt,(x,time),create_graph=True)
                debt_xx=torch.autograd.grad(debt_x,x)[0]
                debt_residual=debt_t-par.mu*debt_x-par.sigma**2/2*debt_xx-par.c+par.q*debt
                self.assertLess(abs(debt_residual.item()),2e-8)
                equity=hx.hx_equity(x,p)
                equity_x=torch.autograd.grad(equity,x,create_graph=True)[0]
                equity_xx=torch.autograd.grad(equity_x,x)[0]
                running=(par.delta*boundary*torch.exp(x)-(1-par.tax)*par.coupon
                         +hx.hx_debt(x,par.maturity,p)-par.p)
                residual=par.r*equity-par.mu*equity_x-par.sigma**2/2*equity_xx-running
                self.assertLess(abs(residual.item()),3e-7)

    def test_custom_boundary_retains_nonzero_slope(self):
        par=reference.HXParams()
        boundary=1.1*reference.hx_boundary(par)
        eta=par.roots()[3]
        integral=par.delta*boundary/(eta-1)+quad(lambda y:math.exp(-eta*y)*(
            -(1-par.tax)*par.coupon+reference.hx_debt(y,par.maturity,par,boundary)-par.p),
            0,np.inf,epsabs=1e-11)[0]
        expected_slope=2*integral/par.sigma**2
        x=torch.tensor(0.0,dtype=torch.float64,requires_grad=True)
        value=hx.hx_equity(x,hx.HXParams(**asdict(par)),boundary=boundary)
        slope=torch.autograd.grad(value,x)[0]
        self.assertAlmostEqual(slope.item(),expected_slope,delta=2e-9)
        self.assertGreater(abs(slope.item()),1)
        for margin in (0.003,0.3):
            actual=hx.hx_equity(torch.tensor(margin,dtype=torch.float64),
                                hx.HXParams(**asdict(par)),boundary=boundary)
            self.assertAlmostEqual(actual.item(),reference.hx_equity(margin,par,boundary),delta=2e-8)

    def test_economic_guard_distinguishes_formal_solution(self):
        invalid=reference.HXParams(sigma=0.2,maturity=0.05,ell=0.3)
        p=hx.HXParams(**asdict(invalid))
        with self.assertRaises(ValueError):
            hx.hx_boundary(p)
        with self.assertRaises(ValueError):
            hx.hx_equity(0.01,p)
        actual=hx.hx_equity(0.01,p,validate=False)
        self.assertLess(actual.item(),0)
        self.assertAlmostEqual(actual.item(),reference.hx_equity(0.01,invalid),delta=2e-8)

    def test_evaluate_preserves_fp32_near_boundary_distance(self):
        parameters=_params_from_vector(torch.tensor(list(asdict(reference.HXParams()).values()),
                                                   dtype=torch.float32))
        boundary=hx.hx_boundary(parameters)
        value=torch.nextafter(boundary,torch.full_like(boundary,float("inf")))
        actual=hx.evaluate(value,parameters,torch.tensor(0.5,dtype=torch.float32))
        x=math.log1p((value.item()-boundary.item())/boundary.item())
        running=(parameters.delta.item()*boundary.item()
                 -(1-parameters.tax.item())*parameters.coupon.item()
                 +parameters.recovery.item()*boundary.item()/parameters.maturity.item()
                 -parameters.principal.item()/parameters.maturity.item())
        expected=-running/parameters.sigma.item()**2*x*x
        self.assertGreater(expected,0)
        self.assertAlmostEqual(actual["E_HX"].item()/expected,1,delta=8e-5)
        self.assertEqual(actual["first_passage_atom"].item(),0)

    def test_full_hx_time_unit_covariance(self):
        baseline=reference.HXParams()
        for dtype,tolerance in ((torch.float64,3e-10),(torch.float32,8e-5)):
            x=torch.tensor([0.003,0.2,2.0],dtype=dtype)
            original=_params_from_vector(torch.tensor(list(asdict(baseline).values()),dtype=dtype))
            original_values=(hx.hx_boundary(original),hx.hx_equity(x,original),
                             hx.hx_debt(x,0.7,original))
            for scale in (0.1,10.0):
                transformed=replace(baseline,r=baseline.r/scale,delta=baseline.delta/scale,
                                    ell=baseline.ell/scale,coupon=baseline.coupon/scale,
                                    sigma=baseline.sigma/math.sqrt(scale),maturity=baseline.maturity*scale)
                par=_params_from_vector(torch.tensor(list(asdict(transformed).values()),dtype=dtype))
                actual=(hx.hx_boundary(par),hx.hx_equity(x,par),scale*hx.hx_debt(x,0.7*scale,par))
                for first,second in zip(original_values,actual):
                    torch.testing.assert_close(first,second,atol=tolerance,rtol=tolerance)


if __name__ == "__main__":
    unittest.main()

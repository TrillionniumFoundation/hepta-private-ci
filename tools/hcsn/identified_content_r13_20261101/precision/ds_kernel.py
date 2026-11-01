"""Full unchanged HX equations with a separately named two-FP32 AD backend."""

import importlib.util
from pathlib import Path

import numpy as np

import ds_math as dm
import green

UP = Path(__file__).resolve().parents[2]/"calibrated_operator_r11_20261031"/"numerics"
SPEC = importlib.util.spec_from_file_location("r13_private_hx_ds", UP/"kernel.py")
k = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(k)


class Dual:
    __array_priority__ = 3000

    def __init__(self, value, tangent):
        self.v, self.g = dm.DS.of(value), dm.DS.of(tangent)

    def coerce(self, other):
        return other if isinstance(other, Dual) else Dual(other, np.zeros_like(self.g.h))

    def __add__(self, other):
        other = self.coerce(other)
        return Dual(self.v+other.v, self.g+other.g)

    __radd__ = __add__

    def __neg__(self):
        return Dual(-self.v, -self.g)

    def __sub__(self, other):
        return self+(-self.coerce(other))

    def __rsub__(self, other):
        return self.coerce(other)-self

    def __mul__(self, other):
        other = self.coerce(other)
        return Dual(self.v*other.v, self.g*other.v+self.v*other.g)

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self.coerce(other)
        value = self.v/other.v
        return Dual(value, (self.g-value*other.g)/other.v)

    def __rtruediv__(self, other):
        return self.coerce(other)/self

    def __pow__(self, power):
        if power == 0:
            return self.coerce(1)
        return Dual(self.v**power, power*(self.v**(power-1))*self.g)


def exp(x):
    value = dm.exp(x.v)
    return Dual(value, value*x.g)


def expm1(x):
    return Dual(dm.expm1(x.v), dm.exp(x.v)*x.g)


def log(x):
    return Dual(dm.log(x.v), x.g/x.v)


def sqrt(x):
    value = dm.sqrt(x.v)
    return Dual(value, x.g/(2*value))


def Phi(x):
    value = dm.exp(dm.logcdf(x.v))
    return Dual(value, dm.exp(-x.v*x.v/2)/dm.C["sqrt_2pi"]*x.g)


def logPhi(x):
    value = dm.logcdf(x.v)
    return Dual(value, dm.exp(-x.v*x.v/2-dm.C["log_sqrt_2pi"]-value)*x.g)


def exp_phi(exponent, argument):
    return exp(argument.coerce(exponent)-argument*argument/2)/dm.C["sqrt_2pi"]


for name in ("Dual", "exp", "expm1", "log", "sqrt", "Phi", "logPhi", "exp_phi"):
    setattr(k, name, globals()[name])
k._NODES, k._WEIGHTS = zip(*dm.GAUSS)
MODEL=green.model_class(k,[(dm.DS(*x),dm.DS(*w)) for x,w in green.NODES])


def evaluate(theta, state, *, coordinate="log_distance", jacobian=True,
             diagnostic_outside_box=False):
    """Quantize inputs once; compute value and AD in two FP32 parts, return FP32."""
    theta, state = np.asarray(theta,dtype=np.float32), np.float32(state)
    if theta.shape != (9,) or not np.isfinite(theta).all() or not np.isfinite(state):
        raise ValueError("Expected finite inputs")
    if coordinate not in ("asset", "log_distance") or state < 0:
        raise ValueError("Invalid coordinate")
    if not diagnostic_outside_box and (np.any(theta<k.LOWER.astype(np.float32)) or np.any(theta>k.UPPER.astype(np.float32))):
        raise ValueError("Outside original parameter box")
    basis = np.eye(10,dtype=np.float32) if jacobian else np.empty((10,0),dtype=np.float32)
    model = MODEL([Dual(v,basis[i]) for i,v in enumerate(theta)])
    arg = Dual(state,basis[-1])
    x = log(arg/model.b) if coordinate == "asset" else arg
    if coordinate == "asset" and x.v <= 0:
        e,f,g = x.coerce(0),x.coerce(1),x.coerce(1)
        debt = model.alpha*model.b/model.m
    else:
        e = model.equity(x)
        f,g = model.first_hit(x,model.m)
        debt = model.c/model.R+model.discount*model.q*(1-f)
        debt += (model.alpha*model.b/model.m-model.c/model.R)*g
    result = [model.b,e,f,g,debt]
    return (np.asarray([t.v.h+t.v.l for t in result],dtype=np.float32),
            np.asarray([t.g.h+t.g.l for t in result],dtype=np.float32))

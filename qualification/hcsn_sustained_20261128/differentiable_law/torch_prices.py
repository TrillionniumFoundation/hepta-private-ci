"""Batched closed-resolvent stationary He–Xiong prices and endogenous boundary.

Each argument is broadcastable to log_margin and may carry an autograd graph.
Rates, payout, sigma and maturity must be positive, and premium nonnegative.
Use float64 for quantitative derivatives, particularly near absorption.
"""
import math
from typing import NamedTuple

import torch


class Quote(NamedTuple):
    boundary: torch.Tensor
    equity: torch.Tensor
    credit_loss: torch.Tensor
    hit: torch.Tensor
    discounted_hit: torch.Tensor


def _tail_integral(k, a, width):
    # Integral_0^inf exp(-k*y) Phi((a-y)/width) dy. Taylor around k=0
    # also supplies the derivative at removable singularities.
    z = a/width
    pdf = torch.exp(-0.5*z.square()) / math.sqrt(2*math.pi)
    cdf = torch.special.ndtr(z)
    m0 = a*cdf + width*pdf
    m1 = ((a.square()+width.square())*cdf+a*width*pdf)/2
    m2 = ((a.pow(3)+3*a*width.square())*cdf+(a.square()+2*width.square())*width*pdf)/3
    small = k.abs() * torch.maximum(torch.maximum(a.abs(), width), torch.ones_like(k)) < 2e-5
    denom = torch.where(small, torch.ones_like(k), k)
    first = torch.special.log_ndtr(z)
    second = -k*a+0.5*(k*width).square()+torch.special.log_ndtr(z-k*width)
    # Signed stable difference; expm1 only receives nonpositive arguments.
    hi = torch.maximum(first,second)
    delta = second-first
    ratio = torch.where(delta<=0,-torch.expm1(delta.clamp_max(0)),
                         torch.expm1((-delta).clamp_max(0)))
    general = torch.exp(hi)*ratio/denom
    return torch.where(small,m0-k*m1+0.5*k.square()*m2,general)


def _exp_integral(k, lo, hi):
    if hi is None:
        return torch.exp(-k*lo)/k
    distance=hi-lo
    z=-k*distance
    small=z.abs()<2e-5
    safe=torch.where(small,torch.ones_like(z),z)
    exprel=torch.where(small,1+z/2+z.square()/6+z.pow(3)/24,torch.expm1(z)/safe)
    return torch.exp(-k*lo)*distance*exprel


def price(log_margin, rate, payout, sigma, tax, recovery, coupon, principal, maturity, premium):
    x,r,delta,sigma,tax,recovery,C,P,T,premium=torch.broadcast_tensors(
            log_margin,rate,payout,sigma,tax,recovery,coupon,principal,maturity,premium)
    positive=x>0
    x=x.clamp_min(0)
    q=r+premium
    var=sigma.square()
    mu=r-delta-.5*var
    width=sigma*torch.sqrt(T)
    speed=torch.sqrt(mu.square()+2*r*var)
    eta=2*r/(speed+mu)
    gamma=(speed+mu)/var
    c=C/T
    par=P/T
    A=torch.exp(-q*T)*(par-c/q)
    # The two first-passage images are invariant to permuting the signed
    # root. Use signed mu for the undiscounted case to avoid an abs(0) kink.
    def terms(speed_q):
        return (((mu+speed_q)/var,speed_q*T),((mu-speed_q)/var,-speed_q*T))
    first=terms(mu)
    discounted=terms(torch.sqrt(mu.square()+2*q*var))
    def hit_integral(images,k,lo,hi):
        total=torch.zeros_like(x)
        for b,a in images:
            m=k+b
            val=torch.exp(-m*lo)*_tail_integral(m,a-lo,width)
            if hi is not None:
                val=val-torch.exp(-m*hi)*_tail_integral(m,a-hi,width)
            total=total+val
        return total
    def hit(images):
        h=sum(torch.exp(-b*x+torch.special.log_ndtr((a-x)/width)) for b,a in images)
        return torch.where(positive,h,torch.ones_like(h))
    zero=torch.zeros_like(x)
    Fi=hit_integral(first,eta,zero,None)
    Gi=hit_integral(discounted,eta,zero,None)
    B=(((1-tax)*C+par-c/q)/eta-A*(1/eta-Fi)+(c/q)*Gi)/(delta/(eta-1)+recovery*Gi/T)
    F=hit(first)
    G=hit(discounted)
    loss=A*F+(c/q-recovery*B/T)*G
    def cash(k,lo,hi):
        const=-(1-tax)*C+c/q+A-par
        return (delta*B*_exp_integral(k-1,lo,hi)+const*_exp_integral(k,lo,hi)
                -A*hit_integral(first,k,lo,hi)+(recovery*B/T-c/q)*hit_integral(discounted,k,lo,hi))
    E=(torch.exp(-gamma*x)*cash(-gamma,zero,x)+torch.exp(eta*x)*cash(eta,x,None))/speed
    return Quote(B,torch.where(positive,E,zero),loss,F,G)

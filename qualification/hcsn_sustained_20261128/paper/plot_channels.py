"""Render the two financial values and the one-year firing probability from Table I."""
from pathlib import Path
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.integrate import solve_ivp

from hx_reference import hit, paper_row


def channels(values,intensity):
    row=paper_row(intensity)
    b=row["boundary"]
    rf,delta,sigma,tax,recovery,coupon,par=.08,.02,.23,.27,.60,6.39,61.68
    mu=rf-delta-.5*sigma**2
    q=rf+.01*intensity
    d0=coupon/q+math.exp(-q)*(par-coupon/q)
    x=np.maximum(0,np.log(values/b))

    def prices(margin):
        f=hit(margin,1.,mu,sigma)
        g=hit(margin,1.,mu,sigma,q)
        d=coupon/q+math.exp(-q)*(par-coupon/q)*(1-f)+(recovery*b-coupon/q)*g
        return d,f

    def ode(margin,y):
        debt,_=prices(margin)
        cash=delta*b*math.exp(margin)-(1-tax)*coupon+debt-par
        return y[1],2*(rf*y[0]-mu*y[1]-cash)/sigma**2

    sol=solve_ivp(ode,(0,float(max(x))),(0.,0.),dense_output=True,rtol=1e-11,atol=1e-13)
    if not sol.success:
        raise ValueError(sol.message)
    e=sol.sol(x)[0]
    pairs=np.array([prices(z) for z in x])
    ix=np.where(values==100.)[0][0]
    if max(abs(e[ix]-row["equity_at_100"]),abs(pairs[ix,1]-row["one_year_passage"]))>1e-7:
        raise ValueError("table calibration mismatch")
    return b,e,d0-pairs[:,0],pairs[:,1]


if __name__=="__main__":
    val=np.linspace(55,125,561)
    fig,axs=plt.subplots(1,3,figsize=(10.8,3.8),sharex=True)
    colors=("#236e82","#bc592c")
    labels=("Equity, $E$","Credit loss, $d_0-d$","One-year first-hit probability, $F$")
    for intensity,color in zip((1,4),colors):
        b,*ys=channels(val,intensity)
        for ax,y in zip(axs,ys):
            ax.plot(val,y,color=color,lw=2.5,label=fr"$\xi={intensity},\;B={b:.2f}$")
            ax.axvline(b,color=color,lw=.9,ls="--",alpha=.8)
    for ax,label in zip(axs,labels):
        ax.set_title(label,loc="left",fontweight="bold",fontsize=11)
        ax.set_xlabel("State $V$")
        ax.set_xlim(55,125)
        ax.grid(axis="y",alpha=.2)
        ax.spines[["top","right"]].set_visible(False)
    axs[-1].set_ylim(-.03,1.04)
    fig.legend(*axs[0].get_legend_handles_labels(),loc="lower center",frameon=False,ncols=2)
    fig.subplots_adjust(left=.055,right=.99,bottom=.25,top=.90,wspace=.26)
    fig.savefig(Path(__file__).with_name("channels.png"),dpi=160,facecolor="white")

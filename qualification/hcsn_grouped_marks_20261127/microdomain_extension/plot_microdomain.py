"""Reproduce the transfer curves and the fixed-weight empirical comparison."""
from pathlib import Path
import json,math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.special import ndtr


def main():
    root=Path(__file__).parent;results=json.loads((root/'frozen_results.json').read_text())['summary'];sig=.23;mu=.03355;T=.25;reset=.30;s=sig*math.sqrt(T);d=mu*T
    colors={1:'#596877',2:'#005f73',4:'#b24c20'};styles={1:'--',2:'-',4:'-.'}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9.5,'axes.labelsize':10,'axes.titlesize':10.5,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white','axes.facecolor':'white'})
    fig,axes=plt.subplots(2,2,figsize=(9,6.4),layout='constrained');(p,g),(m,e)=axes
    x=np.linspace(0,.42,1201);neg=np.linspace(-.045,0.,40)
    refl=np.exp(-2*mu*x/sig**2);h=refl*ndtr((d-x)/s);f=ndtr((-x-d)/s)+h;surv=1-f
    phi=lambda z:np.exp(-z*z/2)/np.sqrt(2*np.pi)
    df=-phi((-x-d)/s)/s-2*mu/sig**2*h-refl*phi((d-x)/s)/s
    first=(x+d)*surv+2*x*h
    for n in [1,2,4]:
        q=1-surv**n;step=first*surv**(n-1)+reset*q;dt=n*surv**(n-1)*df
        for ax,val,absorbed in [(p,q,1.),(g,dt,0.),(m,step,reset)]:
            ax.plot(neg,np.full_like(neg,absorbed),styles[n],color=colors[n],lw=1.7)
            ax.plot(x,val,styles[n],color=colors[n],lw=1.7,label=f'n = {n}')
    for a in [p,g,m]:a.axvline(0,color='#a5aaae',lw=.8,zorder=0);a.grid(axis='y',alpha=.15);a.set_xlabel('Starting log distance to the wall, x')
    p.set(xlim=(-.04,.42),ylim=(-.02,1.04),ylabel='Release probability');p.set_title('A   First hit before the horizon',loc='left',fontweight='bold');p.legend(frameon=False,loc='upper right')
    g.set(xlim=(-.025,.15),ylabel='Probability derivative per log-distance');g.set_title('B   Wall sensitivity',loc='left',fontweight='bold')
    m.set(xlim=(-.04,.42),ylabel='Expected next log distance');m.set_title('C   Consistent reset and survival',loc='left',fontweight='bold')
    vals=[results[str(n)]['minus_n1']*1000 for n in [2,4]];lo=[results[str(n)]['paired_image_95'][0]*1000 for n in [2,4]];hi=[results[str(n)]['paired_image_95'][1]*1000 for n in [2,4]]
    for y,n,v,l,hv in zip([1,0],[2,4],vals,lo,hi):e.errorbar(v,y,xerr=[[v-l],[hv-v]],fmt='o',color=colors[n],elinewidth=2.2,capsize=4,ms=6)
    e.axvline(0,color='#586470',lw=1,ls=':');e.set(yticks=[0,1],yticklabels=['n = 4','n = 2'],ylim=(-.7,1.7),xlabel='NLL difference vs n = 1 (×10⁻³ nats/token)',xlim=(-.65,1.));e.set_title('D   Frozen captioner substitution',loc='left',fontweight='bold');e.grid(axis='x',alpha=.15)
    e.text(.02,.05,'256 validation photos · 3 fixed models\n95% paired image bootstrap intervals',transform=e.transAxes,fontsize=8,color='#46535d')
    fig.savefig(root/'microdomain_curves.png',dpi=160);plt.close(fig)


if __name__=='__main__':main()

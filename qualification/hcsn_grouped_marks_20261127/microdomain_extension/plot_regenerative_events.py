"""Plot repeated events at two reset distances from the numerical verification JSON."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    root=Path(__file__).resolve().parent
    all_rows=json.loads((root/'regenerative_verification.json').read_bytes())['rows']
    rows=[r for r in all_rows if r['drift']==.03355 and r['x']==.07]
    source=json.loads((root/'regenerative_release.json').read_bytes())['rows']
    source=[r for r in source if r['reset']==.30 and r['x']==.18]
    fig,axes=plt.subplots(1,2,figsize=(11.4,4.5),layout='constrained')
    color='#0C6771';warm='#B54A2C';ink='#1E3445'
    loc=np.arange(4);ns=[r['copies'] for r in rows]
    a=axes[0];q=np.array([r['grid_bounds'][-1][1:] for r in rows])
    mid=q.mean(1)
    a.plot(loc,mid,c=color,linewidth=2.2,label='Renewal count midpoint')
    a.fill_between(loc,q[:,0],q[:,1],color=color,alpha=.30)
    a.plot(loc,[r['single_path_distance_series_substituting_n_copy_cdf'] for r in rows],
           marker='s',markersize=4.5,c=warm,linestyle='--',label='Single-path shortcut')
    a.errorbar(loc+.025,[r['simulation_mean'] for r in rows],yerr=[2*r['simulation_se'] for r in rows],
               fmt='o',c=ink,markersize=4.5,capsize=3,label='Simulation ± 2 MC SE')
    a.set(title='Shorter reset distance',ylabel='Expected releases per horizon',xlabel='Independent paths')
    a.text(.02,.97,'Initial 0.07  ·  reset 0.085',transform=a.transAxes,ha='left',va='top',fontsize=10)
    a.legend(frameon=False,loc='lower right',fontsize=9);a.set_ylim(0,3.65)
    b=axes[1]
    b.semilogy(loc,[r['first_event'] for r in source],c=color,marker='o',label='At least one release')
    b.semilogy(loc,[np.mean(r['two_or_more']) for r in source],c=warm,marker='s',label='At least two releases')
    b.fill_between(loc,[r['two_or_more'][0] for r in source],[r['two_or_more'][1] for r in source],color=warm,alpha=.2)
    b.set(title='Source reset distance',ylabel='Probability per horizon (log scale)',xlabel='Independent paths',ylim=(3e-6,2.2))
    b.text(.02,.97,'Initial 0.18  ·  reset 0.30',transform=b.transAxes,ha='left',va='top',fontsize=10)
    b.legend(frameon=False,loc='lower right',fontsize=9)
    for ax in axes:
        ax.set_xticks(loc,ns);ax.grid(axis='y',alpha=.18);ax.spines[['top','right']].set_visible(False)
        ax.tick_params(colors=ink);ax.title.set_fontweight('bold');ax.title.set_color(ink)
    fig.suptitle('Joint first-hit reset can produce a count or a first-event gate',fontsize=14,fontweight='bold')
    fig.savefig(root/'regenerative_events.png',dpi=165,facecolor='white')
    plt.close(fig)


if __name__=='__main__':main()

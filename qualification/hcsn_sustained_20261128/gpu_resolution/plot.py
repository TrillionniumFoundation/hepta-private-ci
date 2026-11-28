"""Render the two warmed board measurements as scale-dependent ratios."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(__file__).resolve().parent
d=json.loads((root/'scaling.json').read_text())
fig,axes=plt.subplots(1,2,figsize=(9.75,4.15),sharex=True,layout='constrained')
styles=[('operator','float64','Operator, float64','#096684','o','-'),
        ('operator','float32','Operator, float32','#c36b22','s','-'),
        ('network','float64','Two-layer network, float64','#4b465a','D','--')]
for ax,key,title in zip(axes,('dense_over_fft_wall','dense_over_fft_board_energy_per_call'),
                          ('Synchronized time per call','Board energy per call')):
    ax.axhline(1.,color='#737377',ls=':',lw=1.25)
    for kind,dtype,label,color,marker,ls in styles:
        rows=sorted((p for p in d['pairs'] if (p['kind'],p['dtype'])==(kind,dtype) and p.get('numeric_pass')),key=lambda p:p['k'])
        ax.plot([p['k'] for p in rows],[p[key] for p in rows],label=label,color=color,marker=marker,
                linewidth=2,markersize=5,ls=ls)
    ax.set_xscale('log',base=2);ax.set_yscale('log',base=2)
    ax.set_xticks([256,512,1024,2048],labels=['256','512','1,024','2,048'])
    ax.set_yticks([.5,1,2,4,8,16],labels=['0.5','1','2','4','8','16'])
    ax.set_ylim(.38,20);ax.set_xlim(230,2310)
    ax.set_title(title,fontsize=12,loc='left',weight='bold')
    ax.grid(True,axis='y',color='#eeeeef',lw=.65)
    ax.spines[['top','right']].set_visible(False)
    ax.set_xlabel('Uniform grid atoms')
axes[0].set_ylabel('Dense / FFT ratio')
axes[0].legend(loc='upper left',frameon=False,fontsize=8.9)
fig.suptitle('T4 cost at increasing spatial resolution',fontsize=15,weight='bold',x=.50)
fig.savefig(root/'t4_resolution.png',dpi=175,facecolor='white')

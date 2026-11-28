"""Plot cell-cluster uncertainty of development-selected multi-path versus conventional waits."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    root=Path(__file__).resolve().parent;r=json.loads((root/'results.json').read_bytes())
    panels=('stationary','no_deadtime','elapsed_adaptation')
    names=('Stationary, 0.5 ms dead time','Stationary, no dead time','Elapsed-time adaptation')
    fig,a=plt.subplots(figsize=(9,4.3),layout='constrained');base=np.array([2,1,0.],dtype=float)
    for key,name,offset,color in [('new_cell','New cells (11 with exposure)',.12,'#0C6771'),
                                 ('new_current','Held-out currents (12 cells with exposure)',-.12,'#AD4A2B')]:
        stats=[r['groups'][key]['panels'][p]['selected_comparison'] for p in panels]
        center=np.array([v['gain_nats_per_second_cell_mean'] for v in stats])
        bounds=np.array([v['paired_cell_95'] for v in stats])
        a.errorbar(center,base+offset,xerr=np.vstack((center-bounds[:,0],bounds[:,1]-center)),
                   fmt='o',color=color,capsize=4,markersize=6,elinewidth=2,label=name)
    a.axvline(0,c='#20384A',linewidth=1.15)
    a.set_yticks(base,names);a.set_ylim(-.5,2.5);a.set_xlim(-11,16)
    a.set_xlabel('Multi-path gain in log likelihood (nats per second of post-spike exposure)')
    a.grid(axis='x',alpha=.15);a.spines[['top','right','left']].set_visible(False)
    a.tick_params(axis='y',length=0);a.legend(frameon=False,loc='upper center',bbox_to_anchor=(.5,-.18),ncol=2,fontsize=9)
    a.set_title('Held-out Allen interspike intervals',loc='left',fontweight='bold',fontsize=15)
    fig.savefig(root/'isi_transfer.png',dpi=165,facecolor='white');plt.close(fig)


if __name__=='__main__':main()

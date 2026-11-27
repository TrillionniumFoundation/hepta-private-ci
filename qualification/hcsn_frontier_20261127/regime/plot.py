from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from stopping import Continuation,FirstHit
from renewal import Renewal

plt.rcParams.update({'font.family':'Noto Sans CJK JP','font.size':10,'axes.spines.top':False,
                     'axes.spines.right':False,'axes.unicode_minus':False})
e=Continuation();h=FirstHit(e);j=FirstHit(e,'switch');v=np.linspace(.22,1.3,540)
fig,axs=plt.subplots(1,3,figsize=(13.5,4.1),layout='constrained')
colors=['#146a70','#ac513e'];names=['低成本状态','高成本状态']
for k in range(2):
    axs[0].plot(v,e.values(v)[:,k],label=names[k],color=colors[k],lw=2.4)
    axs[1].plot(v,h.values(v)[:,k],color=colors[k],lw=2.4)
    axs[1].plot(v,j.values(v)[:,k],color=colors[k],lw=1.6,ls='--')
for a in axs[:2]:
    for b in (e.b0,e.b1):a.axvline(b,color='#86969e',lw=.8,ls=':')
    a.axvspan(e.b0,e.b1,color='#e8eeee',alpha=.55,zorder=0)
    a.set_xlabel('输入状态 V')
axs[0].set_title('延续价值与内生边界',loc='left',weight='bold');axs[0].set_ylabel('延续价值 E');axs[0].legend(frameon=False)
axs[1].set_title('折现首达与状态切换诱发的事件',loc='left',weight='bold')
axs[1].set_ylabel('折现单位首达量');axs[1].text(.62,.88,'实线  全部事件\n虚线  边界跳变事件',transform=axs[1].transAxes,fontsize=9,ha='center')
d=json.loads(Path(__file__).with_name('validation.json').read_text());z=np.array(d['switch_limits'])
for k in range(2):axs[2].semilogx(z[:,0],z[:,k+1],marker='o',ms=3,color=colors[k],lw=2)
axs[2].axhline(d['averaged_cost_boundary'],color='#71838e',ls='--',lw=1)
axs[2].set_title('切换越快，两条边界越接近',loc='left',weight='bold');axs[2].set_xlabel('两种切换率的共同倍数（对数轴）');axs[2].set_ylabel('最优停止边界')
for a in axs:a.grid(axis='y',color='#dce4e5',lw=.65);a.set_axisbelow(True)
fig.savefig(Path(__file__).with_name('regime.png'),dpi=155,bbox_inches='tight')

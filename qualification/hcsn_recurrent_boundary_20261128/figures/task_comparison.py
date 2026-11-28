"""Draw the registered language fit and three-target CPU comparisons from released endpoint files."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

directory=Path(__file__).resolve().parent
root=directory.parent
font_file='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
if Path(font_file).is_file():
    font_manager.fontManager.addfont(font_file)
    plt.rcParams['font.family']=font_manager.FontProperties(fname=font_file).get_name()
plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False,'axes.unicode_minus':False,'font.size':9})
lang=json.loads((root/'spectral_write/terminal.json').read_text())['results']
dev=json.loads((root/'spectral_write/development.json').read_text())
tri=json.loads((root/'trimodal_decoder/paired/terminal.json').read_text())['rows']
fig,(a,b)=plt.subplots(1,2,figsize=(10.1,4.1),gridspec_kw={'width_ratios':[1.13,1]})
green='#146752';gold='#b2642b';blue='#304e79'
for idx,(seed,row) in enumerate(lang.items()):
    rec=dev[seed]['records']
    bp=row['bp']
    a.plot([x['training_wall_s'] for x in bp],[x['test']['ppl'] for x in bp],
           color=blue,alpha=.75,lw=1.1,marker='.',ms=5,label='同架构 BP，每条线一个种子' if idx==0 else None)
    a.scatter(rec[0]['wall_s'],row['fits'][row['fixed']]['scores']['normal']['ppl'],
              c=green,s=39,zorder=3,label='预固定的谱写入' if idx==0 else None)
    t=sum(r['wall_s']+r['validation_s'] for r in rec)
    a.scatter(t,row['fits'][row['chosen']]['scores']['normal']['ppl'],
              marker='D',c=gold,s=28,zorder=3,label='四组写入及开发选择总时长' if idx==0 else None)
for p in [400,500]:a.axhline(p,lw=.65,ls='--',color='#858b90',zorder=0)
a.set_xscale('log');a.set_xticks([1,2,4,8,16,32,64],labels=['1','2','4','8','16','32','64'])
a.set_xlabel('同核耗时（秒，对数刻度）');a.set_ylabel('WikiText-2 留出困惑度')
a.set_title('解析写入更早达到 500，BP 能继续到 400',loc='left',fontsize=11)
a.legend(fontsize=8,frameon=False,loc='upper right')
labels=['视觉摘要','声音摘要','转录词'];x=np.arange(3)
for j,(kind,name,color) in enumerate([('financial','HCSN',green),('smooth','平滑递归','#9faeac'),('lif','硬 LIF','#c9b8a2'),('sdpa_matched','近等参注意力',blue)]):
    arr=np.array([v['nll'] for k,v in tri.items() if k.startswith(kind+'-') and k.endswith('cpu60')])
    pos=x+(j-1.5)*.19
    b.bar(pos,arr.mean(0),width=.165,color=color,label=name)
    for z in arr:b.scatter(pos,z,s=5,color='black',alpha=.55,zorder=3)
b.set_xticks(x,labels);b.set_ylim(0,2.2);b.set_ylabel('留出目标 token 负对数似然')
b.set_title('60 进程 CPU 秒，三项损失均以近等参注意力最低',loc='left',fontsize=10.5)
b.legend(frameon=False,fontsize=8,ncol=2,loc='upper center',bbox_to_anchor=(.5,-.12))
fig.subplots_adjust(left=.072,right=.985,top=.87,bottom=.22,wspace=.29)
fig.savefig(directory/'task_comparison.png',dpi=175,facecolor='white')

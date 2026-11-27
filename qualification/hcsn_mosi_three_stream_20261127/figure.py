"""Render cold video-level errors and corrected modality-dependence intervals."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser();p.add_argument('primary',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    d=json.loads(a.primary.read_bytes());rows=d['terminal_by_design'];sens=d['masked_and_wrong_video_mae_increase']
    plt.rcParams.update({'font.family':'Noto Sans CJK SC','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.labelcolor':'#1a2938','axes.edgecolor':'#9aa9ae','text.color':'#182a35','axes.unicode_minus':False})
    fig,(l,r)=plt.subplots(1,2,figsize=(12.4,5.55),gridspec_kw={'width_ratios':[1,1.15]})
    fig.subplots_adjust(top=.81,bottom=.23,left=.08,right=.98,wspace=.25)
    fig.suptitle('CMU-MOSI 三模态编码器冷测',fontsize=19,fontweight='bold',x=.06,ha='left',y=.98)
    fig.text(.06,.894,'31 个独立源视频 · 686 个片段 · 3 个初始化种子 · 每方法上限 180 个单核 CPU 秒',fontsize=11,color='#465b65')
    widths=(64,256,1024);pos=np.arange(3)
    methods=[('fp_h','HCSN 前向投影','#086f79','o'),('fp_r','ReLU 前向投影','#896223','s'),('random_h','冻结 HCSN + 岭回归','#69757a','v'),('bp_h','HCSN 反向传播','#884783','^'),('transformer','Transformer 反向传播','#2d61a5','D')]
    for key,lab,col,marker in methods:
        ys=np.array([rows.get(f'{w}-{key}',{}).get('video_mae',np.nan) for w in widths])
        l.plot(pos,ys,marker=marker,color=col,lw=2.5 if key=='fp_h' else 1.7,label=lab,ms=6,zorder=4 if key=='fp_h' else 2)
    l.axhline(rows['0-raw_all']['video_mae'],color='#222f3c',ls=':',lw=1.5,label='原始三模态特征岭回归')
    l.set(xticks=pos,xticklabels=['64','256','1,024'],xlabel='HCSN / ReLU 隐层宽度（Transformer 对应三档）',ylabel='视频等权平均绝对误差，低为优')
    l.set_title('完整声、视、文输入',loc='left',fontsize=13,fontweight='bold',pad=10)
    l.grid(axis='y',alpha=.28);l.legend(loc='upper center',bbox_to_anchor=(.5,-.26),ncol=2,frameon=False,fontsize=8.5,handlelength=1.8,columnspacing=1.15)
    r.axvline(0,color='#4a5358',lw=1.1);r.grid(axis='x',alpha=.25)
    offsets=[-.20,0,.20];colors=['#299aa3','#147a83','#124c5a'];symbols=['o','s','D']
    for j,w in enumerate(widths):
        if f'{w}-fp_h' not in sens:continue
        for i,k in enumerate(('text','audio','vision')):
            m=sens[f'{w}-fp_h']['swap_'+k];y=2-i+offsets[j]
            low,high=m['familywise_bonferroni9_ci'];r.hlines(y,low,high,color=colors[j],lw=1.9)
            r.scatter([m['mae_delta']],[y],color=colors[j],s=36,marker=symbols[j],label='宽度 '+str(w) if i==0 else None,zorder=4)
    r.set(yticks=[2,1,0],yticklabels=['文本','声音','视觉'],ylim=(-.48,2.49),xlabel='错配后减完整输入的 MAE，正值表示错配损害预测')
    r.set_title('HCSN 前向投影的跨视频单模态错配',loc='left',fontsize=13,fontweight='bold',pad=10)
    r.legend(loc='upper center',bbox_to_anchor=(.5,-.26),ncol=3,frameon=False,fontsize=8.5)
    fig.text(.06,.018,'右图每个模态使用三组保持片段内部时序的跨视频置换；横线是对 9 个对照同时校正的置信区间。',fontsize=9,color='#536973')
    fig.savefig(a.out,dpi=170,facecolor='white',bbox_inches='tight');plt.close(fig)


if __name__=='__main__':
    main()

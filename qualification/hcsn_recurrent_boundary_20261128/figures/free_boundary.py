"""Render the mathematical and causal checks directly from released source and arrays."""
from pathlib import Path
import sys,json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
p=Path(__file__).resolve().parent
sust=p.parents[1]/"hcsn_sustained_20261128"
sys.path.insert(0,str(sust/"halfline"))
sys.path.insert(0,str(sust/"resolvent"))
from closed_form import Contract,Prices
from halfline import Stationary
font=FontProperties(fname="/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")
plt.rcParams.update({"font.family":font.get_name(),"axes.unicode_minus":False,"font.size":11,
                     "axes.spines.top":False,"axes.spines.right":False,"axes.labelcolor":"#273943",
                     "axes.edgecolor":"#9fa9ac","xtick.color":"#40545d","ytick.color":"#40545d",
                     "svg.fonttype":"none"})
fig,ax=plt.subplots(1,3,figsize=(14,4.3))
fig.subplots_adjust(left=.055,right=.986,top=.76,bottom=.19,wspace=.31)
blue="#156a91";red="#ba583b";teal="#247c68";slate="#43576b"
fig.text(.055,.958,"从合约报价到可写、可读的神经状态",fontsize=21,weight="bold",color="#233943",va="top")
prices=Prices(Contract())
x=np.linspace(0,.55,151)
ax[0].plot(x,[prices.equity(t) for t in x],c=blue,lw=2.6,label="股权 E")
ax[0].plot(x,[prices.credit_loss(t) for t in x],c=red,lw=2.6,label="货币信用损失 L")
ax[0].set(xlabel="安全裕量  log(V / B)",ylabel="货币价值",xlim=(0,.55))
ax[0].set_title("两条价格通道",loc="left");ax[0].legend(frameon=False)
op=Stationary();u=np.linspace(.03,.355,240)
S=np.array([op.stationary(z)[0] for z in u])
ax[1].plot(u,S,c=slate,lw=2);ax[1].axhline(0,c="gray",lw=1)
for root,sign in ((.036790156,1),(.142875032,0),(.311545393,1)):
    ax[1].scatter(root,0,s=65,facecolor=teal if sign else "white",edgecolor=teal if sign else red,zorder=4)
ax[1].set(xlabel="向内物理漂移速率 u",ylabel="自洽残差 S(u)")
ax[1].set_title("同一输入下的三个稳态",loc="left")
ax[1].text(.52,.06,"实心  稳定     空心  不稳定",ha="center",transform=ax[1].transAxes,fontsize=10)
j=json.loads((sust/"boundary_port"/"conditioning.json").read_text())["grids"][-1]
sx=np.array([int(k) for k in j["sampled"]]); sy=np.array([r["receiver_rate_contrast"]*1e3 for r in j["sampled"].values()])
mask=sx>=150
ax[2].plot(sx[mask],sy[mask],"-o",color=blue,lw=2,ms=4)
ax[2].axvline(170,ls=":",c=red,lw=1.4);ax[2].text(171,.17,"接通边界",color=red,fontsize=10,rotation=90)
ax[2].set(xlabel="模型时间",ylabel="下游发放率差 × 1,000",ylim=(-.05,.9))
ax[2].set_title("相同下游接收两种写入状态",loc="left")
for a in ax:a.grid(axis="y",alpha=.16)
fig.text(.055,.035,"左：原论文基准合约。中：群体半轴模型。右：两份接收器在 t=170 前断线，点为数值重放样本。",fontsize=10,color=slate)
fig.savefig(p/"free_boundary.png",dpi=165)

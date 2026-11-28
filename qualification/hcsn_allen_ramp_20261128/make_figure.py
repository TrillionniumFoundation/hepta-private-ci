"""Plot the first preordered held sweep and paired held-cell scores from the original arrays."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
ROOT=Path(__file__).resolve().parent
def main():
    cohort=json.loads((ROOT/"source/cohort.json").read_text());sid=cohort["held"][0]
    t=json.loads((ROOT/"results/terminal.json").read_text())
    record=json.loads((ROOT/f"source/{sid}/attempt-v2.json").read_text())["sweeps"][0];sw=record["row"]["sweep_number"]
    with np.load(ROOT/f"source/{sid}/signals-v2.npz") as f:
        current=f["current_bin_pA_0"];spikes=f["spike_times_s_0"]
    curves={};dt=.002
    for name in ("dual","lif","glm"):
        with np.load(ROOT/f"results/{name}-{sid}-{sw}.npz") as f:curves[name]=f["probability"]
    x=(np.arange(len(current))+.5)*dt
    colors={"dual":"#176257","lif":"#c76535","glm":"#506aa0"};names={"dual":"Dual price","lif":"Escape LIF","glm":"Smooth GLM"}
    plt.rcParams.update({"font.size":10,"font.family":"DejaVu Sans","axes.spines.top":False,"axes.spines.right":False})
    fig=plt.figure(figsize=(9.8,7.0),layout="constrained");gs=GridSpec(3,2,figure=fig,width_ratios=[2.25,1.2],height_ratios=[1.,.37,1.4])
    ax=fig.add_subplot(gs[0,0]);ax.plot(x,current,color="#727779",linewidth=1);ax.set(ylabel="Injected current (pA)",title=f"First held specimen {sid}, sweep {sw}");ax.title.set_ha("left");ax.title.set_position((0,1.))
    ev=fig.add_subplot(gs[1,0],sharex=ax);ev.eventplot([spikes],colors=["#222529"],lineoffsets=[.5],linelengths=[.85],linewidths=1.1);ev.set_ylim(0,1);ev.set_yticks([]);ev.set_ylabel("Spikes",rotation=0,ha="right",va="center");ev.spines["left"].set_visible(False)
    h=fig.add_subplot(gs[2,0],sharex=ax)
    for n in curves:
        window=min(25,len(x));smooth=np.convolve(curves[n],np.ones(window)/window,mode="valid")/dt
        h.plot(x[window-1:],smooth,label=names[n],color=colors[n],linewidth=1.4)
    h.set(xlabel="Time after ramp onset (s)",ylabel="Binned event probability / s");h.legend(frameon=False,fontsize=8,loc="best");h.set_xlim(0,len(current)*dt)
    for j in (ax,ev):j.tick_params(labelbottom=False)
    b=fig.add_subplot(gs[:,1]);arms=["lif","glm","no_price","equity","loss"];labels=["Escape LIF","Smooth GLM","No price","Equity only","Loss only"]
    for i,n in enumerate(arms):
        val=t["paired_dual_minus"][n];mean=val["delta"][0];lo,hi=val["ci95"][0]
        b.plot([lo,hi],[i,i],color="#70777b",lw=1.3);b.scatter([mean],[i],color=colors["dual"],s=35,zorder=3)
    b.axvline(0,color="#a1a7a8",lw=1,linestyle="--");b.set_yticks(range(len(arms)),labels);b.invert_yaxis();b.set_xlabel("Dual minus comparator NLL\n(nats / observed second)");b.set_title("Eight held specimens",loc="left");b.grid(axis="x",color="#eceded",lw=.6)
    fig.suptitle("Spike-train forecasts during recorded current ramps",x=.03,ha="left",weight="bold",fontsize=16)
    fig.savefig(ROOT/"ramp_predictions.png",dpi=175,facecolor="white");plt.close(fig)
if __name__=="__main__":main()

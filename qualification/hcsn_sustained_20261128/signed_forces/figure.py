"""Regime diagram, causal boundary wire and independent current-clamp comparisons."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import torch
from phase import Fixed

def plot(folder):
    torch.set_num_threads(1)
    fx=Fixed(24,samples=1025)
    rows=[fx.steady_roots(float(v),.02,3.) for v in np.linspace(-.95,.65,161)]
    (folder/"figure_scan.json").write_text(json.dumps(rows,separators=(",",":"))+"\n")
    mem=json.loads((folder/"boundary_memory.json").read_text());bio=json.loads((folder/"allen_direct_verified.json").read_text())["cohorts"]
    fig,axes=plt.subplots(1,3,figsize=(12,3.85),layout="constrained")
    dark="#204b63";orange="#ae4c2e";grey="#6e767a"
    for ax in axes:
        ax.spines[["top","right"]].set_visible(False)
        ax.grid(axis="y",color="#e3e8e8",lw=.65);ax.set_axisbelow(True)
    a=axes[0]
    for r in rows:
        for z in r["roots"]:
            stable=z["radius"]<1
            a.plot(r["drive"],max(z["flux"],0),marker="o" if stable else "x",ms=2.3,mew=.7,
                   color=dark if stable else orange,linestyle="")
    a.set(xlabel="Constant normalized drive",ylabel="Absorbed mass per tick",title="Stationary firing states")
    a.axvline(-.3,color=grey,lw=.8,ls=":")
    a.legend(handles=[Line2D([],[],color=dark,marker="o",ls="",ms=4,label="Locally stable"),
                        Line2D([],[],color=orange,marker="x",ls="",ms=4,label="Locally unstable")],fontsize=8,frameon=False,loc="upper left")
    a=axes[1]
    for k,clr in [("0.0",grey),("0.1",dark),("0.3",orange)]:
        rr=np.array(mem[k]["receiver_probe"]);diff=rr[:,1,1]-rr[:,0,1]
        a.plot(np.arange(1,len(diff)+1),diff*1000,color=clr,lw=1.7,label="Coupling "+k)
    a.set(xlabel="Ticks read by second layer",ylabel="Receiver flux difference (× 0.001)",title="Memory through boundary alone")
    a.legend(frameon=False,fontsize=8,loc="lower right")
    a=axes[2]
    pos=[3,2,1,0]
    for yy,(name,control) in zip(pos,[("ephys_records","tonic"),("ephys_records","nonfinancial"),
                                       ("nwb_curve_records","tonic"),("nwb_curve_records","nonfinancial")]):
        rr=bio[name]["models"][control];lo,hi=rr["ci95"];delta=rr["delta"]
        a.errorbar(delta,yy,xerr=np.array([[delta-lo],[hi-delta]]),fmt="o",capsize=3,color=dark if name=="ephys_records" else orange)
    a.axvline(0,color=grey,lw=1,ls="--");a.set_yticks(pos,["72 · tonic","72 · state","36 · tonic","36 · state"],fontsize=8)
    a.set(xlabel="Change in count MAE (95% CI)",title="Allen held currents");a.set_ylim(-.6,3.6)
    for ax in axes:ax.title.set_fontsize(11);ax.xaxis.label.set_size(9);ax.yaxis.label.set_size(9)
    fig.savefig(folder/"phase_and_evidence.png",dpi=195,facecolor="white")
if __name__=="__main__":plot(Path(__file__).resolve().parent)

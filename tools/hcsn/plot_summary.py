"""Export a scientific summary from actual per-seed results, without timing claims."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
COLORS = {"hcsn":"#1769a1", "sigmoid":"#708090", "gru":"#188779",
          "transformer":"#cf7c20", "snn":"#8b5aa7"}


def read(relative):
    return json.loads((ROOT/relative).read_text())


def panel(ax, groups, title, subtitle):
    for index, (label, kind, values) in enumerate(groups):
        values = 100*np.asarray(values)
        offsets = np.linspace(-.13,.13,len(values))
        ax.scatter(index+offsets,values,color=COLORS[kind],s=30,alpha=.8,zorder=3)
        ax.hlines(values.mean(),index-.24,index+.24,color=COLORS[kind],linewidth=2.6,zorder=4)
        ax.text(index,values.mean()+4.2,f"{values.mean():.2f}",ha="center",fontsize=9,
                color=COLORS[kind])
    ax.set_xticks(range(len(groups)),[g[0] for g in groups],fontsize=9)
    ax.set_ylim(-4,112)
    ax.set_yticks([0,25,50,75,100])
    ax.set_ylabel("Accuracy (%)")
    ax.set_title(title,loc="left",fontsize=12,fontweight="bold",pad=22)
    ax.text(0,1.025,subtitle,transform=ax.transAxes,fontsize=9,color="#5a6370")
    ax.grid(axis="y",alpha=.18)
    ax.spines[["top","right"]].set_visible(False)


def main():
    first=read("benchmarks/sequence_results.json")["runs"]
    second=read("benchmarks/sequence_v2_results.json")["runs"]
    snn=read("benchmarks/snn_reference_results.json")["runs"]
    heads=read("encoder/head_results.json")
    newer=read("benchmarks/frozen_v2_results.json")["runs"]
    snn_heads=read("benchmarks/snn_frozen_results.json")["runs"]
    fig,axes=plt.subplots(2,2,figsize=(14,9))
    names=[("HCSN","hcsn"),("Sigmoid","sigmoid"),("GRU","gru"),("Transformer","transformer")]
    groups=[(label,kind,[r["metrics"]["test"]["accuracy"] for r in first
                         if r["kind"]==kind and r["task"]=="irregular"])
            for label,kind in names]
    groups.append(("LIF-SNN","snn",[r["metrics"]["test"]["accuracy"] for r in snn if r["task"]=="irregular"]))
    panel(axes[0,0],groups,"A  Irregular-input integration, v1","32-step test; same synthetic data across models")
    for ax,task,title in [(axes[0,1],"memory","B  Memory length extrapolation, v2"),
                          (axes[1,0],"retrieval","C  Associative retrieval, v2")]:
        groups=[(label,kind,[r["metrics"]["long"]["accuracy"] for r in second
                             if r["kind"]==kind and r["task"]==task])
                for label,kind in names]
        panel(ax,groups,title,"Trained at 32 steps; tested at 64 on fresh v2 data")
    groups=[]
    for label,kind in [("HCSN v1","hcsn"),("Sigmoid v1","sigmoid"),("GRU","gru"),("Transformer","transformer")]:
        groups.append((label,kind,[r["test"]["accuracy"] for r in heads["runs"] if r["kind"]==kind]))
    for label,kind in [("HCSN v2","hcsn"),("Sigmoid v2","sigmoid")]:
        groups.append((label,kind,[r["test"]["accuracy"] for r in newer if r["kind"]==kind]))
    groups.append(("LIF-SNN","snn",[r["metrics"]["test"]["accuracy"] for r in snn_heads]))
    panel(axes[1,1],groups,"D  Frozen MiniLM text encoder","Shared SST subset; only the Head is trained")
    axes[1,1].set_ylim(70,81)
    axes[1,1].set_yticks([70,72,74,76,78,80])
    # Reposition labels for the intentionally magnified final panel.
    for text in axes[1,1].texts:
        if text.get_transform()==axes[1,1].transData:
            x,y=text.get_position();text.set_position((x,y-3.7))
    axes[1,1].tick_params(axis="x",rotation=25)
    linear=100*heads["linear_reference"]["test"]["accuracy"]
    axes[1,1].axhline(linear,color="#272c35",linestyle="--",linewidth=1.1)
    axes[1,1].text(6.3,linear+.25,f"65-parameter linear: {linear:.2f}%",ha="right",fontsize=9)
    fig.suptitle("HCSN research pilot: feasibility established, operator advantage unproven",
                 fontsize=16,fontweight="bold",y=.985)
    fig.text(.5,.017,"Dots: five training seeds. Marks: means. Matched data/updates and approximate parameters, not FLOPs.\n"
             "The later v2 and SNN text comparisons reuse the same holdout. No energy or backbone claim.",
             ha="center",fontsize=10,color="#5a6370")
    fig.tight_layout(rect=(0,.075,1,.95),h_pad=3)
    fig.savefig(ROOT/"results_overview.png",dpi=160)
    fig.savefig(ROOT/"results_overview.svg")


if __name__ == "__main__":
    main()

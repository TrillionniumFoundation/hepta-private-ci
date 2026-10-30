"""Plot actual per-seed next-stage results without conflating quality and cost."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path(__file__).parent
LABELS={"hcsn_v2_reference":"v2", "hcsn":"v3 HCSN", "sigmoid":"v3 sigmoid",
        "memory_only":"Memory only", "full_hx":"Full HX", "transformer":"Transformer"}
COLORS={"hcsn_v2_reference":"#8294a5", "hcsn":"#147bb1", "sigmoid":"#626b78",
        "memory_only":"#a36eaa", "full_hx":"#12a19d", "transformer":"#d58823"}


def main():
    records=[json.loads((ROOT/name).read_text()) for name in
             ("results.json","v2_reference_results.json","full_results.json")]
    assert all(r["complete"] for r in records)
    rows=[r for data in records for r in data["runs"]]
    challenge=json.loads((ROOT/"challenge_results.json").read_text())
    fig,axes=plt.subplots(2,2,figsize=(13,8.5))
    specifications=[("memory","test_128","A  Memory, 128 steps"),
                    ("retrieval","test_128","B  Four-item retrieval, 128 steps"),
                    ("irregular","test_128","C  Irregular input, 128 steps")]
    for ax,(task,split,title) in zip(axes.flat,specifications):
        for index,kind in enumerate(LABELS):
            values=100*np.array([r["metrics"][split]["accuracy"] for r in rows
                                if r["kind"]==kind and r["task"]==task])
            ax.scatter(index+np.linspace(-.1,.1,5),values,color=COLORS[kind],s=26,alpha=.8)
            ax.hlines(values.mean(),index-.24,index+.24,color=COLORS[kind],linewidth=2.6)
            ax.text(index,values.mean()+4,f"{values.mean():.1f}",ha="center",fontsize=9,color=COLORS[kind])
        ax.set_title(title,loc="left",fontweight="bold")
    ax=axes[1,1]
    for index,kind in enumerate(LABELS):
        values=100*np.array([r["metrics"]["accuracy"] for r in challenge["runs"]
                            if r["kind"]==kind and r["challenge"]=="retrieval_8_items_128"])
        ax.scatter(index+np.linspace(-.1,.1,5),values,color=COLORS[kind],s=26,alpha=.8)
        ax.hlines(values.mean(),index-.24,index+.24,color=COLORS[kind],linewidth=2.6)
        ax.text(index,values.mean()+4,f"{values.mean():.1f}",ha="center",fontsize=9,color=COLORS[kind])
    ax.set_title("D  Capacity challenge: eight items, 128 steps",loc="left",fontweight="bold")
    for ax in axes.flat:
        ax.set_xticks(range(len(LABELS)),LABELS.values(),rotation=25,ha="right",fontsize=9)
        ax.set_ylabel("Accuracy (%)")
        ax.set_ylim(20,111)
        ax.set_yticks([25,50,75,100])
        ax.spines[["top","right"]].set_visible(False)
        ax.grid(axis="y",alpha=.16)
    fig.suptitle("HCSN v3: memory improves, retrieval and operator attribution remain limited",
                 fontweight="bold",fontsize=14)
    fig.text(.5,.02,"Five fixed seeds; dots are individual runs, marks are means. All models train on lengths 8/16/32 with 600 updates.\n"
             "The full-HX operator uses a fixed financial template. Eight-item results reuse frozen checkpoints; no challenge tuning.",
             ha="center",fontsize=9,color="#596271")
    fig.tight_layout(rect=(0,.07,1,.95),h_pad=2)
    fig.savefig(ROOT/"sequence_overview.png",dpi=160)
    fig.savefig(ROOT/"sequence_overview.svg")


if __name__=="__main__":
    main()

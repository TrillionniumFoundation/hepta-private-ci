"""Saved logs/parameters only: no forward pass, gradient computation or training."""

import csv
import hashlib
import json
import os
from pathlib import Path
import time

os.environ.setdefault("MPLCONFIGDIR","/tmp/content-block-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME","/tmp/content-block-posthoc-cache")
Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True,exist_ok=True)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from independent.accounting import WorkLedger
from independent.learning import CONTENT_PARAMETERS, step_work
from content_block.learning import heads_work
from model import JointModel


started=time.process_time()
out=Path(__file__).resolve().parent
run=out.parent
root=run.parents[1]
prior=root/"runs/content-control-train-r2-20261023"
build=json.loads((run/"build.json").read_text())
result=json.loads((run/"train-result.json").read_text())
old=json.loads((prior/"train-result.json").read_text())
seeds=(11,23,47)
blocks={"encoder":CONTENT_PARAMETERS[:2],"heads":CONTENT_PARAMETERS[2:]}
price=WorkLedger("read-only-inventory")
records,loaded={},{}


def flat(values,names): return np.concatenate([values[k].ravel() for k in names])
def cosine(a,b): return float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)))


for group,rows in build["candidates"].items():
    for row in rows:
        folder=run/row["name"]
        model=JointModel.load(folder/"model.npz")
        base=JointModel.load(prior/f"base-{row['seed']}.npz")
        with np.load(folder/"updates-and-moments.npz",allow_pickle=False) as archive:
            z={k:archive[k].copy() for k in archive.files}
        loaded[row["name"]]=z
        loss=z["loss"]
        summary={"group":group,"seed":row["seed"],"lr":row["lr"],"updates":row["updates"],
            "encoder_updates":row["clocks"]["encoder"],"train_first32":float(loss[:32].mean()),
            "train_previous32":float(loss[-64:-32].mean()),"train_last32":float(loss[-32:].mean()),
            "train_loss_mean":float(loss.mean()),"train_loss_min":float(loss.min()),
            "training_units":row["training_units"],"quota_units":row["quota_units"],
            "unit_quota_utilization":row["training_units"]/row["quota_units"],
            "training_CPU":row["training_cpu"],"CPU_quota":row["quota_cpu"],
            "CPU_quota_utilization":row["training_cpu"]/row["quota_cpu"],"inner":row["validation"],"blocks":{}}
        for block,names in blocks.items():
            delta=flat({k:z["final_delta/"+k] for k in names},names)
            base_params=flat(base.params,names)
            group_info={"delta_l2":float(np.linalg.norm(delta)),"relative_delta_l2":float(np.linalg.norm(delta)/np.linalg.norm(base_params)),
                        "parameter_l2":float(np.linalg.norm(flat(model.params,names))),"gradients":{}}
            for mode in ("joint","heads"):
                if mode=="heads" and (block=="encoder" or not group.endswith("_alt")):
                    group_info["gradients"][mode]=None
                    continue
                for when in ("first","last"):
                    prefix=when+"_gradient/"+mode+"/"
                    gradient=flat({k:z[prefix+k] for k in names},names)
                    group_info["gradients"].setdefault(mode,{})[when+"_l2"]=float(np.linalg.norm(gradient))
            direction=[]
            for key in names:
                clock=int(z["clock/"+key])
                m=z["first_moment/"+key]/(1-.9**clock)
                v=z["second_moment/"+key]/(1-.999**clock)
                direction.append((-row["lr"]*m/(np.sqrt(v)+1e-8)).ravel())
            group_info["reconstructed_final_active_Adam_direction_l2"]=float(np.linalg.norm(np.concatenate(direction)))
            summary["blocks"][block]=group_info
        joint_norms=[]
        for when in ("first","last"):
            gradient=flat({k:z[when+"_gradient/joint/"+k] for k in CONTENT_PARAMETERS},CONTENT_PARAMETERS)
            joint_norms.append(float(np.linalg.norm(gradient)))
        summary["saved_joint_gradient_norms_first_last"]=joint_norms
        records[row["name"]]=summary

initial,final_cosines=[],[]
for seed in seeds:
    for lr in (.001,.003,.01):
        for objective in ("H","A"):
            j=loaded[f"{objective}_joint-{seed}-{lr}"]
            a=loaded[f"{objective}_alt-{seed}-{lr}"]
            if not all(np.array_equal(j["first_gradient/joint/"+k],a["first_gradient/joint/"+k]) for k in CONTENT_PARAMETERS):
                raise RuntimeError("initial gradient mismatch")
            for block,names in blocks.items():
                dj=flat({k:j["final_delta/"+k] for k in names},names)
                da=flat({k:a["final_delta/"+k] for k in names},names)
                final_cosines.append({"seed":seed,"lr":lr,"objective":objective,"block":block,
                    "alt_to_joint_delta_l2_ratio":float(np.linalg.norm(da)/np.linalg.norm(dj)),"delta_cosine":cosine(da,dj)})
        h=loaded[f"H_joint-{seed}-{lr}"]
        a=loaded[f"A_joint-{seed}-{lr}"]
        for block,names in blocks.items():
            ce=flat({k:h["first_gradient/joint/"+k] for k in names},names)
            utility=flat({k:a["first_gradient/joint/"+k]-h["first_gradient/joint/"+k] for k in names},names)
            dh=flat({k:h["first_delta/joint/"+k] for k in names},names)
            da=flat({k:a["first_delta/joint/"+k] for k in names},names)
            initial.append({"seed":seed,"lr":lr,"block":block,"utility_to_CE_gradient_l2":float(np.linalg.norm(utility)/np.linalg.norm(ce)),
                "CE_utility_gradient_cosine":cosine(ce,utility),"opposed_coordinate_fraction":float(np.mean(ce*utility<0)),
                "first_actual_A_H_delta_cosine":cosine(da,dh),"CE_dot_first_A_delta":float(np.dot(ce,da)),
                "minus_utility_dot_first_A_delta":float(np.dot(utility,da))})

selected=[]
for group,choice in result["selected"].items():
    for si,seed in enumerate(seeds):
        record=records[f"{group}-{seed}-{choice['lr']}"]
        record["strong_old_inner"]=old["reports"][group[0]][si]["means"]
        selected.append(record)
per_seed=[]
for seed in seeds:
    row={"seed":seed}
    for objective in ("H","A"):
        j=next(x for x in selected if x["seed"]==seed and x["group"]==objective+"_joint")
        a=next(x for x in selected if x["seed"]==seed and x["group"]==objective+"_alt")
        row[objective+"_alt_minus_joint"]={"utility":a["inner"]["task_utility"]-j["inner"]["task_utility"],
            "joint_success":a["inner"]["joint_success"]-j["inner"]["joint_success"],
            "tail32_loss":a["train_last32"]-j["train_last32"]}
    per_seed.append(row)

colors={"H_joint":"#275dad","H_alt":"#e18b24","A_joint":"#275dad","A_alt":"#e18b24"}
fig,axes=plt.subplots(2,3,figsize=(12,6.5),sharex=True)
for ci,seed in enumerate(seeds):
    for ri,objective in enumerate(("H","A")):
        ax=axes[ri,ci]
        for recipe in ("joint","alt"):
            group=objective+"_"+recipe
            name=f"{group}-{seed}-0.01"
            z=loaded[name]
            loss=z["loss"]
            unit_joint=price.estimate_kernel(**step_work((202,12,192,32),objective,64))
            unit_head=price.estimate_kernel(**heads_work((202,12,192,32),objective,64))
            units=np.array([unit_head if recipe=="alt" and j%2 else unit_joint for j in range(len(loss))])
            x=np.r_[0,np.cumsum(units)[:-1]]/1e9
            xs,ys=[],[]
            for start in range(0,len(loss),16):
                xs.append(float(x[start:start+16].mean()))
                ys.append(float(loss[start:start+16].mean())+(1 if objective=="A" else 0))
            ax.plot(xs,ys,label=group,color=colors[group],linewidth=1.7)
        ax.set_yscale("log")
        ax.set_title(f"seed {seed}, {objective}, selected LR .01")
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
        if ci==0: ax.set_ylabel("H: 0.2 CE loss" if objective=="H" else "A: 1 + composite loss")
        if ri==1: ax.set_xlabel("Training kernel work before update (B units)")
fig.suptitle("Saved TRAIN minibatch losses: 16-step averages; no inner trajectory recorded",fontsize=11)
fig.tight_layout()
fig.savefig(out/"saved-training-curves.png",dpi=180)
fig.savefig(out/"saved-training-curves.svg")
plt.close(fig)
fig,axes=plt.subplots(1,3,figsize=(12,3.5),sharey=True)
for ax,seed in zip(axes,seeds):
    for group in ("H_joint","H_alt","A_joint","A_alt"):
        values=[records[f"{group}-{seed}-{lr}"]["inner"]["task_utility"] for lr in (.001,.003,.01)]
        ax.plot((.001,.003,.01),values,marker="o",label=group,linestyle="--" if group.startswith("H") else "-")
    ax.set_xscale("log")
    ax.set_title(f"seed {seed}")
    ax.set_xlabel("Candidate LR (three fixed points)")
    ax.grid(alpha=.2)
axes[0].set_ylabel("Final inner expected decoded utility")
axes[0].legend(fontsize=8)
fig.suptitle("Inner endpoints across candidate LRs, NOT an inner learning curve",fontsize=11)
fig.tight_layout()
fig.savefig(out/"inner-endpoints-by-LR.png",dpi=180)
fig.savefig(out/"inner-endpoints-by-LR.svg")
plt.close(fig)

report={"scope":"post hoc read-only analysis; no new inference, gradient calculation, optimization or formal data",
    "records":records,"selected":selected,"per_seed_recipe_differences":per_seed,"initial_objective_gradients":initial,
    "final_parameter_change_comparisons":final_cosines,"initial_recipe_gradients_identical":True,
    "complete_budget":{g:{"units_used_fraction":build["ledgers"][g]["consumed_units"]/12e9,
            "CPU_used_fraction":build["costs"][g]["complete_cpu"]/10} for g in build["costs"]},
    "missing":["inner values at intermediate training steps","intermediate parameter/activation/probe checkpoints",
        "all per-step gradients/clipping history","per-step separated A CE and utility","gradients on skipped encoder steps",
        "matched encoder-update/batch and Adam-state counterfactuals","capacity sweep or independent generalization confirmation"],
    "derivation_boundary":"terminal active Adam direction is reconstructed from final saved moments/clocks; prior-step parameters and rounded subtraction are unavailable",
    "analysis_cpu_before_receipt":time.process_time()-started}
(out/"mechanism-analysis.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
with (out/"all36-training-inner-budget.csv").open("w",newline="") as stream:
    fields=("group","seed","lr","updates","encoder_updates","train_first32","train_previous32","train_last32", "unit_quota_utilization","CPU_quota_utilization","inner_utility","inner_joint_success","encoder_delta_l2","heads_delta_l2")
    writer=csv.DictWriter(stream,fieldnames=fields,lineterminator="\n")
    writer.writeheader()
    for record in records.values():
        row={k:record[k] for k in fields if k in record}
        row.update(inner_utility=record["inner"]["task_utility"],inner_joint_success=record["inner"]["joint_success"],
                   encoder_delta_l2=record["blocks"]["encoder"]["delta_l2"],heads_delta_l2=record["blocks"]["heads"]["delta_l2"])
        writer.writerow(row)
for path in out.glob("*.svg"):
    path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines())+"\n")
print(json.dumps({"candidate_records":len(records),"per_seed":per_seed,"analysis_cpu":report["analysis_cpu_before_receipt"]}))

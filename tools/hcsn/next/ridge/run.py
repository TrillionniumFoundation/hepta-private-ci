"""Frozen v4 ridge confirmation matrix on data disjoint from development."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import jax
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from next.common import train_model,evaluate_model,measure_latency
from next.sequence.run import make_suite
from next.ridge.models import init_model,apply_model,matched_width,count_parameters,state_count


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze():
    freeze=json.loads((HERE/"freeze.json").read_text())
    for name,digest in freeze["source_sha256"].items():
        if sha(ROOT/name)!=digest:raise RuntimeError("Frozen source changed: "+name)
    if not freeze["development_sanity_passed"]:raise RuntimeError("Development sanity failed")
    if not freeze["state_gradient_validation_passed"]:raise RuntimeError("State/gradient validation failed")
    return freeze


def summarize(rows,protocol):
    groups=[]
    for task in protocol["tasks"]:
        for kind in protocol["models"]:
            group=[r for r in rows if r["task"]==task and r["kind"]==kind]
            if not group:continue
            scores={}
            for split in group[0]["metrics"]:
                values=np.asarray([r["metrics"][split]["accuracy"] for r in group])
                scores[split]=dict(mean=float(values.mean()),seed_sd=float(values.std(ddof=1)) if len(values)>1 else None,
                    min=float(values.min()),max=float(values.max()))
            target=protocol["primary_acceptance"].get(task,{}).get("minimum_every_seed_and_heldout_length")
            accepted=None if target is None else all(r["metrics"][f"test_{length}"]["accuracy"]>=target
                for r in group for length in protocol["heldout_lengths"])
            groups.append(dict(task=task,kind=kind,seeds=[r["seed"] for r in group],
                parameter_count=group[0]["parameter_count"],persistent_state_scalars=group[0]["persistent_state_scalars"],
                fixed_operator_bytes=group[0]["fixed_operator_bytes"],metrics=scores,
                all_observed_seed_lengths_meet_target=accepted,
                all_five_seeds_complete=len(group)==len(protocol["training_seeds"]),
                mean_optimizer_execution_seconds=float(np.mean([r["timing"]["optimizer_execution_seconds"] for r in group])),
                mean_optimizer_update_median_ms=float(np.mean([r["timing"]["optimizer_update_median_ms"] for r in group])),
                mean_latency_test32_ms=float(np.mean([r["latency_test32_batch32"]["median_ms"] for r in group]))))
    return groups


def main():
    frozen=verify_freeze()
    protocol=json.loads((HERE/"protocol.json").read_text())
    applies={kind:(lambda p,x,dt,k=kind:apply_model(p,x,dt,k)) for kind in protocol["models"]}
    metadata=dict(protocol=protocol,freeze_sha256=sha(HERE/"freeze.json"),source_sha256=frozen["source_sha256"],
        jax=jax.__version__,numpy=np.__version__,cpu_affinity=sorted(os.sched_getaffinity(0)),
        no_test_for_architecture_selection=True,compiled_optimizer_budget_excludes_compilation=True,
        warmup_optimizer_updates=0,comparison_scope="Parameters/data/updates matched; not memory or FLOPs matched")
    checkpoints=HERE/"checkpoints";checkpoints.mkdir(exist_ok=True)
    result=HERE/"results.json"
    rows=[];prior_elapsed=0.
    if result.exists():
        prior=json.loads(result.read_text())
        if prior["metadata"]["freeze_sha256"]!=metadata["freeze_sha256"]:raise RuntimeError("Resume freeze mismatch")
        rows=prior["runs"];prior_elapsed=prior["elapsed_seconds"]
        for row in rows:
            if sha(HERE/row["checkpoint_file"])!=row["checkpoint_sha256"]:raise RuntimeError("Resume checkpoint changed")
        if prior["complete"]:raise RuntimeError("Confirmation matrix already complete; use independent audit")
    done={(r["task"],r["seed"],r["kind"]) for r in rows}
    start=time.perf_counter()
    table_bytes=sum(a.nbytes for a in np.load(ROOT/"next/full_kernel/baseline_table.npz").values())
    for task in protocol["tasks"]:
        for seed in protocol["training_seeds"]:
            train,suite,hashes=make_suite(task,seed,protocol)
            offset=seed%len(protocol["models"])
            kinds=protocol["models"][offset:]+protocol["models"][:offset]
            for kind in kinds:
                if (task,seed,kind) in done:continue
                verify_freeze()
                width,count=matched_width(kind,16,4,protocol["parameter_target"])
                params=init_model(kind,jax.random.PRNGKey(protocol["initialization_seed_base"]+seed),16,width,4)
                if count_parameters(params)!=count:raise RuntimeError("Parameter matching error")
                learned,history,timing=train_model(params,applies[kind],train,suite["validation"],
                    protocol["optimizer_seed_base"]+seed,steps=protocol["updates"],
                    batch_size=protocol["batch_size"],lr=protocol["learning_rate"])
                target=checkpoints/f"{task}_{kind}_seed{seed}.npz"
                np.savez_compressed(target,**{key:np.asarray(value) for key,value in learned.items()})
                metrics={name:evaluate_model(applies[kind],learned,data) for name,data in suite.items()}
                row=dict(task=task,seed=seed,kind=kind,width=width,parameter_count=count,
                    persistent_state_scalars=state_count(kind,width),fixed_operator_bytes=int(table_bytes) if kind=="full_hx" else 0,
                    data_sha256=hashes,history=history,timing=timing,metrics=metrics,
                    latency_test32_batch32=measure_latency(applies[kind],learned,suite["test_32"],repeats=20),
                    checkpoint_file=str(target.relative_to(HERE)),checkpoint_sha256=sha(target))
                rows.append(row)
                payload=dict(metadata=metadata,runs=rows,summary=summarize(rows,protocol),complete=False,
                    elapsed_seconds=prior_elapsed+time.perf_counter()-start)
                result.write_text(json.dumps(payload,indent=2)+"\n")
                print(json.dumps(dict(task=task,seed=seed,kind=kind,run=len(rows),
                    accuracy={key:val["accuracy"] for key,val in metrics.items()},
                    optimizer_seconds=timing["optimizer_execution_seconds"])),flush=True)
    expected=len(protocol["tasks"])*len(protocol["training_seeds"])*len(protocol["models"])
    payload["complete"]=len(rows)==expected
    result.write_text(json.dumps(payload,indent=2)+"\n")
    print("COMPLETE",payload["complete"],len(rows),flush=True)


if __name__=="__main__":main()

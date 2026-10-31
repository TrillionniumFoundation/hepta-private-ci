"""Small synthetic tests for source binding, reset behavior and timing semantics."""

import argparse
import itertools
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import numpy as np

from .energy import NvmlEnergy, energy_delta, measure_energy
from .measure import HERE, archive_members, bind_case, capability, digest, read, source_map, tensor_hash, timing, write


def run(output):
    import torch
    from ..content.models import build
    torch.set_num_threads(1)
    tick, cpu = time.perf_counter(), time.process_time()
    design = read(HERE/"HARDWARE_DESIGN.json")
    checks, details = [], {}

    def check(name, condition):
        checks.append(dict(name=name, passed=bool(condition)))

    torch.manual_seed(883972)
    x, dt = torch.randn(2,8,64), torch.rand(2,8)+.5
    for arm in design["models"]:
        model = build(arm, width=32, depth=1, seed=design["seed"]).eval()
        with torch.inference_mode():
            first = model(x,dt,return_sequence=True,return_aux=False)
            model(x+1,dt,return_sequence=True,return_aux=False)
            again = model(x,dt,return_sequence=True,return_aux=False)
        check(arm+": full sequence creates fresh state after unrelated call", torch.equal(first,again))
        probe = dict(design, warmup=1, repetitions=2)
        for scope in ("resident","host_end_to_end"):
            measured, actual, _, _ = timing(model,x,dt,torch.device("cpu"),scope,probe)
            check(arm+"/"+scope+": exact output and complete positive timing",
                np.array_equal(actual,first.numpy()) and len(measured["wall_seconds"])==2
                and min(measured["wall_seconds"])>0 and measured["cuda_event_seconds"] is None)
            details[arm+"/"+scope] = measured
    for name,start,end,elapsed,minimum,expected in (
            ("millijoules to joules",1000,3500,2.,1.,2.5),
            ("counter regression",1000,999,2.,1.,None),
            ("unresolved zero increment",1000,1000,2.,1.,None),
            ("short window",1000,1100,.1,1.,None),
            ("nonfinite duration",1000,1100,float('nan'),1.,None)):
        check(name,energy_delta(start,end,elapsed,minimum)["joules"]==expected)
    for value in (None,"MIG-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"):
        counter = NvmlEnergy(value)
        check("unmatched or MIG UUID rejects energy "+str(value), counter.error is not None and not counter.identity["device_match"])
        counter.close()
    class FakeCounter:
        identity, error = {"synthetic": True}, None
        def __init__(self):
            self.values=iter((100,90,95,110,120,130))
        def read(self):
            return next(self.values)
    with patch("time.sleep",lambda _:None), patch("time.perf_counter",side_effect=itertools.count()):
        reading=measure_energy(FakeCounter(),lambda:None,lambda:None,
            dict(idle_seconds=.5,minimum_active_seconds=.5,maximum_iterations=1),batch=1)
    check("within-idle counter regression invalidates active joules",reading["joules"] is None and "regressed" in reading["error"])
    with tempfile.TemporaryDirectory(dir=HERE, prefix="synthetic_binding_") as temp:
        root=Path(temp)
        task,arm=design["tasks"][0],design["models"][0]
        name=f"{task}__{arm}__seed{design['seed']}"
        folder=root/"fixed"/name
        folder.mkdir(parents=True)
        (root/"data").mkdir()
        np.savez_compressed(root/"data/validation.npz",x=x.numpy(),dt=dt.numpy())
        protocol=dict(design=dict(formal_updates=96),data={task:{"val":dict(file="validation.npz",sha256=digest(root/"data/validation.npz"))}})
        write(root/"PROTOCOL.json",protocol)
        write(root/"SELECTION_LOCK.json",dict(choices={task:{arm:dict(learning_rate=.001)}}))
        model=build(arm,width=32,depth=1,seed=design["seed"])
        np.savez_compressed(folder/"selected_state.npz",**{key:value.detach().numpy() for key,value in model.state_dict().items()})
        best=dict(step=48,cross_entropy=2.,sha256="synthetic-validation-receipt",file="synthetic-validation.npz")
        selected=dict(best,state_sha256=digest(folder/"selected_state.npz"),tensor_hash=tensor_hash(folder/"selected_state.npz"))
        result=dict(status="complete",job=dict(stage="fixed",task=task,arm=arm,seed=design["seed"],learning_rate=.001,updates=96,id=name),
            updates=96,protocol_sha256=digest(root/"PROTOCOL.json"),public_execution_commit=design["study_execution_seal"],
            selected=selected,validations=[best,dict(best,step=96,cross_entropy=3.)])
        write(folder/"RESULT.json",result)
        write(folder/"selection.json",dict(selected,locked_utc="synthetic-only"))
        bound=bind_case(root,protocol,task,arm,design)
        check("selected source/checkpoint/validation binding", bound["tensor_hash"]==selected["tensor_hash"])
        original=(folder/"selected_state.npz").read_bytes()
        (folder/"selected_state.npz").write_bytes(original+b"corruption")
        try:
            bind_case(root,protocol,task,arm,design)
            rejected=False
        except ValueError:
            rejected=True
        check("changed checkpoint bytes rejected",rejected)
        (folder/"selected_state.npz").write_bytes(original)
        result["public_execution_commit"]="0"*40
        (folder/"RESULT.json").write_text(json.dumps(result))
        try:
            bind_case(root,protocol,task,arm,design)
            rejected=False
        except ValueError:
            rejected=True
        check("wrong study execution seal rejected",rejected)
        archive_row=dict(path="content/results/hosted001/selected_state.npz",bytes=len(original),sha256=digest(folder/"selected_state.npz"))
        write(root/"members_0000.json",[archive_row])
        write(root/"INDEX.json",dict(schema="hcsn-bounded-member-index.v1",original_member_count=1,
            member_shards=[dict(path="members_0000.json",members=1,bytes=(root/"members_0000.json").stat().st_size,sha256=digest(root/"members_0000.json"))]))
        pinned=digest(root/"INDEX.json")
        check("external archive index binds member hash",archive_members(root/"INDEX.json",pinned)[archive_row["path"]]==archive_row)
        (root/"members_0000.json").write_text("[]")
        try:
            archive_members(root/"INDEX.json",pinned)
            rejected=False
        except ValueError:
            rejected=True
        check("changed publication shard rejected",rejected)
    receipt=dict(schema="hcsn-blocker-hardware-preflight.v1",passed=all(row["passed"] for row in checks),
        checks=checks,details=details,source_sha256=source_map(),capabilities=capability(torch),
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-tick,
        scope="Synthetic CPU inputs and untrained synthetic checkpoint fixture only. No formal checkpoint, validation/test arrays, CUDA timing or real energy counter is claimed.")
    write(output,receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=run(args.output)
    print(json.dumps(dict(passed=result["passed"],checks=len(result["checks"]),cpu_seconds=result["cpu_seconds"])))
    if not result["passed"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()

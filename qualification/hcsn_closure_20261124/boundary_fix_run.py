"""Last bounded prospective confirmation of nominal boundary centering.

Four registered arms, three new seeds, no gain search. Reuses the frozen fit
loop, qualified fast kernel, causal accumulator and detached observer. All
twelve candidates and four checkpoint states per candidate seal before test.
"""

import time
ENTRY_WALL = time.perf_counter()
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import traceback

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from qualification.hcsn_smallnet_20261124.train import runtime_identity
from . import provenance as pv, runner as worker
from .boundary_fix import BoundaryControlHCSN
from .communication_observe import CommunicationObserver
from .data import generate_sources, make_data as smoke_data
from .joint_run import parameter_accounting as base_accounting


ROOT = Path(__file__).resolve().parents[2]
ARMS = {
    "signed_raw": ("signed_only", "raw", "raw"),
    "boundary_accumulate_raw": ("boundary_only", "accumulate", "raw"),
    "boundary_accumulate_centered": ("boundary_only", "accumulate", "centered"),
    "boundary_signed_accumulate_centered": ("boundary_signed", "accumulate", "centered"),
}
SEEDS = (25011, 35011, 45011)
OBSERVERS = []


def factory(slot):
    channel, control, message = ARMS[slot["variant"]]
    return BoundaryControlHCSN(ModelConfig(neurons=32, precision="mixed", backend="uniformized",
        boundary_mode="qvi", feature_bank="value_risk", feature_normalization="none", message_mode="full"),
        channel=channel, control_mode=control, boundary_mode=message)


def accounting(model):
    return {**base_accounting(model), "additional_trainable_parameters":0,
        "nominal_reference_buffer_bytes":model.boundary_reference.numel()*model.boundary_reference.element_size(),
        "additional_control_state_bytes_per_example":2*model.config.input_size*model.input_drive.weight.element_size(),
        "control_memory_active":model.control_spec.mode=="accumulate",
        "scope":"Same allocated parameters; joint has twice single-channel active recurrent weights. All arms allocate explicit pending/held state; only accumulate uses persistent cue memory. Nominal reference is a fixed data-free buffer."}


def sources():
    manifest=ROOT/"INSTALLATION.json"
    if pv.digest(manifest)!="e65404b2a2aac5ed03fee6d1598091100322c3449c6e4a339979aad417299ced":
        raise ValueError("unexpected frozen base installation")
    result=pv.read(manifest)
    for path,expected in result.items():
        if pv.digest(ROOT/path)!=expected:raise ValueError("immutable base source changed: "+path)
    for name in ("fast_kernel.py","joint_run.py","joint_tests.py","communication.py",
                 "communication_observe.py","boundary_fix.py","boundary_fix_run.py","boundary_fix_tests.py"):
        path=Path(__file__).with_name(name);result[str(path.relative_to(ROOT))]=pv.digest(path)
    if pv.digest(Path(__file__).with_name("fast_kernel.py"))!="a92d7cc45af0ccf1e1c2629ee9fe8ef1d4b0bc6dba335bbdc53cd909c42d80b3":
        raise ValueError("unqualified fast kernel")
    return result


def expected_protocol():
    p=pv.read(Path(__file__).with_name("protocol.json"))
    p["experiment_id"]="HCSN-BOUNDARY-NOMINAL-CENTER-CONFIRM-20261125-v1"
    p["suite"]="boundary_center_confirmation"
    p["slots"]=[{"id":f"n32-{arm}-s{seed}","variant":arm,"neurons":32,"boundary":"qvi",
        "features":"value_risk","precision":"mixed","seed":seed} for arm in ARMS for seed in SEEDS]
    p["data"].update(train_sources=list(range(39000,39012)),dev_sources=list(range(40000,40004)),
                     test_sources=list(range(41000,41016)))
    p["source_hashes"],p["runtime"]=sources(),runtime_identity()
    p["arms"]={name:dict(zip(("channel","control","boundary_message"),value)) for name,value in ARMS.items()}
    p["claim_scope"]="One bounded prospective causal confirmation, fixed nominal b0 subtraction only, no gain search, data-fitted normalization or old-test seed selection. All earlier boundary/joint failures remain. Closed-loop trajectories may change; local physical laws and raw local emissions do not."
    p["mechanism"]="Input-drive pulse coordinates 0..3 accumulate since previous slow tick and are consumed once at the next due tick. Writer always sees raw current token. Previous boundary message optionally subtracts fixed nominal b0; zero initial message stays zero. Unsigned recurrent block is zero in every checkpoint."
    p["holdout_policy"]="All12 terminal attempts, complete four-state checkpoints, fixed nominal references and detached mechanism receipts sealed before any test generation. All failures retained; no test tuning/retry/reselection."
    p["comparison_gates"]={"reference":"signed_raw","accuracy_margin":.02,"brier_margin":.02,
        "rule":"Relative accuracy>=signed-.02 and Brier<=signed+.02, at least2/3 per arm; learning/numerical reported separately. Engineering tolerance, not statistical equivalence."}
    p["prespecified_mechanism_contrasts"]=[
        "boundary_accumulate_centered-minus-boundary_accumulate_raw",
        "boundary_signed_accumulate_centered-minus-boundary_accumulate_centered"]
    p["capacity_policy"]="All arms allocate one fixed N FP64 b0 buffer and pending/held BxD tensors. Accumulate adds active temporal memory; joint doubles active recurrent entries. Report these differences, not equal functional capacity."
    p["observation"]="Existing detached per-channel moments, tanh>=.95 saturation and preclip recurrent gradients are recorded by training/development/test-checkpoint phase; none feed the model. Observer costs included."
    p["resource_policy"]={"workers":6,"threads_per_worker":1,"aggregate_cpu_percent_cap":600,
        "aggregate_memory_limit_bytes":6*1024**3,"child_wall_timeout_seconds":2400}
    return p


def prepare(root):
    p=expected_protocol();root.mkdir(parents=True,exist_ok=False);pv.create(root/"PROTOCOL.json",p);return p


def load(root):
    p=pv.read(root/"PROTOCOL.json")
    if p!=expected_protocol():raise ValueError("frozen boundary confirmation/source/runtime changed")
    return p


def validate(directory,p,slot):
    pv.validate_record(directory,p,slot)
    record=pv.read(directory/"result.json")
    if record["status"]!="failed":
        saved=torch.load(directory/"checkpoint.pt",map_location="cpu",weights_only=True)
        expected=factory(slot).boundary_reference
        for key in ("initial_model","selected_model","last_model","cpu_prefix_model"):
            if not torch.equal(saved[key]["boundary_reference"],expected):
                raise ValueError("fixed nominal b0 changed in "+key)
    mechanism=pv.read(directory/"MECHANISM_FIT.json")
    if mechanism["slot"]!=slot or mechanism["protocol_sha256"]!=pv.identity(p):
        raise ValueError("foreign detached mechanism evidence")


def seal(root,p):
    rows={}
    for slot in p["slots"]:
        directory=root/slot["id"];validate(directory,p,slot)
        names=("result.json","worker_cost.json","history.json","checkpoint.pt","parent_cost.json","MECHANISM_FIT.json")
        rows[slot["id"]]={name:pv.digest(directory/name) for name in names if (directory/name).exists()}
    pv.create(root/"SEAL.json",{"schema":"hcsn-boundary-center-seal-v1","protocol_sha256":pv.identity(p),"attempts":rows})


def check_seal(root,p):
    saved=pv.read(root/"SEAL.json")
    if saved["protocol_sha256"]!=pv.identity(p) or set(saved["attempts"])!={s["id"] for s in p["slots"]}:
        raise ValueError("incomplete boundary-center seal")
    for slot in p["slots"]:
        for name,digest in saved["attempts"][slot["id"]].items():
            if pv.digest(root/slot["id"]/name)!=digest:raise ValueError("sealed artifact changed")
        validate(root/slot["id"],p,slot)
    return saved


def bind(p,action):
    def observed_factory(slot):
        model=factory(slot);observer=CommunicationObserver(model.config.neurons);observer.attach(model)
        observer.nominal_boundary=model.boundary_reference.detach().cpu().tolist()
        OBSERVERS.append(observer);return model
    def data(split,*,per_source,length=12,dtype=torch.float32):
        if split.startswith("smoke"):return smoke_data(split,per_source=per_source,length=length,dtype=dtype)
        return generate_sources(p["data"][split+"_sources"],per_source=per_source,length=length,
            dtype=dtype,namespace=p["experiment_id"]+"-"+split)
    original_forward,original_evaluate=worker.forward_batch,worker.evaluate
    evaluation_index=0
    def forward(model,batch):
        model.observer.phase="training";return original_forward(model,batch)
    def evaluate(model,batch,**kwargs):
        nonlocal evaluation_index
        model.observer.phase=("test_selected","test_initial","test_cpu_prefix")[evaluation_index] if action=="test" else "development"
        evaluation_index+=1
        metrics,logits,features=original_evaluate(model,batch,**kwargs)
        observation=model.observer.group()
        metrics["maximum_chunk_state_tensor_bytes"]=observation["maximum_complete_state_tensor_bytes"]
        metrics["additional_control_state_tensor_bytes"]=observation["maximum_control_state_tensor_bytes"]
        metrics["state_bytes_scope"]="five physical fields plus pending/held control tensors; fixed buffers, parameters, outputs and AD tape excluded"
        return metrics,logits,features
    pv.make_model=factory
    worker.make_model,worker.make_data,worker.parameter_accounting=observed_factory,data,accounting
    worker.forward_batch,worker.evaluate,worker.check_seal=forward,evaluate,check_seal


def run_worker(root,p,slot,action):
    status,error="failed",None
    try:
        report=worker.test(root,p,slot) if action=="test" else worker.fit(root,p,slot,smoke=action=="smoke")
        status=report["status"];print(json.dumps({"slot":slot["id"],"status":status,"updates":report.get("updates")}),flush=True)
    except Exception:error=traceback.format_exc();raise
    finally:
        directory=root/slot["id"];directory.mkdir(exist_ok=True)
        pv.create(directory/("MECHANISM_TEST.json" if action=="test" else "MECHANISM_FIT.json"),
            {"slot":slot,"protocol_sha256":pv.identity(p),"models":[dict(o.export(),nominal_boundary=o.nominal_boundary) for o in OBSERVERS]})
        pv.create(directory/("test_worker_cost.json" if action=="test" else "worker_cost.json"),
            {"status":status,"error":error,"wall_from_first_module_statement":time.perf_counter()-ENTRY_WALL,
             "process_cpu_through_receipt":time.process_time(),"process_peak_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
             "energy_joules_process":None,"scope":"fresh Linux worker through receipt; imports and detached observers included, shutdown excluded"})
    return 0 if status in ("completed","censored_cpu","evaluated","unavailable") else 1


def stage(root,p,action):
    before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.perf_counter()
    def one(slot):
        begin=time.perf_counter();row={"slot":slot["id"],"returncode":None,"error":None}
        try:
            with (root/(slot["id"]+"."+action+".log")).open("x") as log:
                child=subprocess.run([sys.executable,"-m",__package__+".boundary_fix_run",action,"--root",str(root),"--slot",slot["id"]],
                    stdout=log,stderr=subprocess.STDOUT,timeout=2400,
                    env=dict(os.environ,OMP_NUM_THREADS="1",MKL_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1"))
            row["returncode"]=child.returncode
        except Exception:row["error"]=traceback.format_exc()
        row["launch_through_exit_wall_seconds"]=time.perf_counter()-begin
        directory=root/slot["id"];directory.mkdir(exist_ok=True)
        pv.create(directory/("test_parent_cost.json" if action=="test" else "parent_cost.json"),row);print(json.dumps({"stage":action,**row}),flush=True);return row
    with ThreadPoolExecutor(max_workers=6) as pool:rows=list(pool.map(one,p["slots"]))
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    pv.create(root/(action.upper()+"_EXECUTION.json"),{"rows":rows,"workers":6,"wall_seconds":time.perf_counter()-start,
        "children_cpu_seconds_including_shutdown":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,"energy_joules_process":None})
    return rows


def run(root,p):
    pv.create(root/"RUN_CLAIM.json",{"protocol_sha256":pv.identity(p),"workers":6})
    start,status,error=time.perf_counter(),"failed",None
    try:
        stage(root,p,"fit");seal(root,p)
        pv.create(root/"TEST_CLAIM.json",{"protocol_sha256":pv.identity(p),"seal_sha256":pv.digest(root/"SEAL.json")})
        rows=stage(root,p,"test")
        if any(r["returncode"]!=0 or r["error"] is not None for r in rows):raise RuntimeError("test worker failure retained")
        for slot in p["slots"]:
            row=pv.read(root/slot["id"]/"test_result.json")
            if row["slot"]!=slot or row["status"] not in ("evaluated","unavailable"):raise ValueError("incomplete test roster")
        status="completed"
    except Exception:error=traceback.format_exc();raise
    finally:pv.create(root/"CAMPAIGN_RECEIPT.json",{"status":status,"error":error,"wall_seconds":time.perf_counter()-start,
        "driver_cpu_through_receipt":time.process_time(),"energy_joules_process":None})


def main():
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("prepare","run","fit","test","smoke"))
    parser.add_argument("--root",type=Path,required=True);parser.add_argument("--slot");args=parser.parse_args();torch.set_num_threads(1)
    if args.action=="prepare":
        p=prepare(args.root);print(json.dumps({"protocol_sha256":pv.identity(p),"slots":len(p["slots"]),"holdout_constructed":False}),flush=True);return 0
    p=load(args.root);bind(p,args.action)
    if args.action=="run":run(args.root,p);return 0
    return run_worker(args.root,p,next(s for s in p["slots"] if s["id"]==args.slot),args.action)


if __name__=="__main__":raise SystemExit(main())

"""CPU cost including immutable model construction, all cached P and online work."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time

import numpy as np
from scipy.linalg import expm

from adapter import PreparedModel
from adapter import ROOT


def probabilities(p):
    if (not np.isfinite(p).all() or (p < 0).any()
            or np.max(abs(p.sum(-1)-1)) > 5e-10):
        raise ValueError("Invalid probability rows")


class NumpyPrepared:
    """Strong same-input reference: immutable Q, exact dt-bit cache, batch BLAS."""

    def __init__(self, q):
        self.q = np.array(q, dtype=np.float64, order="C", copy=True)
        n=len(q); off=self.q.copy(); np.fill_diagonal(off,0)
        outgoing=off.sum(-1); diagonal=np.diag(self.q)
        if (not np.isfinite(q).all() or (off<0).any() or (diagonal>0).any()
            or np.any(abs(outgoing+diagonal)>64*np.finfo(float).eps*np.maximum(outgoing,-diagonal))):
            raise ValueError("Invalid Q")
        self.q.flags.writeable=False
        self.identity=hashlib.sha256(self.q.tobytes()).hexdigest()
        self.cache={}

    def transition(self, dt):
        if not np.isfinite(dt) or dt<0:raise ValueError("Invalid dt")
        key=np.float64(dt).view(np.uint64).item()
        if key not in self.cache:
            if len(self.cache)>=32:raise ValueError("Cache capacity")
            self.cache[key]=expm(self.q*dt)
            probabilities(self.cache[key])
        return self.cache[key]

    def propagate(self,p,dt,out=None):
        probabilities(p)
        result=np.matmul(p,self.transition(dt),out=out)
        probabilities(result)
        return result

    def observe(self,p,likelihood,out=None):
        probabilities(p)
        if not np.isfinite(likelihood).all() or (likelihood<0).any():raise ValueError("Bad likelihood")
        scale=likelihood.max(-1,keepdims=True)
        if (scale<=0).any():raise ValueError("Impossible observation")
        np.multiply(p,likelihood/scale,out=out)
        normalizer=out.sum(-1,keepdims=True)
        if (normalizer<=0).any():raise ValueError("Impossible observation")
        out/=normalizer
        probabilities(out)
        return out


class Legacy:
    def __init__(self,q):
        path=ROOT.parents[1]/"unified_cell_r12_20261031/native/adapter.py"
        spec=importlib.util.spec_from_file_location("r12native",path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.operator=module.NativeOperator();self.q=q.copy()

    def transition(self,dt):
        return expm(self.q*dt)

    def propagate(self,p,dt,out=None):
        for i,row in enumerate(p):out[i]=self.operator.propagate(self.q,row,dt)
        return out

    def observe(self,p,likelihood,out=None):
        for i,row in enumerate(p):out[i]=self.operator.observe(row,likelihood[i])
        return out


def pipeline(backend,p,likes,times):
    current=p.copy();workspace=np.empty_like(current)
    for i,like in enumerate(likes):
        backend.propagate(current,times[i%len(times)],out=workspace)
        backend.observe(workspace,like,out=current)
    return current


def worker(method,fixture,batch,steps):
    with np.load(ROOT/"evidence/prepared_audit/fixtures"/(fixture+".npz")) as data:
        q,prior=data["Q"],data["prior"]
    p=np.tile(prior,(batch,1));rng=np.random.default_rng(20261101+batch)
    likes=rng.uniform(.05,1,(steps,batch,len(prior)));times=[.15,.45,2.1]
    wall=time.perf_counter();start=time.process_time()
    if method=="numpy_cached":backend=NumpyPrepared(q)
    elif method=="legacy_r12":backend=Legacy(q)
    else:backend=PreparedModel(q,version=13,mode=method)
    constructed=time.process_time()
    if method in ["dense","numpy_cached","legacy_r12"]:
        planner_transitions=[backend.transition(dt) for dt in times]
    else:
        for dt in times:backend.prepare(dt)
        # A sparse operator also needs a legal matrix for the common planner.
        planner_transitions=[expm(q*dt) for dt in times]
    prepared=time.process_time()
    result=pipeline(backend,p,likes,times)
    finished=time.process_time();wall_elapsed=time.perf_counter()-wall
    reference=pipeline(NumpyPrepared(q),p,likes,times)
    error=float(np.max(abs(result-reference)))
    info=backend.cache_info() if isinstance(backend,PreparedModel) else None
    if isinstance(backend,PreparedModel):backend.close()
    return {"method":method,"fixture":fixture,"n_states":len(prior),"batch":batch,"steps":steps,
        "pid":os.getpid(),"construction_cpu_seconds":constructed-start,
        "prepare_and_planner_export_cpu_seconds":prepared-constructed,
        "online_cpu_seconds":finished-prepared,"full_cpu_seconds":finished-start,
        "full_wall_seconds":wall_elapsed,"maximum_posterior_error":error,
        "quality_pass":error<3e-11,"cache_info":info,
        "scope":"Common Q/prior/likelihood inputs and imports are outside backend timer. Includes constructor, all three P preparations/exports, first workspace allocation and every prediction/observation. No controller/text-encoder/GPU timing."}


def run(destination,repetitions=3,steps=30):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    settings=[("default",24),("default",64),("default",256),("coarse",64),("fine",64)]
    jobs=[(method,fixture,batch,repeat) for fixture,batch in settings
          for method in ["legacy_r12","sparse","dense","numpy_cached"] for repeat in range(repetitions)]
    random.Random(20261101).shuffle(jobs)
    results=[];env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
    for index,(method,fixture,batch,repeat) in enumerate(jobs):
        command=[sys.executable,str(Path(__file__).resolve()),"--worker",method,"--fixture",fixture,"--batch",str(batch),"--steps",str(steps)]
        start=time.perf_counter();call=subprocess.run(command,text=True,capture_output=True,env=env,check=True)
        row=json.loads(call.stdout);row["repetition"]=repeat;row["outer_process_wall_seconds"]=time.perf_counter()-start
        results.append(row);print(json.dumps({"completed":index+1,"total":len(jobs),"method":method,"fixture":fixture,"batch":batch,"full_cpu":row["full_cpu_seconds"]}),flush=True)
    groups=[]
    for fixture,batch in settings:
        medians={}
        for method in ["legacy_r12","sparse","dense","numpy_cached"]:
            selected=[x for x in results if x["fixture"]==fixture and x["batch"]==batch and x["method"]==method]
            medians[method]={metric:float(np.median([x[metric] for x in selected])) for metric in
                ["construction_cpu_seconds","prepare_and_planner_export_cpu_seconds","online_cpu_seconds","full_cpu_seconds"]}
        groups.append({"fixture":fixture,"batch":batch,"steps":steps,"medians":medians,
            "full_dense_over_legacy":medians["dense"]["full_cpu_seconds"]/medians["legacy_r12"]["full_cpu_seconds"],
            "full_dense_over_numpy":medians["dense"]["full_cpu_seconds"]/medians["numpy_cached"]["full_cpu_seconds"]})
    receipt=json.loads((ROOT/"evidence/build/BUILD_RECEIPT.json").read_text())
    report={"schema":"hcsn-r13-prepared-cost-v1","results":results,"groups":groups,
        "all_quality_pass":all(x["quality_pass"] for x in results),"repetitions":repetitions,
        "compiler_build":receipt,"benchmark_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "platform":platform.platform(),"numpy_version":np.__version__,
        "claim_scope":"Measured CPU on one host with fixed BLAS threads. Full backend cost includes construction and cache preparation; compilation is separately disclosed in compiler_build and is not counted per model. Outer subprocess wall includes startup but no speedup conclusion uses it. Every backend evaluates identical f64 inputs and must pass the same posterior error threshold."}
    (destination/"RESULTS.json").write_text(json.dumps(report,indent=2)+"\n")
    if not report["all_quality_pass"]:raise AssertionError("Benchmark numerical mismatch")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,default=ROOT/"evidence/benchmark")
    parser.add_argument("--worker",choices=["legacy_r12","sparse","dense","numpy_cached"])
    parser.add_argument("--fixture",default="default");parser.add_argument("--batch",type=int,default=64)
    parser.add_argument("--steps",type=int,default=30);parser.add_argument("--repetitions",type=int,default=3)
    args=parser.parse_args()
    if args.worker:print(json.dumps(worker(args.worker,args.fixture,args.batch,args.steps)))
    else:run(args.output,args.repetitions,args.steps)

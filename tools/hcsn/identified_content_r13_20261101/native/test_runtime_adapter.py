"""The research adapter restores actual state in another Python/Rust process."""

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

from adapter import ROOT
from runtime_adapter import ResearchDistributionRuntime
from runtime_adapter import TickRequest
from runtime_adapter import digest


def run(destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    with np.load(ROOT/"evidence/prepared_audit/fixtures/default.npz") as f:
        q,prior,edges=f["Q"],f["prior"],f["edges"]
    with np.load(ROOT/"evidence/prepared_audit/fixtures/updated.npz") as f:newq=f["Q"]
    layout=hashlib.sha256(edges.tobytes()).hexdigest();observation=digest("frozen-observation-model")
    config={"q":q.tolist(),"prior":prior.tolist(),"version":13,
            "layout_identity":layout,"observation_identity":observation}
    like=np.linspace(.1,.9,len(prior)).tolist()
    script=[{"op":"tick","dt":.25,"read":True,"likelihood":like,"input_digest":digest("acquired-text-1")},
            {"op":"tick","dt":.5,"read":False,"input_digest":digest("wait-1")},
            {"op":"migrate","q":newq.tolist(),"version":14,"at":1.,"layout_identity":layout,
             "observation_identity":observation},
            {"op":"tick","dt":.45,"read":True,"likelihood":like,"input_digest":digest("acquired-text-2")},
            {"op":"tick","dt":.15,"read":False,"input_digest":digest("wait-2")}]
    checks=[];receipts=[]
    def check(name,condition,**details):checks.append({"name":name,"pass":bool(condition),**details})
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
    def process(name,operation,configuration,commands,refuse=False):
        source=destination/(name+".input.json");commands_path=destination/(name+".commands.json")
        output=destination/(name+".checkpoint.json")
        source.write_text(json.dumps(configuration));commands_path.write_text(json.dumps(commands))
        args=[sys.executable,str(ROOT/"runtime_adapter.py"),operation,str(source),str(commands_path),str(output)]
        result=subprocess.run(args,env=env,text=True,capture_output=True,check=False)
        receipt={"name":name,"arguments":args,"returncode":result.returncode,"stderr":result.stderr}
        receipts.append(receipt)
        if refuse:
            check(name,result.returncode!=0 and not output.exists());return None,output
        if result.returncode:raise AssertionError(receipt)
        value=json.loads(result.stdout);receipt["result"]=value
        return value,output
    full,fullpath=process("whole","init",config,script)
    before,prefixpath=process("prefix","init",config,script[:2])
    restoration={"path":str(prefixpath),"expected_model_identity":before["model_identity"],
        "expected_version":13,"expected_layout_identity":layout,"expected_observation_identity":observation}
    after,suffixpath=process("suffix","resume",restoration,script[2:])
    check("actual_process_restore_exact",fullpath.read_bytes()==suffixpath.read_bytes() and
        len({full["pid"],before["pid"],after["pid"]})==3 and full["posterior"]==after["posterior"])
    bad=dict(restoration,expected_version=14)
    process("refuse_model_version","resume",bad,[],True)
    bad=dict(restoration,expected_layout_identity=digest("different-grid"))
    process("refuse_layout","resume",bad,[],True)
    q24=destination/"q24.json";q24.write_text(json.dumps({"schema":"hepta.neuron.sparse-checkpoint.q24.v1"}))
    bad=dict(restoration,path=str(q24))
    process("refuse_Q24_as_distribution","resume",bad,[],True)
    runtime=ResearchDistributionRuntime(**config)
    request=TickRequest(1,.45,runtime._model.identity,13,runtime.checkpoint_digest,digest("actual-read"),True,observation)
    initial=runtime.checkpoint_digest
    failures=[("missing_payload",request,None),
        ("unrequested_payload",replace(request,read=False),like),
        ("wrong_tick_version",replace(request,model_version=14),like),
        ("stale_checkpoint",replace(request,expected_checkpoint=digest("stale")),like),
        ("negative_dt",replace(request,dt=-.1),like),
        ("impossible_observation",request,np.zeros(len(prior)))]
    for name,req,likelihood in failures:
        try:runtime.tick(req,likelihood);check(name,False)
        except ValueError:check(name,runtime.checkpoint_digest==initial)
    runtime.tick(request,like)
    check("successful_bound_tick",runtime.sequence==1 and abs(runtime.posterior.sum()-1)<1e-13 and runtime.clock==.45)
    before=runtime.checkpoint_digest
    try:runtime.migrate(newq,14,1.,digest("other-grid"),observation,before);check("refuse_implicit_grid_remap",False)
    except ValueError:check("refuse_implicit_grid_remap",runtime.checkpoint_digest==before)
    save=destination/"no_overwrite.checkpoint.json";runtime.save(save);original=save.read_bytes()
    try:runtime.save(save);check("no_checkpoint_overwrite",False)
    except FileExistsError:check("no_checkpoint_overwrite",save.read_bytes()==original)
    runtime.close()
    report={"schema":"hcsn-r13-research-runtime-adapter-audit-v1","checks":checks,
        "all_passed":all(x["pass"] for x in checks),"process_receipts":receipts,
        "source_sha256":{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
            ["runtime_adapter.py","adapter.py","test_runtime_adapter.py"]},
        "production_activation":False,
        "scope":"Distribution checkpoint and native event checkpoint are distinct tagged states. This adapter does not implement production journal/witness authorization."}
    (destination/"RESULTS.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"all_passed":report["all_passed"],"checks":len(checks)}))
    if not report["all_passed"]:raise AssertionError([x for x in checks if not x["pass"]])
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,default=ROOT/"evidence/runtime_adapter_audit")
    run(parser.parse_args().output)

"""Live trained-model owner recovery with causal Torch reference, never an oracle.

Only after native completion does the auditor consume actual public OPEN and
purchased REFRESH records. Reference predictions are checked before reading the
private scoring labels. No unpurchased response is supplied to either policy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

import numpy as np
import torch
from experiments.hcsn_learned_core_r19_20261102.models import ContentNetwork,replace
from tools.hcsn.addressed_decision_r15_20261101.execution import price
from tools.hcsn.addressed_decision_r15_20261101.law import Law
from tools.hcsn.native_numeric_r19_20261102.campaign import Meter,save,wait_provider
from tools.hcsn.native_numeric_r19_20261102.provider import seal

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
LEARNED=ROOT/"experiments/hcsn_learned_core_r19_20261102"

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def owned(path):
    text=path.read_text();body,trailer=text.rsplit("CHECK\t",1);value=0xcbf29ce484222325
    for byte in body.encode():value=((value^byte)*0x100000001b3)%2**64
    assert trailer==f"{value:016x}\n"
    return body.splitlines()

def stress_seed(protocol):
    # Selection is based solely on declared public prices, never states/labels.
    for seed in range(protocol["world_seed_base"]+50000,protocol["world_seed_base"]+100000):
        scales=[price(seed,q)for q in range(6)]
        if scales[0]==.5 and scales.count(.5)>=3:return seed
    raise RuntimeError("No registered cheap-observation stress seed")

def reference(case,profile,native):
    model=ContentNetwork("analytic",Law())
    weights=LEARNED/"run_01"/f"weights_{profile['name']}.pt"
    assert digest(weights)==profile["checkpoint_sha256"]
    model.load_state_dict(torch.load(weights,weights_only=True));model.eval()
    db=sqlite3.connect(f"file:{case/'provider.sqlite'}?mode=ro",uri=True)
    opens={}
    for (response,)in db.execute("SELECT response FROM replies"):
        if response.startswith("OPEN\t"):
            row=response.split("\t");q=int(row[1])
            if q in opens:assert opens[q]==row
            opens[q]=row
    effects=[(opid,json.loads(semantic),response,float(fee))for opid,semantic,response,fee in db.execute("SELECT opid,semantic,response,fee FROM effects")]
    assert set(opens)==set(range(6))
    initial=torch.tensor([[int(v)for v in opens[0][7].split(',')]],dtype=torch.long)
    state=model.initial(initial);rows=[]
    for q in range(6):
        public=opens[q];key=int(public[2]);dt=float(public[3]);scale=float(public[6])
        if public[8]!="-":
            for event in public[8].split(','):
                k,v=map(int,event.split(':'));kt=torch.tensor([k]);vt=torch.tensor([v]);state=replace(state,kt,model.event_update(state[:,k],vt,0))
        transition=torch.matrix_exp(model.Q*(3.*dt*model.log_scale.exp()))
        state=model.project(state@transition)
        before=model.logits(state[:,key]);prior=before.softmax(-1)
        posterior=torch.stack([model.event_update(state[:,key],torch.tensor([v]),1)for v in range(4)],1)
        after_logits=model.logits(posterior);after_prob=after_logits.softmax(-1)
        expected=((prior@model.channel)*after_prob.max(-1).values).sum(-1)
        fee=torch.tensor([np.float32(.07*scale+.003*3.*dt)],dtype=torch.float32)
        signed=expected-fee-prior.max(-1).values
        read=bool((signed>0)[0])if profile["control"]=="value"else bool((fee<=profile["threshold"])[0])
        # If a native decision differs, reject before consulting a response the
        # reference policy did not purchase under this common observed prefix.
        if read!=bool(native[q,0]):
            save(case/"CHOICE_MISMATCH.json",dict(query=q,torch_read=read,native_read=bool(native[q,0]),
                fee=float(fee[0]),torch_read_value=float(expected[0]),torch_prior=prior.detach().numpy().tolist(),
                no_unpurchased_response_consumed=True))
            raise AssertionError(f"trained READ mismatch at query{q}")
        actuators=[row for row in effects if row[1][0]=="ACT"and row[1][2]==q]
        if read:
            assert sorted(row[1][4]for row in actuators)==["REFRESH","WAIT"]
            receipt=next(row[2].split("\t")for row in actuators if row[1][4]=="REFRESH")
            token=int(receipt[3]);assert int(receipt[2])==3 and abs(float(receipt[4])-float(public[5]))<1e-10
            state=replace(state,torch.tensor([key]),posterior[:,token]);logits=after_logits[:,token]
        else:
            assert not actuators;logits=before
        answer=logits.argmax(-1)
        head_values=torch.cat((before[:,None],after_logits),1).topk(2,dim=-1).values
        min_head=(head_values[...,0]-head_values[...,1]).min(-1).values
        gap=signed.abs()if profile["control"]=="value"else(fee-profile["threshold"]).abs()
        rows.append(torch.cat((torch.tensor([[float(read)]]),answer[:,None],state.flatten(1),before,prior,
            after_logits.flatten(1),after_prob.flatten(1),expected[:,None],gap[:,None],min_head[:,None]),-1).detach().numpy()[0])
    result=np.stack(rows);assert result.shape==native.shape==(6,205)
    errors=np.abs(result-native)
    metrics=dict(state_max_error=float(errors[:,2:162].max()),logits_max_error=float(max(errors[:,162:166].max(),errors[:,170:186].max())),
        probs_max_error=float(max(errors[:,166:170].max(),errors[:,186:202].max())),read_value_max_error=float(errors[:,202].max()),
        margin_max_error=float(errors[:,203:205].max()),
        exact_actions_answers=bool(np.array_equal(result[:,:2],native[:,:2])))
    assert metrics["state_max_error"]<=5e-9 and metrics["logits_max_error"]<=1e-5 and metrics["probs_max_error"]<=2e-6 and metrics["read_value_max_error"]<=1e-5 and metrics["margin_max_error"]<=2e-5 and metrics["exact_actions_answers"]
    # Targets enter only the post-inference scorer comparison below.
    scores=[json.loads(body)for(body,)in db.execute("SELECT body FROM scores ORDER BY query")]
    assert len(scores)==6
    for q,score in enumerate(scores):
        read=bool(native[q,0]);expected_fee=(.07*float(opens[q][6])+.003*3.*float(opens[q][3]))if read else 0.
        assert score["answer"]==int(native[q,1])and abs(score["fee"]-expected_fee)<1e-12
    cursor=json.loads(db.execute("SELECT body FROM cursor").fetchone()[0]);db.close()
    np.savez_compressed(case/"TORCH_PARITY.npz",native=native,torch=result)
    save(case/"PRIVATE_SCORER.json",scores)
    return metrics,dict(reads=int(native[:,0].sum()),correct=sum(row["reward"]for row in scores),
        utility=sum(row["utility"]for row in scores)/6,generation=cursor["generation"],effects=len(effects))

def case(binary,profile,out,mailbox,seed,domain,fault_stage):
    out.mkdir();run=hashlib.sha256(json.dumps(dict(profile=profile["profile_sha256"],seed=seed,domain=domain,fault=fault_stage),sort_keys=True).encode()).hexdigest()
    private=dict(run=run,model=Law().export(),seed=seed,domain=domain,query_count=6);save(out/"private_owner.json",private)
    meter=Meter(out);provider=meter.start("provider",[sys.executable,"-m","tools.hcsn.native_numeric_r19_20261102.provider",str(out/"private_owner.json"),str(out/"provider.sqlite"),str(mailbox),"none",str(out/"provider.marker")]);wait_provider(out)
    marker=out/"fault.marker";args=[str(binary),"owner",str(HERE/profile["profile"]),str(out/"owner.state"),str(mailbox),run,fault_stage,str(marker)]
    child=meter.start("owner1",args);killed=False
    if fault_stage!="none":
        deadline=time.monotonic()+30
        while not marker.exists():
            if(out/"owner1.stderr").read_text():break
            if(out/"owner.state").exists()and int(owned(out/"owner.state")[0].split("\t")[5])==6:break
            if time.monotonic()>deadline:raise TimeoutError("trained owner fault")
            time.sleep(.005)
        killed=marker.exists()
    process=meter.wait(child,kill=killed)
    if killed:
        assert process["exit_code"]==-9;args[-2]="none";child=meter.start("owner2",args);process=meter.wait(child)
    meter.wait(provider,kill=True);shutil.rmtree(mailbox)
    if process["exit_code"]!=0:
        failure=dict(status="FAIL",profile=profile["name"],seed=seed,domain=domain,fault=fault_stage,actually_killed=killed,
            exit_code=process["exit_code"],stderr=(out/f"{process['label']}.stderr").read_text(),quality=None)
        save(out/"CHECK.json",failure);return failure,meter.rows
    lines=owned(out/"owner.state");header=lines[0].split("\t");assert int(header[5])==6 and header[6]=="open"and header[3]==profile["checkpoint_sha256"]
    raw=[line.split("\t")for line in lines if line.startswith("ROW\t")];assert [int(row[1])for row in raw]==list(range(6))
    native=np.asarray([[float(v)for v in row[2:]]for row in raw]);assert native.shape==(6,205)
    try:
        with torch.no_grad():metrics,score=reference(out,profile,native)
    except Exception as error:
        failure=dict(status="FAIL",profile=profile["name"],seed=seed,domain=domain,fault=fault_stage,
            actually_killed=killed,error_type=type(error).__name__,error=str(error),native_completed=True,quality=None)
        save(out/"CHECK.json",failure);return failure,meter.rows
    assert score["generation"]==(2 if killed else 1)and score["effects"]==6+2*score["reads"]
    fee=sum(row["fee"]for row in json.loads((out/"PRIVATE_SCORER.json").read_text()))
    assert int(header[16])==round(fee*1e6)
    record=dict(status="PASS",profile=profile["name"],checkpoint_sha256=profile["checkpoint_sha256"],profile_sha256=profile["profile_sha256"],
        run=run,seed=seed,domain=domain,fault=fault_stage,actually_killed=killed,**metrics,**score,
        child_cpu_seconds=sum(r["cpu_seconds"]for r in meter.rows),native_checkpoint_bytes=(out/"owner.state").stat().st_size)
    save(out/"CHECK.json",record);return record,meter.rows

def reject_bad_state(binary,profile,completed,out):
    out.mkdir();meter=Meter(out);profile_path=HERE/profile["profile"];lines=owned(completed/"owner.state");header=lines[0].split("\t");run=header[1]
    changed=profile_path.read_text().splitlines()
    for i,line in enumerate(changed):
        fields=line.split()
        if fields[0]=="H0W":
            fields[1]=format(float(fields[1])+1e-3,".17e");changed[i]="\t".join(fields);break
    altered=out/"same_checkpoint_changed_head.model";altered.write_text("\n".join(changed)+"\n")
    attempts=[("changed_head_same_checkpoint",altered,seal("\n".join(lines)+"\n"))]
    for name,field,value in [("nan_model_clock",12,"NaN"),("wrong_clock_phase",12,"0")]:
        body=lines.copy();h=header.copy();h[field]=value;body[0]="\t".join(h);attempts.append((name,profile_path,seal("\n".join(body)+"\n")))
    for name,value in [("nan_belief","NaN"),("negative_belief","-0.1")]:
        body=lines.copy();p=body[1].split("\t");p[1]=value;body[1]="\t".join(p);attempts.append((name,profile_path,seal("\n".join(body)+"\n")))
    results={}
    for name,model,text in attempts:
        state=out/f"{name}.state";state.write_text(text);child=meter.start(name,[str(binary),"owner",str(model),str(state),str(out/"absent-mailbox"),run,"none",str(out/f"{name}.marker")]);r=meter.wait(child);error=(out/f"{name}.stderr").read_text()
        assert r["exit_code"]==2 and any(token in error for token in ["trained owner context","nonfinite trained state","trained belief profile","trained model/physical clock phase mismatch"]),error
        results[name]=True
    save(out/"CHECK.json",results);return results,meter.rows

def run(output,binary,development,publication_path=None):
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    protocol=json.loads((HERE/"OWNER_PROTOCOL.json").read_text());profiles=json.loads((HERE/"PROFILE_MANIFEST.json").read_text())["profiles"]
    publication=None
    if not development:
        assert publication_path is not None,"A remote source readback receipt is mandatory"
        freeze=json.loads((HERE/"OWNER_SOURCE_FREEZE.json").read_text());publication=json.loads(publication_path.read_text())
        assert publication["readback_verified"]and publication["manifest_sha256"]==digest(HERE/"OWNER_SOURCE_FREEZE.json")
        for name,expected in freeze["files"].items():assert digest(ROOT/name)==expected,name
    output.mkdir(parents=True,exist_ok=False);save(output/"START.json",dict(development=development,publication=publication))
    cases=[];processes=[];negative_checks=None
    with tempfile.TemporaryDirectory(prefix="learned-owner-")as scratch:
        selected=profiles[:2]if development else profiles
        for profile in selected:
            assert digest(HERE/profile["profile"])==profile["profile_sha256"]
            for domain in protocol["domains"]:
                for index in range(1 if development else protocol["worlds_per_domain"]):
                    seed=(protocol["development_seed"]if development else protocol["world_seed_base"])+(1000 if domain=="ood"else 0)+index
                    row,receipts=case(binary,profile,output/f"{profile['name']}_{domain}_{index}",Path(scratch)/"ipc",seed,domain,"none");cases.append(row);processes+=receipts
                    if negative_checks is None and row["status"]=="PASS":
                        negative_checks,receipts=reject_bad_state(binary,profile,output/f"{profile['name']}_{domain}_{index}",output/"negative_states");processes+=receipts
            for fault_stage in protocol["faults"]:
                seed=stress_seed(dict(protocol,world_seed_base=protocol["development_seed"]))if development else stress_seed(protocol)
                row,receipts=case(binary,profile,output/f"{profile['name']}_{fault_stage}",Path(scratch)/"ipc",seed,"ood",fault_stage);cases.append(row);processes+=receipts
    all_passed=all(row["status"]=="PASS"for row in cases)
    summary=dict(schema="hcsn-learned-owner-recovery-v1",development=development,publication=publication,all_passed=all_passed,
        cases=cases,case_count=len(cases),profile_count=len(selected),actual_kills=sum(row["actually_killed"]for row in cases),
        negative_checks=negative_checks,
        process_count=len(processes),complete_child_cpu_seconds=sum(row["cpu_seconds"]for row in processes),binary_sha256=digest(binary),production_activation=False)
    save(output/"SUMMARY.json",summary);print(json.dumps({k:v for k,v in summary.items()if k!="cases"},sort_keys=True),flush=True)
    if not all_passed:raise RuntimeError("At least one trained native candidate failed; keep every case and do not claim qualification")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);p.add_argument("--binary",type=Path,required=True);p.add_argument("--development",action="store_true");p.add_argument("--publication",type=Path);a=p.parse_args();run(a.output.resolve(),a.binary.resolve(),a.development,a.publication)

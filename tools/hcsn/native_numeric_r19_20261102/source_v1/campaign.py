"""Frozen native numerical/control qualification with a private live owner.

References and scorer records never enter the Rust actor. Native inputs are
public Q/prior/emissions, public OPEN events and actual completed ACT replies.
"""
import argparse
from decimal import Decimal, localcontext
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import expm

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..cold_recovery_r17_20261101.runtime import Session, canonical, digest
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import execute
from .provider import unseal, seal
from .reference_fallback import decision

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as stream:stream.write(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n")

def export_model(payload,path):
    lines=["MODEL\t"+payload["identity"]]
    for name,key in [("Q","Q"),("PRIOR","prior"),("READ","E_read"),("REFRESH","E_refresh")]:
        values=np.asarray(payload[key],dtype=float).ravel()
        lines.append(name+"\t"+"\t".join(format(x,".17e")for x in values))
    with path.open("x") as stream:stream.write("\n".join(lines)+"\n")

class Meter:
    def __init__(self,out):self.out,self.rows=out,[]
    def start(self,label,args):
        out=(self.out/f"{label}.stdout").open("xb");err=(self.out/f"{label}.stderr").open("xb")
        return dict(p=subprocess.Popen(args,stdout=out,stderr=err),label=label,args=args,out=out,err=err,wall=time.perf_counter())
    def wait(self,item,kill=False):
        if kill:os.kill(item["p"].pid,9)
        _,status,r=os.wait4(item["p"].pid,0);code=os.waitstatus_to_exitcode(status);item["p"].returncode=code;item["out"].close();item["err"].close()
        row=dict(label=item["label"],command=item["args"],pid=item["p"].pid,exit_code=code,cpu_seconds=r.ru_utime+r.ru_stime,max_rss_kib=r.ru_maxrss,wall_seconds=time.perf_counter()-item["wall"])
        save(self.out/f"{item['label']}.process.json",row);self.rows.append(row);return row

def wait_provider(directory):
    deadline=time.monotonic()+10
    while not (directory/"provider.stdout").exists() or not (directory/"provider.stdout").read_text().startswith("READY"):
        if time.monotonic()>deadline:raise TimeoutError("provider readiness")
        time.sleep(.005)

def decimal_rare(q,emission,t,basis=28):
    # Independent signed Q-Taylor expansion; uniformization is not called.
    with localcontext() as context:
        context.prec=100
        matrix=[[Decimal.from_float(float(x))for x in row]for row in q]
        step=Decimal.from_float(float(t));term=[Decimal(0)]*40;term[basis]=Decimal(1);total=term.copy()
        for k in range(1,81):
            term=[sum((term[i]*matrix[i][j]for i in range(40)),Decimal(0))*step/Decimal(k)for j in range(40)]
            total=[total[j]+term[j]for j in range(40)]
        p=np.asarray([float(x)for x in total]);weighted=p*emission[:,4]
        return weighted.sum(),weighted/weighted.sum()

def operator_check(binary,model_path,payload,t,directory,meter,protocol):
    out=directory/"operator.tsv"
    process=meter.start("operator",[str(binary),"operator",str(model_path),str(t),str(out)])
    assert meter.wait(process)["exit_code"]==0
    data={line.split()[0]:np.asarray([float(x)for x in line.split()[1:]])for line in out.read_text().splitlines()if line.strip()}
    q=np.asarray(payload["Q"]);killed=q.copy();rate=np.zeros(40);rate[:4]=q[np.arange(4),32+np.arange(4)];killed[np.arange(4),32+np.arange(4)]=0
    p=data["P"].reshape(40,40);pk=data["KILLED"].reshape(40,40)
    aug=np.zeros((41,41));aug[:40,:40]=q;aug[:40,40]=rate;ak=aug.copy();ak[:40,:40]=killed
    errors=dict(scipy_transition=float(np.max(abs(p-expm(t*q)))),scipy_killed=float(np.max(abs(pk-expm(t*killed)))),
        scipy_count=float(np.max(abs(data["COUNT"]-expm(t*aug)[:40,40]))),scipy_hit=float(np.max(abs(data["HIT"]-expm(t*ak)[:40,40]))),
        mass=float(np.max(abs(p.sum(1)-1))),hit_survival=float(np.max(abs(pk.sum(1)+data["HIT"]-1))))
    if t>0:
        initial=np.r_[np.eye(40).ravel(),np.eye(40).ravel(),np.zeros(40)]
        def rhs(_,value):
            full=value[:1600].reshape(40,40);kill=value[1600:3200].reshape(40,40)
            return np.r_[(full@q).ravel(),(kill@killed).ravel(),full@rate]
        solution=solve_ivp(rhs,(0,t),initial,method="DOP853",rtol=2e-12,atol=2e-14)
        assert solution.success
        ref=solution.y[:,-1]
        errors.update(ode_transition=float(np.max(abs(p-ref[:1600].reshape(40,40)))),ode_killed=float(np.max(abs(pk-ref[1600:3200].reshape(40,40)))),ode_count=float(np.max(abs(data["COUNT"]-ref[3200:]))))
    assert all(value<=protocol["operator_absolute_tolerance"]for value in errors.values()),errors
    rare=None
    if t==1e-5:
        emission=np.asarray(payload["E_read"]);mass,posterior=decimal_rare(q,emission,t)
        native=p[28]*emission[:,4];scipy=expm(t*q)[28]*emission[:,4]
        rare=dict(native_likelihood=float(native.sum()),decimal_likelihood=float(mass),native_relative_likelihood_error=float(abs(native.sum()/mass-1)),
            native_posterior_error=float(np.max(abs(native/native.sum()-posterior))),scipy_relative_likelihood_error=float(abs(scipy.sum()/mass-1)),scipy_posterior_error=float(np.max(abs(scipy/scipy.sum()-posterior))))
        assert rare["native_relative_likelihood_error"]<=protocol["rare_relative_tolerance"]
        assert rare["native_posterior_error"]<=protocol["rare_posterior_tolerance"]
    row=dict(time=t,errors=errors,rare=rare,reported_bound=data["BOUND"].tolist())
    save(directory/"CHECK.json",row);return row

def execute_case(binary,model_path,law,owner,fit,domain,index,rep,directory,mailbox,protocol,fault_stage="none"):
    directory.mkdir();seed=protocol["world_seed_base"]+(1000 if domain=="ood"else 0)+index
    run=digest(dict(fit=fit,domain=domain,index=index,rep=rep,fault=fault_stage,namespace=protocol["world_seed_base"]))
    config=dict(run=run,model=owner.export(),seed=seed,domain=domain,query_count=6)
    save(directory/"private_owner.json",config)
    meter=Meter(directory);marker=directory/"fault.marker"
    provider=meter.start("provider",[sys.executable,"-m","tools.hcsn.native_numeric_r19_20261102.provider",str(directory/"private_owner.json"),str(directory/"provider.sqlite"),str(mailbox),"none",str(directory/"provider.marker")])
    wait_provider(directory)
    args=[str(binary),"owner",str(model_path),str(directory/"owner.state"),str(mailbox),run,rep,fault_stage,str(marker)]
    native=meter.start("native1",args)
    killed=False
    if fault_stage!="none":
        deadline=time.monotonic()+20
        while not marker.exists():
            # q==6 persisted means no logical action reached this optional hook.
            if (directory/"owner.state").exists():
                head=unseal((directory/"owner.state").read_bytes()).splitlines()[0].split("\t")
                if int(head[5])==6:break
            if (directory/"native1.stderr").read_text():break
            if time.monotonic()>deadline:raise TimeoutError("native fault")
            time.sleep(.005)
        killed=marker.exists()
    first=meter.wait(native,kill=killed)
    if killed:
        assert first["exit_code"]==-9
        args[-2]="none";native=meter.start("native2",args);final=meter.wait(native)
    else:final=first
    if final["exit_code"]!=0:
        meter.wait(provider,kill=True)
        failure=dict(exit_code=final["exit_code"],stderr=(directory/f"{final['label']}.stderr").read_text(),native_qualified=False)
        if "UNCERTIFIED_" in failure["stderr"]:
            failure["separate_reference_fallback"]=decision(model_path,directory/"owner.state")
        save(directory/"FAILURE.json",failure)
        raise AssertionError(failure)
    assert meter.wait(provider,kill=True)["exit_code"]==-9
    # Only after native execution finishes do references/targets enter scoring.
    ep=make_episode(owner,seed,domain);reference=execute(law,ep,representation=rep)
    session=Session(dict(model=law.export(),owner_model=owner.export(),seed=seed,domain=domain,owner_fingerprint=ep.fingerprint,representation=rep,policy="value",pattern="stop"));state=session.initial()
    while state["status"]!="done":session.advance(state)
    lines=unseal((directory/"owner.state").read_bytes()).splitlines();header=lines[0].split("\t")
    beliefs=np.asarray([float(x)for x in lines[2].split("\t")[1:]]).reshape(4,40)
    expected=state["memory"]
    if rep=="full":expected_beliefs=np.asarray(expected["beliefs"])
    else:
        masses=np.asarray(expected["packed"]);expected_beliefs=np.zeros((4,40))
        for j in range(40):expected_beliefs[:,j]=masses[:,j%4+(4 if j>=32 else 0)]/(2 if j>=32 else 8)
    max_error=float(np.max(abs(beliefs-expected_beliefs)))
    assert max_error<=protocol["owned_state_tolerance"],max_error
    actions=[line.split("\t")[1:5]for line in lines if line.startswith("ACTION\t")]
    expected_actions=[[str(q["query"]),a["action"],str(a["step"]),str(-1 if a["token"]is None else a["token"])]for q in reference["queries"]for a in q["actions"]]
    assert actions==expected_actions,(actions,expected_actions)
    submissions=[line.split("\t")for line in lines if line.startswith("SUBMIT\t")]
    db=sqlite3.connect(f"file:{directory/'provider.sqlite'}?mode=ro",uri=True)
    scores=[json.loads(row[0])for row in db.execute("SELECT body FROM scores ORDER BY query")]
    assert len(scores)==len(submissions)==6
    for query,actual,submitted in zip(reference["queries"],scores,submissions,strict=True):
        assert query["answer"]==actual["answer"]==int(submitted[3])
        assert query["target"]==actual["target"]and query["reward"]==actual["reward"]
        assert abs(query["fee"]-actual["fee"])<=1e-12 and round(query["fee"]*1e6)==int(submitted[4])
    db.close();shutil.rmtree(mailbox)
    row=dict(fit=fit,domain=domain,index=index,representation=rep,run=run,world=ep.fingerprint,fault_stage=fault_stage,actually_killed=killed,
        all_actions_and_answers_equal=True,owned_max_error=max_error,min_action_gap=float(header[21]),min_answer_gap=float(header[22]),total_fee_micros=int(header[16]),
        public_model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),native_model_context=header[2],
        child_cpu_seconds=sum(x["cpu_seconds"]for x in meter.rows),queries=len(scores),actions=len(actions))
    save(directory/"REFERENCE.json",dict(queries=reference["queries"],final_memory=expected));save(directory/"CHECK.json",row)
    return row,meter.rows

def negative_contexts(binary,model_path,completed_case,directory):
    directory.mkdir();meter=Meter(directory);original=(completed_case/"owner.state").read_text();lines=unseal(original.encode()).splitlines();head=lines[0].split("\t");run,rep=head[1],head[3]
    model_lines=model_path.read_text().splitlines();qline=model_lines[1].split("\t");q=np.asarray([float(x)for x in qline[1:]]).reshape(40,40);q[0,4]+=1e-5;q[0,0]-=1e-5
    model_lines[1]="Q\t"+"\t".join(format(x,".17e")for x in q.ravel());altered=directory/"same_header_changed_valid_Q.tsv";altered.write_text("\n".join(model_lines)+"\n")
    cases=[("changed_model_same_header",altered,original)]
    for name,field,value in [("nan_clock",12,"NaN"),("negative_clock",12,"-1")]:
        body=lines.copy();h=head.copy();h[field]=value;body[0]="\t".join(h);cases.append((name,model_path,seal("\n".join(body)+"\n")))
    for name,value in [("nan_belief","NaN"),("negative_belief","-0.1")]:
        body=lines.copy();p=body[2].split("\t");p[1]=value;body[2]="\t".join(p);cases.append((name,model_path,seal("\n".join(body)+"\n")))
    results={}
    for name,model,text in cases:
        state=directory/f"{name}.state";state.write_text(text)
        child=meter.start(name,[str(binary),"owner",str(model),str(state),str(directory/"absent-mailbox"),run,rep,"none",str(directory/f"{name}.marker")]);receipt=meter.wait(child)
        error=(directory/f"{name}.stderr").read_text();assert receipt["exit_code"]==2 and ("state context"in error or"invalid owned"in error),error;results[name]=True
    save(directory/"CHECK.json",results);return results,meter.rows

def run(output,binary,manifest_path):
    output.mkdir(parents=True,exist_ok=False);protocol=json.loads((HERE/"PROTOCOL.json").read_text());manifest=json.loads(manifest_path.read_text())
    for relative,sha in manifest["files"].items():assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==sha,relative
    owner=Law();operator_rows=[];cases=[];receipts=[];negative_checks=None
    with tempfile.TemporaryDirectory(prefix="n19-")as scratch:
        for fit in protocol["fits"]:
            folder=output/str(fit);folder.mkdir();training=json.loads(gzip.decompress((ROOT/protocol["training_pattern"].format(fit=fit)).read_bytes()));law=BlockLaw.from_payload(training["calibration"]["models"]["hx"]["payload"]);model_path=folder/"public_model.tsv";export_model(law.export(),model_path)
            for ti,t in enumerate(protocol["operator_times"]):
                d=folder/f"operator_{ti}";d.mkdir();meter=Meter(d);operator_rows.append(dict(fit=fit,**operator_check(binary,model_path,law.export(),t,d,meter,protocol)));receipts+=meter.rows
            for domain in protocol["domains"]:
                for index in range(protocol["worlds_per_domain"]):
                    for rep in protocol["representations"]:
                        d=folder/f"{domain}_{index}_{rep}";row,rows=execute_case(binary,model_path,law,owner,fit,domain,index,rep,d,Path(scratch)/"ipc",protocol);cases.append(row);receipts+=rows
                        if negative_checks is None:
                            negative_checks,rows=negative_contexts(binary,model_path,d,output/"negative_contexts");receipts+=rows
            for rep in protocol["representations"]:
                d=folder/f"cold_{rep}";row,rows=execute_case(binary,model_path,law,owner,fit,"ood",0,rep,d,Path(scratch)/"ipc",protocol,"received_before_commit");cases.append(row);receipts+=rows
    summary=dict(schema="hcsn-r19-native-numeric-results-v1",source_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        cases=cases,operator_checks=operator_rows,all_passed=True,native_case_count=len(cases),actual_cold_recoveries=sum(r["actually_killed"]for r in cases),
        negative_checks=negative_checks,
        complete_child_cpu_seconds=sum(r["cpu_seconds"]for r in receipts),process_count=len(receipts),production_activation=False)
    save(output/"SUMMARY.json",summary);print(canonical({k:v for k,v in summary.items()if k not in("cases","operator_checks")}),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);p.add_argument("--binary",type=Path,required=True);p.add_argument("--manifest",type=Path,required=True);a=p.parse_args();run(a.output.resolve(),a.binary.resolve(),a.manifest.resolve())

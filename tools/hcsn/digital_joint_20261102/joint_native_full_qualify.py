"""Real joint33/GRU owner, current-at-due FullHX, ACK and transaction crashes.

These are excluded, hand-built engineering fixtures with untrained exported
weights; no latent target labels, teacher Q, scientific cohort or efficacy claim.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import numpy as np
from . import joint_task as task
from .joint_deploy import NumpyPolicy
from . import joint_native_owner as transaction

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]


def same_state(a,b):
    a,b=copy.deepcopy(a),copy.deepcopy(b)
    for key in ("charges","elapsed"):
        if abs(a.pop(key)-b.pop(key))>2e-12:raise AssertionError("task time/fee mismatch")
    if a!=b:raise AssertionError("joint complete task/history/due mismatch")


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--binary",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True);p.add_argument("--models",type=Path)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    models=out/"models";models.mkdir()
    for family in ("renewal","full_markov","affine_markov","gru"):
        source=(a.models/(family+".json") if a.models else HERE/"evidence"/("development_affine_fixture" if family=="affine_markov" else "development_policy_fixture")/(family+".json"))
        shutil.copyfile(source,models/(family+".json"))
    public_template=json.loads((HERE/"evidence/development_policy_fixture/states.json").read_bytes())["public"]
    content=HERE.parent/"round9_20261031/native/fixtures/fullhx.json"
    adapter=task.ContentAdapter();cases=[];fault_cases=[];commands=[];maximum=0.;reads=0;pending=0;refusals=0;memory_refusals=0;blind_checks=0

    def invoke(command,expected=(0,),env=None):
        result=subprocess.run(command,cwd=REPO,capture_output=True,text=True,timeout=90,env=env)
        row=dict(command=command,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
        transaction.save(out/f"invocation_{len(commands):04d}.json",row);commands.append(row)
        if result.returncode not in expected:raise AssertionError(f"unexpected process status {result.returncode}: {result.stderr[-3000:]}")
        return json.loads(result.stdout) if result.returncode==0 else None

    def native(config,snapshot,steps,ack=None,expected=(0,)):
        command=[str(a.binary.resolve()),"--public",str(config["public"]),"--policy",str(config["policy"]),"--content-model",str(content),
                 "--controller",config["controller"],"--seed",str(config["seed"]),"--snapshot",str(snapshot),"--mode","qualification","--steps",str(steps)]
        if ack is not None:command += ["--ack",ack]
        return invoke(command,expected)

    def wrapped(config,root,operation,request,ack=None,fault=None,expected=(0,)):
        command=[sys.executable,"-m","tools.hcsn.digital_joint_20261102.joint_native_owner",operation,"--root",str(root),"--request-id",request]
        for key,value in config.items():command += ["--"+key,str(value)]
        if ack is not None:command += ["--ack",ack]
        if fault is not None:command += ["--fault",fault]
        return invoke(command,expected)

    fixtures=[]
    for distance in (.125,.375,.75):
        for missing in (False,True):
            folder=out/f"engineering_prior{distance}_missing{int(missing)}";folder.mkdir()
            public=copy.deepcopy(public_template);public.update(id=folder.name,prior_distance=distance)
            for i,name in enumerate(public["packets"]):
                transaction.save(folder/name,task.packet(i%2,991800+i,32))
                public["packet_sha256"][i]=transaction.digest(folder/name)
            if missing:(folder/public["packets"][1]).unlink()  # READ(0) completes at boundary 2, packet slot 1.
            transaction.save(folder/"public.json",public);fixtures.append(dict(folder=folder,public=public,missing=missing))
    for family in ("renewal","full_markov","affine_markov","gru"):
        artifact=json.loads((models/(family+".json")).read_bytes());policy=NumpyPolicy(artifact)
        for fi,fixture in enumerate(fixtures):
            public=fixture["public"];folder=fixture["folder"]
            for controller in ("fixed","value"):
                config=dict(binary=a.binary.resolve(),public=folder/"public.json",policy=models/(family+".json"),content=content,controller=controller,seed=991181)
                name=f"{family}_{fi}_{controller}"; rawdir=out/(name+"_raw");rawdir.mkdir()
                actual=native(config,rawdir/"full.json",7)
                prefix=native(config,rawdir/"resume.json",1)
                pending+=prefix["after"]["task"]["pending"] is not None
                resumed=native(config,rawdir/"resume.json",7,prefix["acknowledged_sha256"])
                if actual["after"]!=resumed["after"] or actual["acknowledged_sha256"]!=resumed["acknowledged_sha256"]:
                    raise AssertionError("joint complete probability/GRU/history/native ACK recovery mismatch")
                python=task.Owner(public,folder,adapter); expected=[]
                while not python.state["terminal"]:
                    scores=policy.predict(public,python.state);mask=task.legal(public,python.state)
                    action=task.fixed_action(python.state,mask,scores["belief"]) if controller=="fixed" else int(np.argmax(np.where(mask,scores["q"],-np.inf)))
                    receipt=python.step(action);expected.append(dict(scores=scores,receipt=receipt))
                if [r["action"] for r in actual["receipts"]]!=[r["receipt"]["action"] for r in expected]:raise AssertionError("joint whole-episode route mismatch")
                same_state(actual["after"]["task"],python.state)
                error=0.
                for got,want in zip(actual["receipts"],expected):
                    same_state(got["before"],want["receipt"]["before"]);same_state(got["after"],want["receipt"]["after"])
                    if got["completion"]!=want["receipt"]["completion"] or got["due_source"]!=want["receipt"]["source_opened"]:raise AssertionError("READ observed request-time rather than current-at-due content")
                    score=want["scores"]
                    error=max(error,float(np.max(np.abs(np.asarray(got["q"])-score["q"]))),abs(got["belief"]-score["belief"]))
                    error=max(error,float(np.max(np.abs(np.asarray(got["cell_before"]["mass"])-score["mass"]))),float(np.max(np.abs(np.asarray(got["cell_before"]["bank"])-score["bank"]))))
                    mass,bank,_=policy.represent(public,got["after"])
                    error=max(error,float(np.max(abs(np.asarray(got["cell_after"]["mass"])-mass))),float(np.max(abs(np.asarray(got["cell_after"]["bank"])-bank))))
                    if got["actual_content_calls"]!=int(want["receipt"]["source_opened"] is not None and not want["receipt"]["completion"].get("failure",False)):raise AssertionError("FullHX actual invocation mismatch")
                    reads+=got["actual_content_calls"]
                if error>5e-12:raise AssertionError("joint Rust/NumPy Q/mass/bank mismatch")
                maximum=max(maximum,error)
                if controller=="fixed":
                    native(config,rawdir/"resume.json",0,expected=(2,));native(config,rawdir/"resume.json",0,"0"*64,expected=(2,));refusals+=2
                transaction.save(out/(name+".evidence.json"),dict(full=actual,prefix=prefix,resumed=resumed,python=expected))
                cases.append(dict(name=name,maximum_error=error,actual_content_calls=sum(r["actual_content_calls"] for r in actual["receipts"]),policy_sha256=transaction.digest(config["policy"])))
        print(json.dumps(dict(stage="joint_native_full_episodes",family=family,paired_episodes=len(cases))),flush=True)
        # Complete joint33/GRU pending actions, including real IO crash hooks.
        for fi in (2,3):  # the registered middle prior, success and missing due packet
            fixture=fixtures[fi];config.update(public=fixture["folder"]/"public.json",controller="fixed")
            ordinary=out/f"normal_transaction_{family}_{fi}"
            initial=wrapped(config,ordinary,"init","genesis");started=wrapped(config,ordinary,"step","read-start",initial["ack"])
            assert started["result"]["after"]["task"]["pending"]["due_tick"]==2
            no_fault=wrapped(config,ordinary,"step","due",started["ack"])
            assert no_fault["result"]["receipts"][0]["due_source"]==1
            for fault in ("after_native_tick","after_due_read","after_child_commit","after_io_receipt","after_generation_move","after_publish"):
                root=out/f"fault_{family}_{fi}_{fault}";initial=wrapped(config,root,"init","genesis")
                started=wrapped(config,root,"step","read-start",initial["ack"])
                wrapped(config,root,"step","due",started["ack"],fault,(1,) if fault in ("after_native_tick","after_due_read","after_child_commit") else (87,))
                children=len(list(root.rglob("child_process.json")))
                unavailable=None
                if fault in ("after_io_receipt","after_generation_move","after_publish") and not fixture["missing"]:
                    source=fixture["folder"]/fixture["public"]["packets"][1];unavailable=source.with_suffix(".held");source.rename(unavailable)
                recovered=wrapped(config,root,"step","due",started["ack"])
                if recovered["result"]["after"]!=no_fault["result"]["after"]:raise AssertionError("joint conditional state changed under transaction recovery")
                if fault in ("after_io_receipt","after_generation_move","after_publish") and len(list(root.rglob("child_process.json")))!=children:raise AssertionError("prepared joint IO was reexecuted")
                if unavailable is not None:unavailable.rename(source)
                duplicate=wrapped(config,root,"step","due",started["ack"])
                assert duplicate["duplicate"] and duplicate["ack"]==recovered["ack"]
                fault_cases.append(dict(family=family,missing=fixture["missing"],fault=fault,persisted_mass33_and_bank9=True,prepared_reused=recovered["recovered_prepared"],duplicate_reply_reused=duplicate["duplicate"]))
        # A plausible normalized mass substitution is not a valid checkpoint,
        # even if a caller supplies the digest of the tampered JSON bytes.
        fixture=fixtures[2];config.update(public=fixture["folder"]/"public.json",controller="fixed")
        tamper_dir=out/(family+"_memory_tamper");tamper_dir.mkdir()
        prefix=native(config,tamper_dir/"owner.json",1)
        pair=json.loads((tamper_dir/"owner.json").read_bytes());mass=pair["cell"]["mass"]
        i,j=np.argsort(mass)[-2:].tolist();amount=min(mass[j]/10,1e-4);mass[j]-=amount;mass[i]+=amount
        transaction.save(tamper_dir/"owner.json",pair)
        native(config,tamper_dir/"owner.json",0,transaction.digest(tamper_dir/"owner.json"),expected=(2,));memory_refusals+=1
        # Mutating an unread due packet must not affect the earlier READ
        # decision, its current mass, or cause any early packet open.
        blind=out/(family+"_unread_private_change");shutil.copytree(fixture["folder"],blind)
        (blind/fixture["public"]["packets"][1]).write_bytes(b"unread private bytes changed")
        blind_config={**config,"public":blind/"public.json"};changed=native(blind_config,blind/"owner.json",1)
        assert changed["receipts"][0]["q"]==prefix["receipts"][0]["q"]
        assert changed["after"]["cell"]==prefix["after"]["cell"]
        assert changed["receipts"][0]["read_audit"]["open_attempts"]==0
        blind_checks+=1
    if reads==0 or pending==0:raise AssertionError("actual current-at-due content and pending coverage absent")
    source_names=["joint_native_policy.rs","joint_native_cell.rs","joint_native_port.rs","joint_native_task.rs","joint_native_full_build.py","joint_native_full_qualify.py","joint_native_owner.py","joint_deploy.py","joint_task.py"]
    summary=dict(schema="joint-native-full-owner-qualification-v1",scope="real Hepta NeuronRuntime, hand-built excluded engineering tasks and untrained models; no efficacy or production activation claim",
                 paired_episodes=len(cases),transaction_crash_cases=len(fault_cases),invocations=len(commands),cases=cases,fault_cases=fault_cases,
                 maximum_q_mass_bank_error=maximum,actual_content_calls=reads,pending_cold_resumes=pending,refusals=refusals,
                 normalized_memory_tamper_refusals=memory_refusals,unread_private_payload_blind_checks=blind_checks,
                 sources={n:transaction.digest(HERE/n) for n in source_names},binary_sha256=transaction.digest(a.binary),content_sha256=transaction.digest(content),
                 full_conditional_memory_persisted=True,gru_state_reconstructed_from_completed_history=True,physical_effect_once_claim=False,production_activation=False)
    summary["allocation_accounting"]="ru_maxrss is measured whole-process peak RSS; inherited transient_allocation_bytes=4096 is an unqualified estimate, not measured allocation or a proved upper bound"
    transaction.save(out/"SUMMARY.json",summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ("cases","fault_cases","sources")}),flush=True)


if __name__=="__main__":
    main()

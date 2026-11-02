"""All actual frozen joint weights on existing validation worlds, without tuning.

The publication commit is supplied after root verifies its remote model freeze;
this runner checks every local frozen source/model/data hash before and after.
It never generates IID/OOD worlds, reads evaluator labels, or estimates utility.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
import numpy as np
from .joint_deploy import NumpyPolicy
from . import joint_task as task
from . import joint_native_owner as storage
from .joint_native_full_qualify import same_state

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--formal-root",type=Path,required=True);p.add_argument("--binary",type=Path,required=True)
    p.add_argument("--published-model-commit",required=True);p.add_argument("--out",type=Path,required=True)
    a=p.parse_args();commit=a.published_model_commit
    if len(commit)!=40 or set(commit)-set("0123456789abcdef"):
        raise ValueError("actual root-verified published model commit required")
    frozen=json.loads((a.formal_root/"MODEL_FREEZE.json").read_bytes())
    if frozen["schema"]!="joint-model-freeze-v1" or len(frozen["models"])!=20:
        raise ValueError("all twenty admitted models required")

    def verify():
        if any(storage.digest(REPO/path)!=h for path,h in frozen["sources"].items()):raise ValueError("formal source mutated")
        if any(storage.digest(a.formal_root/path)!=h for path,h in frozen["models"].items()):raise ValueError("frozen final weights mutated")
        if any(storage.digest(a.formal_root/r["path"])!=r["sha256"] for r in frozen["data"].values()):raise ValueError("frozen input manifest mutated")
    verify();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    inputs=out/"inputs";inputs.mkdir();content=HERE.parent/"round9_20261031/native/fixtures/fullhx.json"
    storage.save(out/"STARTED.json",dict(published_model_commit=commit,model_freeze_sha256=storage.digest(a.formal_root/"MODEL_FREEZE.json"),scope="existing validation implementation pairing only"))
    shutil.copyfile(a.formal_root/"MODEL_FREEZE.json",out/"MODEL_FREEZE.json")
    invocations,cases,model_rows=[],[],[];maximum=0.;reads=0;pending=0
    for fit in (11,23,37,53,71):
        prepared_path=a.formal_root/frozen["data"][str(fit)]["path"]
        prepared=json.loads(prepared_path.read_bytes());cohort=prepared["validation_cohort"]
        worlds=[]
        for record in cohort["records"][:2]:
            identifier=record["id"]
            if Path(identifier).name!=identifier:raise ValueError("canonical existing validation id required")
            source=prepared_path.parent/identifier;folder=inputs/f"fit_{fit}"/identifier;folder.mkdir(parents=True)
            public=json.loads((source/"public.json").read_bytes())
            for name in ["public.json",*public["packets"]]:
                key=identifier+"/"+name
                if key in cohort.get("expected_missing",{}):
                    if (source/name).exists():raise ValueError("declared missing packet appeared")
                else:
                    if storage.digest(source/name)!=cohort["files"][key]:raise ValueError("validation bytes changed")
                    shutil.copyfile(source/name,folder/name)
            worlds.append((folder,public))
        for family in ("renewal","full_markov","affine_markov","gru"):
            relative=f"fit_{fit}/model_{family}/model.json";original=a.formal_root/relative
            if storage.digest(original)!=frozen["models"][relative]:raise ValueError("wrong frozen model")
            artifact=json.loads(original.read_bytes())
            if artifact["fit"]!=fit or artifact["family"]!=family:raise ValueError("artifact family/fit mismatch")
            model=inputs/f"fit_{fit}_{family}.json";shutil.copyfile(original,model)
            model_rows.append(dict(fit=fit,family=family,source=relative,sha256=storage.digest(model)))
            policy=NumpyPolicy(artifact);adapter=task.ContentAdapter()
            for wi,(folder,public) in enumerate(worlds):
                for controller in ("fixed","value"):
                    name=f"fit_{fit}_{family}_{wi}_{controller}";run=out/name;run.mkdir()
                    def native(snapshot,steps,ack=None):
                        command=[str(a.binary.resolve()),"--public",str(folder/"public.json"),"--policy",str(model),"--content-model",str(content),
                                 "--controller",controller,"--seed",str(991181+fit),"--mode","qualification","--snapshot",str(snapshot),"--steps",str(steps)]
                        if ack is not None:command += ["--ack",ack]
                        process=subprocess.run(command,cwd=REPO,text=True,capture_output=True,timeout=90)
                        raw=dict(command=command,returncode=process.returncode,stdout=process.stdout,stderr=process.stderr)
                        storage.save(out/f"invocation_{len(invocations):04d}.json",raw);invocations.append(raw)
                        if process.returncode:raise AssertionError("actual frozen model failed native execution: "+process.stderr)
                        result=json.loads(process.stdout)
                        if result["forced_control"] or not result["actual_native"] or result["production_activation"]:raise AssertionError("unexpected execution mode")
                        return result
                    full=native(run/"full.json",7);first=native(run/"resume.json",1)
                    pending+=first["after"]["task"]["pending"] is not None
                    resumed=native(run/"resume.json",7,first["acknowledged_sha256"])
                    if full["after"]!=resumed["after"] or full["acknowledged_sha256"]!=resumed["acknowledged_sha256"]:raise AssertionError("frozen-weight cold recovery mismatch")
                    python=task.Owner(public,folder,adapter);expected=[]
                    while not python.state["terminal"]:
                        scores=policy.predict(public,python.state);mask=task.legal(public,python.state)
                        action=task.fixed_action(python.state,mask,scores["belief"]) if controller=="fixed" else int(np.argmax(np.where(mask,scores["q"],-np.inf)))
                        expected.append(dict(scores=scores,receipt=python.step(action)))
                    if [r["action"] for r in full["receipts"]]!=[r["receipt"]["action"] for r in expected]:raise AssertionError("frozen-weight whole route mismatch")
                    same_state(full["after"]["task"],python.state);error=0.
                    for got,want in zip(full["receipts"],expected):
                        same_state(got["after"],want["receipt"]["after"])
                        if got["completion"]!=want["receipt"]["completion"] or got["due_source"]!=want["receipt"]["source_opened"]:raise AssertionError("frozen-weight due/current mismatch")
                        for field in ("q","belief"):
                            error=max(error,float(np.max(abs(np.asarray(got[field])-want["scores"][field]))))
                        for field in ("mass","bank"):
                            error=max(error,float(np.max(abs(np.asarray(got["cell_before"][field])-want["scores"][field]))))
                        next_mass,next_bank,_=policy.represent(public,got["after"])
                        error=max(error,float(np.max(abs(np.asarray(got["cell_after"]["mass"])-next_mass))),float(np.max(abs(np.asarray(got["cell_after"]["bank"])-next_bank))))
                        reads+=got["actual_content_calls"]
                    if error>5e-12:raise AssertionError("frozen-weight numerical mismatch")
                    maximum=max(maximum,error);storage.save(run/"PAIRING.json",dict(native=full,prefix=first,resumed=resumed,python=expected))
                    cases.append(dict(fit=fit,family=family,world=public["id"],controller=controller,maximum_error=error,public_sha256=storage.digest(folder/"public.json"),policy_sha256=storage.digest(model)))
        print(json.dumps(dict(stage="frozen_native_fit",fit=fit,episodes=len(cases))),flush=True)
    verify()
    report=dict(schema="joint-native-frozen-twenty-weight-qualification-v1",published_model_commit=commit,
                model_freeze_sha256=storage.digest(a.formal_root/"MODEL_FREEZE.json"),models=model_rows,cases=cases,
                models_qualified=len(model_rows),paired_episodes=len(cases),invocations=len(invocations),maximum_q_mass_bank_error=maximum,
                actual_content_calls=reads,pending_cold_resumes=pending,binary_sha256=storage.digest(a.binary),
                scope="actual frozen final weights on first two existing validation worlds per fit; no new confirmation worlds, no label/utility evaluation, no tuning",
                runner_sha256=storage.digest(__file__),production_activation=False)
    storage.save(out/"SUMMARY.json",report);print(json.dumps({k:v for k,v in report.items() if k not in ("cases","models")}),flush=True)


if __name__=="__main__":main()

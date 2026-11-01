"""Fresh-process restoration and old-Q -> new-Q hazard semantics, not in-memory IO."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess

import numpy as np

from adapter import ROOT


def run(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    binary = ROOT/"evidence/build/hcsn-events-r13"
    checks, receipts = [], []

    def check(name, condition, **details):
        checks.append({"name":name,"pass":bool(condition),**details})

    def model_file(name, q, prior, version):
        path=destination/(name+".model")
        path.write_text(f"{len(prior)} {version}\n"+"\n".join(format(float(x),".17g") for x in
            np.r_[q.ravel(),prior])+"\n")
        return path

    def invoke(name, operation, source, commands, identity, refused=False, output=None):
        script=destination/(name+".script")
        script.write_text(commands)
        output=Path(output) if output is not None else destination/(name+".checkpoint")
        command=[str(binary),operation,str(source),str(script),str(output),str(identity)]
        before=output.read_bytes() if output.exists() else None
        response=subprocess.run(command,text=True,capture_output=True,check=False)
        archive=destination/(name+".stdout.json.gz")
        archive.write_bytes(gzip.compress(response.stdout.encode(),mtime=0))
        receipt={"name":name,"command":command,"returncode":response.returncode,
            "stderr":response.stderr,"stdout_sha256":hashlib.sha256(response.stdout.encode()).hexdigest(),
            "stdout_archive":str(archive),"output_checkpoint":str(output)}
        receipts.append(receipt)
        if refused:
            check(name,response.returncode==2 and (output.read_bytes() if output.exists() else None)==before,
                  reason=response.stderr.strip())
            return None,output
        if response.returncode:
            raise AssertionError(receipt)
        data=json.loads(response.stdout)
        receipt.update(pid=data["pid"],model_version=data["model_version"],time=data["time"],
                       counts=data["counts"],model_identity=data["model_identity"],source_identity=data["source_identity"])
        return data,output

    def same_path(name, whole, parts, full_checkpoint, final_checkpoint):
        check(name,whole["jumps"]==sum((x["jumps"] for x in parts),[]) and
            full_checkpoint.read_bytes()==final_checkpoint.read_bytes() and
            len({whole["pid"],*(x["pid"] for x in parts)})==len(parts)+1,
            jumps=len(whole["jumps"]),counts=whole["counts"])

    with np.load(ROOT/"evidence/prepared_audit/fixtures/default.npz") as f:
        q,prior=f["Q"],f["prior"]
    with np.load(ROOT/"evidence/prepared_audit/fixtures/updated.npz") as f:
        updated,prior2=f["Q"],f["prior"]
    old=model_file("fvm_old",q,prior,13); new=model_file("fvm_new",updated,prior2,14)
    whole,cp_whole=invoke("fixed_whole","init",old,"advance 64\n",20261101)
    a,cp_a=invoke("fixed_prefix","init",old,"advance 0.5\n",20261101)
    b,cp_b=invoke("fixed_resume","resume",cp_a,"advance 63.5\n",13)
    same_path("fixed_Q_cross_process_exact",whole,[a,b],cp_whole,cp_b)
    command=f"advance 0.5\nmigrate 0.75 {new} preserve\nadvance 63.25\n"
    whole,cp_whole=invoke("changed_whole","init",old,command,20261101)
    a,cp_a=invoke("changed_prefix","init",old,"advance 0.5\n",20261101)
    b,cp_b=invoke("changed_middle","resume",cp_a,f"migrate 0.75 {new} preserve\nadvance 0.25\n",13)
    c,cp_c=invoke("changed_suffix","resume",cp_b,"advance 63\n",14)
    same_path("model_change_cross_process_exact",whole,[a,b,c],cp_whole,cp_c)
    check("migration_events_versioned",all(x["model_version"]==(13 if x["time"]<=.75 else 14) for x in whole["jumps"]))
    check("actual_FVM_recovery_events",whole["counts"][1]>0 and whole["counts"][2]>0 and whole["counts"][3]>0,
          counts=whole["counts"])
    # Controlled change: old 0->1 destination is removed, new 0->R1 is forced.
    toy=np.zeros((8,8)); changed=np.zeros_like(toy); toy_prior=np.eye(8)[0]
    for bit in range(2):
        k=bit*4
        toy[k,k+1]=1; toy[k+1,k]=1; toy[k+2,k+3]=6; toy[k+3,k]=6
        changed[k,k+2]=20; changed[k+1,k]=1; changed[k+2,k+3]=6; changed[k+3,k]=6
    for matrix in [toy,changed]:matrix[np.diag_indices(8)]=-matrix.sum(-1)
    old_toy=model_file("old_toy",toy,toy_prior,100); new_toy=model_file("new_toy",changed,toy_prior,101)
    init,cp_init=invoke("toy_initial","init",old_toy,"advance 0\n",20261101)
    at=min(.125,init["threshold"]/4)
    residual=init["threshold"]-at
    data,cp=invoke("toy_preserve","resume",cp_init,f"migrate {at:.17g} {new_toy} preserve\nadvance 2\n",100)
    event=data["jumps"][0]; migration=data["migrations"][0]
    check("hazard_exposure_formula",abs(event["time"]-(at+residual/20))<1e-14 and
          migration["new_threshold"]==migration["old_remaining_exposure"])
    check("old_destination_not_reused",event["from"]==0 and event["to"]==2 and event["model_version"]==101)
    check("old_absolute_time_not_reused",event["time"]!=init["next_time_diagnostic"] and
          event["time"]<init["next_time_diagnostic"])
    resampled,cp_resampled=invoke("toy_resample","resume",cp_init,f"migrate {at:.17g} {new_toy} resample\n",100)
    mask=(1<<64)-1
    rng=(20261101+3*0x9e3779b97f4a7c15)&mask
    x=((rng^(rng>>30))*0xbf58476d1ce4e5b9)&mask
    x=((x^(x>>27))*0x94d049bb133111eb)&mask; x^=x>>31
    expected=-math.log(((x>>12)+1)/4503599627370497)
    check("resample_new_exponential",abs(resampled["threshold"]-expected)<1e-14 and
          resampled["rng_state"]==rng and resampled["threshold"]!=residual)
    absorb=changed.copy(); absorb[0]=0
    absorbing=model_file("absorbing",absorb,toy_prior,101)
    next_toy=model_file("next_toy",changed,toy_prior,102)
    stopped,cp_stopped=invoke("absorbing_update","resume",cp_init,
        f"migrate {at:.17g} {absorbing} preserve\nadvance 4\n",100)
    check("absorbing_update_cancels_old_clock",not stopped["jumps"] and stopped["next_time_diagnostic"] is None)
    restored,cp_restored=invoke("absorbing_restart","resume",cp_stopped,
        f"migrate {stopped['time']:.17g} {next_toy} preserve\nadvance 2\n",101)
    check("zero_hazard_preserves_exposure",restored["migrations"][0]["new_threshold"]==stopped["threshold"] and
        abs(restored["jumps"][0]["time"]-(stopped["time"]+residual/20))<1e-14)
    invoke("refuse_wrong_expected_version","resume",cp_a,"advance 0\n",999,True)
    invoke("refuse_backward_migration","resume",cp_a,f"migrate 0.25 {new} preserve\n",13,True)
    invoke("refuse_old_version","resume",cp_a,f"migrate 0.75 {old} preserve\n",13,True)
    invoke("refuse_layout_change","resume",cp_a,f"migrate 0.75 {new_toy} preserve\n",13,True)
    invoke("refuse_overwrite","resume",cp_a,"advance 0\n",13,True,output=cp_a)
    invalid=updated.copy(); invalid[0,0]=1
    bad_model=model_file("invalid_Q",invalid,prior2,14)
    invoke("refuse_bad_new_Q","resume",cp_a,f"migrate 0.75 {bad_model} preserve\n",13,True)
    original=cp_a.read_text()
    corrupt=destination/"corrupt.checkpoint"; corrupt.write_text(original.replace("CHECKSUM ","CHECKSUM 1",1))
    invoke("refuse_corrupt_checkpoint","resume",corrupt,"advance 0\n",13,True)
    body=original.rsplit("CHECKSUM ",1)[0]
    lines=body.splitlines(); lines[1]="0"*64
    altered="\n".join(lines)+"\n"
    source_bad=destination/"wrong_source.checkpoint"
    source_bad.write_text(altered+"CHECKSUM "+hashlib.sha256(altered.encode()).hexdigest()+"\n")
    invoke("refuse_source_identity","resume",source_bad,"advance 0\n",13,True)
    lines=body.splitlines(); header=lines[2].split(); header[2]="0"*64; lines[2]=" ".join(header)
    altered="\n".join(lines)+"\n"
    identity_bad=destination/"wrong_model_identity.checkpoint"
    identity_bad.write_text(altered+"CHECKSUM "+hashlib.sha256(altered.encode()).hexdigest()+"\n")
    invoke("refuse_Q_identity","resume",identity_bad,"advance 0\n",13,True)
    build=json.loads((ROOT/"evidence/build/BUILD_RECEIPT.json").read_text())
    check("executed_exact_build",all(x.get("source_identity",build["source_identity"])==build["source_identity"] for x in receipts))
    report={"schema":"hcsn-r13-migration-audit-v1","checks":checks,
        "all_passed":all(x["pass"] for x in checks),"process_receipts":receipts,
        "binary_sha256":hashlib.sha256(binary.read_bytes()).hexdigest(),
        "build_source_identity":build["source_identity"],
        "test_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "contract":"At update time process old-Q events through that time, preserve remaining unit-exponential exposure or explicitly resample, sample destination only at the new-model jump. Checkpoints contain no pending destination or old absolute event time."}
    (destination/"RESULTS.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"all_passed":report["all_passed"],"checks":len(checks),
                      "failures":[x for x in checks if not x["pass"]],"actual_counts":whole["counts"]}))
    if not report["all_passed"]:raise AssertionError("Migration audit failed")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--output",type=Path,default=ROOT/"evidence/migration_audit")
    run(parser.parse_args().output)

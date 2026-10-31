"""Audit both preserved native qualification attempts and reporting-only repair."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .teacher_confirmation_audit import close,digest,quantize,read


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
NUMERIC="hepta.task.native-q24-residual.v1"


def scores(model,row,quantized):
    raw=np.asarray(row["features"])
    prior=np.asarray(row["prior"])
    if quantized:raw,prior=quantize(raw),quantize(prior)
    x=np.clip((raw-model["norm"]["mean"])/model["norm"]["scale"],-8.,8.)
    w=model["weights"]
    q=prior+np.maximum(0.,np.tanh(x@w["w"]+w["b"])@w["v"]+w["c"])
    q[0]=0.
    return q


def semantic(row):
    traces=[]
    for trace in row["traces"]:
        event={k:v for k,v in trace["event"].items() if "seconds" not in k}
        if "decoded" in event:event["decoded"]={k:v for k,v in event["decoded"].items() if "seconds" not in k}
        traces.append(dict(action=trace["action"],state=trace["state"],event=event,
            external_cell_snapshot_sha256=trace["external_cell_snapshot_sha256"],cell_interval=trace["cell_interval"]))
    return dict(traces=traces,score=row["score"],counts=row["counts"],task_elapsed=row["task_elapsed"],
        failure=row["failure"],final_cell_snapshot=row["final_cell_snapshot"])


def audit(prepared,confirmed,native,out):
    wall,cpu=time.perf_counter(),time.process_time()
    repair_file=ROOT/"tools/hcsn/task_progression_20261031/NATIVE_REPORTING_REPAIR.json"
    repair=read(repair_file)
    old=repair_file.with_name("native_confirmation.py")
    new=repair_file.with_name("native_confirmation_reporting_fix.py")
    if digest(old)!=repair["original_sha256"] or digest(new)!=repair["corrected_sha256"]:
        raise AssertionError("Repair source identity differs")
    delta="".join(difflib.unified_diff(old.read_text().splitlines(True),new.read_text().splitlines(True),fromfile=old.name,tofile=new.name))
    if delta!=repair["diff"]:raise AssertionError("Recorded source diff is incomplete")
    expected_old='    print(json.dumps(dict(accepted=report["accepted"], models=len(summaries)), flush=True))'
    expected_new='    print(json.dumps(dict(accepted=report["accepted"], models=len(summaries))), flush=True)'
    if old.read_text().replace(expected_old,expected_new,1)!=new.read_text():
        raise AssertionError("Repair changes more than terminal reporting argument placement")
    protocol=read(prepared/"PROTOCOL.json")
    contexts={}
    for seed in protocol["seeds"]:
        model_file=prepared/f"seed{seed}/model_nonzero.json"
        model=read(model_file);model["weights"]={k:np.asarray(v) for k,v in model["weights"].items()}
        validation=read(prepared/f"seed{seed}/TEACHER_DATA.json.gz")["validation"]["rows"][512:1024]
        originals={}
        for split in ("test","ood"):
            rows=read(confirmed/f"seed{seed}/{split}_RUNS_AND_DIAGNOSIS.json.gz")["rows"]
            for row in rows:
                if row["policy"]=="nonzero_residual":originals[split,row["session_id"]]=row
        contexts[seed]=dict(model=model,model_sha=digest(model_file),vectors=validation,originals=originals)
    attempts=[];cross_attempt={}
    for attempt in ("01","02"):
        directory=native/("confirmation"+attempt)
        report=read(directory/"REPORT.json")
        process=read(native/("process"+attempt)/"PROCESS.json")
        source_sha=repair["original_sha256"] if attempt=="01" else repair["corrected_sha256"]
        if report["source_sha256"]!=source_sha:raise AssertionError("Attempt bound to wrong source")
        if process["returncode"]!=(1 if attempt=="01" else 0):raise AssertionError("Preserved process outcome differs")
        if report["prepared_manifest_sha256"]!=digest(prepared/"PREPARED_MANIFEST.json") or report["frozen_confirmation_sha256"]!=digest(confirmed/"CONFIRMATION.json"):
            raise AssertionError("Qualified data identity differs")
        numeric_error=0.;numeric_rows=pairs=restores=reads=0;float_changes=0
        task_child_cpu=numeric_child_cpu=0.
        pair_costs={"python":[],"native":[]}
        for seed in protocol["seeds"]:
            base=directory/f"seed{seed}"
            context=contexts[seed]
            vectors=read(base/"VECTORS.json")["rows"]
            if vectors!=context["vectors"]:raise AssertionError("Vector selection differs from frozen 512:1024")
            numeric=read(base/"numeric/REPORT.json")
            receipts=read(base/"numeric/RECEIPTS.json.gz")
            if len(receipts)!=512 or not numeric["accepted"]:raise AssertionError("Incomplete numerical qualification")
            model_sha=context["model_sha"]
            deployment=hashlib.sha256(b"hepta.task.deployment-model.v1"+bytes.fromhex(model_sha)+NUMERIC.encode()).hexdigest()
            before="0"*64;original_diffs=[]
            for i,(row,receipt_record) in enumerate(zip(vectors,receipts,strict=True)):
                receipt=receipt_record["receipt"]
                legal=np.asarray(row["feasible"],bool)
                q=scores(context["model"],row,True)
                error=float(np.max(np.abs(q[legal]-np.asarray(receipt["q_values"])[legal])))
                numeric_error=max(numeric_error,error)
                drive=np.zeros(5,dtype=np.int64);drive[:4][legal]=np.floor((q[legal]+4)*2**24+.5).astype(np.int64)
                action=int(np.argmax(drive))
                if (receipt_record["index"]!=i or receipt["sequence"]!=i+1 or receipt["checkpoint_before"]!=before
                    or receipt["action_index"]!=action or receipt["deployment_identity_sha256"]!=deployment
                    or receipt["model_sha256"]!=model_sha or receipt["numeric_contract"]!=NUMERIC
                    or receipt["native_physics_executed"] or receipt["production_activation"] or receipt["authority"]!="DENY_ALL"):
                    raise AssertionError("Native receipt/model/ordered-owner contract mismatch")
                before=receipt["checkpoint_after"]
                original=scores(context["model"],row,False)
                original_action=int(np.argmax(np.where(legal,original,-np.inf)))
                if original_action!=action:original_diffs.append(i+512)
                numeric_rows+=1
            if original_diffs!=[x["index"] for x in numeric["original_float64_action_differences"]]:
                raise AssertionError("Original-float mismatch record changed")
            float_changes+=len(original_diffs)
            for usage in numeric["process_accounting"]:
                numeric_child_cpu+=usage["child_process_usage"]["user_cpu_seconds"]+usage["child_process_usage"]["system_cpu_seconds"]
            raw=read(base/"PAIRS.json.gz")
            groups={}
            for row in raw["rows"]:
                key=(row["split"],row["session_id"])
                groups.setdefault(key,{})[row["backend"]]=row
                expected_child=sum(x["child_process_usage"]["user_cpu_seconds"]+x["child_process_usage"]["system_cpu_seconds"] for x in row["native_process_accounting"])
                close(expected_child,row["native_child_cpu_seconds"])
                close(row["parent_cpu_seconds"]+expected_child,row["complete_cpu_seconds"],1e-5)
                task_child_cpu+=expected_child;pair_costs[row["backend"]].append(row["complete_cpu_seconds"])
                restores+=row["restored"];reads+=row["counts"]["packet_file_reads"]
                original=context["originals"][key]
                if row["score"]!=original["score"] or row["counts"]!=original["counts"]:
                    raise AssertionError("Native fixture differs from the independently audited original task")
                if [x["action"] for x in row["traces"]]!=[x["action"] for x in original["traces"]]:
                    raise AssertionError("Backend action policy differs from original frozen confirmation")
            if len(groups)!=32 or len(raw["rows"])!=64:raise AssertionError("Missing paired backend tasks")
            for key,pair in groups.items():
                if semantic(pair["python"])!=semantic(pair["native"]):raise AssertionError("Physical same-profile backend effects differ")
                identity=(seed,*key)
                if attempt=="01":cross_attempt[identity]=semantic(pair["python"])
                elif cross_attempt[identity]!=semantic(pair["python"]):raise AssertionError("Reporting repair changed a physical trajectory")
                pairs+=1
        if not report["accepted"] or report["native_physics_executed"] or report["main_activation"] or numeric_error>2e-12:
            raise AssertionError("Native data qualification mismatch")
        attempts.append(dict(attempt=attempt,source_sha256=source_sha,process_exit=process["returncode"],
            data_qualification_passed=True,process_success=process["returncode"]==0,numeric_rows=numeric_rows,
            maximum_native_q_error=numeric_error,original_float_action_differences=float_changes,
            paired_tasks=pairs,actual_file_reads=reads,restored_rollouts=restores,
            average_complete_cpu_seconds={k:float(np.mean(v)) for k,v in pair_costs.items()},
            task_native_child_cpu_seconds=task_child_cpu,numeric_native_child_cpu_seconds=numeric_child_cpu,
            enclosing_process_cpu_seconds=process["total_cpu_seconds"],enclosing_process_wall_seconds=process["wall_seconds"],
            parent_report_cpu_seconds=report["parent_cpu_seconds"]))
    result=dict(schema="hcsn.progression.native-confirmation-audit.v1",passed=True,source_sha256=digest(Path(__file__)),
        reporting_only_source_change_verified=True,original_failed_attempt_preserved=True,
        attempts=attempts,same_160_physical_cases_across_attempts=True,
        effective_independent_backend_cases=160,effective_independent_numeric_vectors=2560,
        measurement_scope="Repeat is engineering verification on identical frozen data, not new independent efficacy. Nested child CPU is already represented by the enclosing process accounting and must not be added again.",
        native_physics_executed=False,production_activation=False,
        audit_cpu_seconds=time.process_time()-cpu,audit_wall_seconds=time.perf_counter()-wall)
    with out.open("x") as stream:json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps(result))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("prepared","confirmed","native","out"):parser.add_argument("--"+name,type=Path,required=True)
    audit(**vars(parser.parse_args()))

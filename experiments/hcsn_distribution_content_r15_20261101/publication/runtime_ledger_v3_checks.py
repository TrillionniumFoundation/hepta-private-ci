#!/usr/bin/env python3
"""Artificial ENOSPC/retry ledger checks; never discovers actual run data."""

import argparse
import itertools
import json
from pathlib import Path
import shutil
import tempfile

if __package__:
    from . import runtime_ledger_v3 as ledger
else:
    import runtime_ledger_v3 as ledger


write = ledger.base.write


def receipt(task,seed,mode,cpu=10.,exit_code=0,attempt=None):
    name=f"{task}_s{seed}_{mode}"
    row=dict(name=name,task=task,seed=seed,train_mode=mode,exit_code=exit_code,
             cpu_user_seconds=.8*cpu,cpu_system_seconds=.2*cpu,wall_seconds=15.,maximum_rss_kib=100.)
    if attempt:
        row.update(attempt_id=attempt,process_attempt_id=attempt+"/"+name,measurement_status="complete_process_lifetime_wait4")
    return row


def file_metadata(path,run):
    return dict(path=str(path.relative_to(run)),bytes=path.stat().st_size,sha256=ledger.sha(path))


def fixture(root):
    run=root/"formal_03"
    protocol=dict(tasks=["recall","binding"],seeds=list(range(15131,15139)),modes=["light","value"])
    write(run/"PROTOCOL.json",protocol)
    write(run/"TRAINING_DATA_CONTEXTS.json",dict(artificial=True))
    write(run/"SOURCE_FREEZE.json",dict(protocol_sha256=ledger.sha(run/"PROTOCOL.json"),
        training_data_contexts_sha256=ledger.sha(run/"TRAINING_DATA_CONTEXTS.json"),files={"artificial.py":"0"*64}))
    identities=list(itertools.product(protocol["tasks"],protocol["seeds"],protocol["modes"]))
    retained=[]
    for task,seed,mode in identities[:13]:
        row=receipt(task,seed,mode);path=run/"receipts/train"/(row["name"]+".json");write(path,row)
        meta=file_metadata(path,run)
        retained.append(dict(name=row["name"],task=task,seed=seed,train_mode=mode,receipt_path=meta["path"],
                             receipt_sha256=meta["sha256"],canonical_files=[meta]))
        target=run/"attempts/train_02_enospc/original"/meta["path"]
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    original=[];quarantine=[]
    for task,seed,mode in identities[13:15]:
        row=receipt(task,seed,mode)
        partial=run/"attempts/train_02_enospc/original/receipts/train"/(row["name"]+".json")
        partial.parent.mkdir(parents=True,exist_ok=True);partial.write_bytes(b"")
        evidence=str(partial.relative_to(run))
        original.append(dict(name=row["name"],task=task,seed=seed,train_mode=mode,
            process_attempt_id="formal03/train_original/"+row["name"],cpu_seconds=None,exit_code=None,
            measurement_status="not_measured",evidence_paths=[evidence]))
        quarantine.append(dict(original_path="receipts/train/"+row["name"]+".json",archive_path=evidence,
                               bytes=0,sha256=ledger.sha(partial)))
    preservation=dict(schema="hcsn.r15.training-interruption-preservation.v1",retained_successful_groups=retained,
                      original_process_attempts=original,quarantine_files=quarantine)
    write(run/ledger.PRESERVATION,preservation)
    def registration(attempt,jobs):
        write(run/"attempts"/attempt/"REGISTRATION.json",dict(attempt_id=attempt,
            source_freeze_sha256=ledger.sha(run/"SOURCE_FREEZE.json"),protocol_sha256=ledger.sha(run/"PROTOCOL.json"),
            training_data_contexts_sha256=ledger.sha(run/"TRAINING_DATA_CONTEXTS.json"),supplement_registrations={},
            pending_groups=[{key:receipt(*job)[key] for key in ("name","task","seed","train_mode")} for job in jobs]))
    def job(attempt,key,cpu=10.,exit_code=0,promote=True):
        row=receipt(*key,cpu=cpu,exit_code=exit_code,attempt=attempt)
        directory=run/"attempts"/attempt/"jobs"/row["name"]
        start={field:row[field] for field in ("name","task","seed","train_mode","attempt_id","process_attempt_id")}
        write(directory/"STARTED.json",start);write(directory/"RECEIPT.json",row)
        if promote:
            target=run/"receipts/train"/(row["name"]+".json")
            shutil.copyfile(directory/"RECEIPT.json",target)
            write(directory/"PROMOTION.json",dict(canonical_promotion=True,process_attempt_id=row["process_attempt_id"],
                canonical_receipt=str(target.relative_to(run)),canonical_fit="fits/"+row["name"],receipt_sha256=ledger.sha(target),fit_files=[]))
    registration("train_resume_001",identities[13:])
    job("train_resume_001",identities[13],cpu=7.,exit_code=1,promote=False)
    for key in identities[14:]:job("train_resume_001",key)
    write(run/"attempts/train_resume_001/RESULT.json",dict(completed=False,attempted_jobs=19,promoted_groups=18))
    registration("train_resume_002",identities[13:14]);job("train_resume_002",identities[13])
    write(run/"attempts/train_resume_002/RESULT.json",dict(completed=True,attempted_jobs=1,promoted_groups=1))
    write(run/"attempts/train_resume_002/before/receipts/train/duplicate.json",dict(fake_duplicate_cpu=999999.))
    for stage in ledger.previous.STAGES:
        modes=("value",) if stage.startswith("recovery_") else ("light",) if stage=="train_execution_cross" else ("light","value")
        jobs=list(itertools.product(protocol["tasks"],protocol["seeds"],modes))
        if stage!="train":
            for key in jobs:
                row=receipt(*key);write(run/"receipts"/stage/(row["name"]+".json"),row)
        total=dict(stage=stage,jobs=len(jobs),failed=0,workers=2,process_cpu_seconds=10.*len(jobs),wall_seconds=3600.)
        if stage=="train":
            total.update(accounting_kind="resumed_consolidated",resumed=True,original_launcher_completed=False,
                wall_scope="elapsed_since_original_restart_including_interruption_and_resume",
                retained_original_successful_groups=13,resume_attempt_ids=["train_resume_001","train_resume_002"],
                canonical_resume_attempt_ids=["train_resume_001","train_resume_002"],
                unknown_original_process_attempts=[row["process_attempt_id"] for row in original])
        write(run/"receipts"/stage/"TOTAL.json",total)
    write(run/"fits/nested_fixture/SUMMARY.json",dict(training_cpu_seconds=99999.,training_wall_seconds=99999.))
    old=root/"formal_02/attempts/train_01_oom"
    failed=receipt("recall",15131,"value",cpu=5.,exit_code=-9)
    write(old/"receipts"/(failed["name"]+".json"),failed)
    workers=[dict(pid=10+index,args=["python","campaign.py","--task","recall","--seed",str(seed),"--mode",mode],
                  user_cpu_seconds=cpu,system_cpu_seconds=0.)
             for index,(seed,mode,cpu) in enumerate(((15131,"light",3.),(15132,"light",4.),(15131,"value",2.)))]
    write(old/"INTERRUPTION.json",dict(launcher_pid=9,workers=workers,utc="artificial",reason="artificial OOM"))
    write(root/"formal_02/receipts/fake_duplicate.json",dict(cpu_seconds=999999.))
    return run,identities,registration


def selfcheck(output, resumer_fixture=None):
    root=Path(tempfile.mkdtemp(prefix="hcsn-ledger-v3-artificial-"))
    run,identities,registration=fixture(root)
    original=ledger.build(root);recovery=original["enospc_training_recovery"]
    checks=dict(canonical_13_plus_19_charged_once=recovery["retained_original_success_count"]==13 and recovery["resumed_success_count"]==19 and recovery["canonical_train_worker_cpu_seconds"]==320.,
        old_and_new_receipt_aliases_excluded=len(recovery["canonical_aliases_not_added"])==32 and all(row["additional_charged_cpu_seconds"]==0 for row in recovery["canonical_aliases_not_added"]),
        failed_retry_separate_from_same_job_later_success=ledger.base.close(recovery["additional_complete_wait4_cpu_seconds"],7.),
        two_original_lost_receipts_remain_unknown=recovery["unknown_process_attempt_count"]==2 and all(row["cpu_seconds"] is None for row in recovery["unknown_process_attempts"]),
        no_unknown_cpu_zero_fill=original["totals"]["enospc_unknown_process_cpu_seconds"] is None and recovery["missing_process_cpu_seconds"] is None,
        oom_and_enospc_failure_costs_both_retained=original["totals"]["successful_failed_and_abandoned_cpu_lower_bound_seconds"]==1459.,
        nested_body_and_snapshot_duplicates_not_added=original["totals"]["formal_03_observed_completed_process_cpu_seconds"]==1440.,
        original_launcher_not_declared_successful=original["formal_03_stages"][0]["original_launcher_completed"] is False,
        training_wall_labeled_interrupted_span=original["formal_03_stages"][0]["wall_scope"]=="elapsed_since_original_restart_including_interruption_and_resume",
        v1_and_v2_versions_retained=original["schema"]=="hcsn.r15.publication.runtime-ledger.v3" and original["previous_ledger_source_sha256"]==ledger.sha(ledger.previous.__file__))
    write(root/"ARTIFICIAL_LEDGER_V3.json",original)
    preservation_path=run/ledger.PRESERVATION
    saved=preservation_path.read_text();partial=json.loads(saved)
    partial["original_process_attempts"][0].update(cpu_seconds=3.5,measurement_status="lower_bound_from_process_cpu_snapshot")
    preservation_path.write_text(json.dumps(partial))
    changed=ledger.build(root)
    checks["partial_old_attempt_lower_bound_added_not_replaced_by_new_success"]=(changed["totals"]["successful_failed_and_abandoned_cpu_lower_bound_seconds"]==1462.5 and changed["enospc_training_recovery"]["unknown_process_attempt_count"]==1)
    preservation_path.write_text(saved)
    # A process intent can survive even when STARTED/RECEIPT could not be written.
    registration("train_resume_003",identities[13:14])
    key=identities[13];row=receipt(*key,attempt="train_resume_003")
    directory=run/"attempts/train_resume_003/jobs"/row["name"]
    write(directory/"LAUNCH_INTENT.json",dict(attempt_id="train_resume_003",process_attempt_id=row["process_attempt_id"],command=["artificial"]))
    total_path=run/"receipts/train/TOTAL.json";saved_total=total_path.read_text();total=json.loads(saved_total)
    total["resume_attempt_ids"].append("train_resume_003");total_path.write_text(json.dumps(total))
    changed=ledger.build(root)
    checks["intent_only_does_not_become_zero_cpu"]=(changed["enospc_training_recovery"]["unknown_process_attempt_count"]==3 and changed["totals"]["successful_failed_and_abandoned_cpu_lower_bound_seconds"]==1459.)
    write(directory/"RECEIPT.json",receipt(*key,cpu=4.,exit_code=1,attempt="train_resume_003"))
    changed=ledger.build(root)
    checks["later_wait4_replaces_that_attempt_unknown_without_double_count"]=(changed["enospc_training_recovery"]["unknown_process_attempt_count"]==2 and changed["totals"]["successful_failed_and_abandoned_cpu_lower_bound_seconds"]==1463.)
    # Successful canonical copy is sufficient to exclude a duplicate charge even
    # if the later PROMOTION marker itself was not retained.
    promotion=run/"attempts/train_resume_002/jobs"/receipt(*key)["name"]/"PROMOTION.json"
    saved_promotion=promotion.read_text();promotion.unlink()
    checks["missing_promotion_marker_does_not_double_charge_same_receipt"]=ledger.build(root)["totals"]["successful_failed_and_abandoned_cpu_lower_bound_seconds"]==1463.
    promotion.write_text(saved_promotion)
    broken=json.loads(saved);broken["original_process_attempts"][0]["cpu_seconds"]=0.
    preservation_path.write_text(json.dumps(broken))
    try:ledger.build(root)
    except ledger.base.LedgerError:checks["unknown_numeric_zero_is_rejected"]=True
    else:checks["unknown_numeric_zero_is_rejected"]=False
    preservation_path.write_text(saved)
    registration_path=run/"attempts/train_resume_001/REGISTRATION.json"
    saved_registration=registration_path.read_text();bad=json.loads(saved_registration);bad["protocol_sha256"]="f"*64
    registration_path.write_text(json.dumps(bad))
    try:ledger.build(root)
    except ledger.base.LedgerError:checks["changed_scientific_freeze_rejected"]=True
    else:checks["changed_scientific_freeze_rejected"]=False
    registration_path.write_text(saved_registration)
    shutil.rmtree(run/"attempts/train_resume_003")
    total_path.write_text(saved_total)
    if resumer_fixture is not None:
        # Explicit fixture path supplied by the test author; never discover a run.
        fake=Path(resumer_fixture).resolve();inputs=ledger.base.Inputs(fake.parent)
        protocol=inputs.read(fake/"PROTOCOL.json");stage=ledger.base.stage_ledger(inputs,fake,"train",protocol)
        integration=ledger.enospc_ledger(inputs,fake,protocol,stage)
        checks["actual_resumer_artificial_schema_integrates"]=(integration["canonical_success_count"]==4 and integration["retained_original_success_count"]==1 and integration["resumed_success_count"]==3 and integration["unknown_process_attempt_count"]==2 and integration["additional_observed_cpu_lower_bound_seconds"] is None)
    result=dict(schema="hcsn.r15.runtime-ledger-v3.fixture.v1",source_sha256=ledger.sha(ledger.SOURCE),
        fixture_root=str(root),checks=checks,passed=all(checks.values()),real_runtime_records_read=False,confirmation_data_accessed=False,
        artificial_resumer_integration_path=str(resumer_fixture) if resumer_fixture else None)
    write(output,result);ledger.base.require(result["passed"],"V3 artificial ledger fixture failed")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--resumer-fixture",type=Path)
    args=parser.parse_args();result=selfcheck(args.output,args.resumer_fixture)
    print(json.dumps(dict(passed=result["passed"],checks=len(result["checks"]),confirmation_data_accessed=False)))


if __name__=="__main__":
    main()

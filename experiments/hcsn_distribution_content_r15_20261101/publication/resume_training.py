#!/usr/bin/env python3
"""Preserve interrupted evidence and complete unchanged registered training.

No experiment imports or test data. Each retry invokes the original campaign in
a new work root with byte-identical registrations. Completed canonical groups
are immutable. wait4 receipts are flushed to stdout before atomic disk writes.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


SOURCE = Path(__file__).resolve()
REPO = SOURCE.parents[3]
MODULE = "experiments.hcsn_distribution_content_r15_20261101.campaign"
REGISTRATIONS = ("PROTOCOL.json", "SOURCE_FREEZE.json", "TRAINING_DATA_CONTEXTS.json")
FIT_FILES = {"DATA.json", "POSTERIOR_QUALIFICATION.json", "SUMMARY.json", "TRACE.json", "final.pt", "selected.pt"}
WALL_SCOPE = "elapsed_since_original_restart_including_interruption_and_resume"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def relative(path, run):
    path, run = Path(path).resolve(), Path(run).resolve()
    require(path.is_relative_to(run), "Path escaped this run")
    return str(path.relative_to(run))


def atomic_json(path, value):
    """Create a complete file without ever exposing a zero-byte final path."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="pending_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)  # Exclusive, atomic publication; no overwrite.
    finally:
        Path(temporary).unlink(missing_ok=True)


def file_record(path, run):
    require(Path(path).is_file() and not Path(path).is_symlink(), "Expected ordinary file: " + str(path))
    return dict(path=relative(path, run), bytes=Path(path).stat().st_size, sha256=sha(path))


def inventory(directory, run):
    if not directory.exists():
        return []
    require(directory.is_dir() and not directory.is_symlink(), "Unsafe input directory")
    records = []
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "Symlink refused in run evidence")
        if path.is_file(): records.append(file_record(path, run))
        else: require(path.is_dir(), "Special evidence file refused")
    return records


def check_files(run, records):
    for record in records:
        path = run / record["path"]
        require(path.is_file() and path.stat().st_size == record["bytes"] and sha(path) == record["sha256"],
                "Protected evidence changed: " + record["path"])


def frozen(run, repo=REPO):
    require(not (run / "EVALUATION_INDEX.json").exists() and not any(run.glob("evaluation/**/*.npz"))
            and not any(run.glob("recovery/confirmation/**/*.npz")), "Training recovery is forbidden after recorded confirmation access")
    freeze, protocol = read(run / "SOURCE_FREEZE.json"), read(run / "PROTOCOL.json")
    require(sha(run / "PROTOCOL.json") == freeze["protocol_sha256"], "Protocol hash changed")
    require(sha(run / "TRAINING_DATA_CONTEXTS.json") == freeze["training_data_contexts_sha256"], "Training identities changed")
    for name, expected in freeze["files"].items():
        require(sha(repo / name) == expected, "Frozen source changed: " + name)
    for directory, source in (("full_online_confirmation", "online_confirm.py"), ("train_execution_cross", "train_execution_cross.py")):
        path = run / directory / "SELF_REGISTRATION.json"
        if path.exists():
            registration = read(path)
            require(sha(run / "SOURCE_FREEZE.json") == registration["parent_source_freeze_sha256"], "Supplement parent changed")
            require(sha(SOURCE.parent.parent / source) == registration["source_sha256"], "Frozen supplement source changed")
            require(sha(path.parent / registration["source_snapshot"]) == registration["source_sha256"], "Supplement snapshot changed")
    return protocol


def fit_validation(fit, task, seed, mode, protocol, contexts):
    require(fit.is_dir() and {p.name for p in fit.iterdir()} == FIT_FILES, "Incomplete or unexpected fit file inventory")
    summary, data, trace = read(fit / "SUMMARY.json"), read(fit / "DATA.json"), read(fit / "TRACE.json")
    require((summary["task"],summary["seed"],summary["train_mode"]) == (task,seed,mode), "Fit identity mismatch")
    require(summary["updates"] == protocol["updates"] and summary["development"] is False and data["development"] is False,
            "Training budget/profile changed")
    require(data["train"] == contexts[task]["train"]["data_sha256"] and data["val"] == contexts[task]["val"]["data_sha256"], "Training/validation data identity changed")
    require(isinstance(trace,list) and [row["step"] for row in trace] == list(range(1,protocol["updates"]+1)), "Training trace does not cover every registered update")
    previous_cpu = -1.
    for row in trace:
        require(len(row["ids"]) == protocol["batch_size"] and all(type(i) is int and 0 <= i < protocol["splits"]["train"][0] for i in row["ids"]), "Invalid training batch trace")
        require(set(row["losses"]) == set(protocol["families"]) and all(math.isfinite(v) for v in row["losses"].values()), "Invalid recorded loss trace")
        expected_policy = "read_all_warmup" if row["step"] <= protocol["warmup_updates"] else "actual_greedy"
        require(row["target_policy"] == expected_policy and math.isfinite(row["cpu"]) and row["cpu"] >= previous_cpu, "Invalid policy/CPU trace")
        previous_cpu = row["cpu"]
    eligible = [0] + [step for step in range(1,protocol["updates"]+1) if step % protocol["validate_every"] == 0 or step == protocol["updates"]]
    require(summary["selected_step"] in eligible and [r["step"] for r in summary["validations"]] == eligible, "Checkpoint selection schedule changed")
    for name, key in (("selected.pt","checkpoint_sha256"),("final.pt","final_checkpoint_sha256")):
        require(sha(fit/name) == summary[key], "Checkpoint hash mismatch: " + name)
    for key in ("initial_hashes","final_hashes","model_hashes"):
        require(set(summary[key]) == set(protocol["families"]), "Missing family model identities")
    read(fit / "POSTERIOR_QUALIFICATION.json")  # Presence/parse only; no scientific metric selects a retry.
    return summary


def valid_receipt(path, task, seed, mode):
    row = read(path)
    require((row["task"],row["seed"],row["train_mode"]) == (task,seed,mode), "Receipt identity mismatch")
    require(type(row["exit_code"]) is int, "Missing wait4 exit status")
    for key in ("cpu_user_seconds","cpu_system_seconds","wall_seconds","maximum_rss_kib"):
        require(type(row[key]) in (int,float) and math.isfinite(row[key]) and row[key] >= 0, "Invalid wait4 field: " + key)
    return row


def inspect(run, repo=REPO):
    run = Path(run).resolve(); protocol = frozen(run,repo); contexts = read(run/"TRAINING_DATA_CONTEXTS.json")
    retained, pending = [], []
    for task,seed,mode in itertools.product(protocol["tasks"],protocol["seeds"],protocol["modes"]):
        name=f"{task}_s{seed}_{mode}"; fit=run/"fits"/name; receipt=run/"receipts/train"/(name+".json")
        files=inventory(fit,run)
        files += [file_record(p,run) for p in sorted((run/"receipts/train").glob(name+".*")) if p.is_file()]
        record=dict(name=name,task=task,seed=seed,train_mode=mode,canonical_files=files,
                    receipt_path=relative(receipt,run),receipt_sha256=sha(receipt) if receipt.is_file() else None)
        try:
            fit_validation(fit,task,seed,mode,protocol,contexts)
            row=valid_receipt(receipt,task,seed,mode); require(row["exit_code"] == 0,"Worker did not exit successfully")
        except (ValueError,KeyError,TypeError,OSError) as error:
            record.update(reason=type(error).__name__+": "+str(error),prior_activity_recorded=bool(files));pending.append(record)
        else:
            record.update(wait4_cpu_seconds=row["cpu_user_seconds"]+row["cpu_system_seconds"]);retained.append(record)
    return dict(schema="hcsn.r15.training-resume.plan.v1",run=str(run),created_utc=utc(),retained_successful_groups=retained,
                pending_groups=pending,expected_groups=len(retained)+len(pending),protocol=protocol)


def copy_records(run, records, destination):
    result=[]
    for record in records:
        source=run/record["path"]; target=destination/record["path"]
        check_files(run,[record]); target.parent.mkdir(parents=True,exist_ok=True)
        require(not target.exists(),"Archive path already exists");shutil.copy2(source,target)
        require(sha(target)==record["sha256"] and target.stat().st_size==record["bytes"],"Archive copy differs")
        result.append(dict(original_path=record["path"],archive_path=relative(target,run),bytes=record["bytes"],sha256=record["sha256"]))
    return result


def preservation(run,plan):
    directory=run/"attempts/train_02_enospc"; path=directory/"PRESERVATION.json"
    if path.exists():
        result=read(path)
        for group in result["retained_successful_groups"]:check_files(run,group["canonical_files"])
        check_files(run,[dict(path=r["archive_path"],bytes=r["bytes"],sha256=r["sha256"]) for r in result["quarantine_files"]])
        return result
    directory.mkdir(parents=True,exist_ok=False)
    files=inventory(run/"receipts/train",run)
    for group in plan["pending_groups"]:files+=inventory(run/"fits"/group["name"],run)
    archives=copy_records(run,files,directory/"original")
    processes=[]
    for group in plan["pending_groups"]:
        if not group["prior_activity_recorded"]:continue
        cpu,status,exit_code=None,"not_measured",None
        try:
            receipt=valid_receipt(run/group["receipt_path"],group["task"],group["seed"],group["train_mode"])
        except (ValueError,KeyError,TypeError,OSError):pass
        else:cpu=receipt["cpu_user_seconds"]+receipt["cpu_system_seconds"];status="complete_process_lifetime_wait4";exit_code=receipt["exit_code"]
        processes.append(dict(process_attempt_id="formal03/train_original/"+group["name"],name=group["name"],task=group["task"],seed=group["seed"],train_mode=group["train_mode"],
            cpu_seconds=cpu,measurement_status=status,exit_code=exit_code,evidence_paths=[r["archive_path"] for r in archives if r["original_path"] in {f["path"] for f in group["canonical_files"]}],
            reason="Original launcher stopped with reported ENOSPC; partial output or logs remain. Missing wait4 CPU/exit status is unknown, not zero."))
    result=dict(schema="hcsn.r15.training-interruption-preservation.v1",created_utc=utc(),run=str(run),
        observed_failure="Operator reported ENOSPC while frozen launcher wrote a receipt. Current filesystem free space does not establish the cause; no quota/layer explanation is asserted.",
        retained_successful_groups=plan["retained_successful_groups"],original_process_attempts=processes,quarantine_files=archives,
        root_receipt_archive_is_duplicate_not_additional_cpu=True)
    atomic_json(path,result);return result


def event(path,kind,**details):
    row=dict(utc=utc(),event=kind,**details)
    print(json.dumps(row),flush=True)
    with path.open("a") as stream:stream.write(json.dumps(row,sort_keys=True)+"\n");stream.flush();os.fsync(stream.fileno())


def disk_guard(active,free,low,high,events,sender=os.killpg):
    now=time.monotonic()
    for job in active:
        if free < low and not job["paused"]:
            try:sender(job["process"].pid,signal.SIGSTOP)
            except ProcessLookupError:continue
            job["paused"]=True;job["pause_start"]=now
            event(events,"disk_pause",process_attempt_id=job["process_attempt_id"],pid=job["process"].pid,free_bytes=free)
        elif free >= high and job["paused"]:
            try:sender(job["process"].pid,signal.SIGCONT)
            except ProcessLookupError:continue
            job["paused"]=False;job["pause_seconds"]+=now-job["pause_start"]
            event(events,"disk_resume",process_attempt_id=job["process_attempt_id"],pid=job["process"].pid,free_bytes=free)


def publish(run,attempt,job,receipt,plan,preserved,protocol,contexts):
    name=job["name"]; source=job["work"]/"fits"/name
    fit_validation(source,job["task"],job["seed"],job["train_mode"],protocol,contexts)
    staging=attempt/"staging"/name;staging.parent.mkdir(exist_ok=True);shutil.copytree(source,staging)
    require([(r["bytes"],r["sha256"],Path(r["path"]).name) for r in inventory(source,run)] == [(r["bytes"],r["sha256"],Path(r["path"]).name) for r in inventory(staging,run)],"Staged fit differs")
    original=next(group for group in plan["pending_groups"] if group["name"]==name)
    check_files(run,original["canonical_files"])
    for file in original["canonical_files"]:
        backup=attempt/"before"/file["path"]
        require(backup.is_file() and sha(backup)==file["sha256"],"Replacement lacks preserved original bytes")
    destination=run/"fits"/name
    if destination.exists():
        retired=attempt/"retired_fits"/name;retired.parent.mkdir(exist_ok=True);os.rename(destination,retired)
    require(not destination.exists(),"Canonical fit unexpectedly appeared");os.rename(staging,destination)
    canonical_receipt=run/"receipts/train"/(name+".json")
    if canonical_receipt.exists():
        retired=attempt/"retired_receipts"/canonical_receipt.name;retired.parent.mkdir(exist_ok=True);os.rename(canonical_receipt,retired)
    canonical_receipt.parent.mkdir(parents=True,exist_ok=True)
    # Publish identical immutable bytes, not a reconstructed or relabelled receipt.
    os.link(job["directory"]/"RECEIPT.json",canonical_receipt)
    old=run/"attempts/train_02_enospc/original/fits"/name/"final.pt"
    comparison=dict(available=old.is_file(),scope="Serialization bytes/SHA only; differences or invalid old bytes do not establish a model difference; old final never substitutes for selected")
    if old.is_file():comparison.update(original_path=relative(old,run),original_sha256=sha(old),new_sha256=sha(destination/"final.pt"),byte_identical=old.read_bytes()==(destination/"final.pt").read_bytes())
    result=dict(schema="hcsn.r15.training-resume.promotion.v1",utc=utc(),canonical_promotion=True,
        process_attempt_id=job["process_attempt_id"],attempt_id=attempt.name,name=name,canonical_fit=relative(destination,run),
        canonical_receipt=relative(canonical_receipt,run),receipt_sha256=sha(canonical_receipt),fit_files=inventory(destination,run),prior_partial_final_comparison=comparison)
    atomic_json(job["directory"]/"PROMOTION.json",result)
    for group in preserved["retained_successful_groups"]:check_files(run,group["canonical_files"])
    return result


def run_attempt(run,attempt_id="train_resume_001",workers=2,low_gib=1.,high_gib=2.,repo=REPO,command_factory=None):
    run=Path(run).resolve();require(1<=workers<=2 and 0<low_gib<high_gib and all(math.isfinite(x) for x in (low_gib,high_gib)),"Use <=2 workers and positive low<high disk thresholds")
    require(attempt_id.startswith("train_resume_") and all(c.isalnum() or c=='_' for c in attempt_id),"Invalid attempt ID")
    require(hasattr(os,"wait4") and hasattr(os,"killpg"),"POSIX wait4 and owned process groups required")
    lock=(run/"RESUME_TRAINING_LOCK").open("a+")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    previous_terminate=signal.getsignal(signal.SIGTERM)
    def terminate(signum,frame):
        raise KeyboardInterrupt("Resume launcher received SIGTERM")
    signal.signal(signal.SIGTERM,terminate)
    try:
        plan=inspect(run,repo);protocol=plan["protocol"];contexts=read(run/"TRAINING_DATA_CONTEXTS.json")
        require(not (run/"receipts/train/TOTAL.json").exists(),"Training TOTAL already exists; nothing may be overwritten")
        preserved=preservation(run,plan)
        attempt=run/"attempts"/attempt_id;attempt.mkdir(parents=True,exist_ok=False)
        before=copy_records(run,[record for group in plan["pending_groups"] for record in group["canonical_files"]],attempt/"before")
        identities={"source_freeze_sha256":sha(run/"SOURCE_FREEZE.json"),"protocol_sha256":sha(run/"PROTOCOL.json"),"training_data_contexts_sha256":sha(run/"TRAINING_DATA_CONTEXTS.json")}
        registration=dict(schema="hcsn.r15.training-resume.registration.v1",utc=utc(),attempt_id=attempt_id,
            source_sha256=sha(SOURCE),**identities,source_files_unchanged=True,workers=workers,
            low_free_gib=low_gib,high_free_gib=high_gib,retained_successful_groups=plan["retained_successful_groups"],pending_groups=plan["pending_groups"],before_files=before,
            preserved_original=relative(run/"attempts/train_02_enospc/PRESERVATION.json",run),
            supplement_registrations={directory:sha(run/directory/"SELF_REGISTRATION.json") for directory in ("full_online_confirmation","train_execution_cross") if (run/directory/"SELF_REGISTRATION.json").exists()},
            training_profile="Original campaign train, exact original updates/data/seeds/objective/selection, freshly initialized in a new work root; no partial checkpoint continuation",
            guard_scope="Visible filesystem free-space guard only. It cannot eliminate unknown quota, sandbox layer, inode or other ENOSPC risks. Only this launcher's own child process groups receive STOP/CONT.")
        atomic_json(attempt/"REGISTRATION.json",registration)
        events=attempt/"EVENTS.jsonl";active=[];pending=list(plan["pending_groups"]);finished=[];promoted=[];failed=False;waiting_for_space=False
        low,high=int(low_gib*1024**3),int(high_gib*1024**3)
        def capture(job,status,usage):
            code=os.waitstatus_to_exitcode(status);job["process"].returncode=code
            if job["paused"]:job["pause_seconds"]+=time.monotonic()-job["pause_start"]
            job["out"].close();job["err"].close()
            receipt=dict(name=job["name"],task=job["task"],seed=job["seed"],train_mode=job["train_mode"],command=job["command"],
                exit_code=code,cpu_user_seconds=usage.ru_utime,cpu_system_seconds=usage.ru_stime,maximum_rss_kib=usage.ru_maxrss,
                wall_seconds=time.monotonic()-job["started"],pause_seconds=job["pause_seconds"],attempt_id=attempt_id,
                process_attempt_id=job["process_attempt_id"],stdout_path=relative(job["directory"]/"stdout.log",run),stderr_path=relative(job["directory"]/"stderr.log",run),
                measurement_status="complete_process_lifetime_wait4",receipt_utc=utc())
            print(json.dumps(dict(event="wait4_receipt_before_disk_write",receipt=receipt)),flush=True)
            atomic_json(job["directory"]/"RECEIPT.json",receipt);finished.append(receipt)
            return receipt
        try:
            while active or (pending and not failed):
                for job in list(active):
                    pid,status,usage=os.wait4(job["process"].pid,os.WNOHANG)
                    if not pid:continue
                    active.remove(job);receipt=capture(job,status,usage)
                    if receipt["exit_code"]==0:
                        try:promotion=publish(run,attempt,job,receipt,plan,preserved,protocol,contexts)
                        except (ValueError,KeyError,TypeError,OSError) as error:
                            failed=True;event(events,"promotion_failed",process_attempt_id=job["process_attempt_id"],error=repr(error))
                        else:promoted.append(promotion);event(events,"promoted",name=job["name"],process_attempt_id=job["process_attempt_id"])
                    else:failed=True;event(events,"worker_failed",name=job["name"],exit_code=receipt["exit_code"])
                free=shutil.disk_usage(run).free;disk_guard(active,free,low,high,events)
                if pending and not failed and len(active)<workers and free<high and not waiting_for_space:
                    event(events,"waiting_for_visible_free_space",free_bytes=free,required_bytes=high);waiting_for_space=True
                elif waiting_for_space and free>=high:
                    event(events,"visible_free_space_recovered",free_bytes=free);waiting_for_space=False
                while pending and not failed and len(active)<workers and free>=high:
                    group=pending.pop(0);directory=attempt/"jobs"/group["name"];work=directory/"work";work.mkdir(parents=True)
                    for filename in REGISTRATIONS:
                        shutil.copy2(run/filename,work/filename);require(sha(run/filename)==sha(work/filename),"Copied registration changed")
                    if (run/"source_snapshot").is_dir():shutil.copytree(run/"source_snapshot",work/"source_snapshot")
                    command=([sys.executable,"-m",MODULE,"train","--output",str(work),"--task",group["task"],"--seed",str(group["seed"]),"--mode",group["train_mode"]]
                             if command_factory is None else command_factory(work,group))
                    identity=attempt_id+"/"+group["name"]
                    atomic_json(directory/"LAUNCH_INTENT.json",dict(utc=utc(),attempt_id=attempt_id,process_attempt_id=identity,command=command,work_root=relative(work,run)))
                    out=(directory/"stdout.log").open("x");err=(directory/"stderr.log").open("x")
                    process=subprocess.Popen(command,stdout=out,stderr=err,cwd=repo,start_new_session=True)
                    job=dict(**group,directory=directory,work=work,command=command,process=process,out=out,err=err,started=time.monotonic(),
                             process_attempt_id=identity,paused=False,pause_seconds=0.)
                    active.append(job)
                    atomic_json(directory/"STARTED.json",dict(utc=utc(),pid=process.pid,attempt_id=attempt_id,process_attempt_id=identity,
                        name=group["name"],task=group["task"],seed=group["seed"],train_mode=group["train_mode"],command=command,work_root=relative(work,run)))
                    event(events,"worker_started",name=group["name"],pid=process.pid,process_attempt_id=identity)
                    free=shutil.disk_usage(run).free
                if active or (pending and not failed):time.sleep(.5)
        except BaseException:
            # Best effort on ordinary Python failures/interrupts. SIGKILL cannot be
            # caught; durable STARTED without RECEIPT remains unknown CPU evidence.
            for job in active:
                try:os.killpg(job["process"].pid,signal.SIGCONT);os.killpg(job["process"].pid,signal.SIGTERM)
                except ProcessLookupError:pass
            deadline=time.monotonic()+10
            while active:
                for job in list(active):
                    pid,status,usage=os.wait4(job["process"].pid,os.WNOHANG)
                    if pid:
                        active.remove(job)
                        try:capture(job,status,usage)
                        except OSError:pass  # Full receipt was already flushed to stdout.
                    elif time.monotonic()>deadline:
                        try:os.killpg(job["process"].pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                if active:time.sleep(.1)
            raise
        final=inspect(run,repo)
        for group in plan["retained_successful_groups"]:check_files(run,group["canonical_files"])
        result=dict(schema="hcsn.r15.training-resume.result.v1",utc=utc(),attempt_id=attempt_id,retained_groups=len(plan["retained_successful_groups"]),
            attempted_jobs=len(finished),promoted_groups=len(promoted),complete_groups=len(final["retained_successful_groups"]),expected_groups=plan["expected_groups"],
            completed=not final["pending_groups"],failed_jobs=sum(row["exit_code"]!=0 for row in finished),
            process_cpu_seconds=sum(row["cpu_user_seconds"]+row["cpu_system_seconds"] for row in finished),
            original_unknown_cpu_process_attempts=[row["process_attempt_id"] for row in preserved["original_process_attempts"] if row["cpu_seconds"] is None])
        atomic_json(attempt/"RESULT.json",result)
        if result["completed"]:
            receipts=[read(run/group["receipt_path"]) for group in final["retained_successful_groups"]]
            start=read(run/"RESTART_REGISTRATION.json")["utc"];end=utc()
            total=dict(stage="train",workers=workers,jobs=len(receipts),failed=0,
                process_cpu_seconds=sum(row["cpu_user_seconds"]+row["cpu_system_seconds"] for row in receipts),
                wall_seconds=(datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds(),wall_scope=WALL_SCOPE,
                span_started_utc=start,span_finished_utc=end,resumed=True,accounting_kind="resumed_consolidated",original_launcher_completed=False,
                retained_original_successful_groups=len(preserved["retained_successful_groups"]),
                resume_attempt_ids=sorted(path.parent.name for path in (run/"attempts").glob("train_resume_*/REGISTRATION.json")),
                canonical_resume_attempt_ids=sorted({row["attempt_id"] for row in receipts if "attempt_id" in row}),
                unknown_original_process_attempts=result["original_unknown_cpu_process_attempts"],
                note="32 selected successful process receipts consolidated, not a normal completion of the original launcher. Prior lost/failed attempt costs are separate evidence and are not zero; launcher/copy/validation CPU is not included.")
            atomic_json(run/"receipts/train/TOTAL.json",total)
        return result
    finally:
        signal.signal(signal.SIGTERM,previous_terminate)
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("inspect","launch","selfcheck"));parser.add_argument("--run",type=Path)
    parser.add_argument("--attempt-id",default="train_resume_001");parser.add_argument("--workers",type=int,default=2)
    parser.add_argument("--low-free-gib",type=float,default=1.);parser.add_argument("--high-free-gib",type=float,default=2.)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.action=="selfcheck":
        require(args.output is not None,"selfcheck requires --output")
        if __package__:
            from .resume_training_selfcheck import selfcheck
        else:
            from resume_training_selfcheck import selfcheck
        result=selfcheck(args.output);print(json.dumps(dict(passed=result["passed"],checks=len(result["checks"]),real_training_or_test_accessed=False)))
    elif args.action=="inspect":
        require(args.run is not None,"inspect requires --run")
        result=inspect(args.run)
        if args.output:atomic_json(args.output,result)
        print(json.dumps(dict(retained=len(result["retained_successful_groups"]),pending=len(result["pending_groups"]),expected=result["expected_groups"])))
    else:
        require(args.run is not None,"launch requires --run")
        result=run_attempt(args.run,args.attempt_id,args.workers,args.low_free_gib,args.high_free_gib)
        print(json.dumps(result));raise SystemExit(int(not result["completed"]))


if __name__=="__main__":
    main()

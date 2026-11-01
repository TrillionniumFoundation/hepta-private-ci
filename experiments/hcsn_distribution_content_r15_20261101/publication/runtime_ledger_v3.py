#!/usr/bin/env python3
"""Account the preserved ENOSPC interruption and immutable resume receipts.

V1 and V2 remain unchanged. Canonical six-stage receipts are charged once by
V2. This extension identifies the 13 retained successes and subsequently
promoted successes, excludes their byte-identical receipt copies, and adds
only distinct, unpromoted process attempts. Missing process CPU remains null.
No models, NPZs, or test data are loaded. Selfcheck uses artificial files only.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import tempfile

if __package__:
    from . import runtime_ledger_v2 as previous
else:
    import runtime_ledger_v2 as previous


base = previous.base
SOURCE = Path(__file__).resolve()
PRESERVATION = "attempts/train_02_enospc/PRESERVATION.json"
LOWER_BOUND_STATUSES = ("lower_bound_at_interrupt_snapshot", "lower_bound_from_nested_body_timer",
                        "lower_bound_from_process_cpu_snapshot")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contained(run, relative):
    base.require(isinstance(relative,str) and relative, "Missing relative recovery path")
    part = Path(relative)
    base.require(not part.is_absolute(), "Recovery evidence path must be relative to formal_03")
    path = (run/part).resolve()
    base.require(path.is_relative_to(run.resolve()), "Recovery path escaped formal_03")
    return path


def identity(row):
    return base.job_identity(row)


def process_id(row):
    value = row.get("process_attempt_id")
    base.require(isinstance(value,str) and value, "Missing stable process-attempt identity")
    return value


def process_measurement(row, receipt=None):
    """Never turn missing CPU into a numeric zero."""
    status = row.get("measurement_status")
    value = row.get("cpu_seconds")
    if status == "not_measured":
        base.require(value is None, "Unmeasured process CPU must be null")
        return None, "not_measured"
    if status in LOWER_BOUND_STATUSES:
        return base.number(value,"partial process CPU lower bound"), status
    if status == "complete_process_lifetime_wait4":
        source = row if receipt is None else receipt
        base.require(identity(source)==identity(row),"Preserved wait4 identifies another job")
        measured = base.number(source.get("cpu_user_seconds"),"wait4 user CPU") + base.number(source.get("cpu_system_seconds"),"wait4 system CPU")
        base.require(base.close(base.number(value,"complete process CPU"),measured), "Wait4 CPU components disagree")
        base.require(type(row.get("exit_code")) is int and source.get("exit_code")==row["exit_code"], "Complete wait4 requires its actual exit code")
        return measured,status
    raise base.LedgerError("Unknown original-process measurement status: " + str(status))


def enospc_ledger(inputs, run, protocol, canonical_stage):
    preservation_path = run/PRESERVATION
    record = inputs.read(preservation_path)
    retained = record.get("retained_successful_groups")
    original = record.get("original_process_attempts")
    quarantine = record.get("quarantine_files")
    base.require(isinstance(retained,list) and isinstance(original,list) and isinstance(quarantine,list),
                 "Incomplete ENOSPC preservation manifest")
    total = canonical_stage["launcher_total"]
    base.require(isinstance(total,dict) and total.get("accounting_kind")=="resumed_consolidated"
        and total.get("original_launcher_completed") is False and total.get("resumed") is True,
        "Training TOTAL must disclose consolidation after an unsuccessful original launcher")
    base.require(total.get("wall_scope")=="elapsed_since_original_restart_including_interruption_and_resume",
                 "Resumed training wall must be the explicitly labeled original-restart span")
    canonical = {}
    for job in canonical_stage["jobs"]:
        key = identity(job)
        path = inputs.root/job["source"]
        row = inputs.read(path)
        base.require(row["exit_code"]==0, "Canonical resumed training requires successful final worker receipts")
        canonical[key] = dict(row=row,path=path,sha256=inputs.sources[inputs.relative(path)]["sha256"])
    expected = set(itertools.product(protocol["tasks"],protocol["seeds"],("light","value")))
    base.require(set(canonical)==expected, "Canonical resumed training matrix is incomplete")
    retained_keys, covered, process_ids = set(),set(),set()
    aliases, charges, unknown, attempts = [],[],[],[]
    for row in retained:
        key = identity(row)
        base.require(key in canonical and key not in retained_keys, "Invalid/duplicate retained successful group")
        path = contained(run,row.get("receipt_path"))
        base.require(path==canonical[key]["path"] and row.get("receipt_sha256")==canonical[key]["sha256"],
                     "Retained success differs from its original canonical receipt")
        retained_keys.add(key); covered.add(key)
        aliases.append(dict(name=row.get("name"),**dict(zip(base.IDENTITY,key)),
            source=inputs.relative(path),sha256=canonical[key]["sha256"],
            charge_location="canonical_train_worker",additional_charged_cpu_seconds=0.,
            reason="Retained original successful process is already in the canonical train sum"))
    for row in original:
        key,pid = identity(row),process_id(row)
        base.require(key in expected and key not in retained_keys, "Original partial attempt overlaps retained successful process")
        base.require(pid not in process_ids, "Duplicate process-attempt identity")
        process_ids.add(pid)
        evidence = row.get("evidence_paths")
        base.require(isinstance(evidence,list) and evidence, "Missing original partial-process evidence inventory")
        for relative in evidence: contained(run,relative)
        complete_receipt = None
        if row.get("measurement_status")=="complete_process_lifetime_wait4":
            candidates = [relative for relative in evidence if relative.endswith("/receipts/train/"+row["name"]+".json")]
            base.require(len(candidates)==1,"Known original wait4 needs its unique preserved raw receipt")
            complete_receipt=inputs.read(contained(run,candidates[0]))
        cpu,status = process_measurement(row,complete_receipt)
        item = dict(**dict(zip(base.IDENTITY,key)),process_attempt_id=pid,source=inputs.relative(preservation_path),
            exit_code=row.get("exit_code"),cpu_seconds=cpu,measurement_status=status,evidence_paths=evidence,
            accounting="Distinct original process attempt; later success of the same job does not remove its cost")
        (unknown if cpu is None else charges).append(item)
    for item in quarantine:
        base.require(isinstance(item,dict) and type(item.get("bytes")) is int and item["bytes"]>=0
            and isinstance(item.get("sha256"),str) and len(item["sha256"])==64,
            "Invalid preserved partial-file inventory")
        contained(run,item.get("original_path")); contained(run,item.get("archive_path"))
    directories = sorted(path for path in (run/"attempts").glob("train_resume_*") if path.is_dir())
    base.require(directories,"No registered resume attempt found")
    observed_attempts,preparation_only = [],[]
    for directory in directories:
        registration_path = directory/"REGISTRATION.json"
        if not registration_path.exists():
            base.require(not any((directory/"jobs").glob("*/STARTED.json"))
                and not any((directory/"jobs").glob("*/RECEIPT.json"))
                and not any((directory/"jobs").glob("*/LAUNCH_INTENT.json")),
                "Process evidence exists without its resume registration")
            preparation_only.append(dict(directory=inputs.relative(directory),worker_start_evidence="not_present",
                launcher_preparation_cpu_seconds=None,measurement_status="not_measured"))
            continue
        registration = inputs.read(registration_path)
        attempt_id = registration.get("attempt_id")
        base.require(attempt_id==directory.name and attempt_id not in observed_attempts, "Resume attempt identity mismatch")
        observed_attempts.append(attempt_id)
        for filename,field in (("SOURCE_FREEZE.json","source_freeze_sha256"),("PROTOCOL.json","protocol_sha256"),
                               ("TRAINING_DATA_CONTEXTS.json","training_data_contexts_sha256")):
            inputs.read(run/filename)
            base.require(registration.get(field)==inputs.sources[inputs.relative(run/filename)]["sha256"],
                         "Resume scientific freeze/context identity changed: "+field)
        supplements=registration.get("supplement_registrations",{})
        base.require(isinstance(supplements,dict),"Invalid resume supplement identity map")
        for name,expected_sha in supplements.items():
            base.require(name in ("full_online_confirmation","train_execution_cross"),"Unknown registered supplement")
            path=run/name/"SELF_REGISTRATION.json";inputs.read(path)
            base.require(inputs.sources[inputs.relative(path)]["sha256"]==expected_sha,"Resume supplement registration changed")
        local_records = []
        for job_directory in sorted((directory/"jobs").glob("*")):
            if not job_directory.is_dir(): continue
            start_path,receipt_path,promotion_path,intent_path = (job_directory/name for name in ("STARTED.json","RECEIPT.json","PROMOTION.json","LAUNCH_INTENT.json"))
            start = inputs.read(start_path) if start_path.exists() else None
            receipt = inputs.read(receipt_path) if receipt_path.exists() else None
            promotion = inputs.read(promotion_path) if promotion_path.exists() else None
            intent = inputs.read(intent_path) if intent_path.exists() else None
            base.require(start is not None or receipt is not None or intent is not None,
                         "Resume job directory has no process intent/start/wait4 evidence")
            if receipt is None and start is None:
                candidates=[row for row in registration.get("pending_groups",[]) if row.get("name")==job_directory.name]
                base.require(len(candidates)==1,"Launch intent lacks a registered pending-job identity")
                source_row={**candidates[0],"process_attempt_id":intent.get("process_attempt_id"),"attempt_id":intent.get("attempt_id")}
            else:
                source_row = receipt if receipt is not None else start
            key,pid = identity(source_row),process_id(source_row)
            base.require(key in expected and key not in retained_keys, "Resume retrained an already retained successful job")
            base.require(source_row.get("attempt_id")==attempt_id and pid==attempt_id+"/"+job_directory.name,
                         "Resume process identity disagrees with its directory")
            base.require(pid not in process_ids,"Process attempt appears twice")
            process_ids.add(pid)
            if start is not None:
                base.require(identity(start)==key and process_id(start)==pid,"STARTED and RECEIPT name different attempts")
            if receipt is None:
                base.require(promotion is None,"Promotion exists without its immutable wait4 receipt")
                item = dict(**dict(zip(base.IDENTITY,key)),process_attempt_id=pid,attempt_id=attempt_id,
                    source=inputs.relative(start_path if start is not None else intent_path),cpu_seconds=None,exit_code=None,measurement_status="not_measured",
                    process_start_confirmed=start is not None,
                    reason="Process intent/start survived without a complete wait4 receipt; CPU and any unconfirmed start remain unknown, including when a later retry succeeds")
                unknown.append(item); local_records.append(item); continue
            cpu = base.number(receipt.get("cpu_user_seconds"),"resume wait4 user CPU")+base.number(receipt.get("cpu_system_seconds"),"resume wait4 system CPU")
            base.require(type(receipt.get("exit_code")) is int,"Resume wait4 exit code missing")
            base.number(receipt.get("wall_seconds"),"resume worker wall")
            receipt_sha = inputs.sources[inputs.relative(receipt_path)]["sha256"]
            is_alias = receipt_sha==canonical[key]["sha256"]
            item = dict(**dict(zip(base.IDENTITY,key)),process_attempt_id=pid,attempt_id=attempt_id,
                source=inputs.relative(receipt_path),sha256=receipt_sha,cpu_seconds=cpu,
                cpu_user_seconds=receipt["cpu_user_seconds"],cpu_system_seconds=receipt["cpu_system_seconds"],
                exit_code=receipt["exit_code"],measurement_status="complete_process_lifetime_wait4")
            if promotion is not None:
                base.require(promotion.get("canonical_promotion") is True and promotion.get("process_attempt_id")==pid
                    and promotion.get("receipt_sha256")==receipt_sha
                    and contained(run,promotion.get("canonical_receipt"))==canonical[key]["path"] and is_alias,
                    "Promotion does not identify the byte-identical canonical receipt")
            if is_alias:
                base.require(key not in covered and receipt["exit_code"]==0,"Canonical process mapped to multiple attempts or failed")
                covered.add(key)
                item.update(charge_location="canonical_train_worker",additional_charged_cpu_seconds=0.,
                    promotion_record_present=promotion is not None,
                    reason="Byte-identical immutable receipt is already charged once in the canonical train sum")
                aliases.append(item)
            else:
                item.update(charge_location="additional_distinct_resume_process",
                    reason="No canonical receipt has this process-attempt identity and byte hash; charge once even if the job later succeeds")
                charges.append(item)
            local_records.append(item)
        result_path = directory/"RESULT.json"
        result = inputs.read(result_path) if result_path.exists() else None
        attempts.append(dict(attempt_id=attempt_id,registration_source=inputs.relative(registration_path),
            same_scientific_freeze_and_contexts=True,result_available=result is not None,result=result,
            process_records=local_records))
    base.require(covered==expected,"Some canonical training successes lack retained/promotion provenance")
    base.require(isinstance(total.get("resume_attempt_ids"),list) and set(total["resume_attempt_ids"])==set(observed_attempts),
                 "Consolidated TOTAL does not identify every preserved resume attempt")
    complete_charges = [row for row in charges if row["measurement_status"]=="complete_process_lifetime_wait4"]
    partial_charges = [row for row in charges if row["measurement_status"] in LOWER_BOUND_STATUSES]
    # None means no measurement exists; a separate additive list permits a
    # lower bound without ever asserting that an unknown process used zero CPU.
    complete_total = sum(row["cpu_seconds"] for row in complete_charges) if complete_charges else None
    partial_total = sum(row["cpu_seconds"] for row in partial_charges) if partial_charges else None
    measured = [row["cpu_seconds"] for row in charges]
    return dict(schema="hcsn.r15.enospc-training-accounting.v1",preservation_source=inputs.relative(preservation_path),
        original_launcher_completed=False,operational_failure=f"ENOSPC while writing original train receipt after {len(retained_keys)} retained complete groups",
        retained_original_success_count=len(retained_keys),resumed_success_count=len(expected)-len(retained_keys),
        canonical_success_count=len(expected),same_scientific_freeze_and_contexts=True,
        canonical_train_worker_cpu_seconds=canonical_stage["observed_worker_cpu_seconds"],
        canonical_aliases_not_added=aliases,original_process_attempts=original,resume_attempts=attempts,
        unregistered_preparation_directories=preparation_only,
        additional_measured_processes=charges,unknown_process_attempts=unknown,unknown_process_attempt_count=len(unknown),
        additional_complete_wait4_cpu_seconds=complete_total,
        additional_partial_cpu_lower_bound_seconds=partial_total,
        additional_observed_cpu_lower_bound_seconds=sum(measured) if measured else None,
        additional_observed_cpu_addends=measured,
        missing_process_cpu_seconds=None,missing_process_cpu_measurement_status="not_measured" if unknown else "no_missing_receipts_observed",
        original_and_resume_launcher_parent_cpu="not_measured",
        training_elapsed_span_seconds=canonical_stage["elapsed_wall_seconds"],training_wall_scope=total["wall_scope"],
        continuous_original_launcher_wall_seconds=None,
        quarantined_files=quarantine,
        ignored_duplicate_receipts="Canonical-success copies, original/receipts snapshots, before/ snapshots and job workroots are not additional worker lifetimes",
        accounting="Canonical successes charged once, plus distinct unpromoted measured attempts; unknown CPU remains null and cannot close a full-cost claim")


def build(results, allow_incomplete=False):
    root = Path(results).resolve(); run=root/"formal_03"
    ledger = previous.build(root,allow_incomplete)
    inputs = base.Inputs(root)
    protocol = inputs.read(run/"PROTOCOL.json")
    train = next(row for row in ledger["formal_03_stages"] if row["stage"]=="train")
    base.require(train["coverage"]=="complete","ENOSPC accounting requires the consolidated canonical training matrix")
    recovery = enospc_ledger(inputs,run,protocol,train)
    totals = ledger["totals"]
    before = totals["successful_failed_and_abandoned_cpu_lower_bound_seconds"]
    whole = sum([before,*recovery["additional_observed_cpu_addends"]])
    totals.update(pre_enospc_extension_cpu_lower_bound_seconds=before,
        enospc_additional_complete_wait4_cpu_seconds=recovery["additional_complete_wait4_cpu_seconds"],
        enospc_additional_partial_cpu_lower_bound_seconds=recovery["additional_partial_cpu_lower_bound_seconds"],
        enospc_additional_observed_cpu_lower_bound_seconds=recovery["additional_observed_cpu_lower_bound_seconds"],
        enospc_unknown_process_attempt_count=recovery["unknown_process_attempt_count"],
        enospc_unknown_process_cpu_seconds=None,
        successful_failed_and_abandoned_cpu_lower_bound_seconds=whole,hours_lower_bound=whole/3600,
        arithmetic="Canonical six-stage worker receipts once, plus formal_02 canonical OOM lower bound, plus measured distinct ENOSPC/resume process attempts. Missing CPU is null, not zero; aliases and nested timers are never added.")
    train.update(status="canonical_jobs_complete_after_operational_recovery",accounting_kind="resumed_consolidated",
        original_launcher_completed=False,wall_scope=recovery["training_wall_scope"],
        continuous_original_launcher_wall_seconds=None,
        original_successes_retained=recovery["retained_original_success_count"],
        successful_jobs_from_resume=recovery["resumed_success_count"],
        canonical_worker_cpu_excludes_distinct_failed_resume_attempts=True)
    sources = {row["path"]:row for row in ledger["input_files"]}
    for name,row in inputs.sources.items():
        base.require(name not in sources or sources[name]==row,"Input changed while accounting resumed training: "+name)
        sources[name]=row
    ledger.update(schema="hcsn.r15.publication.runtime-ledger.v3",created_utc=datetime.now(timezone.utc).isoformat(),
        source_sha256=sha(SOURCE),previous_ledger_source_sha256=sha(previous.__file__),
        enospc_training_recovery=recovery,
        scope="Recorded canonical six-stage worker CPU, original OOM lower bound, and distinct preserved ENOSPC/resume attempts. Some original CPU is unmeasured; this is a lower bound, not an uninterrupted successful-launcher or lifecycle-cost claim.",
        input_files=[sources[name] for name in sorted(sources)])
    ledger["unmeasured"].update(enospc_original_lost_wait4_cpu="not_measured",
        resumed_attempts_without_receipts_cpu="not_measured" if recovery["unknown_process_attempt_count"] else "no_missing_receipts_observed")
    return ledger


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("build",))
    parser.add_argument("--results",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--allow-incomplete",action="store_true")
    args=parser.parse_args()
    result=build(args.results,args.allow_incomplete);base.write(args.output,result)
    print(json.dumps(dict(totals=result["totals"],unknown_process_attempt_count=result["enospc_training_recovery"]["unknown_process_attempt_count"])))


if __name__=="__main__":
    main()

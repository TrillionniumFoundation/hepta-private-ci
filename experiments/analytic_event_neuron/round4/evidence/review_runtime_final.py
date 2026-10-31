"""Post-confirmation independent statistics and serialized-write accounting.

Read-only with respect to all scientific sources, prepared data and outcomes.
No model fitting, dataset generation, native execution, or gate changes.
"""

import argparse
import ast
import base64
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import zipfile

import numpy as np
from scipy.special import ndtr


Q = 1 << 24


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def object_sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def document_bytes(value):
    return canonical({"document": value, "sha256": object_sha(value)}) + b"\n"


def read_json(path):
    return json.loads(Path(path).read_text())


class Review:
    def __init__(self):
        self.checks = 0
        self.failures = []
        self.maximum_errors = defaultdict(float)

    def check(self, condition, label):
        self.checks += 1
        if not bool(condition):
            self.failures.append(label)

    def close(self, actual, expected, label, atol=2e-12, rtol=2e-12):
        a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
        if a.shape != b.shape:
            self.check(False, label + " shape")
            return
        error = float(np.max(np.abs(a - b))) if a.size else 0.0
        self.maximum_errors[label.split(":")[0]] = max(self.maximum_errors[label.split(":")[0]], error)
        self.check(np.allclose(a, b, rtol=rtol, atol=atol, equal_nan=False), label)


def interval(delta, replicates, seed, alpha):
    """Independent flattened-index implementation, same registered RNG stream."""
    delta = np.asarray(delta, dtype=float)
    s, n = delta.shape
    random = np.random.Generator(np.random.PCG64(seed))
    boot = []
    flat = delta.reshape(-1)
    for start in range(0, replicates, 200):
        count = min(200, replicates - start)
        selected_seeds = random.integers(0, s, size=(count, s, 1))
        selected_cases = random.integers(0, n, size=(count, s, n))
        indexes = (n * selected_seeds + selected_cases).reshape(count, -1)
        boot.extend(np.mean(flat[indexes], axis=1).tolist())
    return {"mean_difference": float(delta.mean()),
            "interval": np.quantile(np.asarray(boot), [alpha / 2, 1 - alpha / 2]).tolist(),
            "per_seed_mean_difference": delta.mean(axis=1).tolist(),
            "replicates": replicates, "interval_alpha": alpha,
            "training_seed_count": s, "trajectories_per_seed": n}


def compare_interval(check, actual, expected, label):
    for key in ("mean_difference", "interval", "per_seed_mean_difference"):
        check.close(actual[key], expected[key], label + ":" + key)
    for key in ("replicates", "interval_alpha", "training_seed_count", "trajectories_per_seed"):
        check.check(actual[key] == expected[key], label + ":" + key)


def partial_work_lower_bounds(directory, files):
    """Only count durable returned typed calls; unreturned/sparse calls unknown."""
    forecasts, typed, errors = {}, {}, []
    def inspect(raw, name):
        try:
            envelope = json.loads(raw)
            document = envelope["document"]
            if envelope["sha256"] != object_sha(document):
                raise ValueError("Envelope checksum differs")
            receipts = document.get("receipts", [])
            for receipt in receipts:
                forecasts[receipt["subject"],receipt["sequence"]] = receipt
            native = [n for receipt in receipts for n in receipt["native"]]
            if not receipts and isinstance(document.get("native"),list):
                native.extend(document["native"])
            for row in native:
                if row.get("original_neuron_runtime") is True:
                    typed[row["case"],row["sequence"],row["checkpoint_after"]] = row
        except (ValueError,KeyError,TypeError) as error:
            errors.append({"path":name,"reason":str(error)})
    for relative in files:
        path = directory / relative
        if relative.endswith(".zip"):
            try:
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        if name.endswith(("/state.json","/pending.json")):
                            try:
                                inspect(archive.read(name),relative+":"+name)
                            except (OSError,zipfile.BadZipFile) as error:
                                errors.append({"path":relative+":"+name,"reason":str(error)})
            except (OSError,zipfile.BadZipFile) as error:
                errors.append({"path":relative,"reason":str(error)})
        elif relative.endswith(("/state.json","/pending.json")):
            inspect(path.read_bytes(),relative)
    return {"committed_forecasts_in_readable_state_receipts_lower_bound":len(forecasts),
            "returned_native_typed_requests_lower_bound":len(typed),
            "returned_native_typed_ticks_lower_bound":len(typed),
            "recorded_native_typed_ipc_ns_lower_bound":sum(r["subprocess_roundtrip_ns"] for r in typed.values()),
            "recorded_native_journal_tick_write_bytes_lower_bound":sum(r["journal_bytes_written"] for r in typed.values()),
            "recorded_committed_packet_bytes_lower_bound":sum(r["packet_bytes"] for r in forecasts.values()),
            "duplicate_state_copies_deduplicated_within_attempt":True,
            "incomplete_or_unreadable_fragments":errors,
            "total_native_calls":None,"total_native_ticks":None,"total_cpu_seconds":None,
            "reason_totals_unknown":"Unreturned operations and sparse-feature calls need not be present in durable owner receipts; incomplete ZIP fragments remain preserved. These observed minima are not complete attempt counters."}


def scoring_recovery_review(check, root, repo, frozen, second):
    """Independently bind reused worker outputs and the frozen scoring-only slice."""
    path=root/"runtime_recovery_v2/SCORING_RECOVERY_seed_2017.json"
    receipt=read_json(path)
    started_path=root/"runtime_recovery_v2/SCORING_STARTED_seed_2017.json"
    started=read_json(started_path)
    directory=root/"runtime_confirmation/seed_2017"
    attempt=next(a for a in second["attempts"] if a["seed"]==2017 and a["phase"]=="confirm")
    original_hashes={name:value["sha256"] for name,value in attempt["files"].items()}
    check.check(receipt["seed"]==2017 and receipt["passed"] and receipt["original_inputs_unchanged"],
                "completed-worker scoring receipt passed")
    check.check(receipt["inputs_sha256"]==started["inputs_sha256"]==original_hashes,
                "scoring inputs equal independently preserved pre-recovery worker inventory")
    for name,expected in original_hashes.items():
        check.check(file_sha(directory/name)==expected,"scoring original input byte exact:"+name)
    for value,label in ((receipt,"completed"),(started,"started")):
        check.check(value["reused_in_completed_cohort"] is True and value["reexecuted_policy"] is False,
                    "scoring reuse flags:"+label)
        check.check(value["original_outer_wall_ns"] is None and value["original_outer_cpu_ns"] is None,
                    "scoring unknown original parent cost:"+label)
    check.check(receipt["original_outer_exit_code"] is None and
                receipt["count_completed_worker_native_cost_once_in_formal_cohort"] is True,
                "scoring original exit unknown and reused worker charged once")
    source_relative="experiments/analytic_event_neuron/round4/runtime_study.py"
    source=repo/source_relative
    check.check(started["frozen_source"]==source_relative and
                started["frozen_source_sha256"]==receipt["frozen_source_sha256"]==
                frozen["sources_sha256"][source_relative]==file_sha(source),"frozen scoring source binding")
    parsed=ast.parse(source.read_text())
    function=next(node for node in parsed.body if isinstance(node,ast.FunctionDef) and node.name=="confirm_seed")
    first=next(i for i,node in enumerate(function.body) if isinstance(node,ast.With) and "PUBLIC_ROWS.json.gz" in ast.unparse(node))
    last=next(i for i,node in enumerate(function.body) if isinstance(node,ast.Assign) and
              any(isinstance(target,ast.Name) and target.id=="summary" for target in node.targets))
    nodes=ast.Module(body=function.body[first:last+1],type_ignores=[])
    ast_sha=hashlib.sha256(ast.dump(nodes,include_attributes=False).encode()).hexdigest()
    check.check(started["scoring_ast_sha256"]==receipt["scoring_ast_sha256"]==ast_sha,"exact original scoring AST binding")
    forbidden={"dataset","evaluate_public","worker","Native","subprocess","fit","prepare_seed"}
    called={node.func.id for node in ast.walk(nodes) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)}
    check.check(not forbidden.intersection(called),"scoring slice contains no dataset generation fitting or policy/native call")
    with gzip.open(directory/"PUBLIC_ROWS.json.gz","rt") as stream:
        public_rows=json.load(stream)
    with gzip.open(directory/"ROWS.json.gz","rt") as stream:
        scored_rows=json.load(stream)
    lookup={(row["case"],row["arm"]):row for row in public_rows}
    check.check(len(public_rows)==len(lookup)==len(scored_rows)==2048,"saved worker complete unique case-arm inventory")
    for row in scored_rows:
        identity=(row["case"],row["arm"])
        stripped={key:value for key,value in row.items() if key not in ("target","squared_error","utility","score_started_ns")}
        check.check(identity in lookup and stripped==lookup[identity],"recovered scored row preserves every original policy field:"+str(identity))
        check.check(row["score_started_ns"]>row["final_readback_ns"],"actual recovered score clock follows original readback:"+str(identity))
    summary=read_json(directory/"SUMMARY.json")
    worker=read_json(directory/"WORKER.json")
    check.check(file_sha(directory/"ROWS.json.gz")==receipt["scored_rows_sha256"]==summary["rows_sha256"],"recovered scored rows binding")
    check.check(file_sha(directory/"SUMMARY.json")==receipt["summary_sha256"],"recovered summary binding")
    check.check(summary["wall_ns"] is None and summary["cpu_ns"] is None and
                summary["outer_confirmation_invocation_interrupted"] and summary["outer_confirmation_unknown_costs_must_not_be_zero"],
                "recovered summary unknown interrupted parent times remain null")
    check.check(summary["worker"]==worker and receipt["original_worker_costs"]==
                {key:worker[key] for key in ("wall_ns","cpu_ns","native")},"reused worker costs remain original")
    check.check(summary["reused_in_completed_cohort"] is True and summary["reexecuted_policy"] is False,
                "recovered summary reuse represented")
    cost=receipt["scoring_recovery"]
    check.check(summary["scoring_recovery"]==cost and cost["native_requests"]==cost["native_ticks"]==0 and
                cost["wall_ns"]>=0 and cost["cpu_ns"]>=0,"new scoring costs separately measured without native calls")
    return {"path":str(path.relative_to(root)),"sha256":file_sha(path),"receipt":receipt,
            "started_path":str(started_path.relative_to(root)),"started_sha256":file_sha(started_path),
            "independently_compared_original_policy_rows":len(scored_rows),"policy_fields_exact":True,
            "native_worker_cost_counting":"Already counted once in the completed formal seed 2017 cohort. Do not add this preserved-worker receipt to discarded partial work.",
            "original_parent_cost_unknown":True,"frozen_scoring_ast_sha256":ast_sha}


def interrupted_accounting(check, root, repo, frozen):
    main_path=root/"RUNTIME_INTERRUPTION.json"
    second_path=root/"RUNTIME_SECOND_INTERRUPTION.json"
    if not main_path.exists():
        return {"attempts":[],"additional_work":False},None,None
    main,second=read_json(main_path),read_json(second_path)
    incident_paths=sorted((root/"interrupted_attempts").glob("*/INCIDENT.json"))
    check.check(len(incident_paths)==2,"two preserved operational interruption incidents")
    for source_path,value in ((main_path,main),(second_path,second)):
        check.check(sum(read_json(path)==value for path in incident_paths)==1,
                    "main interruption matches exactly one preserved incident:"+source_path.name)
    check.check(file_sha(root/"RUNTIME_INTERRUPTION_02.json")==file_sha(second_path),"second incident aliases byte identical")
    incident_receipts,attempts=[],[]
    labels=set()
    for path in incident_paths:
        incident=read_json(path)
        frozen_sha=incident.get("frozen_sha256",incident.get("freeze_sha256"))
        check.check(frozen_sha==file_sha(root/"FREEZE.json"),"interruption frozen identity:"+str(path))
        incident_receipts.append({"path":str(path.relative_to(root)),"sha256":file_sha(path)})
        for evidence in incident["termination_evidence"]:
            relative=evidence if isinstance(evidence,str) else evidence["path"]
            check.check((root/relative).is_file(),"termination snapshot retained:"+relative)
            if isinstance(evidence,dict):
                check.check(file_sha(root/relative)==evidence["sha256"],"termination snapshot binding:"+relative)
        for attempt in incident["attempts"]:
            label=attempt["original_label"]
            check.check(label not in labels,"distinct interrupted invocation:"+label)
            labels.add(label)
            start_path,log_path=root/"execution"/(label+"_STARTED.json"),root/"execution"/(label+".log")
            check.check(file_sha(start_path)==attempt["started_receipt_sha256"],"interrupted STARTED preserved:"+label)
            check.check(file_sha(log_path)==attempt["log_sha256"],"interrupted log preserved:"+label)
            check.check(not (root/"execution"/(label+"_COMPLETED.json")).exists(),"interrupted invocation has no fabricated completion:"+label)
            directory=root/attempt["retained_directory"]
            for relative,expected in attempt["files"].items():
                saved=directory/relative
                check.check(file_sha(saved)==expected["sha256"] and saved.stat().st_size==expected["bytes"],
                            "preserved interrupted bytes:"+label+":"+relative)
            start=datetime.fromisoformat(attempt["started_utc"])
            last=datetime.fromisoformat(attempt["last_retained_write_utc"])
            stopped=datetime.fromisoformat(incident["recorded_utc"])
            lower,upper=attempt["observed_lifetime_lower_bound_seconds"],attempt["detected_stopped_lifetime_upper_bound_seconds"]
            check.close(lower,(last-start).total_seconds(),"interruption lower lifetime:"+label,atol=2e-5,rtol=0)
            check.close(upper,(stopped-start).total_seconds(),"interruption upper lifetime:"+label,atol=2e-5,rtol=0)
            check.check(0<=lower<=upper and attempt["total_cpu_seconds"] is None and attempt["exit_code"] is None,
                        "interruption unknown is not zero:"+label)
            identity={}
            if attempt["phase"]=="confirm":
                for name in ("DATA.npz","PUBLIC.npz"):
                    old_path=directory/name
                    new_path=root/"runtime_confirmation"/f"seed_{attempt['seed']}"/name
                    with np.load(old_path,allow_pickle=False) as old,np.load(new_path,allow_pickle=False) as new:
                        same=set(old.files)==set(new.files)
                        check.check(same,"recovery original cohort keys:"+label+name)
                        fields={}
                        for key in sorted(set(old.files)&set(new.files)):
                            a,b=old[key],new[key]
                            equal=np.array_equal(a,b,equal_nan=True) if a.dtype.kind in "fc" else np.array_equal(a,b)
                            fields[key]=bool(a.dtype==b.dtype and a.shape==b.shape and equal)
                            check.check(fields[key],"recovery original cohort exact array:"+label+name+key)
                    identity[name]={"preserved_sha256":file_sha(old_path),"completed_sha256":file_sha(new_path),
                                    "same_arrays_dtype_shape_and_keys":same and all(fields.values()),
                                    "bytes_identical":file_sha(old_path)==file_sha(new_path)}
            reused=bool(attempt.get("reused_in_completed_cohort",False))
            overlapping=bool(attempt.get("overlapping_parent_scope",False))
            additional=bool(attempt.get("additional_interrupted_duplicate_work",not reused and not overlapping))
            if reused:
                check.check(attempt["seed"]==2017 and attempt["phase"]=="confirm" and not additional and
                            attempt["reexecuted_policy"] is False,"only complete saved 2017 worker reused")
                worker=read_json(directory/"WORKER.json")
                check.check(worker["native"]==attempt["known_completed_worker_native"] and
                            worker["wall_ns"]==attempt["known_completed_worker_wall_ns"] and
                            worker["cpu_ns"]==attempt["known_completed_worker_cpu_ns"],"reused completed worker counters exact")
                observed={"known_completed_worker_native":worker["native"],"known_completed_worker_wall_ns":worker["wall_ns"],
                          "known_completed_worker_cpu_ns":worker["cpu_ns"],"already_counted_in_formal_cohort":True,
                          "additional_native_cost_from_preserving_this_worker":0,
                          "unknown_original_parent_overhead_cpu_seconds":None}
            elif overlapping:
                check.check(not additional and attempt.get("do_not_add_parent_scope_to_child_scopes") is True,
                            "interrupted orchestration parent not added to child scopes")
                observed={"nested_parent_scope":True,"add_to_child_costs":False,
                          "total_native_calls":None,"total_native_ticks":None,"total_cpu_seconds":None}
            else:
                observed=partial_work_lower_bounds(directory,attempt["files"])
                observed["additional_discarded_partial_work"]=True
            retained={key:attempt[key] for key in ("original_label","phase","seed","retained_directory",
                "started_receipt_sha256","log_sha256","started_utc","last_retained_write_utc",
                "observed_lifetime_lower_bound_seconds","detected_stopped_lifetime_upper_bound_seconds","exit_code","total_cpu_seconds")}
            retained.update(retained_files=len(attempt["files"]),retained_file_bytes=sum(v["bytes"] for v in attempt["files"].values()),
                full_attempt_wall_seconds=None,completed_recovery_dataset_identity=identity,observed_work_lower_bounds=observed,
                reused_in_completed_cohort=reused,reexecuted_policy=bool(attempt.get("reexecuted_policy",attempt["phase"]=="confirm")),
                additional_interrupted_duplicate_work=additional,overlapping_parent_scope=overlapping,
                native_cost_counting=("Overlapping orchestration parent scope; do not add to child costs; full parent cost remains unknown." if overlapping else
                                     attempt.get("native_cost_counting","Additional discarded partial work; unknown totals remain null.")),
                exhaustively_replayed=False,reused_completed_worker_native_calls_replayed_in_formal_audit=reused,
                original_parent_overhead_exhaustively_accounted=False,additional_registered_samples=0,
                completed_worker_rows_reused_as_registered_cohort=reused,counted_in_registered_sample_size=reused)
            attempts.append(retained)
    detached_path=root/"RUNTIME_DETACHED_LAUNCH_FAILURE.json"
    detached=None
    if detached_path.exists():
        value=read_json(detached_path)
        check.check(value["child_cpu_seconds"] is None and value["exit_code"] is None,"detached failed launch unknown cost not zero")
        detached={"path":str(detached_path.relative_to(root)),"sha256":file_sha(detached_path),"receipt":value,
                  "native_call_total":None,"additional_operational_attempt":True}
    check.check(not (root/"runtime_recovery/COMPLETED.json").exists(),"interrupted v1 orchestration remains incomplete")
    recovery_path=root/"runtime_recovery_v2/COMPLETED.json"
    schedule_path=root/"runtime_recovery_v2/SCHEDULE.json"
    recovery,schedule=read_json(recovery_path),read_json(schedule_path)
    check.check(recovery["passed"] and not recovery["failures"] and
                recovery["runtime_results_sha256"]==file_sha(root/"RUNTIME_RESULTS.json"),"complete serial recovery result binding")
    check.check(all(status=="complete" for state in recovery["state"].values() for status in state.values()),"all serial recovery phases complete")
    check.check(file_sha(schedule_path)==recovery["schedule_sha256"] and schedule["freeze_sha256"]==file_sha(root/"FREEZE.json"),"serial recovery schedule binding")
    check.check(schedule["maximum_simultaneous_heavy_phases"]==1 and schedule["only_full_policy_reexecution_seed"]==1619 and
                schedule["successful_confirmations_1213_1427_1823_reexecuted"] is False and
                schedule["complete_2017_worker_reexecuted"] is False,"serial schedule preserved completed policies")
    check.check(recovery["protected_files_unchanged"] and
                recovery["protected_files_sha256"]==schedule["protected_files_sha256"],"protected completed outputs inventory binding")
    for relative,expected in recovery["protected_files_sha256"].items():
        check.check(file_sha(root/relative)==expected,"protected completed science or old interrupted receipt:"+relative)
    check.check(recovery["previous_completed_wrappers"]==schedule["previous_completed_wrappers"],"previous completed wrapper inventory binding")
    check.check(set(recovery["completed_wrappers"])=={item["label"] for item in schedule["plan"]},"every serial planned wrapper complete exactly once")
    for label,item in (recovery["previous_completed_wrappers"]|recovery["completed_wrappers"]).items():
        actual=read_json(root/item["path"])
        check.check(file_sha(root/item["path"])==item["sha256"] and actual["returncode"]==0,"complete recovery wrapper binding:"+label)
    check.check(recovery["previous_completed_wrappers"]["runtime_confirm_1213"]["sha256"]==
                main["successful_confirmation_1213_completed_receipt_sha256"]==
                file_sha(root/"execution/runtime_confirm_1213_COMPLETED.json"),"successful original 1213 confirmation receipt binding")
    prior_finish=datetime.fromisoformat(schedule["created_utc"])
    for phase in schedule["plan"]:
        item=recovery["completed_wrappers"][phase["label"]]
        value=read_json(root/item["path"])
        current_start,current_finish=map(datetime.fromisoformat,(value["started_utc"],value["finished_utc"]))
        check.check(prior_finish<=current_start<=current_finish,"serial recovered wrappers do not overlap:"+phase["label"])
        prior_finish=current_finish
    check.check(set(recovery["dataset_identity"])=={"1427","1619","1823","2017"},"all four original interrupted cohorts independently bound")
    for item in recovery["dataset_identity"].values():
        actual=read_json(root/item["path"])
        check.check(file_sha(root/item["path"])==item["sha256"] and actual["passed"] and actual["no_replacement_cohort"],
                    "recovery identity receipt:"+item["path"])
    incident_bindings={str(path.relative_to(root)):file_sha(path) for path in (main_path,second_path)}
    check.check(recovery["interruption_receipts"]==schedule["interruption_receipts"]==incident_bindings,
                "serial recovery binds both preserved incidents")
    check.check(recovery["reused_complete_2017_worker_counted_once_in_formal_cohort"] is True and
                recovery["discarded_partial_attempts_are_additional_work_not_new_independent_samples"] is True and
                recovery["original_interrupted_parent_total_wall_ns"] is None and
                recovery["original_interrupted_parent_total_cpu_ns"] is None,"recovery explicit nonduplicate and unknown cost accounting")
    score=scoring_recovery_review(check,root,repo,frozen,second)
    check.check(recovery["scoring_recovery_receipt"]=={key:score[key] for key in ("path","sha256")},"serial recovery scoring-only receipt binding")
    main_receipts=[{"path":str(path.relative_to(root)),"sha256":file_sha(path)} for path in (main_path,second_path)]
    summaries={"main_receipt_path":str(main_path.relative_to(root)),"main_receipt_sha256":file_sha(main_path),
               "main_receipts":main_receipts,"incident_receipts":incident_receipts,"attempts":attempts,"detached_launch_failure":detached,
               "additional_work":True,"discarded_partial_attempt_count":sum(a["additional_interrupted_duplicate_work"] for a in attempts),
               "reused_completed_worker_attempt_count":sum(a["reused_in_completed_cohort"] for a in attempts),
               "overlapping_parent_attempt_count":sum(a["overlapping_parent_scope"] for a in attempts),
               "complete_attempted_native_call_total":None,"complete_attempted_cpu_seconds":None,
               "lifetime_bounds_require_consistent_wall_clock":True,"overlapping_lifetime_bounds_must_not_be_added_as_elapsed":True,
               "unreturned_and_discarded_partial_attempts_not_exhaustively_replayed":True,
               "reused_2017_worker_counted_once_in_formal_cohort":True,"additional_registered_samples":0}
    recovery_summary={"path":str(recovery_path.relative_to(root)),"sha256":file_sha(recovery_path),"receipt":recovery,
                      "schedule_path":str(schedule_path.relative_to(root)),"schedule_sha256":file_sha(schedule_path),
                      "schedule":schedule,"old_and_new_cohort_arrays_independently_compared":True}
    return summaries,recovery_summary,score


def archive_member(check, archive, manifest, name):
    raw = archive.read(name)
    check.check(manifest[name] == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
                "archive member:" + name)
    return raw


def reconstruct_owner(check, archive, manifest, prefix, row):
    """Recreate every normal-success Owner.step write from original receipts."""
    state_raw = archive_member(check, archive, manifest, prefix + "state.json")
    witness_raw = archive_member(check, archive, manifest, prefix + "witness.json")
    state_envelope, witness_envelope = json.loads(state_raw), json.loads(witness_raw)
    final = state_envelope["document"]
    receipts = [stage["runtime"] for stage in row["stages"]]
    check.check(final["receipts"] == receipts, "archive receipts:" + prefix)
    check.check(document_bytes(final) == state_raw, "state original canonical bytes:" + prefix)
    check.check(document_bytes(witness_envelope["document"]) == witness_raw,
                "witness original canonical bytes:" + prefix)
    totals = defaultdict(int)
    witness = {"subject": final["subject"], "records": []}
    for sequence, receipt in enumerate(receipts, 1):
        packet = base64.b64decode(receipt["packet_base64"], validate=True)
        packet_raw = archive_member(check, archive, manifest, prefix + f"packet-{sequence}.bin")
        check.check(packet == packet_raw and len(packet) == receipt["packet_bytes"],
                    "packet original bytes:" + prefix + str(sequence))
        totals["packet_serialized_write_bytes"] += len(packet)
        totals["packet_write_operations"] += 1
        for committed in range(len(receipt["native"]) + 1):
            pending = {"request_sha256": receipt["request_sha256"],
                       "packet_sha256": hashlib.sha256(packet).hexdigest(),
                       "native": receipt["native"][:committed]}
            totals["adapter_pending_serialized_write_bytes"] += len(document_bytes(pending))
            totals["adapter_pending_write_operations"] += 1
        state = {"schema": final["schema"], "subject": final["subject"],
                 "sequence": sequence, "checkpoint": receipt["checkpoint_after"],
                 "native_checkpoints": [native["checkpoint_after"] for native in receipt["native"]],
                 "decoder": receipt["decoder"], "receipts": receipts[:sequence]}
        witness["records"].append({"sequence": sequence, "before": receipt["checkpoint_before"],
                                   "after": receipt["checkpoint_after"], "state_sha256": object_sha(state)})
        totals["adapter_state_serialized_write_bytes"] += len(document_bytes(state))
        totals["adapter_witness_serialized_write_bytes"] += len(document_bytes(witness))
        totals["adapter_state_write_operations"] += 1
        totals["adapter_witness_write_operations"] += 1
        totals["native_journal_tick_receipt_write_bytes"] += sum(n["journal_bytes_written"] for n in receipt["native"])
    state_matches = document_bytes(state) == state_raw
    witness_matches = document_bytes(witness) == witness_raw
    check.check(state_matches, "reconstructed final state byte exact:" + prefix)
    check.check(witness_matches, "reconstructed final witness byte exact:" + prefix)
    if not (state_matches and witness_matches):
        raise ValueError("Cumulative adapter writes cannot be used: final byte reconstruction differs at " + prefix)
    check.check(prefix + "pending.json" not in manifest, "successful owner has no pending:" + prefix)
    totals["owners_reconstructed"] = 1
    totals["owners_final_state_byte_exact"] = int(state_matches)
    totals["owners_final_witness_byte_exact"] = int(witness_matches)
    totals["adapter_final_state_retained_bytes"] = len(state_raw)
    totals["adapter_final_witness_retained_bytes"] = len(witness_raw)
    for component, native in enumerate(receipts[-1]["native"]):
        journal = archive_member(check, archive, manifest, prefix + f"native-{component}/state.journal")
        anchor = archive_member(check, archive, manifest, prefix + f"native-{component}/anchor.witness")
        check.check(len(journal) == native["journal_bytes"], "native journal final size:" + prefix)
        check.check(len(anchor) == native["witness_bytes"], "native witness final size:" + prefix)
        totals["native_journal_retained_file_bytes"] += len(journal)
        totals["native_witness_retained_file_bytes"] += len(anchor)
    totals["native_journal_extra_retained_bytes_outside_tick_receipts"] = (
        totals["native_journal_retained_file_bytes"] - totals["native_journal_tick_receipt_write_bytes"])
    totals["adapter_cumulative_serialized_write_bytes"] = sum(totals[k] for k in (
        "adapter_pending_serialized_write_bytes", "adapter_state_serialized_write_bytes",
        "adapter_witness_serialized_write_bytes"))
    return dict(totals)


def law_cdf(law, value):
    return float(np.dot(law["weights"], ndtr((value - np.asarray(law["means"])) / np.sqrt(law["variances"]))))


def event_probabilities(law, lower, upper):
    means, scales = np.asarray(law["means"]), np.sqrt(law["variances"])
    low, high = (lower - means) / scales, (upper - means) / scales
    middle = np.where(low >= 0, ndtr(-low) - ndtr(-high), ndtr(high) - ndtr(low))
    return np.asarray([np.dot(law["weights"], ndtr(low)), np.dot(law["weights"], middle),
                       np.dot(law["weights"], ndtr(-high))])


def prepared_write_accounting(check, root, frozen, seeds, registration):
    totals = {split: defaultdict(int) for split in ("train", "development")}
    scopes = []
    for seed in seeds:
        output = root / "runtime_prepared" / f"seed_{seed}"
        receipt = read_json(output / "TRAINING_RECEIPT.json")
        rows_path = output / "TRAINING_ROWS.json.gz"
        check.check(file_sha(rows_path) == receipt["training_rows_sha256"] ==
                    frozen["artifacts_sha256"][str(rows_path.relative_to(root))],
                    "prepared accounting rows bound:" + str(seed))
        with gzip.open(rows_path, "rt") as stream:
            collections = json.load(stream)
        requests = ticks = ipc = 0
        for split, rows in collections.items():
            expected_count = registration["train_rows" if split == "train" else "development_rows"]
            check.check(len(rows) == expected_count, "prepared accounting row count:" + str(seed) + split)
            archived = receipt["training_archive" if split == "train" else "development_archive"]
            zip_path, manifest_path = output / (split + ".zip"), output / (split + ".manifest.json")
            check.check(file_sha(zip_path) == archived["sha256"] ==
                        frozen["artifacts_sha256"][str(zip_path.relative_to(root))],
                        "prepared accounting archive bound:" + str(seed) + split)
            check.check(file_sha(manifest_path) == archived["manifest_sha256"] ==
                        frozen["artifacts_sha256"][str(manifest_path.relative_to(root))],
                        "prepared accounting manifest bound:" + str(seed) + split)
            manifest = read_json(manifest_path)["files"]
            with zipfile.ZipFile(zip_path) as archive:
                check.check(set(archive.namelist()) == set(manifest), "prepared exact archive inventory:" + str(seed) + split)
                owners = set()
                for i, row in enumerate(rows):
                    prefix = f"case-{i}/owners/{row['stages'][0]['runtime']['subject']}/"
                    owners.add(prefix + "state.json")
                    cost = reconstruct_owner(check, archive, manifest, prefix, row)
                    for key, value in cost.items(): totals[split][key] += value
                    for stage in row["stages"]:
                        native = [*stage["runtime"]["native"],
                                  *(x for feature in stage["native"].values() for x in feature)]
                        stage_requests = len(native)
                        stage_ticks = sum(x.get("original_sparse_tick_calls", int(x.get("original_neuron_runtime", False))) for x in native)
                        stage_ipc = sum(x["subprocess_roundtrip_ns"] for x in native)
                        requests += stage_requests; ticks += stage_ticks; ipc += stage_ipc
                        totals[split]["native_requests"] += stage_requests
                        totals[split]["native_ticks"] += stage_ticks
                        totals[split]["native_roundtrip_ns"] += stage_ipc
                actual = {name for name in manifest if name.endswith("/state.json") and "/owners/" in name}
                check.check(actual == owners, "all prepared owners reconstructed:" + str(seed) + split)
            scopes.append({"seed": seed, "split": split, "owners": len(rows),
                           "archive_bytes": zip_path.stat().st_size,
                           "archive_uncompressed_member_bytes": sum(v["bytes"] for v in manifest.values())})
        check.check([requests,ticks,ipc] == [receipt["native"][k] for k in ("requests","ticks","roundtrip_ns")],
                    "prepared all original native counters:" + str(seed))
    return {"per_split": {key: dict(value) for key,value in totals.items()}, "scopes": scopes,
            "shared_training_and_development_execution_counted_once": True,
            "not_multiplied_by_number_of_learned_heads": True}


def float_boundary_diagnostic(repo):
    """Direct frozen-code probes, independent of all confirmation samples."""
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(repo))
    from experiments.analytic_event_neuron.round4.runtime_codec import Encoder, Decoder
    from experiments.analytic_event_neuron.round4.runtime_law import make_law, validate_law
    fixtures = []
    for name, weights in (
        ("small_last", [1.0, math.exp(-40)]),
        ("small_first", [math.exp(-40), 1.0]),
        ("last_near_unit_ulp", [1-math.exp(-36), math.exp(-36)]),
    ):
        law = make_law(weights, [0.0,1.0], [.2,.3])
        validate_law(law)
        fixture = {"name":name,"source_law":law,"fp64_weight_sum":sum(law["weights"]),
                   "source_law_validation":"accepted","modes":{}}
        for mode in ("event","direct","float"):
            try:
                packet = Encoder(mode).encode(law,1,1.0)
                decoded = Decoder(mode).apply(packet)
                fixture["modes"][mode] = {"accepted":True,"decoded_weights":decoded["weights"],"packet_bytes":len(packet)}
            except ValueError as error:
                fixture["modes"][mode] = {"accepted":False,"exception":type(error).__name__,"message":str(error)}
        fixtures.append(fixture)
    return {"postfreeze_boundary_diagnostic":True,"fixtures":fixtures,
            "source_or_gate_changed":False,"confirmation_generated_or_filtered":False,
            "limitation":"FP64 mode stores K-1 weights and reconstructs the final weight by subtraction. It is not lossless for all positive mixtures; near-unit first weights can round the last weight to zero. The admissible domain depends on component order. Count modes impose their separately declared positive Q24 weight projection.",
            "scope":"This diagnosis limits domain/generalization claims. It does not change the registered common-eligible-cohort gate or justify dropping a confirmation row."}


def metrics(rows):
    result = {key: float(np.mean([r[key] for r in rows])) for key in (
        "utility", "squared_error", "cost", "wall_ns", "cpu_ns", "packet_bytes", "native_requests",
        "native_ticks", "native_roundtrip_ns")}
    probabilities, raw, labels, covered, logs, parameter_errors = [], [], [], [], [], []
    zeros, bad_totals, max_release = 0, 0, 0.0
    for row in rows:
        first = row["stages"][0]["runtime"]
        law = first["law"]
        probabilities.append(law["probabilities"])
        raw.append(np.asarray(law["raw_probabilities_q24"]) / Q)
        observed = row["target"] - first["public"]["initial"]
        label = 0 if observed <= law["lower"] else 2 if observed > law["upper"] else 1
        labels.append(label)
        logs.append(law["physical_log_probabilities"][label])
        rank = law_cdf(law["conditional_law"], observed)
        covered.append(.025 <= rank <= .975)
        source = event_probabilities(first["source_law"], law["lower"], law["upper"])
        parameter_errors.append(float(np.max(np.abs(source - law["physical_probabilities"]))))
        for stage in row["stages"]:
            release = stage["runtime"]["law"]
            zeros += min(release["probabilities_q24"]) < 1
            bad_totals += sum(release["probabilities_q24"]) != Q
            max_release = max(max_release, max(abs(x-y) for x,y in zip(
                release["native_mixture_probabilities"], release["probabilities"])))
    probabilities, raw, labels = np.asarray(probabilities), np.asarray(raw), np.asarray(labels)
    calibration = []
    for category in range(3):
        assigned = np.minimum(np.floor(probabilities[:,category] * 10).astype(int), 9)
        error = 0.0
        for group in range(10):
            mask = assigned == group
            if mask.any():
                error += abs(float(np.sum(probabilities[mask,category]) - np.sum(labels[mask] == category))) / len(rows)
        calibration.append(error)
    chosen = probabilities[np.arange(len(rows)), labels]
    raw_chosen = raw[np.arange(len(rows)), labels]
    result.update(executions=len(rows), waits=sum("wait" in r["actions"] for r in rows),
        repairs=sum("repair" in r["actions"] for r in rows), initial_classwise_ece=float(np.mean(calibration)),
        initial_exact_mixture_95_coverage=float(np.mean(covered)), initial_released_event_nll=float(-np.log(chosen).mean()),
        initial_physical_event_nll=float(-np.mean(logs)),
        initial_raw_q24_nll=None if np.any(raw_chosen == 0) else float(-np.log(raw_chosen).mean()),
        raw_q24_any_zero_rows=int(np.sum(np.any(raw == 0, axis=1))), raw_q24_true_event_zero_rows=int(np.sum(raw_chosen == 0)),
        released_zero_rows=int(np.sum(np.any(probabilities == 0, axis=1))),
        released_zero_forecasts=int(zeros), released_bad_total_forecasts=int(bad_totals),
        max_native_to_released_coordinate_error=max_release, max_source_to_effective_category_error=max(parameter_errors),
        packet_bytes_total=sum(r["packet_bytes"] for r in rows),
        native_journal_bytes_written=sum(n["journal_bytes_written"] for r in rows for s in r["stages"] for n in s["runtime"]["native"]),
        native_witness_bytes_final_per_component=sum(n["witness_bytes"] for r in rows for n in r["stages"][-1]["runtime"]["native"]))
    return result


def review(run_dir, repo):
    started = time.perf_counter_ns()
    root, repo = Path(run_dir), Path(repo)
    check = Review()
    frozen = read_json(root / "FREEZE.json")
    result = read_json(root / "RUNTIME_RESULTS.json")
    protocol = read_json(repo / "experiments/analytic_event_neuron/round4/PROTOCOL.json")
    registration = protocol["runtime_feedback"]
    seeds, arms = registration["seeds"], registration["arms"]
    n, reps = registration["confirmation_rows"], registration["bootstrap_replicates"]
    check.check(file_sha(repo / "experiments/analytic_event_neuron/round4/PROTOCOL.json") == frozen["protocol_sha256"], "frozen protocol")
    for relative, expected in frozen["sources_sha256"].items():
        check.check(file_sha(repo / relative) == expected, "frozen source:" + relative)
    check.check(result["source_commit"] == frozen["source_commit"], "reported source commit")
    check.check(result["seeds"] == seeds, "reported seeds")
    schedule_path = root / "EXECUTION_SCHEDULE.json"
    schedule = read_json(schedule_path)
    check.check(schedule["freeze_sha256"] == file_sha(root/"FREEZE.json"), "operational schedule frozen identity")
    scheduled_at = datetime.fromisoformat(schedule["created_utc"])
    for seed in schedule["subsequent_concurrent_confirmation_seeds"]:
        start = read_json(root/"execution"/f"runtime_confirm_{seed}_STARTED.json")
        check.check(datetime.fromisoformat(start["started_utc"]) >= scheduled_at,
                    "schedule retained before additional concurrent launch:"+str(seed))
    prefreeze_path = root / "validation/PREFREEZE_REVIEW.json"
    check.check(file_sha(prefreeze_path) == frozen["prefreeze_review_sha256"], "frozen prefreeze review binding")
    prefreeze = read_json(prefreeze_path)
    prepared_replay_path = root / "runtime_preparation_review/REVIEW.json"
    check.check(file_sha(prepared_replay_path) == prefreeze["runtime_prepared_replay_receipt"]["sha256"],
                "independent prepared native replay receipt binding")
    prepared_replay = read_json(prepared_replay_path)
    check.check(prepared_replay["passed"] and prepared_replay["seeds"]==seeds, "prepared complete replay passed")
    preparation_replay_summary = {
        "path": str(prepared_replay_path.relative_to(root)), "sha256": file_sha(prepared_replay_path),
        "checks": prepared_replay["checks"], "passed": prepared_replay["passed"],
        "core_source_receipt_scope": prepared_replay["core_source_receipt_scope"],
        "native_requests": sum(s["native_replay"]["requests"] for s in prepared_replay["scopes"]),
        "native_ticks": sum(s["native_replay"]["ticks"] for s in prepared_replay["scopes"]),
        "native_roundtrip_ns": sum(s["native_replay"]["roundtrip_ns"] for s in prepared_replay["scopes"]),
        "original_artifact_members": sum(s["original_artifact_members"] for s in prepared_replay["scopes"]),
        "independent_png_readbacks": sum(s["independent_png_readbacks"] for s in prepared_replay["scopes"]),
        "wall_ns_sum": sum(s["wall_ns"] for s in prepared_replay["scopes"])}
    prepared_costs = prepared_write_accounting(check, root, frozen, seeds, registration)
    all_rows = {arm: [] for arm in arms}
    cost_totals = {arm: defaultdict(int) for arm in arms}
    scopes, hashes = [], {}
    for seed in seeds:
        output = root / "runtime_confirmation" / f"seed_{seed}"
        summary, audit = read_json(output / "SUMMARY.json"), read_json(output / "AUDIT.json")
        qualification = read_json(root / "runtime_qualification" / f"seed_{seed}" / "QUALIFICATION.json")
        check.check(summary["seed"] == audit["seed"] == seed, "scope seed:" + str(seed))
        check.check(summary["independent_trajectories"] == n and summary["executions"] == n * len(arms), "scope count:" + str(seed))
        check.check(audit["passed"] and not audit["development_only"], "formal audit passed:" + str(seed))
        qr = protocol["runtime_qualification"]
        check.check(qualification["passed"] and not qualification["development_only"] and qualification["seed"]==seed,
                    "formal qualification passed:" + str(seed))
        check.check(qualification["histories"]==qr["histories_per_seed"]
                    and qualification["ordinary_forecasts"]==qr["ordinary_forecasts_per_seed"]
                    and qualification["fresh_processes"]==qr["fresh_processes_per_seed"]
                    and qualification["calibration_bridge_forecasts"]==qr["cross_track_calibration_fixtures_per_seed"]
                    and qualification["tails"]==qr["tail_fixture_laws"],"full registered qualification scope:"+str(seed))
        check.check(qualification["cross_owner_atomicity"] is False and qualification["production_promotion"] is False,
                    "qualification authority limitations:"+str(seed))
        fresh = [read_json(root/"runtime_qualification"/f"seed_{seed}"/f"recovery_{mode}_{sequence}.json")
                 for mode in qr["modes"] for sequence in (2,3)]
        fresh_counts = {key:sum(r["native"][key] for r in fresh) for key in ("requests","ticks","roundtrip_ns")}
        check.check(fresh_counts["ticks"]==qualification["fresh_process_native_ticks"],
                    "qualification fresh-process tick accounting:"+str(seed))
        model_relative = f"runtime_prepared/seed_{seed}/MODELS.json"
        check.check(summary["model_file_sha256"] == frozen["artifacts_sha256"][model_relative] == file_sha(root / model_relative),
                    "model binding:" + str(seed))
        for name, key in (("DATA.npz", "data_sha256"), ("ROWS.json.gz", "rows_sha256")):
            hashes[str((output / name).relative_to(root))] = file_sha(output / name)
            check.check(hashes[str((output / name).relative_to(root))] == summary[key], "scope hash:" + name + str(seed))
        with gzip.open(output / "ROWS.json.gz", "rt") as stream:
            rows = json.load(stream)
        with np.load(output / "DATA.npz", allow_pickle=False) as data:
            targets = dict(zip(data["ids"].tolist(), data["target"].tolist()))
        expected_ids = {f"feedback4:confirmation:{seed}:{i}" for i in range(n)}
        check.check(set(targets) == expected_ids, "target identities:" + str(seed))
        archived = summary["worker"]["archive"]
        zip_path, manifest_path = output / archived["path"], output / "execution.manifest.json"
        check.check(file_sha(zip_path) == archived["sha256"] == audit["source_archive_sha256"], "original archive binding:" + str(seed))
        check.check(file_sha(manifest_path) == archived["manifest_sha256"], "archive manifest binding:" + str(seed))
        manifest = read_json(manifest_path)["files"]
        source_requests = source_ticks = source_ipc = 0
        with zipfile.ZipFile(zip_path) as archive:
            check.check(len(archive.namelist()) == len(set(archive.namelist())) == len(manifest) == archived["verified_files"],
                        "unique archive inventory:" + str(seed))
            check.check(set(archive.namelist()) == set(manifest), "archive exact inventory:" + str(seed))
            for info in archive.infolist():
                check.check(info.file_size == manifest[info.filename]["bytes"], "archive stored length:" + info.filename)
            owners = set()
            for arm in arms:
                selected = sorted((r for r in rows if r["arm"] == arm), key=lambda r: r["case"])
                check.check(len(selected) == n and {r["case"] for r in selected} == expected_ids, "paired identities:" + str(seed) + arm)
                all_rows[arm].extend(selected)
                for row in selected:
                    identity, stages = row["case"], row["stages"]
                    check.check(row["target"] == targets[identity], "target matches original:" + identity + arm)
                    squared = (row["delivered"] - targets[identity]) ** 2
                    cost = sum(stage["public"]["wait_cost"] if stage["action"] == "wait" else
                               stage["public"]["repair_cost"] if stage["action"] == "repair" else 0 for stage in stages)
                    check.close([row["squared_error"], row["cost"], row["utility"]], [squared, cost, 1-squared-cost],
                                "actual score:" + identity + arm, atol=0, rtol=0)
                    check.check(row["actions"] == [s["action"] for s in stages] and len(stages) in (1,2)
                                and stages[-1]["action"] in ("stop", "repair")
                                and (len(stages)==1 or stages[0]["action"]=="wait"), "valid action path:" + identity + arm)
                    check.check(stages[-1]["decision_ns"] <= row["final_readback_ns"] < row["score_started_ns"],
                                "public decision before private score:" + identity + arm)
                    native = [x for s in stages for x in [*s["runtime"]["native"], *s["native"]]]
                    requests = len(native)
                    ticks = sum(x.get("original_sparse_tick_calls", int(x.get("original_neuron_runtime", False))) for x in native)
                    ipc = sum(x["subprocess_roundtrip_ns"] for x in native)
                    check.check((requests,ticks,ipc)==(row["native_requests"],row["native_ticks"],row["native_roundtrip_ns"]),
                                "native row counters:" + identity + arm)
                    source_requests += requests; source_ticks += ticks; source_ipc += ipc
                    packet_bytes = sum(len(base64.b64decode(s["runtime"]["packet_base64"])) for s in stages)
                    check.check(packet_bytes == row["packet_bytes"], "row packet total:" + identity + arm)
                    for stage in stages:
                        law = stage["runtime"]["law"]
                        counts = law["probabilities_q24"]
                        check.check(all(type(x) is int and x>=1 for x in counts) and sum(counts)==Q,
                                    "positive exact categorical mass:" + identity + arm)
                        check.close(law["probabilities"], np.asarray(counts)/Q,
                                    "counts equal released probabilities:" + identity + arm, atol=0, rtol=0)
                    case_index = int(identity.rsplit(":",1)[1])
                    prefix = f"case-{case_index}/{arm}/owners/{stages[0]['runtime']['subject']}/"
                    owners.add(prefix+"state.json")
                    owner_cost = reconstruct_owner(check, archive, manifest, prefix, row)
                    for key, value in owner_cost.items(): cost_totals[arm][key] += value
                    for key in ("wall_ns","cpu_ns","native_requests","native_ticks","native_roundtrip_ns"):
                        cost_totals[arm][key+"_sum"] += row[key]
            actual_owners = {name for name in manifest if name.endswith("/state.json") and "/owners/" in name}
            check.check(actual_owners == owners, "all archived owners reconstructed:" + str(seed))
        worker_native = summary["worker"]["native"]
        check.check([source_requests,source_ticks,source_ipc] == [worker_native[k] for k in ("requests","ticks","roundtrip_ns")],
                    "worker all source native counters:" + str(seed))
        check.check([source_requests,source_ticks] == [audit["native_replay"][k] for k in ("requests","ticks")],
                    "formal replay count binding:" + str(seed))
        scopes.append({"seed":seed,"source_native_requests":source_requests,"source_native_ticks":source_ticks,
                       "source_native_roundtrip_ns":source_ipc,
                       "archive_bytes":zip_path.stat().st_size,"archive_uncompressed_member_bytes":sum(v["bytes"] for v in manifest.values()),
                       "archive_members":len(manifest),"worker_wall_ns":summary["worker"]["wall_ns"],
                       "confirmation_parent_wall_ns":summary["wall_ns"],"replay_wall_ns":audit["wall_ns"],
                       "replay_native_requests":audit["native_replay"]["requests"],
                       "replay_native_ticks":audit["native_replay"]["ticks"],
                       "replay_native_roundtrip_ns":audit["native_replay"]["roundtrip_ns"],
                       "replay_archive_bytes":audit["replay_archive"]["bytes"],
                       "replay_checks":audit["checks"],"independent_png_readbacks":audit["independent_png_readbacks"],
                       "qualification_in_process_native":qualification["in_process_native"],
                       "qualification_fresh_process_native":fresh_counts,
                       "qualification_total_native_requests":qualification["in_process_native"]["requests"]+fresh_counts["requests"],
                       "qualification_total_native_ticks":qualification["in_process_native"]["ticks"]+fresh_counts["ticks"],
                       "qualification_archive_bytes":qualification["archive"]["bytes"],
                       "qualification_wall_ns":qualification["wall_ns"],
                       "qualification_all_calls_replayed":False,
                       "qualification_passed":bool(qualification["passed"]),"audit_passed":bool(audit["passed"])})
    independent_metrics = {arm:metrics(rows) for arm,rows in all_rows.items()}
    for arm, values in independent_metrics.items():
        for key, value in values.items():
            expected = result["metrics"][arm][key]
            if value is None or expected is None:
                check.check(value is expected, "metric null:" + arm + key)
            else:
                check.close(value, expected, "reported metric:" + arm + key)
        check.check(cost_totals[arm]["packet_serialized_write_bytes"]==values["packet_bytes_total"], "cost packet binding:"+arm)
        check.check(cost_totals[arm]["native_journal_tick_receipt_write_bytes"]==values["native_journal_bytes_written"], "cost native tick journal binding:"+arm)
        check.check(cost_totals[arm]["native_witness_retained_file_bytes"]==values["native_witness_bytes_final_per_component"], "cost native witness binding:"+arm)
    comparisons = registration["primary_noninferiority"] + registration["secondary"]
    contrasts, mechanisms, paired_costs = {}, {}, {}
    for index,(candidate,baseline) in enumerate(comparisons):
        left,right = all_rows[candidate],all_rows[baseline]
        name = candidate+"_vs_"+baseline
        delta = np.asarray([a["utility"]-b["utility"] for a,b in zip(left,right)]).reshape(len(seeds),n)
        primary = index < len(registration["primary_noninferiority"])
        alpha = registration["family_alpha"]/registration["primary_family_size"] if primary else .05
        estimate = interval(delta,reps,registration["bootstrap_seed"]+index,alpha)
        compare_interval(check,estimate,result["utility_contrasts"][name],"reported utility CI:"+name)
        passes = estimate["interval"][0] > -registration["noninferiority_margin"] and min(estimate["per_seed_mean_difference"]) > -registration["noninferiority_margin"]
        check.check(bool(passes)==result["utility_contrasts"][name]["passes_noninferiority"], "reported NI gate:"+name)
        estimate.update(primary_noninferiority=primary,passes_noninferiority=bool(passes))
        contrasts[name]=estimate
        mechanism={"discrete_action_disagreements":sum(a["actions"]!=b["actions"] for a,b in zip(left,right)),
                   "final_output_disagreements":sum(a["delivered"]!=b["delivered"] for a,b in zip(left,right)),
                   "max_initial_release_probability_difference":max(max(abs(x-y) for x,y in zip(a["stages"][0]["runtime"]["law"]["probabilities"],b["stages"][0]["runtime"]["law"]["probabilities"])) for a,b in zip(left,right)),
                   "max_abs_utility_difference":float(np.max(np.abs(delta))),
                   "mean_error_reduction":float(np.mean([b["squared_error"]-a["squared_error"] for a,b in zip(left,right)])),
                   "mean_paid_cost_increase":float(np.mean([a["cost"]-b["cost"] for a,b in zip(left,right)]))}
        for key,value in mechanism.items(): check.close(value,result["mechanism"][name][key],"reported mechanism:"+name+key)
        mechanisms[name]=mechanism
        if primary:
            paired_costs[name]={}
            for offset,metric in enumerate(("packet_bytes","wall_ns","cpu_ns","native_roundtrip_ns")):
                difference=np.asarray([a[metric]-b[metric] for a,b in zip(left,right)]).reshape(len(seeds),n)
                cost=interval(difference,reps,registration["bootstrap_seed"]+100+10*index+offset,.05)
                compare_interval(check,cost,result["descriptive_paired_cost_contrasts"][name][metric],"reported cost CI:"+name+metric)
                paired_costs[name][metric]=cost
    expected_gates={"event_vs_direct_noninferiority":contrasts["event_vs_direct"]["passes_noninferiority"],
                    "event_vs_float_noninferiority":contrasts["event_vs_float"]["passes_noninferiority"],
                    "event_direct_exact_actions_outputs_utility":all(mechanisms["event_vs_direct"][key]==0 for key in (
                        "discrete_action_disagreements","final_output_disagreements","max_abs_utility_difference","max_initial_release_probability_difference")),
                    "positive_q24_all_scored_outputs":all(v["released_zero_forecasts"]==0 and v["released_bad_total_forecasts"]==0 and v["max_native_to_released_coordinate_error"]<=3/Q for v in independent_metrics.values()),
                    "all_replays_passed":all(s["audit_passed"] for s in scopes),
                    "all_runtime_qualifications_passed":all(s["qualification_passed"] for s in scopes),"production_promotion":False}
    check.check(expected_gates==result["acceptance"],"exact reported runtime gate map")
    check.check(result["independent_trajectories"]==len(seeds)*n and result["completed_control_executions"]==len(seeds)*n*len(arms),"independent unit vs executions")
    quantum_units = {"mixture_weight_q24":0,"component_mean_q12":0,"component_logvariance_q12":0}
    for row in all_rows["event"]:
        previous = None
        for stage in row["stages"]:
            decoder = stage["runtime"]["decoder"]
            current, k = np.asarray(decoder["values"],dtype=np.int64), decoder["components"]
            difference = np.abs(current - (previous if previous is not None else 0))
            quantum_units["mixture_weight_q24"] += int(difference[:k-1].sum())
            quantum_units["component_mean_q12"] += int(difference[k-1:2*k-1].sum())
            quantum_units["component_logvariance_q12"] += int(difference[2*k-1:].sum())
            previous = current
    check.check(quantum_units == result["event_integer_quantum_units"],"registered integer quantum units")
    check.check(result["quantum_units_are_not_physical_spike_operations"] is True,"integer units not executed spike count")
    float_rows = [stage["runtime"] for row in all_rows["float"] for stage in row["stages"]]
    weight_sources = np.asarray([r["source_law"]["weights"] for r in float_rows])
    weight_decoded = np.asarray([r["law"]["conditional_law"]["weights"] for r in float_rows])
    weight_error = np.abs(weight_decoded-weight_sources)
    float_corpus = {"forecasts":len(float_rows),"minimum_source_component_weight":float(weight_sources.min()),
                    "minimum_received_component_weight":float(weight_decoded.min()),
                    "max_absolute_weight_error":float(weight_error.max()),
                    "max_relative_weight_error":float((weight_error/weight_sources).max()),
                    "max_absolute_log_weight_error":float(np.abs(np.log(weight_decoded)-np.log(weight_sources)).max()),
                    "confirmation_rows_discarded":0,
                    "zero_discard_claim_basis":"Exact registered case identity and count checks for every seed and every arm in this review."}
    boundary = float_boundary_diagnostic(repo)
    interrupted,recovery,score_recovery = interrupted_accounting(check,root,repo,frozen)
    wrapper=[]
    for path in sorted((root/"execution").glob("*_COMPLETED.json")):
        value=read_json(path)
        wrapper.append({"path":str(path.relative_to(root)),"sha256":file_sha(path),
                        "label":value["label"],"returncode":value["returncode"],"wall_ns":value["wall_ns"],
                        "command":value["command"],
                        "encloses_recovery_phase_wrappers":any("resume_runtime" in str(part) for part in value["command"]),
                        "children_user_seconds":value["children_user_seconds"],
                        "children_system_seconds":value["children_system_seconds"],
                        "started_utc":value["started_utc"],"finished_utc":value["finished_utc"]})
    uncompleted=[]
    interrupted_labels={x["original_label"] for x in interrupted["attempts"]}
    for path in sorted((root/"execution").glob("*_STARTED.json")):
        label=path.name.removesuffix("_STARTED.json")
        if not (root/"execution"/(label+"_COMPLETED.json")).exists():
            uncompleted.append({"path":str(path.relative_to(root)),"sha256":file_sha(path),"label":label,
                                "known_interrupted":label in interrupted_labels,
                                "current_review_in_progress":label=="runtime_final_independent_review",
                                "exit_code":None,"total_cpu_seconds":None,"completed_wall_ns":None})
    for relative,expected in frozen["sources_sha256"].items():
        check.check(file_sha(repo/relative)==expected,"frozen source after review:"+relative)
    return {"schema":"hepta.round4.independent-final-runtime-review.v1","created_utc":datetime.now(timezone.utc).isoformat(),
            "passed":not check.failures,"checks":check.checks,"failures":check.failures,"maximum_errors":dict(check.maximum_errors),
            "freeze_sha256":file_sha(root/"FREEZE.json"),"results_sha256":file_sha(root/"RUNTIME_RESULTS.json"),
            "reviewer_sha256":file_sha(__file__),"source_commit":frozen["source_commit"],"input_hashes":hashes,
            "independent_trajectories":len(seeds)*n,"control_executions":len(seeds)*n*len(arms),
            "metrics":independent_metrics,"utility_contrasts":contrasts,"mechanism":mechanisms,
            "descriptive_paired_cost_contrasts":paired_costs,"acceptance":expected_gates,
            "event_integer_quantum_units":quantum_units,
            "float_transport_corpus_weight_diagnostics":float_corpus,
            "float_complement_boundary_diagnostic":boundary,
            "prior_preparation_replay_review":preparation_replay_summary,
            "interrupted_attempts":interrupted,"runtime_recovery":recovery,"scoring_only_recovery2017":score_recovery,
            "native_replay_scope":{"completed_cohort_replay":bool(expected_gates["all_replays_passed"] and prepared_replay["passed"]),
                "completed_training_development_and_formal_cohort_calls_only":True,
                "attempted_calls_exhaustively_replayed":False,
                "qualification_fault_recovery_calls_all_replayed":False,
                "interrupted_partial_or_unreturned_calls_all_replayed":False,
                "discarded_partial_attempts_are_additional_work_not_additional_registered_samples":True,
                "reused_completed_2017_worker_charged_once_in_formal_cohort":True,
                "overlapping_parent_scopes_not_added_to_children":True},
            "serialized_write_accounting":{"method":"Independent reconstruction of each successful Owner.step pending/state/witness serialization; all final state and witness bytes checked against original ZIP members before aggregation.",
                "formal_confirmation_per_arm":{arm:dict(v) for arm,v in cost_totals.items()},
                "shared_preparation":prepared_costs,
                "qualification_adapter_cumulative_write_bytes":None,
                "qualification_accounting_scope":"Failure injection, rollback/corruption writes and fresh process tests are timed and counted separately in their original receipts; not included in normal-success reconstruction totals.",
                "native_journal_cumulative_write_bytes":None,"native_witness_cumulative_write_bytes":None,
                "unknown_reason":"Native tick receipts omit initialization; retained native file sizes are verified but this audit does not reconstruct every native filesystem write.",
                "includes_atomic_temporary_file_payload":True,"counts_temporary_rename_as_additional_payload_write":False,
                "filesystem_metadata_or_journaling_write_amplification_bytes":None,"physical_device_bytes":None,"hardware_energy":None,
                "posthoc_descriptive_accounting":True,"new_scientific_gate":False},
            "scopes":scopes,"completed_execution_wrappers":wrapper,
            "started_without_completion_at_review_time":uncompleted,
            "execution_schedule":{"path":str(schedule_path.relative_to(root)),"sha256":file_sha(schedule_path),"receipt":schedule},
            "timing_scope":{"row_wall":"Initial delivery through final delivery readback and receipt persistence; excludes following ZIP compression, verification and cleanup.",
                "row_cpu":"Python worker process_time; excludes native child CPU.",
                "worker_wall":"Includes archive compression, verification and cleanup, native startup and shutdown, and worker output persistence.",
                "phase_wrapper_cpu":"RUSAGE_CHILDREN user+system seconds for the full invoked child process tree as reaped; not a per-arm native CPU measurement.",
                "concurrency":"Mixed concurrency on a shared host: initial execution and first recovery used concurrent phases; the second recovery executes one heavy phase at a time. Original/reused workers retain their original timings. Latency intervals span different contention and are descriptive; no isolated hardware latency claim.",
                "seed2017_original_parent_wall_and_cpu_unknown":True,
                "seed2017_original_worker_counted_once_and_new_scoring_separate":True,
                "nested_times_must_not_be_added":True,"simultaneous_wrappers_must_not_be_summed_as_session_elapsed_time":True},
            "review_native_calls":0,"confirmation_generated_by_review":False,"fitting_or_selection_performed":False,
            "wall_ns":time.perf_counter_ns()-started}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir",required=True)
    parser.add_argument("--repo",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    report=review(args.run_dir,args.repo)
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x") as stream:
        json.dump(report,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed":report["passed"],"checks":report["checks"],"failures":report["failures"],"output":str(output)}))
    raise SystemExit(0 if report["passed"] else 1)

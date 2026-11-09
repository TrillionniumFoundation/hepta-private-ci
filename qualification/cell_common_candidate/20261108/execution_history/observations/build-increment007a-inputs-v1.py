#!/usr/bin/env python3
"""Prepare two terminal 3fc packets and four exact correction observations; no mutation."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile

R=Path("/home/qian-qi/work/hepta-cell-s0-records-20261108-898e")
W=Path("/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e")
C=Path("/home/qian-qi/worktrees/hepta-cell-s0-common-20261108-898e")
OUT=R/"increment007-preparation-v1"
HEAD="02f75555a857b161275ea5c6f7c960dde6cf8b13"
TREE="456903461ff59e9fca71ba1fed2dcc5701d21b78"
INDEX="3a2771028bdcb0778eb4266a02994255d63e7875a1996d2fe6411e800f934664"
REL="qualification/cell_common_candidate/20261108/execution_history"
SOURCE="bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d"
SOURCE_TREE="f7b65a747a1d2f585be38a4665ab2b4f1b07efb6"
CURRENT="c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4"
COMBINED="3fc4725343dccfc9487e937f77e30bc6a5d80dbc"
COMBINED_TREE="89d698ef2fba525a3b03466808337f125306085b"
DEFINITIONS=[["combined-3fc4725-native-history-v1","combined-3fc4725-native-history-v1-import.tar.xz",5439844,"ffafc08752e9f6d9c45258389858002b7afaf7239363e7bc6372c54dca162c4e",309,"Separate combined 3fc Linux source: strict preparation, 1348 app-server and 781 agentd default cases, overlapping 13-component scope, one actual Root parent, original dependency failure and recovery retained",[["metadata/SCOPE.json","3d0b56f6c63c96295cef51b45c4f04c258d9b350afa781fc1637b02448d5a5cf"],["metadata/COUNT_BINDINGS.json","6a68176bc7fe6be249f9d2072e46c7e2a81998bde64aeea6725a10bb5c1926af"],["metadata/TERMINAL_SUMMARIES.json","a87d3cd2c64d59a406a4ef797dd12af41bcbe031a849f87e82c0fdf7b2b08195"],["originals/combined-3fc4725-strict-v1/preparation.json","b392ce360950d0507ac0da5ee567412e9341018c288e90a4e965e608d37a1bec"],["originals/combined-3fc4725-appserver-stage-audit-v1/RESULT.json","d902285d38a25ac7eb1034e62e90fa490b476872834a56871e7a552381702baf"],["originals/combined-3fc4725-agentd-stage-audit-v1/RESULT.json","8473ff99ed37d0df59a4249692a9ad134e6f1082e4723952f4814f8fbfc451ff"],["originals/combined-3fc4725-checkpoint-components-v1/RESULT.json","022d374a755730680516eca17258f0d18897d54737c82e9d6dca4d4acdd1c9cd"],["originals/combined-3fc4725-checkpoint-root-v1/RESULT.json","5ee653b64a230422c0df5ada45b81d087522fdaeba27a3218b261fea952bfb00"],["originals/combined-3fc4725-agentd-owning-v1/RESULT.json","bd25eee21d143c7e998c27cd7377204f8bb11271c6de8a89e6cf710596a29180"],["originals/combined-3fc4725-agentd-dependency-recovery-request-v1.json","301935e3b7ce04b2eb54a03441c4a2afe05326c9a7a3c81753a651decca0cd68"]]],["combined-callers-3fc4725-desktop-history-v1","combined-callers-3fc4725-desktop-history-v1/combined-callers-3fc4725-desktop-history.tar.xz",2330412,"8eba6d8438f9109fc9c1e0850c233ec1cc588cc27d730675d817b0b75ebd9bbb",24,"One complete original closed-set caller engineering gate on exact 3fc; original command, raw, source inventories and wall-time observation, no new native execution",[["metadata/SCOPE.json","924c0bf574140c268c946a2c001fc9ea8f0825f47067fbd08301adf937f4545d"],["originals/combined-callers-3fc4725-desktop-v1/RESULT.json","b35baf5a9861a3159e17f0c63afddd2a171f62d5ac395b12685beccdaab2f1e4"]]]]
OBSERVATIONS=[
 ("evidence-increment006-metadata-correction-publication-v1/RESULT.json","c157d9441a26d97046dce8d9431ee28b4e4c5207894e74a8b39bcb815da45fc2"),
 ("evidence-increment006-metadata-correction-publication-v1/commands.json","97e8e4975faf656eb82fb91bd585767a9a647972ed4149a0a05cad1a8fb5bcc5"),
 ("evidence-increment006-metadata-correction-independent-readback-v1/RESULT.json","d53377d9418e110fa90eaa71a6d2e42f828e99579362d7ac83df76bb0717dfd4"),
 ("evidence-increment006-metadata-correction-independent-readback-v1/commands.json","beb068206fafa4f1b4e2e5de74e555a059f12709de8e4a27f05ec0f6ca3869de"),
]
NATIVE_ID="combined-3fc4725-native-history-v1"
CALLER_ID="combined-callers-3fc4725-desktop-history-v1"

def digest(data): return hashlib.sha256(data).hexdigest()
def file_hash(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()
def state(path):
    s=path.lstat()
    assert stat.S_ISREG(s.st_mode) and s.st_nlink==1
    return {"bytes":s.st_size,"sha256":file_hash(path),"mode":stat.S_IMODE(s.st_mode),"device":s.st_dev,"inode":s.st_ino,"mtime_ns":s.st_mtime_ns,"ctime_ns":s.st_ctime_ns}
def git(work,*args):return subprocess.check_output(["git",*args],cwd=work,text=True).strip()
def source():
    s={"source_sha":git(C,"rev-parse","HEAD"),"source_tree":git(C,"rev-parse","HEAD^{tree}"),"branch":git(C,"branch","--show-current"),"dirty":git(C,"status","--porcelain=v1","--untracked-files=all"),"current_sha256":file_hash(C/"qualification/cell-research-stages-20261108/CURRENT_RESULT.json")}
    assert s=={"source_sha":SOURCE,"source_tree":SOURCE_TREE,"branch":"codex/cell-s0-common-20261108-898e","dirty":"","current_sha256":CURRENT}
    return s
def evidence():
    v={"head":git(W,"rev-parse","HEAD"),"tree":git(W,"rev-parse","HEAD^{tree}"),"branch":git(W,"branch","--show-current"),"dirty":git(W,"status","--porcelain=v1","--untracked-files=all")}
    assert v=={"head":HEAD,"tree":TREE,"branch":"codex/cell-s0-evidence-20261108-898e","dirty":""}
    return v
def write(path,obj):
    with path.open("x") as f:json.dump(obj,f,indent=2,ensure_ascii=False);f.write("\n")

def same_typed(a,b):
    if type(a) is not type(b):return False
    if isinstance(a,dict):return a.keys()==b.keys() and all(same_typed(a[k],b[k]) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(same_typed(x,y) for x,y in zip(a,b))
    return a==b

def main():
    if not __debug__:raise RuntimeError("Required immutable-input assertions must remain enabled")
    before={"common":source(),"evidence":evidence()}
    OUT.mkdir(exist_ok=False)
    original=subprocess.check_output(["git","show",HEAD+":"+REL+"/manifest.json"],cwd=W)
    assert digest(original)==INDEX
    (OUT/"ORIGINAL_INDEX.json").write_bytes(original)
    prior=json.loads(original)
    assert len(prior["packets"])==81 and sum(p["file_member_count"] for p in prior["packets"])==9136
    assert prior["full_history_cost"] is None and prior["stages"]=={f"S{i}":"HOLD" for i in range(6)}
    assert (W/REL/"manifest.json").read_bytes()==original
    existing={p["packet_id"] for p in prior["packets"]}
    packets=[];objects={};inventories=[];json_pins=[]
    bindings_dir=OUT/"required-json-originals";bindings_dir.mkdir(exist_ok=False)
    for pid,relative,size,expected_sha,count,scope,bindings in DEFINITIONS:
        assert pid not in existing;existing.add(pid)
        path=R/relative;start=state(path)
        assert start["bytes"]==size and start["sha256"]==expected_sha
        desired=dict(bindings);assert len(desired)==len(bindings)
        got={};names=set();file_count=0
        with tarfile.open(path,"r|xz") as archive:
            for member in archive:
                pp=PurePosixPath(member.name)
                assert member.name and not pp.is_absolute() and ".." not in pp.parts and "\0" not in member.name
                assert member.name not in names;names.add(member.name)
                assert member.isfile() or member.isdir()
                if not member.isfile():continue
                file_count+=1
                if member.name in desired:
                    assert member.size<=524288
                    data=archive.extractfile(member).read()
                    assert len(data)==member.size and digest(data)==desired[member.name]
                    got[member.name]=(data,json.loads(data))
        assert file_count==count and set(got)==set(desired)
        required=[]
        for name,_ in bindings:
            data,value=got[name]
            required.append({"path":name,"bytes":len(data),"sha256":digest(data),"equals":[{"path":[],"value":value}]})
            saved=bindings_dir/pid/name;saved.parent.mkdir(parents=True,exist_ok=True)
            with saved.open("xb") as f:f.write(data)
            objects[(pid,name)]=value
            json_pins.append({"packet_id":pid,"archive_member":name,"bytes":len(data),"sha256":digest(data)})
        end=state(path);assert start==end
        inventories.append({"packet_id":pid,"path":str(path),"before":start,"after":end,"file_member_count":count})
        packets.append({"packet_id":pid,"scope":scope,"archive_path":str(path),"bytes":size,"sha256":expected_sha,"file_member_count":count,"required_json_members":required})
    assert len(packets)==2 and sum(p["file_member_count"] for p in packets)==333 and len(json_pins)==12
    n=lambda path:objects[(NATIVE_ID,path)]
    scope=n("metadata/SCOPE.json");counts=n("metadata/COUNT_BINDINGS.json")
    assert scope["source_sha"]==COMBINED and scope["source_tree"]==COMBINED_TREE
    assert same_typed(scope["counts"],counts)
    assert counts["default_owning_unique_passed"]==2129
    assert counts["appserver"]=={"actual_unique_passed":1348,"original_ignored_not_executed":2}
    assert counts["agentd"]=={"actual_unique_passed":781,"original_ignored_not_executed":71,"one_slow_case_is_not_additional_execution":True}
    assert counts["checkpoint_components"]["actual_executions"]==13
    assert counts["checkpoint_components"]["subset_of_agentd_default_781"] is True
    assert counts["checkpoint_components"]["added_to_unique_count"] is False
    assert counts["root_parent"]["actual_parent_passed"]==1
    assert counts["root_parent"]["child_summaries_added_to_acceptance_count"] is False
    assert counts["root_parent"]["native_root_pid"]==2254272
    assert counts["root_parent"]["ordinary_child_pid"]==2254274
    assert scope["host_only_binary_file_count"]==35 and scope["binary_bytes_archived"] is False
    for key in ("full_workspace","windows_native","windows_bazel","ordinary_daemon_learning","full_learning_owner_ports","production_registration","real_learning_candidate_adoption","real_successor_task_consumption","scientific_acceptance","full_history_cost_complete"):
        assert scope[key] is False
    assert scope["physical_cost"] is None and scope["full_history_cost"] is None
    strict=n("originals/combined-3fc4725-strict-v1/preparation.json")
    assert strict["source_sha"]==COMBINED and strict["source_tree"]==COMBINED_TREE
    assert strict["status"]=="prepared_clean" and strict["returncode"]==0 and strict["source_unchanged"] is True
    assert len(strict["steps"])==7 and all(p["returncode"]==0 for p in strict["steps"])
    assert strict["source_before"]["files_count"]==15010
    assert strict["source_before"]["files_sha256"]==strict["source_after"]["files_sha256"]
    app=n("originals/combined-3fc4725-appserver-stage-audit-v1/RESULT.json")
    agent=n("originals/combined-3fc4725-agentd-stage-audit-v1/RESULT.json")
    for audit,count,ignored in ((app,1348,2),(agent,781,71)):
        assert audit["source_sha"]==COMBINED and audit["source_tree"]==COMBINED_TREE
        assert audit["returncode"]==0 and audit["source_unchanged"] is True
        assert audit["clean_passed_original_executions"]==count and audit["original_ignored_not_executed"]==ignored
        assert audit["raw"]["whole_raw_leak_markers"]==[] and audit["raw"]["known_guard_markers"]==[]
        assert audit["raw"]["no_test_retries_in_real_statuses"] is True
        assert audit["junit"]["unique_passed"]==count and audit["junit"]["retry_nodes"]==0
        assert audit["junit"]["failures"]==0 and audit["junit"]["skipped_in_xml"]==0
    components=n("originals/combined-3fc4725-checkpoint-components-v1/RESULT.json")
    root=n("originals/combined-3fc4725-checkpoint-root-v1/RESULT.json")
    assert components["status"]=="PASS" and components["returncode"]==0 and components["source_unchanged"] is True
    assert root["status"]=="PASS" and root["returncode"]==0 and root["source_unchanged"] is True
    assert root["parent_case_pass_count"]==1 and root["fixture_child_is_additional_acceptance_case"] is False
    failure=n("originals/combined-3fc4725-agentd-owning-v1/RESULT.json")
    recovery=n("originals/combined-3fc4725-agentd-dependency-recovery-request-v1.json")
    assert failure["status"]=="FAIL" and failure["returncode"]==1 and failure["source_unchanged"] is True
    assert len(failure["steps"])==1 and failure["steps"][0]["name"]=="v8" and failure["steps"][0]["returncode"]==1
    assert recovery["original_result_sha256"]=="bd25eee21d143c7e998c27cd7377204f8bb11271c6de8a89e6cf710596a29180"
    assert recovery["original_native_executed"]==0 and recovery["native_retries"]==0
    assert recovery["dependency_validation_bypassed"] is False and recovery["automatic_recovery_loop"] is False
    caller=objects[(CALLER_ID,"originals/combined-callers-3fc4725-desktop-v1/RESULT.json")]
    caller_scope=objects[(CALLER_ID,"metadata/SCOPE.json")]
    assert caller["status"]=="passed" and caller["caller_gate_passed"] is True
    assert caller["source_sha"]==COMBINED and caller["source_tree"]==COMBINED_TREE
    assert caller["source_unchanged"] is True and caller["command_exit_code"]==0 and caller["wrapper_exit_code"]==0
    assert 0<caller["command_wall_seconds"]<600 and caller["timeout_seconds"]==600 and caller["minimum_tests"]==0
    assert caller["unit_tests_executed"] is False and caller_scope["scientific_acceptance"] is False

    observation_rows=[];observation_objects={};observation_states=[]
    for relative,pin in OBSERVATIONS:
        path=R/relative;start=state(path);assert start["sha256"]==pin
        data=path.read_bytes();assert len(data)<=490000
        target="observations/"+relative
        assert not (W/REL/target).exists()
        saved=OUT/"supplementary-originals"/relative;saved.parent.mkdir(parents=True,exist_ok=True)
        with saved.open("xb") as f:f.write(data)
        observation_rows.append({"source_path":str(path),"relative_path":target,"bytes":len(data),"sha256":pin})
        observation_objects[relative]=json.loads(data)
        observation_states.append({"path":str(path),"before":start,"after":state(path)})
        assert observation_states[-1]["before"]==observation_states[-1]["after"]
    pubprefix="evidence-increment006-metadata-correction-publication-v1/"
    readprefix="evidence-increment006-metadata-correction-independent-readback-v1/"
    pub=observation_objects[pubprefix+"RESULT.json"]
    readback=observation_objects[readprefix+"RESULT.json"]
    assert pub["status"]=="metadata_correction_published_and_exact_commit_objects_verified"
    assert pub["commit"]==readback["commit"]==HEAD and pub["tree"]==readback["tree"]==TREE
    assert pub["commands_sha256"]==dict(OBSERVATIONS)[pubprefix+"commands.json"]
    assert readback["commands_sha256"]==dict(OBSERVATIONS)[readprefix+"commands.json"]
    assert readback["publication_receipt_sha256"]==dict(OBSERVATIONS)[pubprefix+"RESULT.json"]
    assert readback["publication_commands_sha256"]==dict(OBSERVATIONS)[pubprefix+"commands.json"]
    assert readback["status"]=="independent_correction_remote_and_closed_commit_readback_verified"
    assert readback["original_observations_closed_set_verified"]==15
    assert readback["exact_new_paths_checked_by_commit_blob"]==97
    assert readback["parent_actual_tracked_evidence_files"]==1139 and readback["corrected_actual_tracked_evidence_files"]==1236
    for prefix in (pubprefix,readprefix):
        cmds=observation_objects[prefix+"commands.json"]
        assert cmds and all(type(c.get("exit_code")) is int and c["exit_code"]==0 for c in cmds)

    current=deepcopy(prior["current_common_validation"])
    assert current["source_sha"]==SOURCE and current["source_tree"]==SOURCE_TREE
    assert current["full_repository_ci"]["green"] is False
    separate=current["separate_source_observations"]
    assert "combined_3fc_terminal_history" not in separate
    original_omission=separate["combined_source_results"]
    assert original_omission=="deliberately omitted from increment006a; require a separate terminal packet and review"
    separate["combined_3fc_terminal_history"]={
        "source_sha":COMBINED,"source_tree":COMBINED_TREE,"parents":scope["parents"],"base_sha":SOURCE,
        "native_packet_id":NATIVE_ID,"caller_packet_id":CALLER_ID,
        "scope":"Separate Linux candidate engineering executions; not bf42 CI or ordinary deployed learning",
        "same_source_strict":{"steps_passed":7,"source_unchanged":True,"source_entries":15010,"finished_at":strict["finished_at"],"native_test_cases":0},
        "appserver_owning":{"actual_unique_passed":1348,"original_ignored_not_executed":2,"selected_retries":0,"leak_or_known_guard_markers":0,"independent_readback_finished_at":app["finished_at"]},
        "agentd_owning":{"actual_unique_passed":781,"original_ignored_not_executed":71,"selected_retries":0,"leak_or_known_guard_markers":0,"slow_records_are_not_additional_attempts":True,"independent_readback_finished_at":agent["finished_at"]},
        "unique_default_owning_cases":2129,"two_package_sets_disjoint":True,
        "checkpoint_component_scope":{"actual_executions":13,"subset_of_agentd_781":True,"added_to_unique_count":False},
        "root_transport_parent":{"actual_parent_passed":1,"child_is_additional_case":False,"native_root_pid":2254272,"ordinary_child_pid":2254274,"test_only_registered_bind":True,"production_registration":False},
        "original_agentd_dependency_failure":{"status":"FAIL","failure_phase":"V8 checksum ConnectionRefusedError errno111","native_executed":0,"original_result_sha256":recovery["original_result_sha256"]},
        "explicit_dependency_recovery":{"request_count":1,"same_source":True,"native_execution_first_on_v2":True,"native_retry":False,"checksum_bypass":False,"test_budgets_changed":False,"automatic_loop":False},
        "caller_gate":{"passed":True,"original_command":caller["command"],"wall_seconds_not_full_cost":caller["command_wall_seconds"],"timeout_seconds":600,"unit_tests_executed":False},
        "binary_bytes_archived":False,"host_only_binary_count":35,
        "full_workspace":False,"windows_native":False,"windows_bazel":False,
        "ordinary_daemon_learning":False,"full_learning_owner_ports":False,"production_registration":False,
        "real_learning_candidate_adoption":False,"real_successor_task_consumption":False,
        "elapsed_lease_expiry_independent_experiment":False,
        "common_source_advanced":False,"scientific_acceptance":False,
        "physical_cost":None,"full_history_cost":None,"full_history_cost_complete":False}
    unchanged=deepcopy(current)
    del unchanged["separate_source_observations"]["combined_3fc_terminal_history"]
    assert same_typed(unchanged,prior["current_common_validation"])
    correction_observation_scope={
        "source_commit":HEAD,"source_tree":TREE,"parent_commit":pub["parent"],
        "files_included":"Only both RESULT.json files and both complete commands.json indexes",
        "complete_stdout_stderr_prefixes_archived_here":False,
        "external_original_prefixes":[str(R/pubprefix.rstrip("/")),str(R/readprefix.rstrip("/"))],
        "original_raw_log_hashes_referenced_by_commands":True,
        "raw_bytes_not_promoted_from_hash_references_to_archived_content":True,
        "original_a911_1140_local_vs_1139_committed_preserved":True,
        "corrected_1236_committed_files_verified":True,"original_15_observations_verified":True,
        "packet_count_changed_by_metadata_correction":False,
        "publication_or_readback_is_not_native_validation":True,
        "new_tests_executed":False,"physical_cost":None,"full_history_cost":None}
    inputs={
        "schema_version":1,"phase":"increment-007a",
        "expected_evidence_head":HEAD,"expected_evidence_tree":TREE,"expected_index_sha256":INDEX,
        "expected_prior_packet_count":81,"expected_final_packet_count":83,
        "expected_common_source_sha":SOURCE,"expected_common_source_tree":SOURCE_TREE,
        "formal_current_sha256":CURRENT,"current_common_validation":current,"packets":packets,
        "supplementary_observations":observation_rows,
        "supplementary_observation_scope":correction_observation_scope,
        "all_old_common_validation_fields_retained_typed":True,
        "only_new_current_validation_path":["separate_source_observations","combined_3fc_terminal_history"],
        "complete_execution_history":False,"physical_cost":None,"full_history_cost":None,
        "stage_advancement_claimed":False,"stages":{f"S{i}":"HOLD" for i in range(6)},
        "core_45a_or_negative_records_included":False,
        "preparation_scope":"Read-only exact terminal inputs; no append, evidence/source writes, tests or network calls."}
    payload=(json.dumps(inputs,indent=2,ensure_ascii=False)+"\n").encode()
    assert len(payload)<=490000
    after={"common":source(),"evidence":evidence()};assert before==after
    assert (W/REL/"manifest.json").read_bytes()==original
    for row in inventories:assert state(Path(row["path"]))==row["before"]
    for row in observation_states:assert state(Path(row["path"]))==row["before"]
    write(OUT/"ARCHIVE_INPUTS_BEFORE_AFTER.json",inventories)
    write(OUT/"SUPPLEMENTARY_INPUTS_BEFORE_AFTER.json",observation_states)
    write(OUT/"REQUIRED_JSON_PINS.json",json_pins)
    write(OUT/"SUPPLEMENTARY_OBSERVATION_SCOPE.json",correction_observation_scope)
    with (R/"increment007a-inputs.json").open("xb") as f:f.write(payload)
    result={
        "status":"read_only_inputs_prepared_not_appended",
        "inputs":{"path":str(R/"increment007a-inputs.json"),"bytes":len(payload),"sha256":digest(payload)},
        "packet_count_before":81,"packet_count_after_if_approved":83,"new_packet_count":2,
        "new_member_entries_with_overlap":333,"all_member_entries_with_prior_overlap":9469,
        "archive_bytes_total":sum(p["bytes"] for p in packets),
        "required_json_member_count":len(json_pins),"supplementary_json_observations":4,
        "all_required_json_bound_by_exact_bytes_and_whole_typed_object":True,
        "archive_hashes_and_file_counts_match":True,"all_inputs_before_after_unchanged":True,
        "all_old_bf42_validation_and_006a_cutoffs_retained_typed":True,
        "correction_result_commands_hash_links_verified":True,
        "common_and_evidence_before":before,"common_and_evidence_after":after,
        "appender_executed":False,"new_tests_executed":False,"network_calls":0,"source_mutation":False,
        "full_history_cost":None,"scientific_advancement_claimed":False,
        "finished_at":datetime.now(timezone.utc).isoformat()}
    write(OUT/"INPUT_PREPARATION.json",result)
    print(json.dumps(result),flush=True)

if __name__=="__main__":main()

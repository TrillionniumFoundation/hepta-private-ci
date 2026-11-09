#!/usr/bin/env python3
"""Prepare four terminal failure histories and seven exact metadata files; never mutate evidence."""
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
OUT=R/"increment008-preparation-v1"
HEAD="e781fbebad63968adf18cce97dd04657b3854917"
TREE="ebe2226e8b63d261fd04ae56d4859617301c264a"
INDEX="6a1a7c2ed7cf55f72b0e9beff24b01be09c326a7097fdd32af6ab09352b89aed"
REL="qualification/cell_common_candidate/20261108/execution_history"
SOURCE="bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d"
SOURCE_TREE="f7b65a747a1d2f585be38a4665ab2b4f1b07efb6"
CURRENT="c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4"
FAILED="45a50bffd1631d502889069fc3f713b8a5e775d8"
FAILED_TREE="60fd0cc181f3f34dbbb3a4a9a63226b920260ce2"
TIMER="6ec5993fec3dcd6a3c569498a1d5b4c277f1c142"
TIMER_TREE="b0ddbe6b6f83dc42657260b266774f79c9d1ed90"
DEFINITIONS=json.loads("[{\"packet_id\":\"core-output-45a50bf-ai-failed-owning-history-v1\",\"archive_path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-45a50bf-failed-native-history-import-v1/core-output-45a50bf-failed-native-history.tar.xz\",\"bytes\":3559024,\"sha256\":\"f5ad5116de21dc92dfb5946e9487ce2577bd7c14e77cd505a1956efb25ace436\",\"file_member_count\":187,\"scope\":\"Original failed 45a whole-core execution, strict preparation and failure-aware closed-set accounting; FAIL retained, 3827 selected/9 ignored, fourteen executable bytes host-only\",\"bindings\":[{\"path\":\"metadata/SCOPE.json\",\"bytes\":15994,\"sha256\":\"2d4b377124aa6d5ce0324607cbebc0ad6aa9c10209ce2e7f904b14a2a5cec537\"},{\"path\":\"metadata/COUNT_BINDINGS.json\",\"bytes\":11068,\"sha256\":\"c23dd472897129559bc16bacedc860bc8c17fc29559f1e59d1aea8ca6a113b54\"},{\"path\":\"originals/core-output-45a50bf-owning-v1/RESULT.json\",\"bytes\":11294,\"sha256\":\"08cdb1dc07ac689c287a326495aace745fe4838d374f7050929be5d69fc2edc9\"},{\"path\":\"originals/core-output-45a50bf-stage-audit-v1/RESULT.json\",\"bytes\":11769,\"sha256\":\"aff375991401d14dd656958a900bc2f02ca923d7ff16e01bcb06e2220f82ce01\"},{\"path\":\"originals/core-output-45a50bf-strict-v1/preparation.json\",\"bytes\":11048,\"sha256\":\"8781ddeac41b77cd6f67e94a5b1dc035ac76b3952d23006dcbedbf793034a76b\"},{\"path\":\"originals/core-output-45a50bf-failure-cause-readback-v1/RESULT.json\",\"bytes\":8919,\"sha256\":\"8c20c8cc478260f6e5ac66b14b9e4484e3ceb43c1d46948954ebb9a14c6c8bfa\"},{\"path\":\"originals/core-output-45a50bf-retained-binaries-v1/RESULT.json\",\"bytes\":6780,\"sha256\":\"6d7d38e18b7f479ede50a782d8d527f1766810ed25495db570e41e16f9010b49\"}]},{\"packet_id\":\"core-output-45a50bf-desktop-preparation-caller-history-v3\",\"archive_path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-45a50bf-desktop-context-history-v3/core-output-45a50bf-desktop-context-history.tar.xz\",\"bytes\":2830716,\"sha256\":\"b5aa757ab9003bb6d8bdae47dd0903f3a30e3cd116624e2dfb7d69d6e657103c\",\"file_member_count\":278,\"scope\":\"45a desktop source, formatting, full caller and unexecuted timer preparation history; original collector failures retained, no native execution in this scope\",\"bindings\":[{\"path\":\"metadata/SCOPE.json\",\"bytes\":6823,\"sha256\":\"5ecc30c529a87ab29753c5884a12f8f391649f0577372a86f34aeeed8dc76f5d\"},{\"path\":\"metadata/COUNT_BINDINGS.json\",\"bytes\":848,\"sha256\":\"28592f00d087aceaf4b1e2cce39c044ef5ba572a907fd45680b25f0833a35975\"},{\"path\":\"originals/core-output-callers-45a50bf-desktop-v1/RESULT.json\",\"bytes\":2561,\"sha256\":\"cd8df88b3b1e73ab9b7a47ed8043e7b654da6f5681df13ec2ed3d197dee5159d\"},{\"path\":\"originals/core-output-summary-3fc-draft-v2/RESULT.json\",\"bytes\":9675,\"sha256\":\"4e873a11168b15e65e78e8cb5cadb78e0241264988e9b4621c2493ceaed25f34\"},{\"path\":\"originals/core-output-summary-source-freeze-v1/RESULT.json\",\"bytes\":12609,\"sha256\":\"17f94bf08c499ea218e9f54829b7cb629ced97a5b4fcc284b6283fdb266d5018\"},{\"path\":\"originals/core-output-45a50bf-desktop-context-history-v1/RESULT.json\",\"bytes\":1754,\"sha256\":\"61ddb535d2cac3d34e7b9804fd454c20054729156e243b89abf3d6b1585c5162\"},{\"path\":\"originals/core-output-45a50bf-desktop-context-history-v2/RESULT.json\",\"bytes\":1318,\"sha256\":\"1dd46a6d50489a3678840c876cf4fb518b0456870afc5c38450b973e508d82a7\"},{\"path\":\"originals/core-output-remote-timer-oracle-45a-preparation-v1/RESULT.json\",\"bytes\":5024,\"sha256\":\"d59171557076b2efe394172052dbd1cc7ffff1b87a68831269aa567b1a72baa9\"}]},{\"packet_id\":\"core-output-6ec5993-ai-two-checksum-failures-environment-history-v2\",\"archive_path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-ai-dependency-failure-history-v2/core-output-6ec5993-ai-dependency-failure-history.tar.xz\",\"bytes\":1076276,\"sha256\":\"8a19f8d2a2bb455240d079dbc61187aaef456735cd83c4b92da381c4d1f461c3\",\"file_member_count\":61,\"scope\":\"Both same-source strict attempts ended in official checksum HTTP504; no helper, lint or native case launched. One explicit dependency recovery remains FAIL. Collector-v1 failed on an incorrect null-field schema assumption; original FAIL receipt, console, invocation and collector/spec are preserved. No native was run by that collector.\",\"bindings\":[{\"path\":\"SUMMARY.json\",\"bytes\":7376,\"sha256\":\"435bcd5ff2dc1cf345900b76ad12fd7567334d659cf5d5e572a78d9c94366d5a\"},{\"path\":\"originals/core-output-6ec5993-strict-v1/preparation.json\",\"bytes\":7621,\"sha256\":\"74fa9a89fdb8ed8d5f8c6311be06b7d1d6f3dc7232df8a6917a99fa5baaa87e2\"},{\"path\":\"originals/core-output-6ec5993-strict-v1/v8.json\",\"bytes\":1510,\"sha256\":\"74680ff5935a07d291050a543dd810dc9e12c7d3e792ba1c8e90fceca923010f\"},{\"path\":\"originals/core-output-6ec5993-strict-v2/preparation.json\",\"bytes\":7619,\"sha256\":\"d330d6ec89e827e37b37a00666eccf5195fce004dc5f0187b9fe9dafb3b7ebef\"},{\"path\":\"originals/core-output-6ec5993-strict-v2/v8.json\",\"bytes\":1510,\"sha256\":\"be85d89adb6163239cdb44d277a345943833de62db27f5b10d04fa5ba2f165c6\"},{\"path\":\"originals/core-output-6ec5993-strict-dependency-recovery-v1/RESULT.json\",\"bytes\":14079,\"sha256\":\"f6f90bba6b9f11c40b96597e34d12e94a963b564d4b12df62f5f76945b70cd6a\"},{\"path\":\"originals/core-output-6ec5993-ai-dependency-failure-history-v1/RESULT.json\",\"bytes\":274,\"sha256\":\"6e8818d384d32b6a345e519b026de25281c046f36cdefb3818ddd779206073e6\"}]},{\"packet_id\":\"core-output-6ec5993-desktop-source-caller-and-unexecuted-control-preparation-v1\",\"archive_path\":\"/home/qian-qi/work/hepta-cell-s0-records-20261108-898e/core-output-6ec5993-desktop-freeze-caller-preparation-history-v1/core-output-6ec5993-desktop-freeze-caller-preparation-history.tar.xz\",\"bytes\":2383948,\"sha256\":\"eb49b7680e375f3d5090be457911a0f01a85fdbac23a0c2f534b2ece1c7dac39\",\"file_member_count\":109,\"scope\":\"6ec source freeze, original full caller and unexecuted control/admission preparation; later desktop V8 recovery and native attempts excluded\",\"bindings\":[{\"path\":\"SUMMARY.json\",\"bytes\":3180,\"sha256\":\"07ca82291f564168a18451d2943f52011e5550d6f8a13f1b3f49c6679f1f5685\"},{\"path\":\"originals/core-output-callers-6ec5993-desktop-v1/RESULT.json\",\"bytes\":2567,\"sha256\":\"5a3e155c7008606b276f7643be1b9ba8b53a11ce8e8a5fe0fe84682add1c9f8c\"},{\"path\":\"originals/core-output-clock-oracle-source-freeze-v1/RESULT.json\",\"bytes\":22743,\"sha256\":\"faf1cd529dc930f34049645c36d7bac5ee41dd671af5cad57170a6890ed64027\"},{\"path\":\"originals/core-output-clock-oracle-admission-static-v1/RESULT.json\",\"bytes\":3794,\"sha256\":\"6f32dada9822b96d66192f4f1e95958440501036e8404b4e13ec9772cea78f19\"},{\"path\":\"originals/core-output-clock-oracle-positive-negative-source-comparison-v1/RESULT.json\",\"bytes\":3301,\"sha256\":\"0bd5e347b09b5c1425d54ce9616d3179180a0efa08c4aba564f550ebfe76abbc\"}]}]")
OBSERVATIONS=json.loads("[{\"source_relative\":\"evidence-increment007-publication-v1/RESULT.json\",\"target_relative\":\"observations/evidence-increment007-publication-v1/RESULT.json\",\"bytes\":15831,\"sha256\":\"4aad75f1910cc76eeada06bb45f7abf874d10fca3a65009ce9f81bd0606f2792\",\"kind\":\"original_json_observation\"},{\"source_relative\":\"evidence-increment007-publication-v1/commands.json\",\"target_relative\":\"observations/evidence-increment007-publication-v1/commands.json\",\"bytes\":53135,\"sha256\":\"52c1210628d3dde6d22ec20ea33d41c5e50adb3459a0ff6f78536a72f9605257\",\"kind\":\"original_json_observation\"},{\"source_relative\":\"evidence-increment007-independent-readback-v1/RESULT.json\",\"target_relative\":\"observations/evidence-increment007-independent-readback-v1/RESULT.json\",\"bytes\":2999,\"sha256\":\"a66ae2e39b0aabf283fcce40413295f8871b431f151e01836d8f9da66c8aa08b\",\"kind\":\"original_json_observation\"},{\"source_relative\":\"evidence-increment007-independent-readback-v1/commands.json\",\"target_relative\":\"observations/evidence-increment007-independent-readback-v1/commands.json\",\"bytes\":93897,\"sha256\":\"1e19a400ce4db5deec685351883df7d68365e678954763da35a727d50fc9b9e0\",\"kind\":\"original_json_observation\"},{\"source_relative\":\"core-output-summary-3fc-draft-v2/core-output-owner-transcript.patch\",\"target_relative\":\"reviewed_changes/core-output-45a-reviewed.patch\",\"bytes\":25852,\"sha256\":\"b7e4cfb754a4c0bad55dc15ad9ee67a2932dc4a386223845a5686be275e04e6f\",\"kind\":\"reviewed_source_patch\"},{\"source_relative\":\"core-output-remote-timer-oracle-45a-preparation-v1/remote-collector-clock-oracle.patch\",\"target_relative\":\"reviewed_changes/remote-timer-6ec-reviewed.patch\",\"bytes\":1651,\"sha256\":\"4b7a8813bd83b07a26050d9859bbbf5d0f20a914ca1d378804cf5530dae88a42\",\"kind\":\"reviewed_source_patch\"},{\"source_relative\":\"core-output-clock-oracle-source-freeze-v1/formatted.patch\",\"target_relative\":\"reviewed_changes/remote-timer-6ec-frozen.patch\",\"bytes\":1919,\"sha256\":\"4a5b2dba27bc88ca5ad16a909dc66a7368f08c23096917e3139618a609fb3866\",\"kind\":\"reviewed_source_patch\"}]")
INDEPENDENT=json.loads("[[\"core-output-45a50bf-packets-independent-verification-v1/RESULT.json\",20681,\"61a3a47db1f214adaa50d9479e8928ed31ecd5ad6bbdf66dd86577a6c57a4160\",\"TWO_COMPLETED_FAILURE_HISTORY_PACKETS_INDEPENDENTLY_VERIFIED\"],[\"core-output-6ec5993-ai-history-desktop-readback-v1/RESULT.json\",10591,\"88e3cd246e85c590f98e2a27e03d2694cc069dbf2ced1ea61bc990f595de88b0\",\"TRANSPORTED_ORIGINALS_AND_ALL_61_MEMBERS_VERIFIED\"],[\"core-output-6ec5993-desktop-history-independent-readback-v1/RESULT.json\",5945,\"398821514942d2400a434e314bf14cbcc2b6272de3f0002cece784af8f3e6ff6\",\"DESKTOP_ORIGINALS_AND_ALL_109_MEMBERS_VERIFIED\"]]")
OBSERVATION_TEMPLATE=json.loads("{\"core_output_45a_failed_history\":{\"source_sha\":\"45a50bffd1631d502889069fc3f713b8a5e775d8\",\"source_tree\":\"60fd0cc181f3f34dbbb3a4a9a63226b920260ce2\",\"parents\":[\"3fc4725343dccfc9487e937f77e30bc6a5d80dbc\"],\"original_native_execution_status\":\"FAIL\",\"strict_preparation\":{\"steps_passed\":9,\"source_unchanged\":true,\"scope\":\"owning preparation and read-only strict checks; not a native pass\"},\"counts\":{\"executed\":3827,\"passed\":3274,\"failed_exit101\":6,\"signal_aborted\":545,\"timed_out\":2,\"failed_including_timeouts\":553,\"original_ignored_not_executed\":9,\"retries\":0,\"leaks\":0},\"required_four\":{\"passed\":2,\"failed_exit101\":1,\"signal_aborted\":1,\"all_passed\":false,\"subset_of_3827\":true},\"original_exit_codes\":{\"test_command\":100,\"collector\":1,\"driver\":1},\"failure_payload_classification\":{\"sigabrt_constructor_enospc_text_matches\":545,\"ordinary_exit101_enospc_text_matches\":5,\"ordinary_exit101_timing_assertion\":1,\"timeouts_both_proven_same_constructor_cause\":false,\"all_failures_explained\":false,\"all_failures_fixed\":false,\"environment_change_proven_to_fix_any_case\":false},\"original_large_output_integration_case_passed\":false,\"original_ci_large_output_race_proven\":false,\"original_large_output_integration_case_status\":\"SIGABRT\",\"negative_control\":{\"source_sha\":\"d27431b69195a2a6331a77d19e22ebeb4cf910c7\",\"executed\":false,\"prepared_only\":true},\"published_source\":false,\"common_source_advanced\":false,\"scientific_acceptance\":false,\"physical_cost\":null,\"full_history_cost\":null,\"full_history_cost_complete\":false},\"remote_timer_6ec_dependency_failure_history\":{\"source_sha\":\"6ec5993fec3dcd6a3c569498a1d5b4c277f1c142\",\"source_tree\":\"b0ddbe6b6f83dc42657260b266774f79c9d1ed90\",\"parents\":[\"45a50bffd1631d502889069fc3f713b8a5e775d8\"],\"source_change_scope\":\"timer-only regression oracle; production code and original20ms deadline unchanged\",\"dependency_attempt_count\":2,\"explicit_recovery_count\":1,\"dependency_result\":\"Both original AI preparations failed fetching the V8 checksum with HTTP504\",\"helper_executed\":0,\"lint_executed\":0,\"native_executed\":0,\"negative_native_executed\":0,\"caller_gate\":{\"passed\":true,\"timeout_seconds\":600,\"wall_seconds_as_reported\":408.24210778297856,\"wall_time_is_not_complete_cost\":true,\"rust_files_scanned\":6480,\"boundaries\":173,\"protected_files\":160,\"source_unchanged\":true,\"unit_test_count\":null,\"source_entries_before_after_equal\":15010},\"later_desktop_precheck_included\":false,\"published_source\":false,\"common_source_advanced\":false,\"scientific_acceptance\":false,\"physical_cost\":null,\"full_history_cost\":null,\"full_history_cost_complete\":false,\"preparation_field_mapping\":{\"original_preparation_returncode\":null,\"overall_preparation_returncode\":1,\"v8_returncode\":1,\"applies_to_both_original_AI_attempts\":true,\"derived_summary_preparation_returncode\":1,\"derived_summary_value_refers_to\":\"original overall preparation.json returncode, not its internal preparation_returncode field\",\"original_summary_bytes_preserved\":true,\"original_null_is_not_relabelled_zero\":true,\"internal_null_semantics\":\"No owning lint command was reached after the V8 failure\",\"actual_original_JSON_binding_required_before_append\":true}}}")
FAILED_AI_ID=DEFINITIONS[0]["packet_id"]
FAILED_DESKTOP_ID=DEFINITIONS[1]["packet_id"]
TIMER_AI_ID=DEFINITIONS[2]["packet_id"]
TIMER_DESKTOP_ID=DEFINITIONS[3]["packet_id"]

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
    if not __debug__:
        raise RuntimeError("Required immutable-input assertions must remain enabled")
    before={"common":source(),"evidence":evidence()}
    OUT.mkdir(exist_ok=False)
    original=subprocess.check_output(["git","show",HEAD+":"+REL+"/manifest.json"],cwd=W)
    assert digest(original)==INDEX
    with (OUT/"ORIGINAL_INDEX.json").open("xb") as f:f.write(original)
    prior=json.loads(original)
    assert len(prior["packets"])==83
    assert sum(p["file_member_count"] for p in prior["packets"])==9469
    assert prior["full_history_cost"] is None
    assert prior["stages"]=={f"S{i}":"HOLD" for i in range(6)}
    assert (W/REL/"manifest.json").read_bytes()==original
    old_paths=subprocess.check_output(["git","ls-tree","-r","-z","--name-only",HEAD,"--",REL],cwd=W).split(b"\0")
    assert len([p for p in old_paths if p])==1281
    existing={p["packet_id"] for p in prior["packets"]}
    packets=[];objects={};inventories=[];json_pins=[]
    bindings_dir=OUT/"required-json-originals";bindings_dir.mkdir(exist_ok=False)
    for definition in DEFINITIONS:
        pid=definition["packet_id"]
        assert pid not in existing;existing.add(pid)
        path=Path(definition["archive_path"]);start=state(path)
        assert start["bytes"]==definition["bytes"] and start["sha256"]==definition["sha256"]
        bindings=definition["bindings"]
        desired={b["path"]:b for b in bindings}
        assert len(desired)==len(bindings)
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
                    pin=desired[member.name]
                    assert member.size==pin["bytes"] and member.size<=490000
                    data=archive.extractfile(member).read()
                    assert len(data)==member.size and digest(data)==pin["sha256"]
                    got[member.name]=(data,json.loads(data))
        assert file_count==definition["file_member_count"] and set(got)==set(desired)
        required=[]
        for binding in bindings:
            name=binding["path"];data,value=got[name]
            required.append({"path":name,"bytes":len(data),"sha256":digest(data),"equals":[{"path":[],"value":value}]})
            saved=bindings_dir/pid/name;saved.parent.mkdir(parents=True,exist_ok=True)
            with saved.open("xb") as f:f.write(data)
            objects[(pid,name)]=value
            json_pins.append({"packet_id":pid,"archive_member":name,"bytes":len(data),"sha256":digest(data)})
        end=state(path);assert start==end
        inventories.append({"packet_id":pid,"path":str(path),"before":start,"after":end,"file_member_count":file_count})
        packets.append({k:definition[k] for k in ("packet_id","scope","archive_path","bytes","sha256","file_member_count")}|{"required_json_members":required})
    assert len(packets)==4 and sum(p["file_member_count"] for p in packets)==635 and len(json_pins)==27
    get=lambda pid,path:objects[(pid,path)]
    failed_scope=get(FAILED_AI_ID,"metadata/SCOPE.json")
    failed_counts=get(FAILED_AI_ID,"metadata/COUNT_BINDINGS.json")
    desktop_scope=get(FAILED_DESKTOP_ID,"metadata/SCOPE.json")
    desktop_counts=get(FAILED_DESKTOP_ID,"metadata/COUNT_BINDINGS.json")
    for scope in (failed_scope,desktop_scope):
        assert scope["source_sha"]==FAILED and scope["source_tree"]==FAILED_TREE
        assert scope["parents"]==["3fc4725343dccfc9487e937f77e30bc6a5d80dbc"]
        assert scope["original_native_execution_status"]=="FAIL"
        assert scope["formal_current_sha256"]==CURRENT
        assert scope["physical_cost"] is None and scope["full_history_cost"] is None
        assert scope["scientific_acceptance"] is False and scope["stage_advancement_claimed"] is False
        assert scope["native_tests_started_or_rerun"]==0 and scope["full_history_cost_complete"] is False
    assert same_typed(failed_scope["counts"],failed_counts)
    assert same_typed(desktop_scope["counts"],desktop_counts)
    assert same_typed(failed_counts["counts"],OBSERVATION_TEMPLATE["core_output_45a_failed_history"]["counts"])
    assert (failed_counts["original_test_exit_code"],failed_counts["original_collector_exit_code"],failed_counts["original_driver_exit_code"])==(100,1,1)
    assert failed_counts["original_execution_status"]=="FAIL"
    required_four=failed_counts["required_four_actual_results"]
    assert len(required_four)==4 and [r["raw_status"] for r in required_four]==["PASS","PASS","FAIL","SIGABRT"]
    assert required_four[-1]["name"]=="suite::unified_exec::unified_exec_formats_large_output_summary"
    assert failed_counts["per_abort_constructor_enospc_text_matches"]==545
    assert failed_counts["ordinary_exit101_enospc_text_matches"]==5
    assert len(failed_counts["timeouts"])==2
    assert not any(x["same_test_codex_home_enospc_text"] for x in failed_counts["timeouts"])
    for k in ("all_failures_explained","all_failures_fixed","environment_change_proven_to_fix_any_case"):
        assert failed_counts[k] is False
    assert failed_scope["host_only_binary_file_count"]==14
    assert failed_scope["host_only_split"]=={"same_source_helpers":10,"actual_test_binaries":4}
    assert failed_scope["binary_bytes_archived"] is False
    original_native=get(FAILED_AI_ID,"originals/core-output-45a50bf-owning-v1/RESULT.json")
    assert original_native["source_sha"]==FAILED and original_native["source_tree"]==FAILED_TREE
    assert original_native["status"]=="FAIL" and original_native["returncode"]==1
    assert original_native["test_returncode"]==100 and original_native["collect_returncode"]==1
    assert original_native["source_unchanged"] is True and original_native["exact_fresh_unique_executed_set"] is True
    failed_audit=get(FAILED_AI_ID,"originals/core-output-45a50bf-stage-audit-v1/RESULT.json")
    assert failed_audit["status"]=="ORIGINAL_FAILED_EXECUTION_CLOSED_SET_VERIFIED"
    assert failed_audit["returncode"]==0 and failed_audit["original_execution_status"]=="FAIL"
    assert failed_audit["original_execution_clean_pass"] is False and failed_audit["all_required_four_passed"] is False
    strict=get(FAILED_AI_ID,"originals/core-output-45a50bf-strict-v1/preparation.json")
    assert strict["status"]=="prepared_clean" and strict["returncode"]==0
    assert strict["source_sha"]==FAILED and strict["source_tree"]==FAILED_TREE and strict["source_unchanged"] is True
    assert len(strict["steps"])==9 and all(type(s["returncode"]) is int and s["returncode"]==0 for s in strict["steps"])
    causes=get(FAILED_AI_ID,"originals/core-output-45a50bf-failure-cause-readback-v1/RESULT.json")
    assert causes["returncode"]==0 and causes["native_executions"]==0 and causes["original_execution_status"]=="FAIL"
    assert causes["all_failures_explained"] is False and causes["all_failures_fixed"] is False
    retention=get(FAILED_AI_ID,"originals/core-output-45a50bf-retained-binaries-v1/RESULT.json")
    assert retention["status"]=="ALL_FOUR_BINARIES_INDEPENDENTLY_RETAINED"
    assert retention["include_binary_bytes_in_archive"] is False
    for version in ("v1","v2"):
        failure=get(FAILED_DESKTOP_ID,"originals/core-output-45a50bf-desktop-context-history-"+version+"/RESULT.json")
        assert failure["status"]=="COLLECTION_REJECTED" and failure["returncode"]==1
        assert failure["original_native_execution_status"]=="FAIL"
    timer_preparation=get(FAILED_DESKTOP_ID,"originals/core-output-remote-timer-oracle-45a-preparation-v1/RESULT.json")
    assert timer_preparation["native_executed"] is False and timer_preparation["production_changed"] is False
    assert timer_preparation["budget_milliseconds_unchanged"]==20
    caller45=get(FAILED_DESKTOP_ID,"originals/core-output-callers-45a50bf-desktop-v1/RESULT.json")
    caller6=get(TIMER_DESKTOP_ID,"originals/core-output-callers-6ec5993-desktop-v1/RESULT.json")
    for caller,sha,tree in ((caller45,FAILED,FAILED_TREE),(caller6,TIMER,TIMER_TREE)):
        assert caller["source_sha"]==sha and caller["source_tree"]==tree
        assert caller["status"]=="passed" and caller["caller_gate_passed"] is True
        assert caller["source_unchanged"] is True
        assert caller["command_exit_code"]==0 and caller["wrapper_exit_code"]==0
        assert 0<caller["command_wall_seconds"]<600 and caller["timeout_seconds"]==600
        assert caller["minimum_tests"]==0 and caller["unit_tests_executed"] is False
        assert caller["scientific_acceptance"] is False
    assert caller45["command_wall_seconds"]==desktop_counts["actual_command_wall_seconds_not_full_cost"]
    assert desktop_counts["gate"]["rust_files_scanned"]==6480
    assert desktop_counts["gate"]["boundaries"]==173 and desktop_counts["gate"]["protected_files_entries"]==160
    timer_ai=get(TIMER_AI_ID,"SUMMARY.json");timer_desktop=get(TIMER_DESKTOP_ID,"SUMMARY.json")
    for summary,pid in ((timer_ai,TIMER_AI_ID),(timer_desktop,TIMER_DESKTOP_ID)):
        assert summary["packet_id"]==pid and summary["source_sha"]==TIMER and summary["source_tree"]==TIMER_TREE
        assert summary["parent_sha"]==FAILED and summary["original_common_source_sha"]==SOURCE
        assert summary["formal_CURRENT_sha256"]==CURRENT and summary["all_scientific_stages"]=="HOLD"
        assert summary["full_history_cost"] is None and summary["physical_cost"] is None
        assert summary["scientific_acceptance"] is False
        assert summary["later_desktop_V8_readiness_or_preflight_included"] is False
        assert summary["negative_control_native_outcome"]=="not_run"
    attempts=timer_ai["facts"]["strict_attempts"]
    assert [a["attempt"] for a in attempts]==[1,2]
    actual_attempts=[]
    for attempt in attempts:
        prep=get(TIMER_AI_ID,attempt["preparation"]["archive_path"])
        v8=get(TIMER_AI_ID,attempt["v8_receipt"]["archive_path"])
        assert prep["source_sha"]==TIMER and prep["source_tree"]==TIMER_TREE
        assert prep["status"]=="preparation_failed" and prep["returncode"]==1
        assert prep["preparation_returncode"] is None and prep["source_unchanged"] is True
        assert len(prep["steps"])==1 and prep["steps"][0]["returncode"]==1
        assert v8["source_sha"]==TIMER and v8["status"]=="failed"
        assert v8["returncode"]==v8["command_exit_code"]==1
        assert v8["log_sha256"]==attempt["raw"]["sha256"]=="f41c3bf5c8916da47c6238e28c5ab59f35062c2ece23f61233ba9c8744e09298"
        assert attempt["preparation_returncode"]==prep["returncode"]
        assert attempt["failure_phase"]=="official_checksum_download_HTTP_504"
        for k in ("helper_commands_executed","owning_lint_commands_executed","native_test_cases_executed"):
            assert type(attempt[k]) is int and attempt[k]==0
        actual_attempts.append({"attempt":attempt["attempt"],"status":prep["status"],"original_preparation_returncode":prep["preparation_returncode"],"overall_preparation_returncode":prep["returncode"],"v8_returncode":v8["returncode"],"helper_executed":0,"lint_executed":0,"native_executed":0,"source_unchanged":True,"finished_at":prep["finished_at"],"preparation_member":attempt["preparation"]["archive_path"],"v8_receipt_member":attempt["v8_receipt"]["archive_path"]})
    recovery=get(TIMER_AI_ID,"originals/core-output-6ec5993-strict-dependency-recovery-v1/RESULT.json")
    assert recovery["status"]=="DEPENDENCY_RECOVERY_FAILED"
    assert recovery["returncode"]==recovery["strict_returncode"]==1 and recovery["explicit_recovery_attempt"]==1
    assert recovery["original_native_executions"]==recovery["native_executions"]==0
    for k in ("automatic_retry_loop","resolver_bypassed","checksums_copied_to_destination","V8_overrides_preseeded","prior_failure_relabelled"):
        assert recovery[k] is False
    old_collector=get(TIMER_AI_ID,"originals/core-output-6ec5993-ai-dependency-failure-history-v1/RESULT.json")
    assert old_collector["status"]=="incomplete" and old_collector["new_tests_executed"] is False
    dfacts=timer_desktop["facts"]
    assert dfacts["caller_gate_status"]=="PASS"
    assert dfacts["caller_wall_seconds_partial_not_full_cost"]==caller6["command_wall_seconds"]
    assert dfacts["caller_rust_files"]==6480 and dfacts["caller_boundaries"]==173 and dfacts["caller_protected_files"]==160
    assert dfacts["caller_source_entries_before_after_equal"]==15010
    assert dfacts["native_test_cases_executed_by_this_desktop_scope"]==0
    assert dfacts["negative_native"]=="prepared_only_not_executed"
    assert dfacts["negative_source_sha"]=="d27431b69195a2a6331a77d19e22ebeb4cf910c7"
    freeze6=get(TIMER_DESKTOP_ID,"originals/core-output-clock-oracle-source-freeze-v1/RESULT.json")
    assert freeze6["source_sha"]==TIMER and freeze6["source_tree"]==TIMER_TREE
    assert freeze6["status"]=="local_source_frozen_not_published" and freeze6["published"] is False and freeze6["native_executed"] is False

    independent_rows=[];independent_states=[]
    for relative,size,pin,status in INDEPENDENT:
        path=R/relative;start=state(path);assert start["bytes"]==size and start["sha256"]==pin
        data=path.read_bytes();value=json.loads(data)
        assert value["status"]==status and value["returncode"]==0
        assert value["scientific_acceptance"] is False
        assert value["full_history_cost"] is None
        saved=OUT/"independent-readback-originals"/relative;saved.parent.mkdir(parents=True,exist_ok=True)
        with saved.open("xb") as f:f.write(data)
        independent_rows.append({"source_path":str(path),"bytes":size,"sha256":pin,"status":status,"returncode":0,"scope":"Independent archive/member readback, not product test success","original_bytes_copied_to_preparation":True})
        independent_states.append({"path":str(path),"before":start,"after":state(path)})
        assert start==independent_states[-1]["after"]

    observation_rows=[];observation_objects={};observation_states=[]
    for definition in OBSERVATIONS:
        relative=definition["source_relative"];path=R/relative;start=state(path)
        assert start["sha256"]==definition["sha256"] and start["bytes"]==definition["bytes"]
        data=path.read_bytes();assert len(data)<=490000
        target=definition["target_relative"]
        assert not (W/REL/target).exists()
        saved=OUT/"supplementary-originals"/relative;saved.parent.mkdir(parents=True,exist_ok=True)
        with saved.open("xb") as f:f.write(data)
        observation_rows.append({"source_path":str(path),"relative_path":target,"bytes":len(data),"sha256":definition["sha256"],"kind":definition["kind"]})
        if definition["kind"]=="original_json_observation":
            observation_objects[relative]=json.loads(data)
        else:
            assert data.startswith(b"diff --git ") or data.startswith(b"--- a/")
        observation_states.append({"path":str(path),"before":start,"after":state(path)})
        assert observation_states[-1]["before"]==observation_states[-1]["after"]
    pubprefix="evidence-increment007-publication-v1/"
    readprefix="evidence-increment007-independent-readback-v1/"
    pub=observation_objects[pubprefix+"RESULT.json"]
    readback=observation_objects[readprefix+"RESULT.json"]
    pins={x["source_relative"]:x["sha256"] for x in OBSERVATIONS}
    assert pub["status"]=="published_and_all_new_metadata_commit_blobs_remote_readback_verified"
    assert readback["status"]=="independent_007_remote_and_exact_committed_metadata_readback_verified"
    assert pub["commit"]==readback["commit"]==HEAD and pub["tree"]==readback["tree"]==TREE
    assert pub["commands_receipt_sha256"]==pins[pubprefix+"commands.json"]
    assert readback["commands_sha256"]==pins[readprefix+"commands.json"]
    assert readback["publication_receipt_sha256"]==pins[pubprefix+"RESULT.json"]
    assert readback["publication_commands_sha256"]==pins[pubprefix+"commands.json"]
    assert pub["packet_count"]==readback["packet_count"]==83
    assert pub["manifest_sha256"]==readback["manifest_sha256"]==INDEX
    assert pub["published_file_count"]==readback["published_actual_committed_files"]==1281
    assert readback["new_metadata_observations_complete_in_index_and_commit"]==21
    for prefix in (pubprefix,readprefix):
        cmds=observation_objects[prefix+"commands.json"]
        assert cmds and all(type(c.get("exit_code")) is int and c["exit_code"]==0 for c in cmds)

    current=deepcopy(prior["current_common_validation"])
    assert current["source_sha"]==SOURCE and current["source_tree"]==SOURCE_TREE
    assert current["full_repository_ci"]["green"] is False
    separate=current["separate_source_observations"]
    new_observations=deepcopy(OBSERVATION_TEMPLATE)
    failed=new_observations["core_output_45a_failed_history"]
    failed.update(native_packet_id=FAILED_AI_ID,desktop_packet_id=FAILED_DESKTOP_ID,
        original_native_finished_at=original_native["finished_at"],
        historical_cutoff="Original 45a execution and independent classification; later 6ec or desktop recovery is excluded",
        original_required_four=deepcopy(required_four),
        binary_bytes_archived=False,host_only_binary_count=14,
        caller_gate={"passed":True,"wall_seconds_not_full_cost":caller45["command_wall_seconds"],"timeout_seconds":600,"unit_tests_executed":False,"rust_files_scanned":6480,"boundaries":173,"protected_files":160})
    failed["strict_preparation"]["finished_at"]=strict["finished_at"]
    timer=new_observations["remote_timer_6ec_dependency_failure_history"]
    timer.update(ai_packet_id=TIMER_AI_ID,desktop_packet_id=TIMER_DESKTOP_ID,actual_original_AI_attempts=actual_attempts,
        collector_v1_schema_failure_preserved=True,
        historical_cutoff="Exactly two original AI checksum failures and completed desktop freeze/caller preparation; subsequent desktop V8 or native work is excluded")
    timer["preparation_field_mapping"]["actual_original_JSON_binding_required_before_append"]=True
    for key,value in new_observations.items():
        assert key not in separate;separate[key]=value
    retained=deepcopy(current)
    for key in new_observations:del retained["separate_source_observations"][key]
    assert same_typed(retained,prior["current_common_validation"])
    observation_scope={
        "source_commit":HEAD,"source_tree":TREE,"parent_commit":pub["parent"],
        "files_included":"Both original 007 RESULT.json files and complete commands.json indexes, plus three exact directly readable source patches",
        "complete_stdout_stderr_prefixes_archived_here":False,
        "external_original_prefixes":[str(R/pubprefix.rstrip("/")),str(R/readprefix.rstrip("/"))],
        "original_raw_log_hashes_referenced_by_commands":True,
        "raw_bytes_not_promoted_from_hash_references_to_archived_content":True,
        "original_21_metadata_observations_and_1281_actual_committed_files_verified":True,
        "source_patch_bytes_not_execution_or_native_pass":True,
        "reviewed_1651_byte_timer_patch_and_frozen_1919_byte_diff_are_distinct":True,
        "reviewed_patch_bytes_overlap_packet_members_not_additional_execution":True,
        "new_patch_files_need_index_and_commit_blob_verification_at_publication":True,
        "publication_or_readback_is_not_native_validation":True,
        "new_tests_executed":False,"physical_cost":None,"full_history_cost":None}
    inputs={
        "schema_version":1,"phase":"increment-008a",
        "expected_evidence_head":HEAD,"expected_evidence_tree":TREE,"expected_index_sha256":INDEX,
        "expected_prior_packet_count":83,"expected_final_packet_count":87,
        "expected_common_source_sha":SOURCE,"expected_common_source_tree":SOURCE_TREE,
        "formal_current_sha256":CURRENT,"current_common_validation":current,"packets":packets,
        "supplementary_observations":observation_rows,"supplementary_observation_scope":observation_scope,
        "independent_preparation_readbacks":independent_rows,
        "all_old_common_validation_fields_retained_typed":True,
        "only_new_current_validation_paths":[["separate_source_observations",key] for key in new_observations],
        "complete_execution_history":False,"physical_cost":None,"full_history_cost":None,
        "stage_advancement_claimed":False,"stages":{f"S{i}":"HOLD" for i in range(6)},
        "later_desktop_6ec_V8_or_strict_or_native_records_included":False,
        "preparation_scope":"Read-only exact terminal inputs; no append, evidence/source writes, tests or network calls."}
    payload=(json.dumps(inputs,indent=2,ensure_ascii=False)+"\n").encode()
    assert len(payload)<=490000
    after={"common":source(),"evidence":evidence()};assert before==after
    assert (W/REL/"manifest.json").read_bytes()==original
    for row in inventories+observation_states+independent_states:assert state(Path(row["path"]))==row["before"]
    write(OUT/"ARCHIVE_INPUTS_BEFORE_AFTER.json",inventories)
    write(OUT/"SUPPLEMENTARY_INPUTS_BEFORE_AFTER.json",observation_states)
    write(OUT/"INDEPENDENT_READBACK_INPUTS_BEFORE_AFTER.json",independent_states)
    write(OUT/"REQUIRED_JSON_PINS.json",json_pins)
    write(OUT/"SUPPLEMENTARY_OBSERVATION_SCOPE.json",observation_scope)
    write(OUT/"INDEPENDENT_READBACK_PINS.json",independent_rows)
    with (R/"increment008a-inputs.json").open("xb") as f:f.write(payload)
    result={
        "status":"read_only_inputs_prepared_not_appended",
        "inputs":{"path":str(R/"increment008a-inputs.json"),"bytes":len(payload),"sha256":digest(payload)},
        "packet_count_before":83,"packet_count_after_if_approved":87,"new_packet_count":4,
        "new_member_entries_with_overlap":635,"all_member_entries_with_prior_overlap":10104,
        "archive_bytes_total":sum(p["bytes"] for p in packets),
        "required_json_member_count":len(json_pins),"supplementary_json_observations":4,"directly_readable_source_patches":3,
        "all_required_json_bound_by_exact_bytes_and_whole_typed_object":True,
        "archive_hashes_and_file_counts_match":True,"all_inputs_before_after_unchanged":True,
        "all_old_bf42_validation_and_historical_cutoffs_retained_typed":True,
        "parent_publication_and_readback_commands_hash_links_verified":True,
        "independent_packet_readback_originals":independent_rows,
        "derived_AI_summary_field_mapping_note_preserves_original_null_and_overall_one":True,
        "new_desktop_dependency_or_native_observations_included":False,
        "common_and_evidence_before":before,"common_and_evidence_after":after,
        "appender_executed":False,"new_tests_executed":False,"network_calls":0,"source_mutation":False,
        "full_history_cost":None,"scientific_advancement_claimed":False,
        "finished_at":datetime.now(timezone.utc).isoformat()}
    write(OUT/"INPUT_PREPARATION.json",result)
    print(json.dumps(result),flush=True)

if __name__=="__main__":
    try:
        main()
    except BaseException as exc:
        if OUT.is_dir() and not (OUT/"INPUT_PREPARATION_FAILED.json").exists():
            write(OUT/"INPUT_PREPARATION_FAILED.json",{"status":"preparation_failed_not_appended","error":repr(exc),"new_tests_executed":False,"source_or_evidence_mutated":False,"full_history_cost":None,"finished_at":datetime.now(timezone.utc).isoformat()})
        raise

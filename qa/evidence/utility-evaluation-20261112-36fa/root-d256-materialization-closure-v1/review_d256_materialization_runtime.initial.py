#!/usr/bin/env python3
"""Review original d256 materialization records without dispatching H or modifying source."""
import hashlib,json,pathlib
R=pathlib.Path("/tmp/hepta-36fa-current-workspace-reconstruction-v3")
D=pathlib.Path("/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1")
def pin(raw):
    return {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}
def read(name,sha,base=D):
    raw=(base/name).read_bytes()
    assert pin(raw)["git_blob"]==sha,(name,pin(raw))
    return json.loads(raw)
def primary(obj):
    assert obj.get("isError") is False
    return json.loads(obj["content"][0]["text"])
result=read("RESULT.json","30ab4aad6ff10942063da972e02db49629e3809c")
normal=primary(read("STATUS_04.original.json","2a11b4b9e2baa380c247b6a728f90edfbcdcd644"))
admission=primary(read("MAIN_ADMISSION.original.json","0efe672783a0d3b5b68f17433859ec64ae48de74"))
request=read("MAIN_REQUEST.original.json","a5a3f6b6bcc0bdbfb4c36261d4c2d31f6fb5cefa")
approval=read("ROOT_D256_SINGLE_MATERIALIZATION_APPROVAL.json","a395a49b15c861be88d4e4e49f1e03557470ca55",R)
clarification=read("ROOT_MATERIALIZATION_INPUT_VERIFICATION_CLARIFICATION.json","8473a68b5906c4b31285749259a87158e2e8f0bf",R)
commands=read("COMMANDS.json","c3286df54535e30914d1d33e62cd9d19cc8f8246")
mutations=read("MUTATION_INTENTS.json","c4a8dbca67be8f9d30367a82e121f1f212532e64")
before=read("INPUT_IDENTITIES.before.json","e201c4c7f5fdcb485effad0514c7c51020bd5687")
after=read("INPUT_IDENTITIES.final.json","c25a91aab99d6492594684b08ca9a5b7f24178e2")
artifacts=read("ARTIFACTS.json","5d2eb472d5651500e02957013e5cdacb3f7b05af")
metadata=read("final.git-metadata.json","8d6af319d99c5f9c47e5a7e761c118c5ba2c767b")
readback=read("ACTUAL_ARTIFACT_READBACK_REVIEW.json","a7da58190ee8a0203a7e2ef628938f8f1714232e")
index_review=read("ROOT_D256_ACTUAL_INDEX_REVIEW.json","32d516ab084499572ad44bf17716fa964691524a",R)
job="1a1d468462a-392-3bb"
assert admission["audit_recorded"] and admission["launch"]["ok"] and not admission["reused"]
assert admission["local_record_pending"] is False
assert admission["job"]["id"]==normal["job_id"]==job
assert admission["job"]["env_keys"]==[]
assert set(request)=={"args","cwd","executable","host","idempotency_key","stdin","timeout_seconds"}
for field in ("args","cwd","executable","host","idempotency_key"):
    assert request[field]==admission["job"][field]
assert request["timeout_seconds"]==900
assert approval["approval_issued"] and approval["maximum_process_starts"]==1 and approval["maximum_fixed_create_only_stage_writes"]==5
assert approval["idempotency_key"]==request["idempotency_key"]
assert approval["main_request"]["git_blob"]==pin((D/"MAIN_REQUEST.original.json").read_bytes())["git_blob"]
assert normal["state"]=="succeeded" and normal["exit_code"]==0
assert normal["launch_nonce"]=="27c9390952a0a208dfcae8c66e25c805"
for key in ("automatic_retry","cancelled","timed_out"):
    assert normal[key] is False
for key in ("output_complete","output_durable","terminal_publication_confirmed"):
    assert normal[key] is True
for stream,size in (("stdout",2095),("stderr",0)):
    assert normal["log_bytes"][stream]=={"seen":size,"stored":size}
    assert normal["log_errors"][stream] is None
    assert normal["log_synced"][stream] is True
    assert normal["log_truncated"][stream] is False
chunks={"stdout":bytearray(),"stderr":bytearray()}
stream_pins=[]
for n,sha in enumerate(("689e9372d525fa48ed4e5b1df3c955334b27a9f4","2383505ac04eb43180e42a6bdcf22ba3440b74ac","e79e579a386c3417b4695556894a3e06150e85ab"),1):
    name=f"STREAM_READ_{n:02d}.original.json"
    raw=(D/name).read_bytes(); p=pin(raw); assert p["git_blob"]==sha
    x=primary(json.loads(raw));assert x["job_id"]==job and x["audit_recorded"]
    for stream in chunks:
        row=x[stream];actual=bytes.fromhex(row["bytes_hex"])
        assert row["offset"]==len(chunks[stream])
        assert row["next_offset"]==row["offset"]+len(actual)
        assert actual.decode()==row["text"]
        chunks[stream].extend(actual)
    stream_pins.append({"name":name,**p})
for stream,sha in (("stdout","c84b496372186628010c39c46d4dc908cbc49609"),("stderr","e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")):
    raw=bytes(chunks[stream])
    assert x[stream]["eof"] and x[stream]["next_offset"]==normal["log_bytes"][stream]["stored"]
    assert raw==(D/(stream.upper()+".complete.original.txt")).read_bytes()
    assert pin(raw)["git_blob"]==sha
assert len(commands)==40
assert all(c["returncode"]==0 and not c["timed_out"] and c["actual_terminal"]=="observed" for c in commands)
assert len(mutations)==4 and [m["ordinal"] for m in mutations]==[1,2,3,4]
assert all(m["actual_terminal"]=="observed" for m in mutations)
assert [m["kind"] for m in mutations]==["create_new_repository","write_exact_new_physical_source_and_standard_pack","import_independent_standard_pack","new_index_and_detached_head"]
assert mutations[1]["object_count"]==mutations[2]["objects"]==16661
assert mutations[1]["source_leaves"]==15243
assert mutations[3]["commit"]==result["source_commit"]=="d25675445c39f76db69a7bd8e71a1a72e1cd5b9f"
assert mutations[3]["tree"]==result["source_tree"]=="a489b394666b8141840275128a780605b024cde0"
after_map={v["path"]:{k:v[k] for k in ("bytes","git_blob","sha256")} for v in after}
assert len(after)==len(after_map)==len(before)==13 and after_map==before
assert len(artifacts)==267
am={a["name"]:a for a in artifacts};assert len(am)==267
for key,name in (("command_records","COMMANDS.json"),("mutation_records","MUTATION_INTENTS.json"),("input_records","INPUT_IDENTITIES.before.json"),("artifact_records","ARTIFACTS.json")):
    assert {k:result[key][k] for k in ("bytes","git_blob","sha256")}==pin((D/name).read_bytes())
for c in commands:
    for key in ("stdout","stderr"):
        assert am[c[key]["name"]]==c[key]
assert len(metadata)==6
assert len(result["final_audits"])==3 and all(a["status"]=="verified" for a in result["final_audits"])
assert {a["check"] for a in result["final_audits"]}=={"donor_physical_source_and_git_files","new_source_and_git","inputs_and_coordination"}
for prefix in ("current_source","current_git_state","donor_source","donor_git_state"):
    assert result[prefix+"_before"]==result[prefix+"_after"]
source=result["current_source_after"]
assert source["head"]==result["source_commit"] and source["tree"]==result["source_tree"]
assert source["parents"]==["cc57c7198db6293ccca562253c42fffbe2a04633"] and source["status"]==""
assert source["inventory"]["git_blob"]=="f1e2d72f99093581403a2dcc91b55da22a33f905"
assert source["native_inventory"]["git_blob"]=="7647480c5ed06525e1661ac451d0ac0ff2b23ea7"
assert result["physical_leaves_created"]==15243
assert result["new_objects_fully_verified"]==16661 and result["donor_objects_fully_verified"]==16449
assert result["qualification"] is False and result["test_commands_dispatched"]==0
for k in ("automatic_retry","cargo_or_formatter_started","dependency_installation_started","old_source_writes","remote_ref_updates","rollback"):
    assert result[k] is False
for k in ("action_completed","new_repo_created","new_files_and_directories_synced","input_identities_unchanged","donor_physical_and_git_file_state_unchanged"):
    assert result[k] is True
assert result["cleanup_errors"]==[]
assert result["status"]=="MATERIALIZED_EXACT_CANDIDATE_FOR_MAINTENANCE_REVIEW_ONLY"
assert index_review["entries"]==15243 and index_review["all_paths_modes_blob_ids_sizes_equal_actual_bound_frozen_inventory"]
assert index_review["footer_checksum_and_cache_tree_verified"] and index_review["original_binary_read_SDKs"]==17
assert result["coordination_lock"]["stat"]["st_mtime_ns"]==1794513889031523889
report={
 "format":"hepta-root-d256-original-runtime-closure-v1",
 "status":"ORIGINAL_MATERIALIZATION_RUNTIME_CLOSED_FOR_MAINTENANCE_REVIEW",
 "job":job,"launch_nonce":normal["launch_nonce"],"approval":pin((R/"ROOT_D256_SINGLE_MATERIALIZATION_APPROVAL.json").read_bytes()),
 "input_verification_clarification":pin((R/"ROOT_MATERIALIZATION_INPUT_VERIFICATION_CLARIFICATION.json").read_bytes()),
 "request":pin((D/"MAIN_REQUEST.original.json").read_bytes()),"admission":pin((D/"MAIN_ADMISSION.original.json").read_bytes()),
 "normal":pin((D/"STATUS_04.original.json").read_bytes()),"result":pin((D/"RESULT.json").read_bytes()),
 "source":source,"started_at":result["started_at"],"finished_at":result["finished_at"],
 "observed_command_count":40,"observed_mutation_count":4,"input_identities_unchanged":13,"listed_artifacts":267,
 "all_artifacts_externally_downloaded":False,
 "all_three_original_final_audits_verified":True,
 "original_stream_reads":stream_pins,"stdout":pin(bytes(chunks["stdout"])),"stderr":pin(bytes(chunks["stderr"])),
 "index_and_six_artifact_full_readback_review":pin((R/"ROOT_D256_ACTUAL_INDEX_REVIEW.json").read_bytes()),
 "new_objects_producer_fully_verified":16661,"donor_objects_producer_fully_verified":16449,
 "current_and_donor_source_and_git_states_before_after_equal":True,
 "same_job_request_key_and_no_retry":True,
 "actual_integer_handling":"All native JSON parsed with Python integers; no JavaScript serialization of ns metadata.",
 "scope":"Root independently verifies original records, stream bytes, and complete actual index. Full native source/object/stat audits are the original producer observations. No claim of separate Root H rescan or external download of all 267 artifacts.",
 "H_calls":0,"source_mutations":0,"test_commands_dispatched":0,"qualification":False,"real_authorized_task_chains":0
}
out=R/"ROOT_D256_MATERIALIZATION_RUNTIME_CLOSURE.json"
out.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
print(json.dumps({"path":str(out),**pin(out.read_bytes()),"status":report["status"]}))

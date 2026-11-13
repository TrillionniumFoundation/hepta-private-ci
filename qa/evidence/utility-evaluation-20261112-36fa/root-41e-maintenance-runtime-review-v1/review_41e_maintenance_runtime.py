#!/usr/bin/env python3
"""Close the actual 41e runtime using original retained bytes; no native actions."""
import base64,gzip,hashlib,json,pathlib,re
R=pathlib.Path("/tmp/hepta-36fa-current-workspace-reconstruction-v3")
D=pathlib.Path("/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1")
C=pathlib.Path("/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1/execution-candidate-v1")
def pin(b):return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def ident(p):return pin(p.read_bytes())
def sub(x):return {k:x[k] for k in ("bytes","sha256","git_blob")}
def j(p):return json.loads(p.read_bytes())
def primary(raw):
 x=json.loads(raw);assert x.get("isError") is False
 return json.loads(x["content"][0]["text"])
result=j(D/"RESULT.json");assert ident(D/"RESULT.json")["git_blob"]=="b87aed7647ac34e3db0e381110bf685438aee0ee"
normal=primary((D/"STATUS_06.original.json").read_bytes());assert ident(D/"STATUS_06.original.json")["git_blob"]=="70e1866f963a2a2a8d6f3bd468ddd0c291fbf871"
admission=primary((D/"MAIN_ADMISSION.original.json").read_bytes());request=j(D/"MAIN_REQUEST.original.json")
assert ident(D/"MAIN_REQUEST.original.json")["git_blob"]=="3dc51d216864f13a4fcd8c8ebceeb88ba3d8413d"
assert normal["job_id"]==admission["job"]["id"]=="1a1d47cebc8-392-41e"
assert admission["launch"]["ok"] and admission["reused"] is False and admission["job"]["env_keys"]==[]
for k in ("host","cwd","executable","args","idempotency_key"):assert admission["job"][k]==request[k]
assert request["timeout_seconds"]==9300 and "stdin" not in request and "env" not in request
assert normal["state"]=="succeeded" and normal["exit_code"]==0
for k in ("timed_out","cancelled","automatic_retry"):assert normal[k] is False
for k in ("output_complete","output_durable","terminal_publication_confirmed"):assert normal[k] is True
streams={"stdout":bytearray(),"stderr":bytearray()};stream_records=[]
for f in sorted(f for f in D.iterdir() if re.fullmatch(r"STREAM_READ_[0-9]{2}\.original\.json",f.name)):
 raw=f.read_bytes();x=primary(raw);assert x["job_id"]==normal["job_id"] and x["audit_recorded"]
 for key,b in streams.items():
  row=x[key];chunk=bytes.fromhex(row["bytes_hex"]);assert row["offset"]==len(b) and row["next_offset"]==len(b)+len(chunk)
  assert row["text"]==chunk.decode("utf-8");b.extend(chunk)
 stream_records.append({"name":f.name,**pin(raw)})
assert len(stream_records)==11
for key,n in (("stdout",119309),("stderr",0)):
 assert len(streams[key])==n and normal["log_bytes"][key]=={"seen":n,"stored":n}
 assert normal["log_synced"][key] and not normal["log_truncated"][key] and normal["log_errors"][key] is None
 assert bytes(streams[key])==(D/(key.upper()+".complete.original.txt")).read_bytes()
 assert x[key]["eof"] and x[key]["next_offset"]==n
a=j(D/"ARTIFACTS.json");am={v["name"]:v for v in a["files"]};assert len(am)==len(a["files"])==170
groups={};sdk_records=[]
for f in sorted(D.iterdir()):
 if not re.fullmatch(r".+\.READ_[0-9]{2}\.original\.json",f.name):continue
 raw=f.read_bytes();v=primary(raw);groups.setdefault(v["path"],[]).append(v);sdk_records.append({"name":f.name,**pin(raw)})
assert len(sdk_records)==38 and len(groups)==35
read_files=[];unlisted=set()
for path,rows in sorted(groups.items()):
 assert path.startswith("/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/")
 rows.sort(key=lambda r:r["offset"]);out=bytearray();version=rows[0]["version"];size=rows[0]["size"]
 for row in rows:
  chunk=base64.b64decode(row["data_base64"],validate=True)
  assert row["offset"]==len(out) and row["next_offset"]==len(out)+len(chunk)
  assert row["path"]==path and row["version"]==version and row["size"]==size
  assert hashlib.sha256(chunk).hexdigest()==row["chunk_sha256"];out.extend(chunk)
 assert row["eof"] and len(out)==size
 name=pathlib.Path(path).name;raw=bytes(out);assert raw==(D/name).read_bytes()
 if name in am:
  assert pin(raw)==sub(am[name])
  if "raw_git_blob" in am[name]:
   decompressed=gzip.decompress(raw);record=am[name]
   assert pin(decompressed)=={"bytes":record["raw_bytes"],"sha256":record["raw_sha256"],"git_blob":record["raw_git_blob"]}
 else:unlisted.add(name)
 read_files.append({"native_path":path,"name":name,**pin(raw),"version":version,"chunks":len(rows)})
assert unlisted=={"RESULT.json","ARTIFACTS.json","SOURCE_COORDINATION_EX.json","ACTUAL_LAUNCHER.py","ACTUAL_LAUNCHER_ARGV.json"}
for ordinal,name in enumerate(("fix","fmt")):
 terminal=j(D/(name+".terminal.json"));execution=j(D/(name+".execute_logged.original.json"))
 assert terminal==result["stages"][ordinal] and terminal["execution"]==execution
 assert terminal["status"]=="completed_review_required" and terminal["execution_outcome"]=="completed" and terminal["command_returned"]
 assert terminal["timeout_seconds"]==(7200 if name=="fix" else 900) and terminal["test_command"] is False
 assert execution["returncode"]==0 and execution["timed_out"] is False and execution["output_limit_exceeded"] is False
 assert execution["observed_passed_tests"]==execution["observed_failed_tests"]==0 and terminal["raw_log_retained"]
 assert terminal["retention"]["complete"] and terminal["maximum_log_bytes"]==67108864
log=bytes(streams["stdout"])[862:118383]
assert pin(log)["git_blob"]=="3fd1317daf9db7c84fe0956cbf75c8571cc7e80e"
assert log==(D/"fix.raw.log.exact_extracted.txt").read_bytes()
assert len(log)==result["stages"][0]["execution"]["log_bytes"] and pin(log)["sha256"]==result["stages"][0]["execution"]["log_sha256"]
assert (D/"fmt.raw.log").read_bytes()==b"" and result["stages"][1]["execution"]["log_bytes"]==0
states=[(D/n).read_bytes() for n in ("SOURCE_GIT_STATE.before.json","fix.after.git-state.json","fmt.after.git-state.json","final.git-state.json")]
assert len(set(states))==1 and pin(states[0])["git_blob"]=="aef9e645b81c2a7f349b11d546c5555b1475c906"
state=json.loads(states[0]);assert state["head"]=="d25675445c39f76db69a7bd8e71a1a72e1cd5b9f" and state["tree"]=="a489b394666b8141840275128a780605b024cde0"
before=gzip.decompress((D/"SOURCE_GIT_METADATA.before.json.gz").read_bytes());after=gzip.decompress((D/"SOURCE_GIT_METADATA.after.json.gz").read_bytes())
assert before==after==(D/"SOURCE_GIT_METADATA.before.json").read_bytes()==(D/"SOURCE_GIT_METADATA.after.json").read_bytes()
assert pin(before)["git_blob"]=="42e3986f6a5f06d8518067f0d9dd2ec3e6b46c6a"
commands=j(D/"READONLY_COMMANDS.json");assert len(commands)==32 and all(c["returncode"]==0 for c in commands)
inputs=j(D/"INPUT_IDENTITIES.json");assert len(inputs)==24
cfg=j(C/"MAINTENANCE_CONFIG.execution-candidate.json")
assert ident(C/"MAINTENANCE_CONFIG.execution-candidate.json")["git_blob"]=="7bddb6c423afbe739bc36a7df2516730911a9337"
env=j(D/"ENVIRONMENT_PREFLIGHT.json");assert env["effective_explicit_environment"]==cfg["environment"]
assert env["tool_or_dependency_installation_commands_executed"] is False
for obs in (env["process_observation"],j(D/"fix.process-preflight.json"),j(D/"fmt.process-preflight.json")):
 assert obs["active_matching_processes"]==[] and obs["unreadable_matching_processes"]==[]
assert (D/"ACTUAL_LAUNCHER.py").read_bytes()==(C/"LAUNCHER.execution-candidate.py").read_bytes()
argv=j(D/"ACTUAL_LAUNCHER_ARGV.json");assert argv["argv"]==[request["executable"],*request["args"]] and argv["cwd"]==request["cwd"]
lease=j(D/"SOURCE_COORDINATION_EX.json");assert lease["lock_acquired"]=="LOCK_EX|LOCK_NB" and lease["inheritable"] and lease["created"] is False
assert lease["inode"]==cfg["coordination_lock"]["stat"]["st_ino"]==50139448 and lease["device"]==2050
assert result["status"]=="MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED" and result["attempted_commands"]==["fix","fmt"] and result["not_run_commands"]==[]
assert result["source_preflight_complete"] and result["git_metadata_unchanged"] and result["test_commands_dispatched"]==0
assert result["qualification"] is False and result["automatic_retry"] is False and result["source_ref_updates"] is False
assert len(result["final_audits"])==2 and all(v["status"]=="verified" for v in result["final_audits"])
assert result["final_audits"][1]["input_count"]==24 and result["final_audits"][1]["unchanged"] is True
source_review=j(R/"ROOT_41E_ACTUAL_SOURCE_GRAPH_REVIEW.json");assert source_review["actual_final_physical_tree"]==result["actual_final_source"]["postimages"]["all_actual_physical_tree"]
report={"format":"hepta-root-41e-original-runtime-closure-v1","status":"ORIGINAL_FIX_AND_FMT_COMPLETED_WITH_COMPLETE_REVIEWED_RECORDS",
"job":normal["job_id"],"launch_nonce":normal["launch_nonce"],"result":ident(D/"RESULT.json"),"normal":ident(D/"STATUS_06.original.json"),"request":ident(D/"MAIN_REQUEST.original.json"),
"engineering_approval":ident(R/"ROOT_D256_ORDERED_MAINTENANCE_APPROVAL.json"),"stage410_independent_archive":"ed88974cded0eeb59516fee1373d31603aa88dfe",
"commands":[{"name":v["name"],"argv":v["argv"],"timeout_seconds":v["timeout_seconds"],"execution":v["execution"]} for v in result["stages"]],
"original_stream_reads":stream_records,"complete_stdout":pin(bytes(streams["stdout"])),"complete_stderr":pin(bytes(streams["stderr"])),
"fix_raw_log":{"identity":pin(log),"source":"Exact contiguous supervisor stdout interval 862..118383; not a separate H raw-log file read."},
"original_binary_read_sdks":sdk_records,"complete_actual_native_paths":read_files,"readonly_commands":32,"input_identities":24,"producer_final_input_audit_unchanged":True,
"four_actual_git_state_paths_equal":True,"both_actual_git_metadata_paths_equal":pin(before),"exact_original_environment_and_process_preflights":True,
"actual_source_graph_review":ident(R/"ROOT_41E_ACTUAL_SOURCE_GRAPH_REVIEW.json"),"actual_final_source":result["actual_final_source"],
"listed_artifacts":170,"all_170_artifacts_externally_downloaded":False,
"integer_handling":"All native metadata parsed with Python integers. No native nanosecond evidence serialized through JavaScript.",
"observation_errors":"Local observer post-loop condition and later local-save/text-read failures remain retained separately. Original H outcomes, saved SDK bytes and main terminal are unchanged; no replacement main was issued.",
"reviewer_initial_correction":"Initial stream filename wildcard also included later Git SDK wrappers. Exact original stream names are now selected; all eleven actual streams remain required. Initial reviewer and exit1 are preserved; no runtime input or predicate changed.",
"scope":"Original retained SDK/record bytes and complete source composition, not a second Root H scan or real task utility comparison.",
"test_commands_dispatched":0,"H_calls":0,"source_writes":0,"qualification":False,"real_qualified_chains":0}
o=R/"ROOT_41E_MAINTENANCE_RUNTIME_CLOSURE.json";o.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
print(json.dumps({"path":str(o),**ident(o),"binary_sdks":len(sdk_records),"complete_paths":len(groups),"streams":len(stream_records)}))

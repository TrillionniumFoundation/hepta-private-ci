#!/usr/bin/env python3
"""Offline producer/consumer check. Fixed retained bytes and memory-only adapters; no native access."""
import ast
import copy
import gzip
import hashlib
import json
import pathlib
import struct

HERE = pathlib.Path(__file__).resolve().parent
INPUT = HERE / "actual-inputs"
RUN = pathlib.Path("/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1")
AUTHOR = pathlib.Path("/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1")

def ident(raw):
    return {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}

def read_fixed(path, pin):
    raw = path.read_bytes()
    assert all(ident(raw)[key] == value for key,value in pin.items()), (str(path),ident(raw),pin)
    return raw

def freeze(name, raw):
    p=HERE/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():
        assert p.read_bytes()==raw, ("immutable output differs",str(p))
    else:
        with p.open("xb") as f:f.write(raw)
    return {"path":str(p),**ident(raw)}

cfg_raw=read_fixed(INPUT/"WAITING_CONFIG.ACTUAL_MATERIALIZATION.json",
                  {"git_blob":"eb322791ff64a67389b4e37b341bc01c63f3d5cb","bytes":13728,
                   "sha256":"63c1f09ffcd3e0cb97dcb0896c2831eb6ad5eb91e1091d66faf7a442c2c06ca8"})
cfg=json.loads(cfg_raw)
waiting=json.loads((HERE/"inputs/WAITING_CONFIG.E9308.json").read_bytes())
drv=read_fixed(HERE/"inputs/DRIVER_594610.HOLD.py",
               {"git_blob":"59461030d4160f7ad6a978df5a7b6aaeb33fb2a6","bytes":68520})
tree=ast.parse(drv.decode())
result_raw=read_fixed(INPUT/"RESULT.json",cfg["materialization"]["result"])
terminal_raw=read_fixed(INPUT/"STATUS_04.original.json",cfg["materialization"]["supervisor"])
result=json.loads(result_raw)
terminal_outer=json.loads(terminal_raw)
terminal=json.loads(terminal_outer["content"][0]["text"])
assert terminal["job_id"]==cfg["materialization"]["job_id"]=="1a1d468462a-392-3bb"
assert result["source_commit"]==cfg["source_commit"]
assert result["source_tree"]==cfg["source_tree"]
assert result["destination_repo"]==cfg["source_repo"]
assert result["current_source_before"]==result["current_source_after"]
assert result["current_source_before"]["inventory"]==cfg["source_inventory"]

record_names={
 "command_records":"COMMANDS.json","mutation_records":"MUTATION_INTENTS.json",
 "input_records":"INPUT_IDENTITIES.before.json","artifact_records":"ARTIFACTS.json"}
raw_records={}
for field,name in record_names.items():
    p=cfg["materialization"]["records"][field]
    raw_records[name]=read_fixed(INPUT/name,p)
    assert {k:result[field][k] for k in ("bytes","sha256","git_blob")}==p
    assert result[field]["name"]==name
artifacts=json.loads(raw_records["ARTIFACTS.json"])
assert len(artifacts)==267 and len({r["name"] for r in artifacts})==267
art_by_name={r["name"]:r for r in artifacts}
metadata_raw=read_fixed(INPUT/"final.git-metadata.json",cfg["materialization"]["git_metadata"])
metadata_gz=read_fixed(RUN/"final.git-metadata.json.gz",cfg["materialization"]["git_metadata_gzip"])
assert gzip.decompress(metadata_gz)==metadata_raw
meta_art=art_by_name["final.git-metadata.json.gz"]
assert {k:meta_art["raw_"+k] for k in ("bytes","sha256","git_blob")}==ident(metadata_raw)
assert {k:meta_art[k] for k in ("bytes","sha256","git_blob")}==ident(metadata_gz)
metadata=json.loads(metadata_raw)
assert len(metadata)==6 and len({x["path"] for x in metadata})==6
assert {x["path"] for x in metadata if "/" not in x["path"]}=={"HEAD","config","index"}
stat_keys={"st_dev","st_ino","st_mode","st_uid","st_gid","st_nlink","st_size","st_mtime_ns","st_ctime_ns"}
for row in metadata:
    assert set(row)=={"path","bytes","sha256","git_blob","stat"}
    assert set(row["stat"])==stat_keys and row["stat"]["st_size"]==row["bytes"]
    assert row["stat"]["st_nlink"]==1
    assert all(type(x) is int for x in row["stat"].values())
    assert not pathlib.PurePosixPath(row["path"]).is_absolute()
    assert ".." not in pathlib.PurePosixPath(row["path"]).parts
assert json.dumps(metadata,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()+b"\n"==metadata_raw
index_raw=read_fixed(RUN/"final.new-index.raw",cfg["materialization"]["index"]["raw"])
signature,version,count=struct.unpack(">4sII",index_raw[:12])
assert signature==b"DIRC" and version==2 and count==15243
assert hashlib.sha1(index_raw[:-20]).digest()==index_raw[-20:]
index_meta=next(row for row in metadata if row["path"]=="index")
assert {k:index_meta[k] for k in ("bytes","sha256","git_blob")}==ident(index_raw)
assert result["current_git_state_before"]==result["current_git_state_after"]==cfg["materialization"]["git_state"]
assert len(index_raw)==cfg["materialization"]["git_state"]["index_bytes"]
assert ident(index_raw)["sha256"]==cfg["materialization"]["git_state"]["index_sha256"]
for name,key in (("HEAD","head_raw_sha256"),("config","config_sha256")):
    row=next(r for r in metadata if r["path"]==name)
    assert row["sha256"]==cfg["materialization"]["git_state"][key]

lock_art=art_by_name["SOURCE_COORDINATION_EX.json"]
lock_raw=read_fixed(RUN/"SOURCE_COORDINATION_EX.json",{k:lock_art[k] for k in ("bytes","sha256","git_blob")})
assert json.loads(lock_raw)==result["coordination_lock"]==cfg["coordination_lock"]
assert cfg["coordination_lock"]["stat"]["st_ino"]==50139448
assert cfg["coordination_lock"]["stat"]["st_dev"]==2050
final_inputs_art=art_by_name["INPUT_IDENTITIES.final.json"]
final_inputs_raw=read_fixed(RUN/"INPUT_IDENTITIES.final.json",
                           {k:final_inputs_art[k] for k in ("bytes","sha256","git_blob")})
before_inputs=json.loads(raw_records["INPUT_IDENTITIES.before.json"])
after_inputs=json.loads(final_inputs_raw)
assert len(before_inputs)==len(after_inputs)==13
assert len({r["path"] for r in after_inputs})==13
assert {r["path"]:{k:r[k] for k in ("bytes","sha256","git_blob")} for r in after_inputs}==before_inputs

expected=copy.deepcopy(waiting)
expected["materialization"].update(
 job_id=terminal["job_id"],result=ident(result_raw),supervisor=ident(terminal_raw),
 git_state=result["current_git_state_after"],index=result["current_index"],
 git_metadata=result["current_git_metadata"],git_metadata_gzip=ident(metadata_gz),
 records={k:ident(raw_records[v]) for k,v in record_names.items()})
expected["coordination_lock"]=result["coordination_lock"]
for prose in ("waiting_for_actual_records","source_inventory_observation"):
    expected[prose]=cfg[prose]
assert expected==cfg, "actual-bound config differs beyond proof fields/lock/prose"
assert cfg["root_execution_approved"] is False and cfg["formal_approved_config_created"] is False
assert cfg["status"]==waiting["status"]=="HOLD_ACTUAL_MATERIALIZATION_AND_ROOT_EXACT_REVIEW_REQUIRED"
assert cfg["environment"]==waiting["environment"] and cfg["runtime_restoration"]==waiting["runtime_restoration"]
assert cfg["archive_restoration"]==waiting["archive_restoration"]

# Run only the original schema/pin predicates, with reads/writes adapted to fixed in-memory bytes.
# No reviewed module-level statements, main, preflight, current-source reader, Git or stage are executed.
names={"sha256","oid","check","nodup","parse","pin_bytes","parse_supervisor","validate_materialization"}
selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
assert {n.name for n in selected}==names and len(selected)==8
assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) for definition in selected for n in ast.walk(definition))
live_forbidden={"main","initial_preflight","environment_preflight","git","run_readonly","stage",
                "regular_read","open","exec","eval","subprocess"}
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in live_forbidden
               for definition in selected for n in ast.walk(definition))
parent=pathlib.Path(cfg["materialization"]["result_path"]).parent
memory={str(parent/"RESULT.json"):result_raw,
        cfg["materialization"]["supervisor_path"]:terminal_raw,
        str(parent/"final.git-metadata.json.gz"):metadata_gz}
memory.update({str(parent/name):raw for name,raw in raw_records.items()})
read_trace=[];write_trace={}
def memory_read(path,pin):
    key=str(path);assert key in memory, ("unprovided original input",key)
    body=memory[key]
    assert all(ident(body)[k]==pin[k] for k in ("bytes","sha256","git_blob"))
    read_trace.append({"path":key,**ident(body)})
    return body
def memory_write(name,body):
    assert name not in write_trace, name
    write_trace[name]=body
    return {"name":name,**ident(body)}
const={}
for n in tree.body:
    if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
        try:const[n.targets[0].id]=ast.literal_eval(n.value)
        except (ValueError,TypeError):pass
sandbox={
 "__builtins__":{"isinstance":isinstance,"str":str,"dict":dict,"list":list,"int":int,
                 "len":len,"set":set,"type":type,"all":all,"any":any,"ValueError":ValueError},
 "hashlib":hashlib,"json":json,"gzip":gzip,"pathlib":pathlib,
 "cfg":copy.deepcopy(cfg),"read_input":memory_read,"write":memory_write,
 "MATERIALIZATION_DONOR":pathlib.Path("/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1"),
 "REPO":pathlib.Path(cfg["source_repo"]),
 "COORDINATION_LOCK":pathlib.Path(cfg["coordination_lock"]["path"]),
 **{name:const[name] for name in ["HEAD","TREE","PARENTS","DONOR_HEAD","DONOR_TREE",
                                "SUCCESSOR_INVENTORY","NATIVE_INVENTORY","LEAVES"]}}
exec(compile(ast.Module(body=selected,type_ignores=[]),"<fixed-consumer-predicates-only>","exec"),sandbox,sandbox)
observed=sandbox["validate_materialization"]()
assert observed==result and len(read_trace)==7 and len(write_trace)==7
assert write_trace["MATERIALIZATION_GIT_METADATA.original.json"]==metadata_raw
commands=json.loads(raw_records["COMMANDS.json"])
mutations=json.loads(raw_records["MUTATION_INTENTS.json"])
assert len(commands)==40 and len(mutations)==4
assert all(r["actual_terminal"]=="observed" and r["returncode"]==0 and r["timed_out"] is False for r in commands)
assert all(r["actual_terminal"]=="observed" for r in mutations)

proof={
 "format":"hepta-a489-maintenance-independent-actual-binding-review-v1",
 "status":"ACTUAL_FIXED_PRODUCER_CONSUMER_MATCHED_MAINTENANCE_STILL_HOLD",
 "inputs":{
  "driver":ident(drv),"null_proof_HOLD":ident((HERE/"inputs/WAITING_CONFIG.E9308.json").read_bytes()),
  "actual_bound_HOLD":ident(cfg_raw),"result":ident(result_raw),"normal":ident(terminal_raw),
  "records":{k:ident(raw_records[v]) for k,v in record_names.items()},
  "full_git_metadata":ident(metadata_raw),"full_git_metadata_gzip":ident(metadata_gz),
  "actual_raw_index":ident(index_raw),"coordination":ident(lock_raw),"final_inputs":ident(final_inputs_raw)},
 "original_job_id":terminal["job_id"],
 "source":{"commit":result["source_commit"],"tree":result["source_tree"],"parents":result["parents"],
           "endpoint":result["current_source_after"],"source_before_after_equal":True,
           "raw_git_before_after_equal":True,"three_final_audits":result["final_audits"]},
 "config_changes_only_actual_proofs_lock_and_descriptive_fields":True,
 "original_historical_runtime_archive_environment_and_budgets_unchanged":True,
 "original_consumer_predicate_functions":[n.name for n in selected],
 "memory_only_original_validator_result_equal":True,"memory_reads":read_trace,
 "memory_writes":[{"name":k,**ident(v)} for k,v in write_trace.items()],
 "live_functions_never_called":["main","initial_preflight","environment_preflight",
                               "validate_materialization_current","stage","git","run_readonly"],
 "actual_counts":{"commands":40,"mutation_records":4,"input_identities":13,"artifacts":267,
                  "git_metadata_files":6,"materialized_leaves":15243,"new_objects":16661,"donor_objects":16449},
 "all_original_commands_normal0_no_timeout":True,"all_mutation_terminals_observed":True,
 "all_13_input_identities_before_after_equal":True,
 "metadata_whole_raw_gzip_and_all_nine_stat_field_types_checked":True,
 "raw_index_check":{"whole_bytes_pin_equal":True,"header_signature":"DIRC","version":version,
                    "entries":count,"trailer_sha1_equal":True,"metadata_pin_equal":True,
                    "scope":"Full retained bytes/header/trailer and producer identity checked; original producer's all-entry logical/stat checks remain bound, not independently rerun here."},
 "still_HOLD":{"status":cfg["status"],"root_execution_approved":False,
               "formal_approved_config_created":False,"exact_successor_launcher_and_typed_requests_reviewed":False},
 "qualification":False,"H_calls":0,"project_gate_or_Rust_runs":0,
 "scope":"Offline original retained-artifact verification and original consumer predicates with fixed-memory I/O only. No current native source/Git observation, no maintenance command, no new source/ref write.",
 "future_live_checks_required":"Original complete current source/Merkle and full Git-file/stat reconstruction, original environment/target/tool/process guard, unique inherited EX lock, exact separately approved staging/main."}
out=freeze("ACTUAL_BINDING_BYTE_AND_PREDICATE_REVIEW.json",(json.dumps(proof,indent=2,ensure_ascii=False)+"\n").encode())
freeze("actual-inputs/final.git-metadata.json.gz",metadata_gz)
freeze("actual-inputs/SOURCE_COORDINATION_EX.json",lock_raw)
freeze("actual-inputs/INPUT_IDENTITIES.final.json",final_inputs_raw)
print(json.dumps({"report":out,"job_id":terminal["job_id"],"consumer_result_equal":True,
                  "config_still_HOLD":True,"source_and_native_qualification":False}))

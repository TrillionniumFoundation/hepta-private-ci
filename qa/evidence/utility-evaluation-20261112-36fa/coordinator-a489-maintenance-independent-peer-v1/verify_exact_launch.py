#!/usr/bin/env python3
"""Pure exact request and embedded-file audit; never executes a launcher or stage."""
import ast
import base64
import copy
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
CANDIDATE=Path("/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1/execution-candidate-v1")
OLD_CONTROL="/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-maintenance-v1"
CONTROL="/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1"
OLD_REPO="/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1"
REPO="/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1"

def ident(b):
    return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def read_pin(p,expected):
    b=p.read_bytes()
    assert all(ident(b)[k]==v for k,v in expected.items()),(str(p),ident(b),expected)
    return b
def freeze(name,b):
    p=HERE/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==b,("immutable artifact differs",str(p))
    else:
        with p.open("xb") as f:f.write(b)
    return {"name":name,**ident(b)}
def jbytes(v):return (json.dumps(v,indent=2,ensure_ascii=False)+"\n").encode()
def assignment(code,name):
    lines=code.splitlines(keepends=True)
    ns=[n for n in ast.parse(code).body if isinstance(n,ast.Assign)
        and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
    assert len(ns)==1
    n=ns[0]
    return "".join(lines[n.lineno-1:n.end_lineno]),n.value
def helpers(code):
    lines=code.splitlines(keepends=True)
    return {n.name:"".join(lines[n.lineno-1:n.end_lineno]).encode()
            for n in ast.parse(code).body if isinstance(n,ast.FunctionDef)}
def invert(new,old,replacements):
    inv=new
    rows=[]
    for before,after in reversed(replacements):
        assert old.count(before)==1 and inv.count(after)==1,(before,after)
        inv=inv.replace(after,before)
        rows.append({"before":before,"after":after})
    assert inv==old
    assert ast.dump(ast.parse(inv),include_attributes=False)==ast.dump(ast.parse(old),include_attributes=False)
    return list(reversed(rows))
def calls(code,name):
    return [n for n in ast.walk(ast.parse(code)) if isinstance(n,ast.Call)
            and isinstance(n.func,ast.Attribute) and n.func.attr==name]

index_raw=read_pin(CANDIDATE/"FILE_INDEX.json",{"git_blob":"66ffc8b9969f30d149647bc83092e539aa899bd7","bytes":4201})
index=json.loads(index_raw)
assert len(index["files"])==17 and len({x["name"] for x in index["files"]})==17
files={}
for row in index["files"]:
    pin={k:row[k] for k in ("bytes","sha256","git_blob")}
    files[row["name"]]=read_pin(CANDIDATE/row["name"],pin)
old_main_raw=read_pin(HERE/"launch-inputs/OLD_MAIN.request.json",
                      {"git_blob":"c6a5a907647a97204878b5b5371eab540b778403","bytes":5371})
old_stage_raw=read_pin(HERE/"launch-inputs/OLD_STAGE.request.json",
                       {"git_blob":"dd593f5d41f7ecc46072f2fe60eb1047579588a2","bytes":150734})
old_main=json.loads(old_main_raw);old_stage=json.loads(old_stage_raw)
main_raw=files["PROCESS_INPUT.execution-candidate.json"]
stage_raw=files["STAGING_REQUEST.execution-candidate.json"]
main=json.loads(main_raw);stage=json.loads(stage_raw)
new_launcher=files["LAUNCHER.execution-candidate.py"].decode()
new_bootstrap=files["STAGING_BOOTSTRAP.execution-candidate.py"].decode()
old_launcher=old_main["args"][2];old_bootstrap=old_stage["args"][2]
assert main["args"]==["-B","-c",new_launcher] and stage["args"]==["-B","-c",new_bootstrap]
main_keys={"host","executable","args","cwd","idempotency_key","timeout_seconds"}
stage_keys=main_keys|{"stdin"}
assert set(main)==set(old_main)==main_keys and set(stage)==set(old_stage)==stage_keys
for req,old,seconds,key in (
 (main,old_main,9300,"hepta-utility-36fa-provider-coordinator-a489-maintenance-v1"),
 (stage,old_stage,900,"hepta-utility-36fa-provider-coordinator-a489-maintenance-control-staging-v1")):
    assert req["host"]==old["host"]=="desktop"
    assert req["executable"]==old["executable"]=="/usr/bin/python3"
    assert req["cwd"]==old["cwd"]=="/home/qian-qi"
    assert req["timeout_seconds"]==old["timeout_seconds"]==seconds
    assert type(req["timeout_seconds"]) is int
    assert req["idempotency_key"]==key and req["idempotency_key"]!=old["idempotency_key"]
    assert "env" not in req
assert main["idempotency_key"]!=stage["idempotency_key"]
assert len(stage_raw)<=1048576 and len(main_raw)<=1048576
payload_raw=stage["stdin"].encode()
assert payload_raw==files["STAGING_PAYLOAD.execution-candidate.json"] and len(payload_raw)<=1048576
payload=json.loads(payload_raw);old_payload=json.loads(old_stage["stdin"])
assert set(payload)=={"format","files"} and payload["format"]=="hepta-original-maintenance-control-staging-v1"
assert set(payload["files"])==set(old_payload["files"])=={
 "driver-maintenance.py","APPROVED_MAINTENANCE_CONFIG.json","inventory-driver.original.py",
 "MAINTENANCE_STARTED.original.json","MATERIALIZATION_SUPERVISOR.original.json","V8_RESTORATION_SUPERVISOR.original.json"}
stage_pins=ast.literal_eval(assignment(new_bootstrap,"PINS")[1])
main_pins=ast.literal_eval(assignment(new_launcher,"PINS")[1])
assert set(stage_pins)==set(payload["files"])
decoded={}
for name,enc in payload["files"].items():
    assert type(enc) is str
    decoded[name]=base64.b64decode(enc,validate=True)
    assert ident(decoded[name])==stage_pins[name]
    assert decoded[name]==files["staged-files/"+name]
assert set(main_pins)=={"driver-maintenance.py","APPROVED_MAINTENANCE_CONFIG.json"}
for name,pin in main_pins.items():
    assert pin==(ident(decoded[name])["bytes"],ident(decoded[name])["sha256"],ident(decoded[name])["git_blob"])
unchanged=[name for name in decoded if decoded[name]==base64.b64decode(old_payload["files"][name],validate=True)]
assert set(unchanged)=={"inventory-driver.original.py","MAINTENANCE_STARTED.original.json","V8_RESTORATION_SUPERVISOR.original.json"}
assert decoded["driver-maintenance.py"]==(HERE/"inputs/DRIVER_594610.HOLD.py").read_bytes()
assert decoded["MATERIALIZATION_SUPERVISOR.original.json"]==(HERE/"actual-inputs/STATUS_04.original.json").read_bytes()

cfg_raw=decoded["APPROVED_MAINTENANCE_CONFIG.json"];cfg=json.loads(cfg_raw)
actual_raw=(HERE/"actual-inputs/WAITING_CONFIG.ACTUAL_MATERIALIZATION.json").read_bytes()
actual=json.loads(actual_raw)
expected=copy.deepcopy(actual);expected["status"]="ROOT_APPROVED_TO_EXECUTE";expected["root_execution_approved"]=True
assert cfg==expected and cfg_raw==files["MAINTENANCE_CONFIG.execution-candidate.json"]
cfg_inverse=cfg_raw.replace(b'"status": "ROOT_APPROVED_TO_EXECUTE"',
                           b'"status": "HOLD_ACTUAL_MATERIALIZATION_AND_ROOT_EXACT_REVIEW_REQUIRED"',1)
cfg_inverse=cfg_inverse.replace(b'"root_execution_approved": true',b'"root_execution_approved": false',1)
assert cfg_inverse==actual_raw
assert cfg["formal_approved_config_created"] is False
assert cfg["materialization"]==actual["materialization"] and cfg["coordination_lock"]==actual["coordination_lock"]
assert cfg["source_repo"]==REPO and cfg["outer_timeout_seconds"]==9300
assert cfg["fix_seconds"]==7200 and cfg["fmt_seconds"]==900 and cfg["preflight_seconds"]==600 and cfg["record_seconds"]==300
assert cfg["minimum_target_free_bytes"]==34359738368 and cfg["create_target_if_absent"] is False
assert cfg["test_commands_authorized"] is False and cfg["remote_ref_updates_authorized"] is False

bootstrap_replacements=[]
for name in ("BASE","PINS"):
    before,_=assignment(old_bootstrap,name);after,_=assignment(new_bootstrap,name)
    bootstrap_replacements.append((before,after))
bootstrap_inverse=invert(new_bootstrap,old_bootstrap,bootstrap_replacements)
assert assignment(new_bootstrap,"BASE")[0]=="BASE = pathlib.Path("+repr(CONTROL)+")\n"
old_helpers=helpers(old_bootstrap);new_helpers=helpers(new_bootstrap)
assert list(old_helpers)==list(new_helpers)==["check","identity","real_parents","retain"]
assert old_helpers==new_helpers
assert not calls(new_bootstrap,"execv") and not calls(new_bootstrap,"flock")
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in ("exec","eval","compile")
               for n in ast.walk(ast.parse(new_bootstrap)))
assert "O_EXCL" in new_bootstrap and "O_NOFOLLOW" in new_bootstrap
assert "sys.stdin.buffer.read(1048577)" in new_bootstrap
assert "len(raw_input) <= 1048576" in new_bootstrap
assert "check(not os.path.lexists(BASE)" in new_bootstrap
assert "BOOTSTRAP_FAILURE.json" in new_bootstrap and "'partial_records_preserved': True" in new_bootstrap

launcher_replacements=[]
for name in ("ROOT","PINS"):
    before,_=assignment(old_launcher,name);after,_=assignment(new_launcher,name)
    launcher_replacements.append((before,after))
launcher_replacements.extend([
 (OLD_REPO,REPO),
 ("fixed_original_maintenance_0c59_launcher_verified","fixed_original_maintenance_coordinator_a489_launcher_verified")])
launcher_inverse=invert(new_launcher,old_launcher,launcher_replacements)
assert assignment(new_launcher,"ROOT")[0]=='ROOT=Path("'+CONTROL+'")\n'
assert helpers(new_launcher)==helpers(old_launcher)
assert list(helpers(new_launcher))==["need","sha","oid","read","save"]
assert len(calls(new_launcher,"flock"))==1 and len(calls(new_launcher,"set_inheritable"))==1 and len(calls(new_launcher,"execv"))==1
assert ast.unparse(calls(new_launcher,"flock")[0])=="fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)"
assert ast.unparse(calls(new_launcher,"set_inheritable")[0])=="os.set_inheritable(lock_fd, True)"
exec_call=ast.unparse(calls(new_launcher,"execv")[0])
assert exec_call=="os.execv('/usr/bin/python3', ['/usr/bin/python3', '-B', str(ROOT / 'driver-maintenance.py')])"
assert "os.open(LOCK,os.O_RDWR|os.O_NOFOLLOW)" in new_launcher
assert "config[\"coordination_lock\"][\"stat\"]" in new_launcher
assert "existing lock parent" in new_launcher
assert "not os.path.lexists(ROOT/\"run\")" in new_launcher
assert "'flock'" not in decoded["driver-maintenance.py"].decode() and b"fcntl" not in decoded["driver-maintenance.py"]
ordered=[
 'need(config["coordination_lock"]["path"]==str(LOCK)',
 '==config["coordination_lock"]["stat"]',
 "fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)",
 "os.set_inheritable(lock_fd,True)",
 'save("SOURCE_COORDINATION_EX.json"',
 'save("ACTUAL_LAUNCHER.py"',
 'os.execv("/usr/bin/python3"']
positions=[new_launcher.index(x) for x in ordered]
assert positions==sorted(positions)

main_inverse=copy.deepcopy(main);main_inverse["args"]=old_main["args"];main_inverse["idempotency_key"]=old_main["idempotency_key"]
stage_inverse=copy.deepcopy(stage);stage_inverse["args"]=old_stage["args"]
stage_inverse["idempotency_key"]=old_stage["idempotency_key"];stage_inverse["stdin"]=old_stage["stdin"]
assert jbytes(main_inverse)==old_main_raw and jbytes(stage_inverse)==old_stage_raw

proof={
 "format":"hepta-a489-maintenance-independent-exact-launch-review-v1",
 "status":"FIXED_CANDIDATE_REQUEST_BYTES_MATCH_ORIGINAL_CONTRACT_NO_DISPATCH",
 "input_index":ident(index_raw),"candidate_file_count":len(files),
 "inputs":[{"name":name,**ident(raw)} for name,raw in files.items()],
 "original_requests":{"main":ident(old_main_raw),"stage":ident(old_stage_raw)},
 "only_config_changed_fields":["status","root_execution_approved"],
 "config_two_field_inverse_full_bytes_equal":True,
 "candidate_permission_values_are_not_root_execution_authorization":True,
 "actual_materialization_proofs_unchanged_from_reviewed_eb322":True,
 "stage":{
  "request":ident(stage_raw),"key":stage["idempotency_key"],"field_count":7,
  "exact_field_names":list(stage),"host":stage["host"],"cwd":stage["cwd"],
  "executable":stage["executable"],"args_prefix":stage["args"][:2],
  "seconds":900,"env_present":False,"stdin":ident(payload_raw),"decoded_file_count":6,
  "decoded_files":{name:ident(raw) for name,raw in decoded.items()},
  "exact_unchanged_old_files":sorted(unchanged),
  "four_helper_bytes_equal":True,"whole_inverse_byte_and_ast_equal":True,
  "inverse_replacements":bootstrap_inverse,
  "no_lock_or_exec_or_driver_call":True,
  "new_private_directory_create_only":True,"existing_directory_rejected":True,
  "nine_stat_readback_and_fsync_unchanged":True,"failure_partial_records_preserved":True,
  "one_mib_request_and_input_limits_unchanged":True},
 "main":{
  "request":ident(main_raw),"key":main["idempotency_key"],"field_count":6,
  "exact_field_names":list(main),"host":main["host"],"cwd":main["cwd"],
  "executable":main["executable"],"args_prefix":main["args"][:2],
  "seconds":9300,"env_present":False,"stdin_present":False,
  "launcher":ident(new_launcher.encode()),"five_helper_bytes_equal":True,
  "whole_inverse_byte_and_ast_equal":True,"inverse_replacements":launcher_inverse,
  "exact_two_input_pins":{name:ident(decoded[name]) for name in main_pins},
  "same_actual_lock":cfg["coordination_lock"],"only_one_flock":True,
  "lock_existing_open_only":True,"lock_stat_before_EX_exact":True,
  "inheritable_before_exec":True,"original_exec_call":exec_call,
  "ordered_guard_lock_record_exec_fragments":list(zip(ordered,positions)),
  "driver_second_flock":False,
  "unknown_or_failed_identity_not_overwritten_or_automatically_retried":True},
 "both_typed_request_inverse_original_full_bytes_equal":True,
 "maintenance_budgets":{"preflight":600,"fix":7200,"fmt":900,"records":300,"main_outer":9300,"stage_outer":900},
 "dispatch_order_requirement":"Separate Root exact approval; one exact stage; actual same-job normal0, complete original staging readback and six input identities; only then one exact main. Unknown reconciles the original key/job and never advances.",
 "authority_boundary":"This script checks static data only. Candidate status/root_execution_approved values are proposed bytes; no H or maintenance permission is issued here.",
 "reviewed_code_executed":False,"H_calls":0,"Rust_or_QA_runs":0,"source_or_ref_writes":0,"qualification":False}
out=freeze("EXACT_LAUNCH_BYTE_REVIEW.json",jbytes(proof))
for name in ("FILE_INDEX.json","PROCESS_INPUT.execution-candidate.json","STAGING_REQUEST.execution-candidate.json",
             "MAINTENANCE_CONFIG.execution-candidate.json","LAUNCHER.execution-candidate.py",
             "STAGING_BOOTSTRAP.execution-candidate.py","STAGING_PAYLOAD.execution-candidate.json"):
    body=index_raw if name=="FILE_INDEX.json" else files[name]
    freeze("launch-inputs/NEW_"+name,body)
print(json.dumps({"report":out,"cfg_two_fields":True,"stage_fields":7,"main_fields":6,
                  "six_inputs":6,"sole_inherited_EX":True,"H_calls":0}))

#!/usr/bin/env python3
"""Pure exact request/payload review; does not run either embedded Python program."""
import ast
import base64
import hashlib
import json
import pathlib

HERE=pathlib.Path(__file__).resolve().parent
P=HERE/"execution-inputs"
I=HERE/"inputs"
A=pathlib.Path("/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1")

def identity(raw):
    return {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}

def read(name):
    raw=(P/name).read_bytes()
    assert json.loads((P/(name+".GET.original.json")).read_bytes())["structuredContent"]["content"].encode()==raw
    return raw

def defs(raw):
    s=raw.decode()
    return {n.name:(ast.get_source_segment(s,n),ast.dump(n,include_attributes=False)) for n in ast.parse(s).body
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}

def assigned(raw,name):
    node=next(n for n in ast.parse(raw).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
    return ast.literal_eval(node.value)

cfg_raw=read("MAINTENANCE_CONFIG.execution-candidate.json");cfg=json.loads(cfg_raw)
before_raw=(I/"MAINTENANCE_CONFIG.HOLD.json").read_bytes();before=json.loads(before_raw)
diff=json.loads(read("CONFIG_FOUR_AUTHORIZED_FIELDS.json"))
changed=[k for k in before if before[k]!=cfg[k]]
assert set(before)==set(cfg) and changed==["status","root_execution_approved","waiting_for_actual_records","formal_approved_config_created"]
assert len(diff)==4 and {r["field"] for r in diff}==set(changed)
for row in diff:assert before[row["field"]]==row["before"] and cfg[row["field"]]==row["after"]
assert cfg["status"]=="ROOT_APPROVED_TO_EXECUTE" and cfg["root_execution_approved"] is True
restored=dict(cfg)
for k in changed:restored[k]=before[k]
assert restored==before

launcher=read("LAUNCHER.execution-candidate.py");hold_launcher=(I/"LAUNCHER.HOLD.py").read_bytes()
old_pins=assigned(hold_launcher,"PINS");new_pins=assigned(launcher,"PINS")
assert set(new_pins)==set(old_pins)=={"driver-maintenance.py","APPROVED_MAINTENANCE_CONFIG.json"}
assert new_pins["driver-maintenance.py"]==old_pins["driver-maintenance.py"]
new_tuple=(len(cfg_raw),identity(cfg_raw)["sha256"],identity(cfg_raw)["git_blob"])
old_tuple=(len(before_raw),identity(before_raw)["sha256"],identity(before_raw)["git_blob"])
assert new_pins["APPROVED_MAINTENANCE_CONFIG.json"]==new_tuple
assert old_pins["APPROVED_MAINTENANCE_CONFIG.json"]==old_tuple
assert launcher.count(repr(new_tuple).encode())==1
assert launcher.replace(repr(new_tuple).encode(),repr(old_tuple).encode())==hold_launcher
assert defs(launcher)==defs(hold_launcher)

main_raw=read("PROCESS_INPUT.execution-candidate.json");main=json.loads(main_raw)
old_main_raw=(A/"inputs/ACTUAL_V5_PROCESS_INPUT.original.json").read_bytes();old_main=json.loads(old_main_raw)
assert set(main)==set(old_main)=={"host","executable","args","cwd","idempotency_key","timeout_seconds"}
assert main["args"]==["-B","-c",launcher.decode()]
assert main["timeout_seconds"]==old_main["timeout_seconds"]==9300
for key in ("host","executable","cwd"):assert main[key]==old_main[key]
assert main["idempotency_key"]=="hepta-utility-36fa-provider-0c59-maintenance-v1"
assert "env" not in main and "stdin" not in main

stage=read("STAGING_BOOTSTRAP.execution-candidate.py")
payload_raw=read("STAGING_PAYLOAD.execution-candidate.json");payload=json.loads(payload_raw)
request_raw=read("STAGING_REQUEST.execution-candidate.json");request=json.loads(request_raw)
assert set(request)=={"host","executable","args","cwd","idempotency_key","stdin","timeout_seconds"}
assert request["args"]==["-B","-c",stage.decode()] and request["stdin"].encode()==payload_raw
assert request["timeout_seconds"]==900 and len(payload_raw)<=1048576 and len(request_raw)<=1048576
for key in ("host","executable","cwd"):assert request[key]==main[key]
assert request["idempotency_key"]=="hepta-utility-36fa-provider-0c59-maintenance-control-staging-v1"
assert "env" not in request
assert set(payload)=={"format","files"} and payload["format"]=="hepta-original-maintenance-control-staging-v1"
pins=assigned(stage,"PINS")
assert set(pins)==set(payload["files"])=={"driver-maintenance.py","APPROVED_MAINTENANCE_CONFIG.json",
  "inventory-driver.original.py","MAINTENANCE_STARTED.original.json","MATERIALIZATION_SUPERVISOR.original.json",
  "V8_RESTORATION_SUPERVISOR.original.json"}
decoded={name:base64.b64decode(text,validate=True) for name,text in payload["files"].items()}
for name,raw in decoded.items():assert identity(raw)==pins[name]
assert decoded["driver-maintenance.py"]==(I/"driver-maintenance.HOLD.py").read_bytes()
assert decoded["APPROVED_MAINTENANCE_CONFIG.json"]==cfg_raw
assert decoded["MATERIALIZATION_SUPERVISOR.original.json"]==(I/"MATERIALIZATION_SUPERVISOR.original.json").read_bytes()
assert decoded["V8_RESTORATION_SUPERVISOR.original.json"]==(I/"RESTORE_V3_NORMAL.original.json").read_bytes()
assert pins["inventory-driver.original.py"]["git_blob"]=="51181866cbbb6e0176aab04117efffa8b6792b31"
assert pins["MAINTENANCE_STARTED.original.json"]["git_blob"]=="69a3d38ff1cf800813f1fbf1f30bca224157f223"

baseline=pathlib.Path("/tmp/hepta-36fa-new-source-materializer-hold-v1/MATERIALIZATION_BOOTSTRAP.candidate.py").read_bytes()
assert identity(baseline)["git_blob"]=="4df01b20c666912cf022c806be06ff8757b4714e"
old_helpers,new_helpers=defs(baseline),defs(stage)
assert set(new_helpers)==set(old_helpers)=={"check","identity","real_parents","retain"}
assert new_helpers==old_helpers
stage_ast=ast.parse(stage)
called=[]
for node in ast.walk(stage_ast):
    if isinstance(node,ast.Call):
        called.append(ast.unparse(node.func))
assert not any(name in called for name in ("exec","eval","os.execv","os.execve","subprocess.run","subprocess.Popen"))
assert "execv" not in stage.decode() and "subprocess" not in stage.decode()

# Structural lease order; no OS lock or subprocess is invoked here.
text=launcher.decode()
anchors=["lock_fd=os.open(LOCK,os.O_RDWR|os.O_NOFOLLOW)","lock_info=os.fstat(lock_fd)",
  "exact actual lock inode/stat; no replacement lock", "fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)",
  "os.set_inheritable(lock_fd,True)","save(\"SOURCE_COORDINATION_EX.json\"", "os.execv(\"/usr/bin/python3\""]
positions=[text.index(value) for value in anchors]
assert positions==sorted(positions)
assert "os.close(lock_fd)" not in text and "LOCK_UN" not in text and "O_CREAT" not in text[text.index("LOCK=Path"):text.index("lease=")]
assert cfg["coordination_lock"]["stat"]==json.loads((I/"MATERIALIZATION_RESULT.original.json").read_bytes())["coordination_lock"]["stat"]

report={"format":"hepta-independent-successor-exact-request-review-v1",
 "status":"EXACT_BYTES_CONSISTENT_PENDING_ROOT_APPROVAL_AND_ACTUAL_STAGING",
 "config":identity(cfg_raw),"launcher":identity(launcher),"main_request":identity(main_raw),
 "stage_bootstrap":identity(stage),"stage_payload":identity(payload_raw),"stage_request":identity(request_raw),
 "four_config_fields_only":changed,"all_other_config_values_equal":True,
 "launcher_inverse_config_tuple_replacement_reproduces_HOLD_full_bytes":True,
 "main_request_fields":sorted(main),"main_request_same_original_six_field_shape":True,
 "main_host":main["host"],"main_executable":main["executable"],"main_cwd":main["cwd"],
 "main_key":main["idempotency_key"],"main_outer_seconds":9300,"main_has_environment_override":False,
 "stage_request_fields":sorted(request),"stage_outer_seconds":900,"stage_key":request["idempotency_key"],
 "stage_payload_maximum_bytes":1048576,"stage_payload_actual_bytes":len(payload_raw),
 "six_strictly_decoded_complete_payloads":pins,"stage_four_original_helpers_byte_and_ast_equal":sorted(new_helpers),
 "stage_baseline":identity(baseline),"stage_has_no_main_exec_or_subprocess":True,
 "stage_scope":"Only fresh external evidence/control directory and fixed six files plus exact launcher/argv/payload/readback/failure records. Original source/result/environment paths are not modified.",
 "lease":{"existing_same_inode_only":True,"nine_stat_keys":sorted(cfg["coordination_lock"]["stat"]),
          "exclusive_nonblocking":True,"inheritable_before_exec":True,"no_unlock_or_close_before_exec":True,
          "path":cfg["coordination_lock"]["path"],"stat_matches_actual_materialization":True,
          "limitation":"Cooperative lock only; original complete source/Git verification and live global process guards remain mandatory."},
 "required_external_order":["Root approves these exact request bytes and conditions.",
   "Dispatch the exact stage request once; require original same-job normal exit0 and complete durable terminal.",
   "Read and verify STAGING_READBACK plus all six actual stored full file pins and retained launcher/payload; reject partial/failed/unknown staging.",
   "Only then dispatch the exact main request once; it opens the fixed existing lock, checks all original source/runtime/guard conditions and runs original fix then conditional fmt.",
   "Unknown reconciles original operation/key/bytes only; no new key, directory or request to bypass the state."],
 "future_live_checks_not_executed":True,"H_calls":0,"source_writes":0,"Rust_QA_formatter_calls":0,
 "qualification":False,"engineering_approval_granted_by_this_review":False}
out=HERE/"EXACT_REQUEST_DATAFLOW.json"
with out.open("xb") as f:f.write((json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode())
print(json.dumps({"report":str(out),**identity(out.read_bytes()),"six_payloads_verified":True,
                  "four_stage_helpers_exact":True,"main_fields":len(main),"stage_fields":len(request),"execution":False},sort_keys=True))

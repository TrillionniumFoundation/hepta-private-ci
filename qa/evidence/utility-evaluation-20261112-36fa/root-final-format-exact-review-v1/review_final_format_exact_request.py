#!/usr/bin/env python3
"""Root exact final-format candidate review. Pure byte/data checks; no native calls."""
import ast,base64,gzip,hashlib,json,pathlib
R=pathlib.Path("/tmp/hepta-36fa-current-workspace-reconstruction-v3")
D=pathlib.Path("/tmp/hepta-36fa-coordinator-a489-final-nonrust-preparation-v1")
C=D/"execution-candidate-v1";H=D/"launch-hold-v1"
def pin(b):return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def sub(x):return {k:x[k] for k in ("bytes","sha256","git_blob")}
def read(p,sha=None):
 b=p.read_bytes()
 if sha:assert pin(b)["git_blob"]==sha,(str(p),pin(b))
 return b
def jbytes(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
def assignments(raw):
 s=raw.decode();return {n.targets[0].id:ast.get_source_segment(s,n) for n in ast.parse(s).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
def functions(raw):
 s=raw.decode();return {n.name:ast.get_source_segment(s,n).encode() for n in ast.parse(s).body if isinstance(n,ast.FunctionDef)}
def inverse(raw,old,names):
 a,b=assignments(raw),assignments(old);s=raw.decode()
 for name in names:
  assert s.count(a[name])==1;s=s.replace(a[name],b[name],1)
 assert s.encode()==old
ledgerraw=read(R/"ROOT_FINAL_FORMAT_CONTROL_FULL_GET_LEDGER.json")
ledger=json.loads(ledgerraw);assert len(ledger["entries"])==61
for e in ledger["entries"]:assert e["full_GET"] is True and pin(read(pathlib.Path(e["local_path"])))==sub(e),e["path"]
old=read(D/"inputs/ORIGINAL_NONRUST_FMT_080753.py","080753bf6fa5070c0f71096ace0cf199762ee42c")
driver=read(D/"driver.HOLD.py","27c0db4e4bceb69bcaafc97f5cc843a37b180941")
oldf,newf=functions(old),functions(driver)
unchanged=[name for name in oldf if name in newf and oldf[name]==newf[name]]
assert sorted(unchanged)==["apply_packet","first_read","identity","lock_identity","main","retain_terminal"]
assert set(oldf)-set(newf)=={"prove_actual_capture"} and set(newf)-set(oldf)=={"prove_actual_maintenance"}
assert sorted(name for name in set(oldf)&set(newf) if oldf[name]!=newf[name])==["module_from_original","prepare"]
driver_ast=ast.parse(driver);const={n.targets[0].id:n.value for n in driver_ast.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
allowed=ast.literal_eval(const["NONRUST_PATHS"])
expected_paths=(".github/blob-size-allowlist.txt","CALLERS.toml","qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json","qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py")
assert allowed==expected_paths
assert [ast.literal_eval(const[x]) for x in ("PREFLIGHT_SECONDS","FMT_SECONDS","RECORD_SECONDS")]==[600,900,300]
calls=[n for n in ast.walk(driver_ast) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="stage"]
assert len(calls)==1 and ast.literal_eval(calls[0].args[0])=="fmt"
canonical=read(pathlib.Path("/tmp/hepta-36fa-coordinator-a489-final-canonical-preparation-v1/driver.HOLD.py"),"e8d606b801b54ab949c5f215c49cdf47ed0ea89a")
original_can=read(D/"inputs/ORIGINAL_CANONICAL_765ADA.py","765ada67a33f4d9aeaf29c9c522898057083cafb")
inverse(canonical,original_can,["REPO","CONTROL","INVENTORY","OLD","OLD_TREE","OLD_PARENTS","LEAVES"])
assert functions(canonical)==functions(original_can) and len(functions(canonical))==46
reconstructed={}
for directory in (H,C):
 enc=json.loads((directory/"ENCODING_MANIFEST.json").read_bytes())
 for member in enc["members"]:
  name_key="original_name" if directory==H else "name"
  assert name_key in member and ("name" if directory==H else "original_name") not in member
  member_name=member[name_key]
  chunks=[];offset=0
  for item in member["parts"]:
   b=read(directory/item["name"]);assert pin(b)==sub(item)
   q=base64.b64decode(b[:-1],validate=True);assert b==base64.b64encode(q)+b"\n"
   assert pin(q)==item["decoded"] and item["decoded_offset"]==offset
   chunks.append(q);offset+=len(q)
  z=b"".join(chunks);assert pin(z)==member["gzip"]
  raw=gzip.decompress(z);assert pin(raw)==member["raw"] and raw==read(directory/member_name)
  reconstructed[str(directory/member_name)]=raw
request_raw=reconstructed[str(C/"ACTUAL_PROCESS_INPUT.candidate.json")]
stdin_raw=reconstructed[str(C/"ACTUAL_STDIN.candidate.json")]
assert pin(request_raw)["git_blob"]=="9ca09c7e486277f72669173c649290d2124d794e"
assert pin(stdin_raw)["git_blob"]=="17a80f7079d350bafb73bcd82bb54c45a5f8c990"
req=json.loads(request_raw);oldreq=json.loads(reconstructed[str(H/"ACTUAL_PROCESS_INPUT.HOLD.json")])
bootstrap=read(C/"ACTUAL_BOOTSTRAP.candidate.py","3f4692a37efcdc6cb6cfe070f1d574d88fbea14a")
oldbootstrap=read(D/"inputs/ORIGINAL_9101_BOOTSTRAP.py","9ca752893983b582f2394c054e92a0adc265cb8f")
inverse(bootstrap,oldbootstrap,["BASE","PINS"])
assert functions(bootstrap)==functions(oldbootstrap) and len(functions(bootstrap))==4
holdbootstrap=read(H/"ACTUAL_BOOTSTRAP.HOLD.py","cb67cf33b0262e9c4836e16888d125d5ee9c7ed7")
inverse(bootstrap,holdbootstrap,["PINS"])
assert set(req)==set(oldreq)=={"args","cwd","executable","host","idempotency_key","stdin","timeout_seconds"}
assert {k:req[k] for k in req if k not in ("args","stdin")}=={k:oldreq[k] for k in oldreq if k not in ("args","stdin")}
assert req["host"]=="desktop" and req["cwd"]=="/home/qian-qi" and req["executable"]=="/usr/bin/python3"
assert req["idempotency_key"]=="hepta-utility-36fa-provider-coordinator-a489-final-nonrust-format-v1" and req["timeout_seconds"]==2100
assert req["args"]==["-B","-c",bootstrap.decode()] and req["stdin"].encode()==stdin_raw and len(stdin_raw)<=1048576
configraw=read(C/"APPROVED_CONFIG.candidate.json","c05c83f1b6ce14afa2bcef5c9e4d8eaae3059708")
boundraw=read(C/"REVIEW_BOUND_HOLD_CONFIG.json","26783f1a7de2bd49164b0f83675e3a6c732d3d96")
holdraw=read(H/"APPROVED_CONFIG.HOLD.json","92d3fa23a8894c6aed4d224b2ae9bfccfc8653e3")
cfg,bound,hold=map(json.loads,(configraw,boundraw,holdraw))
assert set(cfg)==set(bound)==set(hold)
assert sorted(k for k in cfg if cfg[k]!=bound[k])==["root_execution_approved","status"]
assert sorted(k for k in bound if bound[k]!=hold[k])==["root_input_review","source_peer_review","waiting_for"]
assert cfg["root_execution_approved"] is True and cfg["status"]=="ROOT_APPROVED_TO_EXECUTE"
assert bound["root_execution_approved"] is False and hold["root_execution_approved"] is False
inversecfg=dict(cfg);inversecfg.update(root_execution_approved=bound["root_execution_approved"],status=bound["status"]);assert jbytes(inversecfg)==boundraw
inversecfg.update({k:hold[k] for k in ("root_input_review","source_peer_review","waiting_for")});assert jbytes(inversecfg)==holdraw
assert cfg["root_input_review"]=="94c9d4fa5843806a0ae8e0a08296840c4ad625d9" and cfg["source_peer_review"]=="7dce432cbecd7b349db5e8599a8e1c58a0b7f4bf"
assert cfg["allowed_paths"]==list(allowed)
assert cfg["fix_authorized"] is cfg["test_commands_authorized"] is cfg["ref_updates_authorized"] is False
assert cfg["fmt_argv"]==["just","fmt","--base","c0f78493f815780f68b9bf5e390a21314d79311f"] and cfg["fmt_seconds"]==900
pins=ast.literal_eval(ast.parse(assignments(bootstrap)["PINS"]).body[0].value)
payload=json.loads(stdin_raw);oldpayload=json.loads(reconstructed[str(H/"ACTUAL_STDIN.HOLD.json")])
assert set(payload)=={"format","files"} and payload["format"]=="hepta-final-nonrust-format-bootstrap-v1"
assert set(payload["files"])==set(pins)=={"driver.py","APPROVED_CONFIG.json","NONRUST_PACKET.json","MAINTENANCE_NORMAL.original.json"}
assert [k for k in payload["files"] if payload["files"][k]!=oldpayload["files"][k]]==["APPROVED_CONFIG.json"]
decoded={}
for name,encoded in payload["files"].items():
 raw=base64.b64decode(encoded,validate=True)
 if name=="NONRUST_PACKET.json":raw=gzip.decompress(raw)
 assert pin(raw)==pins[name];decoded[name]=raw
assert decoded["driver.py"]==driver and decoded["APPROVED_CONFIG.json"]==configraw
strict=read(pathlib.Path("/tmp/hepta-36fa-a489-maintenance-nonrust-apply-packet-v1/NONRUST_PACKET.json"),"ab032ffdfd8b540a0d3a82558d8a07e70ab0c548")
assert decoded["NONRUST_PACKET.json"]==strict and [x["path"] for x in json.loads(strict)["changes"]]==list(allowed)
assert pins["MAINTENANCE_NORMAL.original.json"]["git_blob"]=="70e1866f963a2a2a8d6f3bd468ddd0c291fbf871"
report={"format":"hepta-root-final-format-exact-request-byte-review-v1","H_calls":0,"qualification":False,"native_dispatch_authorized_by_this_review":False,"full_GET_ledger":pin(ledgerraw),"full_GET_ledger_entries":61,"request":pin(request_raw),"stdin":pin(stdin_raw),"bootstrap":pin(bootstrap),"driver":pin(driver),"config":pin(configraw),"review_bound_HOLD":pin(boundraw),"original_HOLD":pin(holdraw),"config_review_binding_changes":["root_input_review","source_peer_review","waiting_for"],"config_permission_changes":["root_execution_approved","status"],"whole_byte_config_inverses_equal":True,"bootstrap_full_inverse_original_BASE_PINS":True,"unchanged_thin_functions":unchanged,"canonical_seven_constants_inverse_equal":True,"canonical_unchanged_functions":46,"canonical_execution_authorized":False,"four_payload_pins":pins,"exact_allowed_paths":list(allowed),"new_explicit_JSON_permission_target":allowed[2],"old_path_rule_pure_subset":False,"other_QA_wildcard_write_permission_removed":True,"outer_seconds":2100,"preflight_apply_seconds":600,"fmt_seconds":900,"record_seconds":300,"single_EX":"Only original thin main. Bootstrap stages and execs without acquiring or inheriting EX.","idempotency_key":req["idempotency_key"],"source_peer":"7dce432cbecd7b349db5e8599a8e1c58a0b7f4bf","control_peer":"0216a7064812580ba6e2eb8db3fbc9ef71f19a8d","exact_request_peer":"12c4dce5eb6b587e437ba961abc283916c17e301","root_actual_maintenance_runtime_review":"775898e4ef848f9203576a5efac2da4c505bc39d","root_actual_complete_source_review":"43d03bd7f8d663de9893fd603ff0162ab03c349b","root_nonrust_projection_review":cfg["root_input_review"],"status":"EXACT_STATIC_BYTES_REVIEWED_WAITING_ROOT_DISPATCH_DECISION","limits":["No native functions executed by this review; all live guards must still pass in the exact approved job.","No real A/B/C task or owner authority, causal outcome/cost/evaluator independence or process cold recovery is established.","Any missing or failed actual proof remains Unknown/failed; no retry, rollback, overwrite or new identity."]}
out=jbytes(report);(R/"ROOT_FINAL_FORMAT_EXACT_REQUEST_REVIEW.json").write_bytes(out)
print(json.dumps({"review":pin(out),"request":pin(request_raw),"config":pin(configraw),"no_H":True}))

import base64,hashlib,json
from pathlib import Path
D=Path(__file__).parent
def pins(b):return dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),git_blob=hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest())
def put(n,b):
 p=D/n
 if p.exists():assert p.read_bytes()==b,n
 else:
  with p.open("xb") as f:f.write(b)
def canon(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
def sdk(p):
 x=json.loads(p.read_bytes());assert not x.get("isError"),p.name
 if x.get("structuredContent") is not None:return x["structuredContent"]
 texts=[x["text"] for x in x["content"] if x.get("type")=="text"];assert len(texts)==1
 return json.loads(texts[0])
indexraw=(D/"CLOSED_RUNTIME_ARCHIVE_INPUTS.json").read_bytes();index=json.loads(indexraw);job=index["job_id"]
proof={}
for p in sorted(D.glob("*.PUBLISH_GET.original.json")):
 n=p.name.removesuffix(".PUBLISH_GET.original.json");body=(D/n).read_bytes();f=json.loads(p.read_bytes());cpath=D/(n+".PUBLISH_CREATE.original.json");c=json.loads(cpath.read_bytes());q=pins(body)
 assert not f.get("isError") and not c.get("isError")
 assert f["structuredContent"]["content"].encode()==body and c["structuredContent"]["sha"]==q["git_blob"]
 proof.setdefault(q["git_blob"],dict(body_name=n,create_response=dict(name=cpath.name,**pins(cpath.read_bytes())),full_get_response=dict(name=p.name,**pins(p.read_bytes()))))
ledger=[]
for r in index["files"]:
 b=(D/r["name"]).read_bytes();q=pins(b);assert q=={k:r[k] for k in q};assert len(b)<=512000;b.decode()
 assert q["git_blob"] in proof,r["name"]
 ledger.append({**r,"actual_git_create_and_full_get_equal":True,"publication_response_proof":proof[q["git_blob"]]})
normal=sdk(D/"STATUS_06.original.json");assert normal["job_id"]==job and normal["state"]=="succeeded" and normal["exit_code"]==0
assert normal["output_complete"] and normal["output_durable"] and normal["terminal_publication_confirmed"]
for k in ["timed_out","cancelled","automatic_retry"]:assert normal[k] is False
for v in normal["log_errors"].values():assert v is None
for v in normal["log_truncated"].values():assert v is False
streams={"stdout":bytearray(),"stderr":bytearray()};intervals=[]
for i in range(1,12):
 n="STREAM_READ_"+str(i).zfill(2)+".original.json";r=sdk(D/n);assert r["job_id"]==job;row={"sdk":n}
 for k in streams:
  x=r[k];b=bytes.fromhex(x["bytes_hex"]);assert x["offset"]==len(streams[k]) and x["next_offset"]==x["offset"]+len(b)
  assert b.decode("utf-8",errors="replace")==x["text"];assert x["size"]>=x["next_offset"];streams[k].extend(b);row[k]={"offset":x["offset"],"next_offset":x["next_offset"],"eof":x["eof"]}
 intervals.append(row)
for k,b in streams.items():
 assert b==(D/(k.upper()+".complete.original.txt")).read_bytes()
 assert len(b)==normal["log_bytes"][k]["seen"]==normal["log_bytes"][k]["stored"]
 assert normal["log_synced"][k] is True
binary={}
for r in index["files"]:
 if ".READ_" not in r["name"]:continue
 z=sdk(D/r["name"]);b=base64.b64decode(z["data_base64"],validate=True)
 assert hashlib.sha256(b).hexdigest()==z["chunk_sha256"] and z["next_offset"]==z["offset"]+len(b)
 binary.setdefault(z["path"],[]).append((z,r["name"],b))
bs=[]
for path,chunks in sorted(binary.items()):
 chunks.sort(key=lambda x:x[0]["offset"]);off=0;b=bytearray();version=chunks[0][0]["version"]
 for z,n,q in chunks:
  assert z["offset"]==off and z["version"]==version;off=z["next_offset"];b.extend(q)
 assert chunks[-1][0]["eof"] and off==chunks[-1][0]["size"]
 bs.append(dict(native_path=path,version=version,**pins(b),chunks=[x[1] for x in chunks]))
R=json.loads((D/"RESULT.json").read_bytes());A=json.loads((D/"ARTIFACTS.json").read_bytes())
assert R["qualification"] is False and R["test_commands_dispatched"]==0 and R["source_ref_updates"] is False
commands=json.loads((D/"READONLY_COMMANDS.json").read_bytes());assert len(commands)==32 and all(c["returncode"]==0 for c in commands)
inputs=json.loads((D/"INPUT_IDENTITIES.json").read_bytes());assert len(inputs)==24
fix=json.loads((D/"fix.after.postimages.json").read_bytes());fmt=json.loads((D/"fmt.after.postimages.json").read_bytes());final=json.loads((D/"final.postimages.json").read_bytes())
assert fix["after_inventory_sha256"]==fmt["base_inventory_sha256"] and fmt["after_inventory_sha256"]==final["after_inventory_sha256"]
assert fix["base_inventory_sha256"]==final["base_inventory_sha256"]
assert [len(x["changes"]) for x in [fix,fmt,final]]==[12,14,17]
assert {x["path"] for x in final["changes"]}=={x["path"] for x in fix["changes"]}|{x["path"] for x in fmt["changes"]}
gitnames=["SOURCE_GIT_STATE.before.json","fix.after.git-state.json","fmt.after.git-state.json","final.git-state.json"]
assert all((D/n).read_bytes()==(D/gitnames[0]).read_bytes() for n in gitnames)
assert (D/"SOURCE_GIT_METADATA.before.json").read_bytes()==(D/"SOURCE_GIT_METADATA.after.json").read_bytes()
for n in ["fix","fmt"]:
 t=json.loads((D/(n+".terminal.json")).read_bytes());e=json.loads((D/(n+".execute_logged.original.json")).read_bytes());assert t["execution"]==e and e["returncode"]==0 and e["timed_out"] is False and e["output_limit_exceeded"] is False
review={"format":"hepta-completed-maintenance-runtime-closure-v1","job_id":job,"closed_input_index":pins(indexraw),"explicit_payload_count":len(ledger),"unique_payload_blobs":len({x["git_blob"] for x in ledger}),"all_payload_git_full_get_verified":True,"normal":normal,"actual_binary_reads":{"sdk_count":sum(len(x["chunks"]) for x in bs),"complete_original_file_paths":len(bs),"failures_observed_in_these_native_sdk_results":0,"files":bs},"complete_streams":{"stdout":pins(streams["stdout"]),"stderr":pins(streams["stderr"]),"intervals":intervals},"original_command_record_count":32,"original_input_record_count":24,"artifact_catalog_named_entries":len(A["files"]),"catalog_limitation":"The catalog names 170 retained artifacts. This archive explicitly covers the 116 local payloads, 35 complete native paths and stated representations; it does not claim separately downloading every artifact.","actual_transition_counts":{"fix":12,"fmt":14,"final_union":17},"source_and_git":{"head_unchanged":"d25675445c39f76db69a7bd8e71a1a72e1cd5b9f","head_tree_unchanged":"a489b394666b8141840275128a780605b024cde0","actual_final_physical_tree":"c026a8d7e93c958b39a36c666debecb3dba4be14","four_original_git_states_fullbytes_equal":True,"two_original_git_metadata_fullbytes_equal":True,"metadata_integer_handling":"Python integer parsing and exact original bytes only"},"source_full_inventory_transport":"Separately recovered by ordinary_path from pre-held full inventory and actual complete postimage records, requiring all producer raw/gzip/part pins; no duplicate H full inventory read is claimed.","observer_errors":[{"record":"OBSERVER_POSTLOOP_ERROR_REVIEW.json","scope":"g2:665 local JS postprocessing condition error after original H results saved"},{"record":"FUNCTIONS_G2_688_OBSERVATION_ERRORS.json","scope":"local read/save branches threw; all five H SDK originals were found complete and verified without repeating H reads","followup":"PATCHES_AND_SUMMARIES_READBACK_REVIEW.json"}],"test_commands_dispatched":0,"qualification":False,"new_native_main_or_source_mutation_during_collection":False,"represented_companions":index["represented_companions"]}
put("RUNTIME_COMPLETE_READBACK_LEDGER.json",canon({"format":"hepta-runtime-complete-git-readback-ledger-v1","entries":ledger}))
put("RUNTIME_COMPLETE_READBACK_REVIEW.json",canon(review))
print(json.dumps({"review":pins(canon(review)),"ledger":pins(canon({"format":"hepta-runtime-complete-git-readback-ledger-v1","entries":ledger})),"counts":{"payloads":len(ledger),"binary_sdks":sum(len(x["chunks"]) for x in bs),"binary_files":len(bs)},"source_review_complete":True},indent=2))

from pathlib import Path
import json,hashlib,re
B=Path("/workspace/scratch/08f5efd48967");D=B/"hepta-cell/qualification/cell-unification-20261106";U=D/"history/source51-report-update";OLD=D/"history/source49-r23-checkpoint"
def load(p):return json.loads(Path(p).read_bytes())
def jd(o):return (json.dumps(o,ensure_ascii=False,indent=2)+"\n").encode()
def pin(p,raw=None):
 p=Path(p);raw=p.read_bytes() if raw is None else raw
 try:n=p.relative_to(D).as_posix()
 except ValueError:n=str(p)
 return dict(path=n,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),git_blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest())
def create(p,raw):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==raw,str(p)
 else:
  with p.open("xb") as f:f.write(raw)
 return pin(p,raw)
oldraw={n:(OLD/n).read_bytes() for n in ["README.md","STATUS.json","SOURCE_IDENTITY.json"]}
expected={"README.md":"d73b5224327a01f59aa5e739cff1d3a7ea836a0366cf065dbcfb46dfce668712","STATUS.json":"82b7faba60db84719daa30e0f34ac9bb98d5a6a40987b183c564d37eeb3c297b","SOURCE_IDENTITY.json":"3d136a9015c73643d8db728cc9f4026c012f25b3ab536a8c8f04446e7e0d701d"}
for n,raw in oldraw.items():assert hashlib.sha256(raw).hexdigest()==expected[n] and (D/n).read_bytes()==raw
candidate={"README.md":(U/"README.candidate.md").read_bytes(),"STATUS.json":(U/"STATUS.candidate.json").read_bytes(),"SOURCE_IDENTITY.json":(U/"SOURCE_IDENTITY.candidate.json").read_bytes()}
s=json.loads(candidate["STATUS.json"]);i=json.loads(candidate["SOURCE_IDENTITY.json"]);s0=json.loads(oldraw["STATUS.json"]);i0=json.loads(oldraw["SOURCE_IDENTITY.json"]);readme=candidate["README.md"].decode();oldread=oldraw["README.md"].decode()
assert s["current_source"]["commit"]==i["current_source_commit"]=="e28b0f385ee882f842911044958b2810f62f6379";assert s["current_source"]["tree"]==i["current_source_tree"]=="763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
assert s["current_source"]["scope"]==i["source_scope"]
scope=i["source_scope"];assert (scope["changed_source_paths"],scope["rust_paths"],scope["other_paths"],scope["owner_package_count"],scope["ci_package_selector_count"])==(194,180,14,26,27)
ledgerp=D/"history/source51-ledger-snapshot/publication-ledger.json";ledger=load(ledgerp);assert i["created_source_commits"]==ledger["commits"] and len(ledger["commits"])==51 and len(ledger["created_blobs"])==176
preserved=["overall","taxonomy","source_inputs","implementation","science","source_compatibility","historical_assets","upstream_ci_history"]
for k in preserved:assert s[k]==s0[k],k
for g in ["r20","r21","r22","r23"]:assert s["validation"]["gates"][g]==s0["validation"]["gates"][g]
assert i["scientific_reference_source"]==i0["scientific_reference_source"]
assert readme[readme.index("## 1."):readme.index("## 2.")]==oldread[oldread.index("## 1."):oldread.index("## 2.")]
assert readme[readme.index("## 4."):readme.index("## 5.")]==oldread[oldread.index("## 4."):oldread.index("## 5.")]
r26=s["validation"]["gates"]["r26"];assert r26==i["pending_native_gates"]["r26"]==s["next_source_preparation"]["r26"];assert r26["state"]=="RUNNING_PYTHON_PASS_STRICT_STARTED" and r26["python_exit_code"]==0 and r26["python_counts"]["executed"]==32
assert r26["strict_exit_code"] is r26["tests_raw_exit_code"] is r26["original_outer_exit_code"] is None and all(v is None for v in r26["counts"].values())
assert s["validation"]["gates"]["r24"]["counts"]==dict(unique_test_results=1564,passed=1561,failed=3,timed_out=0,reported_skipped=3)
assert not s["overall"]["all_engineering_blockers_closed"] and not s["overall"]["default_workspace_gate_pass"]
assert not s["publication"]["branch_created"] and not s["publication"]["pull_request_created"] and not s["final_fix_fmt"]["fix_executed"] and not s["final_fix_fmt"]["fmt_executed"]
# Verify links against current local bytes plus the exact published checkpoint leaf map.
mp=B/"publication-recovery-prep/checkpoint4-actual-leaf-map.json";mapraw=mp.read_bytes();assert len(mapraw)==228219 and hashlib.sha256(mapraw).hexdigest()=="be37e4960b6bb22a57ddfbae85dfb4d77a680765d6b6f598a3e056e46273f93c";mapping=json.loads(mapraw);assert mapping["count"]==len(mapping["files"])==1369 and mapping["checkpoint_commit"]=="464603f9b710d24b52dd5ba5f2dc34207352397d"
mapcopy=create(U/"checkpoint4-actual-leaf-map.json",mapraw)
prefix="qualification/cell-unification-20261106/"
refs={}
for label,target in re.findall(r"(?m)^\[([^\]]+)\]:\s*(\S+)\s*$",readme):
 if not target.startswith(("https://","http://","#")):refs.setdefault(target,[]).append("README:"+label)
def walk(v,location):
 if isinstance(v,dict):
  for k,x in v.items():walk(x,location+"."+k)
 elif isinstance(v,list):
  for n,x in enumerate(v):walk(x,location+"["+str(n)+"]")
 elif isinstance(v,str) and v.startswith(("native-evidence/","history/","study-evidence/")) and not any(c in v for c in ("\n"," ","{","}")):
  refs.setdefault(v,[]).append(location)
for n,o in [("STATUS",s),("SOURCE_IDENTITY",i)]:walk(o,n)
checked=[];missing=[]
for target,places in sorted(refs.items()):
 t=target.split("#",1)[0];p=D/t
 if p.is_file():
  checked.append(dict(path=target,resolution="LOCAL_FILE",actual_git_blob=pin(p)["git_blob"],references=places))
 elif prefix+t in mapping["files"]:
  checked.append(dict(path=target,resolution="REGISTERED_CHECKPOINT464_BLOB_NOT_RAW_BYTES_REHASHED",git_blob=mapping["files"][prefix+t],references=places))
 else:missing.append(dict(path=target,references=places))
assert not missing,missing
# Validate complete hash pins for local report artifacts; remote-only references retain their original SHA provenance.
pinned=[]
def verify_pins(v,location):
 if isinstance(v,dict):
  p=v.get("path")
  if isinstance(p,str) and p.startswith(("native-evidence/","history/","study-evidence/")) and "sha256" in v:
   actual=D/p
   if actual.is_file():
    q=pin(actual)
    for k in ["bytes","sha256","git_blob"]:
     if k in v:assert v[k]==q[k],(location,k,v[k],q[k])
    pinned.append(dict(path=p,scope="LOCAL_RAW_BYTES",location=location))
   elif prefix+p in mapping["files"]:
    if "git_blob" in v:assert v["git_blob"]==mapping["files"][prefix+p],(location,p)
    pinned.append(dict(path=p,scope="REMOTE_BLOB_ID_ONLY_ORIGINAL_RAW_PIN_NOT_REHASHED",location=location))
  for k,x in v.items():verify_pins(x,location+"."+k)
 elif isinstance(v,list):
  for n,x in enumerate(v):verify_pins(x,location+"["+str(n)+"]")
verify_pins(s,"STATUS");verify_pins(i,"SOURCE_IDENTITY")
linkreport=dict(schema="hepta.source51-report-link-readback.v1",map=mapcopy,distinct_referenced_paths=len(checked),local_paths=sum(x["resolution"]=="LOCAL_FILE" for x in checked),registered_remote_only_paths=sum(x["resolution"]!="LOCAL_FILE" for x in checked),checked=checked,pinned_references=pinned,missing=[],remote_original_bytes_not_redownloaded=True)
linkpin=create(U/"LINK-READBACK.json",jd(linkreport))
for n,raw in candidate.items():(D/n).write_bytes(raw);assert (D/n).read_bytes()==raw
result=dict(schema="hepta.source51-current-report-adoption.v1",state="SOURCE51_APPLIED_R26_PYTHON_PASS_STRICT_STARTED_NO_RUST_TERMINAL",previous_artifact_commit=mapping["checkpoint_commit"],prior_exact_report_snapshot=pin(OLD/"MANIFEST.json"),fixed_ledger_snapshot=pin(ledgerp),outputs=[pin(D/n) for n in candidate],checks=dict(exact_previous_report_bytes_preserved=True,fixed_51_source_and_176_binary_ledger_snapshot=True,scientific_status_fields_preserved=preserved,README_taxonomy_and_science_sections_byte_equal=True,original_r20_through_r23_gate_records_unchanged=True,current_source_and_scope_match=True,r26_counts_null_except_closed_Python32=True,source50_Rust_failed100_preserved=True,final_fix_fmt_not_executed=True,branch_and_PR_not_created=True),link_readback=linkpin,modified_only_three_current_reports_and_new_history=True,ledger_source_old_formal_groups_modified=False,rust_training_or_native_probe_executed=False)
rp=create(U/"REPORT-ADOPTION.json",jd(result))
roots=["source49-r23-checkpoint","source51-ledger-snapshot","source51-registration","source51-apply-checkpoint","source51-scope-preparation","source51-r26-launch","source51-r26-python-checkpoint","source51-report-update"]
allfiles=[D/n for n in candidate]+[p for name in roots for p in sorted((D/"history"/name).rglob("*")) if p.is_file() and p.name!="HANDOFF-MANIFEST.json"]
assert len(allfiles)==len(set(allfiles))
handoff=dict(schema="hepta.source51-current-report-handoff.v1",status="FROZEN_CURRENT_REPORT_AND_HISTORY_SNAPSHOT",snapshot_state=result["state"],source_commit=i["current_source_commit"],source_tree=i["current_source_tree"],files=[pin(p) for p in allfiles],file_count=len(allfiles),bytes=sum(p.stat().st_size for p in allfiles),all_UTF8=True,no_binary_upload_required=True,report_adoption=rp,mutable_ledger_not_touched=True,old_formal_groups_not_touched=True,terminal_Rust_qualification_not_claimed=True)
hp=create(U/"HANDOFF-MANIFEST.json",jd(handoff))
print(json.dumps(dict(report_adoption=rp,link_readback=linkpin,handoff=hp,files=len(allfiles),bytes=handoff["bytes"],reports=result["outputs"]),ensure_ascii=False))


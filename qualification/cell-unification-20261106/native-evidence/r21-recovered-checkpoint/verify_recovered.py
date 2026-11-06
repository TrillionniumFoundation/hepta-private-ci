#!/usr/bin/env python3
"""New post-recovery readback. Never runs Rust or mutates original evidence."""
from pathlib import Path, PurePosixPath
import argparse,collections,gzip,hashlib,io,json,re,stat,tarfile
C={
20:dict(prefix="native-app-server-r20",size=1271446,sha="926c742219a6fae6bd96c0997d72bf730930e120a5f7bbf528383ec96466bfe7",blob="2b1933b3437a8caff85bfe2aa56b43c06e4ab56b",members=210,sources=187,tree="e65356fc570296b74644967054eaded15b8ed440",source="native-candidate-r20-source.json",run=1495,skip=2,rc=0),
21:dict(prefix="native-workspace-r21",size=1190333,sha="1d9c0dc71fdda73158d1011d828046aa3c6f02219ed311a10d6e864795519652",blob="8ddbd58b9be4c3efde5b971ad3e772909c3eba2e",members=206,sources=187,tree="e65356fc570296b74644967054eaded15b8ed440",source="native-candidate-r20-source.json",run=None,skip=None,rc=101),
22:dict(prefix="native-app-server-client-r22",size=1145892,sha="c7a770bfa2d17e23c05009862c688ab70fed4b30744df7642fe5d2db75b95e95",blob="dc38717525e664bb0da982f24a8c2f9b6b451a57",members=215,sources=188,tree="be34ab1afe622ad3b8f030c8c5018f4f54fbc304",source="native-candidate-r22-source.json",run=30,skip=0,rc=0)}
OLD={20:("r20-project-checkpoint",16165,"5534ba07505f98c7ca1fb8146862b055fc26df58c3fe5f546138686dea735382"),21:("r21-workspace-checkpoint",7687,"3ee7fff91796550272569f56792caf9d35c67cdb52ac0a90e294143b93332e4a"),22:("r22-client-checkpoint",10400,"be06d7952fe5fc52449cd4400efd7e79860b9c2fd16332795cb589bc9af3d5f2")}
LOCK="4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
ROW=re.compile(rb"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$")
START=re.compile(rb"^\s*Starting ([0-9]+) tests across ([0-9]+) binar(?:y|ies)(?: \(([0-9]+) tests skipped\))?\s*$")
SUMMARY=re.compile(rb"^\s*Summary \[\s*([0-9.]+)s\]\s+([0-9]+) tests run: (.+)$")
def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def pin(b):return dict(bytes=len(b),sha256=sha(b),git_blob=blob(b))
def enc(x):return (json.dumps(x,ensure_ascii=False,indent=2)+"\n").encode()
def js(p):return json.loads(p.read_bytes())
def write(p,b):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==b,f"Refusing unequal existing artifact: {p}"
 else:
  with p.open("xb") as f:f.write(b)
 assert p.read_bytes()==b
def lines(b):
 o=0
 for n,l in enumerate(b.splitlines(keepends=True),1):
  yield n,o,l
  o+=len(l)
def lp(n,o,l):return dict(line=n,byte_start=o,byte_end=o+len(l),sha256=sha(l),text=l.decode().rstrip("\r\n"))
def archive_check(w,s,c):
 p=w/"native-validation-results"/f"checkpoint-r{s}";a=w/"native-validation-results"/f"checkpoint-r{s}-closed.tar.gz";raw=a.read_bytes()
 assert pin(raw)==dict(bytes=c["size"],sha256=c["sha"],git_blob=c["blob"])
 idx=js(p/"INDEX.json");by={x["path"]:x for x in idx};assert len(by)==len(idx)==c["members"]-1
 members=[]
 with tarfile.open(fileobj=io.BytesIO(raw),mode="r:gz") as t:
  ms=t.getmembers();assert len(ms)==c["members"]
  seen=set()
  for m in ms:
   q=PurePosixPath(m.name);assert m.isfile() and not q.is_absolute() and ".." not in q.parts and m.name not in seen
   seen.add(m.name);b=t.extractfile(m).read();assert (p/m.name).is_file() and (p/m.name).read_bytes()==b
   if m.name!="INDEX.json":
    x=by[m.name];assert len(b)==x["bytes"] and sha(b)==x["sha256"]
    if "mode" in x:assert int(str(x["mode"]),8)&0o7777==m.mode&0o7777
   members.append(dict(path=m.name,**pin(b),tar_mode=format(m.mode,"o")))
  assert seen==set(by)|{"INDEX.json"}
 assert {str(q.relative_to(p)) for q in p.rglob("*") if q.is_file()}==set(by)|{"INDEX.json"}
 source=js(p/"evidence"/c["source"]);assert source["source_tree"]==c["tree"] and source["lock_sha256"]==LOCK
 files=source["changed_files"];assert len(files)==len({x["path"] for x in files})==c["sources"];sources=[]
 for x in files:
  b=(p/"source"/x["path"]).read_bytes();assert pin(b)=={k:x[k] for k in ("bytes","sha256","git_blob")}
  mode=int(x["mode"],8);assert stat.S_IFMT(mode)==stat.S_IFREG and mode&0o7777==int(by["source/"+x["path"]]["mode"],8)&0o7777
  sources.append(dict(path=x["path"],**pin(b),git_mode=x["mode"]))
 assert {"source/"+x["path"] for x in files}=={x for x in by if x.startswith("source/")}
 assert sha((p/"input/Cargo.lock").read_bytes())==LOCK
 assert sha((p/"source/.github/workflows/hepta-cell-framework-native.yml").read_bytes())==source["workflow_sha256"]
 inputs=[q for q in (p/"input").iterdir() if q.name.startswith("stage") and q.name.endswith(".tar.gz")]
 if inputs:assert len(inputs)==1 and sha(inputs[0].read_bytes())==source["input_archive_sha256"]
 return p,a,source,members,sources
def phase_check(p,s,c,source):
 e=p/"evidence";prefix=c["prefix"];env=js(e/(prefix+"-environment.json"));assert env["source_tree"]==c["tree"]
 if "source_manifest_sha256" in env:assert env["source_manifest_sha256"]==sha((e/c["source"]).read_bytes())
 out={}
 for phase in (["tests"] if s==21 else ["strict","tests"]):
  name=prefix+"-"+phase;rpath=e/(name+"-receipt.json");rawpath=e/(name+"-raw-process-result.json")
  r=js(rpath);raw=js(rawpath);log=(e/(name+".log")).read_bytes();res=(e/(name+"-resources.txt")).read_bytes();expected=c["rc"] if phase=="tests" else 0
  assert r["exit_code"]==raw["exit_code"]==expected
  for field in ("source_tree","source_commit","command","cwd","start_unix","end_unix"):assert r[field]==raw[field]
  assert r["source_tree"]==c["tree"] and r["source_commit"]==source["source_commit"]
  assert r["log_sha256"]==sha(log) and r["resources_sha256"]==sha(res)
  assert abs(r["elapsed_seconds"]-(raw["end_unix"]-raw["start_unix"]))<1e-6
  assert int(re.search(rb"^\s*Exit status:\s*(\d+)\s*$",res,re.M)[1])==expected
  assert re.search(rb'Command being timed: "(.*)"',res)[1].decode()==" ".join(r["command"])
  if s==21:
   assert r["command"]==["just","test","--locked","--retries","0"];guardname=prefix+"-source-post-test-verification.json"
  else:
   command=["just","clippy","--locked"] if phase=="strict" else ["just","test","--locked"]
   for pkg in (["codex-app-server","codex-linux-sandbox"] if s==20 else ["codex-app-server-client"]):command+=["-p",pkg]
   command+=["--","-D","warnings"] if phase=="strict" else ["--retries","0"];assert r["command"]==command;guardname=name+"-source-post-verification.json"
  g=js(e/guardname)
  assert g["pass"] and g["actual_tree"]==g["expected_tree"]==c["tree"] and g["file_mismatches"]==g["untracked_paths"]==g["unstaged_paths"]==[]
  assert g["changed_file_count"]==c["sources"] and g["lock_sha256"]==LOCK and g["gate_exit_code"]==expected
  out[phase]=dict(command=r["command"],exit_code=expected,elapsed_seconds=r["elapsed_seconds"],receipt=pin(rpath.read_bytes()),raw_process_result=pin(rawpath.read_bytes()),log=pin(log),resources=pin(res),source_guard=dict(path=guardname,**pin((e/guardname).read_bytes()),passed=True))
 tp=e/(prefix+"-terminal-process-status.json");t=js(tp)
 assert t["exit_code"]==c["rc"] and not t["timed_out"] and not t["cancelled"] and t["output_complete"] and t["output_durable"] and t["terminal_publication_confirmed"]
 assert not any(t["log_truncated"].values())
 if s==21:
  g=js(e/(prefix+"-source-pre-verification.json"));assert g["pass"] and g["actual_tree"]==g["expected_tree"]==c["tree"]
 else:
  co=js(e/(prefix+"-complete.json"));assert co["source_tree"]==c["tree"] and co["strict_exit"]==co["tests_exit"]==0 and not co["fix_fmt_executed"]
 return out,dict(path=tp.name,**pin(tp.read_bytes()),job=t["job_id"],exit_code=t["exit_code"],state=t["state"],cancelled=False,timed_out=False)
def log_check(p,s,c):
 e=p/"evidence";prefix=c["prefix"];log=(e/(prefix+"-tests.log")).read_bytes();rows=[];starts=[];sums=[];errors=[];after=False
 for n,o,l in lines(log):
  m=START.match(l)
  if m:starts.append(dict(**lp(n,o,l),tests=int(m[1]),binaries=int(m[2]),reported_skip=int(m[3] or b"0")))
  m=SUMMARY.match(l)
  if m:sums.append(dict(**lp(n,o,l),seconds=float(m[1]),tests_run=int(m[2])));after=True
  m=ROW.match(l)
  if m and not after:rows.append(dict(status=m[1].decode(),seconds=float(m[2]),binary=m[3].decode(),name=m[4].decode(),**{k:v for k,v in lp(n,o,l).items() if k!="text"}))
  if re.match(rb"^error\[E\d+\]",l):errors.append((n,o,l))
 assert len(rows)==len({(r["binary"],r["name"]) for r in rows})
 if s==21:
  assert rows==starts==sums==[] and len(errors)==2;blocks=[]
  for n,o,l in errors:
   end=log.find(b"\n\n",o);assert end!=-1;b=log[o:end+2]
   assert b.startswith(b"error[E0063]: missing field") and b"trace" in b and b"app-server-client/src/remote_process_indeterminate_tests.rs" in b
   blocks.append(dict(line=n,byte_start=o,byte_end=end+2,**pin(b),text=b.decode()))
  assert {re.search(r"remote_process_indeterminate_tests.rs:(\d+):(\d+)",b["text"]).groups() for b in blocks}=={("71","66"),("92","58")}
  assert b"cargo test --no-run" in log and b"exited with code 101" in log
  return rows,dict(state="COMPILE_FAILED_NEXTEST_NOT_STARTED",test_execution_started=False,unique_test_results=None,passed=None,failed=None,timed_out=None,reported_skipped=None,execution_rows_observed=0,starting_lines=[],summary_lines=[],compiler_errors=blocks)
 assert len(starts)==len(sums)==1 and len(rows)==c["run"] and starts[0]["tests"]==sums[0]["tests_run"]==len(rows)
 assert starts[0]["reported_skip"]==c["skip"]
 counts=collections.Counter(r["status"] for r in rows);assert counts=={"PASS":c["run"]}
 assert re.search(rf"\b{c['run']} passed\b",sums[0]["text"]) and int(re.search(r"(\d+) skipped",sums[0]["text"])[1])==c["skip"]
 orig=js(e/(prefix+"-test-results.json"));assert [{k:r[k] for k in ("status","seconds","binary","name")} for r in rows]==orig
 result=dict(state="PASS",test_execution_started=True,unique_test_results=len(rows),passed=counts["PASS"],failed=0,timed_out=0,reported_skipped=c["skip"],individual_skip_identities_inferred=False,starting_lines=starts,summary_lines=sums,per_package=dict(collections.Counter(r["binary"].split("::")[0] for r in rows)),compiler_errors=[],raw_failure_blocks=[])
 if s==20:
  baseline=js(p/"input/original-app-server-test-results.json");old={(r["binary"],r["name"]):r for r in baseline};new={(r["binary"],r["name"]):r for r in rows}
  assert len(old)==1345 and set(old)=={k for k in new if k[0].split("::")[0]=="codex-app-server"}
  fail=[r for r in baseline if r["status"]=="FAIL"];assert len(fail)==7
  result["original_app_server_id_set_exact"]=True;result["original_seven"]=[dict(previous=r,current=new[(r["binary"],r["name"])]) for r in fail]
  names=["owner_lifetime::tests::already_exited_owner_is_rejected_before_payload_start","owner_lifetime::tests::owner_exit_is_observed_after_observer_start","owner_lifetime::tests::inherited_owner_handle_is_resealed_before_inner_setup","suite::landlock::sandbox_payload_does_not_inherit_the_owner_pidfd"]
  result["new_owner_fd_cases"]=[]
  for name in names:
   found=[r for r in rows if r["name"]==name];assert len(found)==1 and found[0]["status"]=="PASS";result["new_owner_fd_cases"]+=found
 else:
  assert orig==js(e/(prefix+"-closed-test-results.json"))==js(e/(prefix+"-closed-v2-test-results.json"))
  cor=js(e/(prefix+"-readback-correction-v2.json"));ex=js(e/(prefix+"-export-v1-terminal-process-status.json"))
  assert ex["exit_code"]==cor["v1_export_exit"]==1 and cor["original_gate_unchanged"] and not cor["rust_or_tests_rerun"] and cor["test_log_sha256"]==sha(log)
  for item in cor["superseded_files"]:assert sha((e/item["path"]).read_bytes())==item["sha256"]
  result["export_history"]=dict(v1_export_exit=1,original_rust_gate_exit=0,v1_v2_and_raw_log_rows_equal=True,v1_bad_starting_assumption_preserved=True,correction=cor,no_rust_rerun=True)
  result["repaired_fixture"]=[r for r in rows if r["name"]=="remote::process_indeterminate_tests::process_spawn_checks_this_connection_echo_and_decodes_unknown_notifications"];assert len(result["repaired_fixture"])==1
 return rows,result
def scope_check(p):
 e=p/"evidence";mp=e/"native-workspace-r21-metadata.json";m=js(mp);s=js(e/"native-workspace-r21-scope.json")
 assert sha(mp.read_bytes())==s["metadata_sha256"];members=set(m["workspace_members"]);defaults=set(m["workspace_default_members"])
 assert len(members)==len(defaults)==193 and members==defaults;packages={x["id"]:x["name"] for x in m["packages"]}
 for key,ids in [("workspace_members",members),("workspace_default_members",defaults)]:
  assert {x["id"] for x in s[key]}==ids and all(packages[x["id"]]==x["name"] for x in s[key])
 return dict(actual_workspace_members=193,actual_default_members=193,same_member_id_set=True,metadata=pin(mp.read_bytes()),command_package_selector_added=False,all_features_platforms_external_services_qualified=False)
def oracles(p):
 command=p/"source/codex-rs/app-server/tests/suite/v2/command_exec.rs";landlock=p/"source/codex-rs/linux-sandbox/tests/suite/landlock.rs";t=command.read_text()
 def fn(text,name):
  a=text.index(name);a=text.rfind("\n",0,a)+1;return text[a:text.index("\n}\n",a)+3].encode()
 dis=fn(t,"async fn command_exec_process_ids_are_connection_scoped_and_disconnect_terminates_process");helper=fn(t,"async fn wait_for_process_marker")
 assert b"time.sleep(30)" in dis and b"ws1.close(None).await?" in dis and b"Duration::from_secs(5)" in helper and b"Duration::from_millis(50)" in helper
 fd=fn(landlock.read_text(),"async fn sandbox_payload_does_not_inherit_the_owner_pidfd")
 for token in [b"PermissionProfile::read_only()",b"PermissionProfile::workspace_write_with(",b"NetworkSandboxPolicy::Restricted",b"/*exclude_tmpdir_env_var*/ true",b"/*exclude_slash_tmp*/ true",b"anon_inode:[pidfd]",b"SHORT_TIMEOUT_MS"]:assert token in fd
 assert re.search(rb"const SHORT_TIMEOUT_MS:\s*u64\s*=\s*5_000",landlock.read_bytes())
 return dict(disconnect_source=pin(command.read_bytes()),disconnect_function=pin(dis),marker_helper=pin(helper),payload_sleep_seconds=30,marker_timeout_seconds=5,poll_interval_ms=50,fd_source=pin(landlock.read_bytes()),fd_function=pin(fd),fd_profiles=2,fd_timeout_ms=5000,both_launcher_execution_forced=False,source47_function_byte_identity_recomputed_here=False,boundary="Current frozen source oracles read. Historical original source47 byte comparison not recomputed without the original.")
def copy_original(mapping,dest,source,label):
 raw=source.read_bytes();compress=False
 if len(raw)>=100000 and not source.name.endswith((".gz",".zip",".png",".pdf")):
  try:raw.decode("utf-8");compress=True
  except UnicodeDecodeError:pass
 output=dest.with_name(dest.name+".gz") if compress else dest;b=gzip.compress(raw,compresslevel=9,mtime=0) if compress else raw
 if compress:assert b[4:8]==b"\0\0\0\0" and gzip.decompress(b)==raw
 write(output,b);mapping.append(dict(source=label,destination=str(output),encoding="gzip-mtime-zero" if compress else "identity",original=pin(raw),stored=pin(b),roundtrip_exact=True))
def audit(w,s,attach):
 c=C[s];p,a,source,members,sources=archive_check(w,s,c);phases,terminal=phase_check(p,s,c,source);rows,execution=log_check(p,s,c)
 result=dict(schema="hepta.recovered-checkpoint-readback.v1",audit_identity="NEW_POST_RECOVERY_REVERIFICATION",stage=s,source_commit=source["source_commit"],source_tree=c["tree"],archive=pin(a.read_bytes()),regular_members=c["members"],indexed_members=c["members"]-1,source_files=c["sources"],source_raw_sha256_git_blob_mode_verified=True,full_git_tree_reconstruction_by_this_script=False,phase_bindings=phases,outer_terminal=terminal,execution=execution,workspace_scope=scope_check(p) if s==21 else None,source_oracles=oracles(p) if s==20 else None,history=dict(old_group=OLD[s][0],old_summary_bytes=OLD[s][1],old_summary_sha256=OLD[s][2],old_formal_bytes_recreated_or_claimed=False),cost_boundary="Original /usr/bin/time retained; shared filesystem free-space samples are not task-exclusive cost.",rust_tests_or_formatter_rerun=False,active_future_gate_logs_read=False,original_source_or_evidence_mutated=False,qualification_transferred=False,final_fix_fmt="NOT_EXECUTED_AT_ORIGINAL_GATE",independent_recovered_tree_review="PENDING_SEPARATE_HANDOFF")
 if not attach:return result
 dest=w/"hepta-cell/qualification/cell-unification-20261106/native-evidence"/f"r{s}-recovered-checkpoint";dest.mkdir(parents=True,exist_ok=True);mapping=[]
 copy_original(mapping,dest/"archive"/a.name,a,str(a.relative_to(w)))
 copy_original(mapping,dest/"archive/INDEX.json",p/"INDEX.json",str((p/"INDEX.json").relative_to(w)))
 for sub in ("evidence","input"):
  for original in sorted((p/sub).rglob("*")):
   if original.is_file():copy_original(mapping,dest/"original"/sub/original.relative_to(p/sub),original,str(original.relative_to(w)))
 for item in mapping:item["destination"]=str(Path(item["destination"]).relative_to(dest))
 write(dest/"verify_recovered.py",Path(__file__).read_bytes())
 for name,value in [("ARCHIVE-MEMBER-READBACK.json",members),("SOURCE-BYTE-READBACK.json",sources),("PARSED-EXECUTION-ROWS.json",rows),("RECOVERY-READBACK.json",result),("SOURCE-TO-DESTINATION.json",mapping)]:write(dest/name,enc(value))
 text=("# 恢复后重新核验\n\n"+f"这是 r{s} 原始 checkpoint 恢复后的新读回，不是旧正式附件组的逐字恢复。\n\n"+"archive、INDEX、evidence 和 input 均来自按原 SHA 恢复的归档。大 UTF-8 文件采用 mtime=0 的 gzip；映射保留压缩前后 SHA，并逐项验证解压后等于原字节。完整源码留在原 archive 中，不另复制 source 目录。\n\n"+"本次只运行 Python 读回，没有重跑 Rust、改写原件或读取后续活动日志。唯一测试 ID、退出码、资源、outer terminal 和 source guards 分别核对。原阶段数值不转移为其他源码资格。\n\n"+"RECOVERY-READBACK.json 中旧组 pin 仅为历史记录，不表示旧报告字节已恢复。独立原树重建由另一个新审计补充；最终附件清单待 handoff 后封存。\n")
 write(dest/"RECOVERY.md",text.encode())
 return dict(stage=s,new_group=str(dest.relative_to(w)),summary=pin(enc(result)),original_artifact_mappings=len(mapping),attachment_state="CORE_READBACK_COMPLETE_PENDING_INDEPENDENT_HANDOFF",execution={k:execution[k] for k in ("state","unique_test_results","passed","failed","timed_out","reported_skipped")})
if __name__=="__main__":
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--workspace",type=Path,required=True);ap.add_argument("--stage",type=int,choices=sorted(C),required=True);ap.add_argument("--attach",action="store_true");args=ap.parse_args()
 print(json.dumps(audit(args.workspace,args.stage,args.attach),ensure_ascii=False,indent=2))

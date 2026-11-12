from pathlib import Path
from datetime import datetime,timezone
import base64,fcntl,gzip,hashlib,json,os,shutil,stat,subprocess,sys,traceback
sys.dont_write_bytecode=True
P=INPUT;repo=Path(P["repo"]);records=Path(P["evidence_root"]);out=records/"final-b298-prepublish-maintenance-v2";packet_dir=records/"final-b298-candidate-packet-v1"
source="e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd";source_tree="b607ff5f50812c5e0f932d7dae18d4c74f1269cb";prepared="a8c41e56f1f8685444022692d1a636ec61b44e70";fixed="b29869e856d08db1bfb066116a9c443376ccc57d"
genv=dict(os.environ);genv.update(GIT_OPTIONAL_LOCKS="0",GIT_NO_LAZY_FETCH="1")
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(kind,b):return hashlib.sha1(kind.encode()+b" "+str(len(b)).encode()+b"\0"+b).hexdigest()
def put(path,b):
 if isinstance(b,str):b=b.encode()
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
 return {"path":str(path),"bytes":len(b),"sha256":sha(b),"git_blob_sha":oid("blob",b)}
def save(path,value):return put(path,json.dumps(value,sort_keys=True,indent=2)+"\n")
def git(args,data=None,root=repo,env=genv):
 q=subprocess.run(["git","-C",str(root),*args],input=data,env=env,capture_output=True,timeout=180)
 if q.returncode:raise RuntimeError("git "+repr(args)+" failed: "+q.stderr.decode(errors="replace"))
 return q.stdout
def ls(tree):
 rows=[]
 for line in git(["ls-tree","-r","--full-tree","-z",tree]).split(b"\0"):
  if not line:continue
  meta,path=line.split(b"\t",1);mode,kind,s=meta.decode().split()
  if kind!="blob" or mode not in ("100644","100755","120000"):raise RuntimeError("unexpected tree member")
  rows.append({"mode":mode,"path":os.fsdecode(path),"sha":s,"type":kind})
 return sorted(rows,key=lambda e:os.fsencode(e["path"]))
def index_tree(root):
 node={}
 for record in git(["ls-files","--stage","-z"],root=root).split(b"\0"):
  if not record:continue
  meta,path=record.split(b"\t",1);mode,s,stage=meta.decode().split()
  if stage!="0" or mode not in ("100644","100755","120000"):raise RuntimeError("unmerged or unsupported index")
  names=os.fsdecode(path).split("/");current=node
  for n in names[:-1]:
   child=current.setdefault(n,{})
   if not isinstance(child,dict):raise RuntimeError("index path collision")
   current=child
  if names[-1] in current:raise RuntimeError("duplicate index path")
  current[names[-1]]=(mode,s)
 def build(current):
  records=[]
  for name,value in current.items():
   if isinstance(value,dict):key=os.fsencode(name+"/");data=b"40000 "+os.fsencode(name)+b"\0"+bytes.fromhex(build(value))
   else:mode,s=value;key=os.fsencode(name);data=mode.encode()+b" "+key+b"\0"+bytes.fromhex(s)
   records.append((key,data))
  return oid("tree",b"".join(data for key,data in sorted(records)))
 return build(node)
def physical(root,label):
 names=sorted(set(git(["ls-files","-z"],root=root).split(b"\0")+git(["ls-files","--others","--exclude-standard","-z"],root=root).split(b"\0"))-{b""})
 rows=[]
 for raw in names:
  p=root/os.fsdecode(raw);st=p.lstat()
  if stat.S_ISLNK(st.st_mode):b=os.fsencode(os.readlink(p));mode="120000"
  elif stat.S_ISREG(st.st_mode):b=p.read_bytes();mode="100755" if st.st_mode&0o111 else "100644"
  else:raise RuntimeError("unexpected source file kind "+str(p))
  rows.append({"path":os.fsdecode(raw),"mode":mode,"bytes":len(b),"sha256":sha(b),"blob":oid("blob",b)})
 raw=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
 put(out/(label+".files.json.gz"),gzip.compress(raw,mtime=0))
 summary={"head":git(["rev-parse","HEAD"],root=root).decode().strip(),"head_tree":git(["rev-parse","HEAD^{tree}"],root=root).decode().strip(),"index_tree":index_tree(root),"status":git(["status","--porcelain=v1","--untracked-files=all"],root=root).decode(),"files":len(rows),"physical_inventory_sha256":sha(raw)}
 save(out/(label+".json"),summary)
 return summary,rows
def logical(rows):return [{"mode":r["mode"],"path":r["path"],"sha":r["blob"],"type":"blob"} for r in rows]
def exact_old(summary,rows):
 if summary["head"]!=source or summary["head_tree"]!=source_tree or summary["index_tree"]!=source_tree or summary["status"] or summary["files"]!=14741 or summary["physical_inventory_sha256"]!="efdf0a2b8aa9879d3ae03c256ac24a23263a195c306f25d9815b05a4af702d56":raise RuntimeError("original e8 full source differs")
def state(phase,extra=None):
 value={"phase":phase,"at":now(),"source_head":source,"prepared_tree":prepared,"qualification":False,**(extra or {})}
 tmp=out/("STATE."+str(os.getpid())+".tmp")
 put(tmp,json.dumps(value,indent=2,sort_keys=True)+"\n");os.chmod(tmp,0o600);os.replace(tmp,out/"STATE.json")
def safe_parent(p):
 rel=p.relative_to(repo)
 cur=repo
 for item in rel.parts[:-1]:
  cur=cur/item
  if cur.exists():
   if cur.is_symlink() or not cur.is_dir():raise RuntimeError("unsafe source parent "+str(cur))
  else:cur.mkdir()
def actual_tree(label):
 idx=out/(label+".index");e={**genv,"GIT_INDEX_FILE":str(idx)}
 git(["read-tree",prepared],env=e);git(["add","-A","--","."],env=e)
 return git(["write-tree"],env=e).decode().strip()
out.mkdir(mode=0o700)
put(out/"driver.py",P["driver"]);save(out/"INPUT.json",P)
result={"started_at":now(),"status":"preparing","source_parent":source,"fixed_upstream":fixed,"prepared_tree":prepared,"qualification":False,"tests_started":False,"source_reapplied":False,"cargo_command_requested":False,"new_empty_cache_created":False,"commands":[],"previous_history_fsck_exit":3,"history_failure_preserved":True}
lock=None;head_bytes=None;candidate_after=None
def brief(s):
 return {k:v for k,v in s.items() if k!="status"}|{"status_sha256":sha(s["status"].encode()),"status_bytes":len(s["status"].encode())}
try:
 if os.geteuid()==0:raise RuntimeError("ordinary operator required")
 prior_dir=records/"final-b298-prepublish-maintenance-v1"
 prior_raw=(prior_dir/"RESULT.json").read_bytes();prior=json.loads(prior_raw)
 put(out/"PRIOR_FAILED_RESULT_ORIGINAL.json",prior_raw)
 if prior["status"]!="failed" or not prior["source_applied"] or prior["commands"] or prior["cargo_command_requested"] or "FileNotFoundError" not in prior["error"] or "/data/hepta-utility-36fa-e8-diagnostic-target-v1" not in prior["error"]:raise RuntimeError("prior failure is not the observed precommand missing-cache failure")
 result["prior_failed_attempt"]={"bytes":len(prior_raw),"sha256":sha(prior_raw),"error":prior["error"],"source_applied":prior["source_applied"],"commands":prior["commands"],"finished_at":prior["finished_at"]}
 expected_after=prior["source_after_apply"]
 if expected_after["head"]!=source or expected_after["index_tree"]!=prepared or expected_after["files"]!=14851:raise RuntimeError("prior applied source identity differs")
 lock=open(records/"REVIEW_SOURCE.lock","rb");fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 active=[]
 for proc in Path("/proc").iterdir():
  if not proc.name.isdigit():continue
  try:
   if proc.stat().st_uid!=os.getuid():continue
   comm=(proc/"comm").read_text().strip();cwd=os.readlink(proc/"cwd");exe=os.readlink(proc/"exe")
   if (comm in ("cargo","rustc","cargo-nextest","just","gdb") and cwd.startswith(str(repo))) or exe==P["pinned_diagnostic_binary"]:active.append({"pid":int(proc.name),"comm":comm,"cwd":cwd,"exe":exe})
  except (OSError,PermissionError):pass
 save(out/"NATIVE_TERMINAL_PRECONDITION.json",{"matching_live_processes":active,"prior_attempt_finished_at":prior["finished_at"]})
 if active:raise RuntimeError("own native process remains live")
 state("checking_applied_candidate_and_retained_e8")
 result["source_before"],before_rows=physical(repo,"source-before")
 if result["source_before"]!=expected_after:raise RuntimeError("applied candidate changed after failed preflight")
 retained_summary,retained_rows=physical(Path(P["retained_repo"]),"retained-e8-before")
 exact_old(retained_summary,retained_rows);result["retained_e8_before"]=retained_summary
 hp=Path(git(["rev-parse","--path-format=absolute","--git-path","HEAD"]).decode().strip());head_bytes=hp.read_bytes()
 if head_bytes!=source.encode()+b"\n":raise RuntimeError("detached e8 HEAD changed")
 manifest_raw=(packet_dir/"MANIFEST.json").read_bytes()
 if oid("blob",manifest_raw)!="582d161baa468c4bcabb0d9c1b38f6db3b9d1541":raise RuntimeError("packet manifest differs")
 manifest=json.loads(manifest_raw);encoded=b""
 for part in manifest["parts"]:
  b=(packet_dir/part["name"]).read_bytes()
  if len(b)!=part["bytes"] or sha(b)!=part["sha256"] or oid("blob",b)!=part["git_blob_sha"]:raise RuntimeError("packet part differs")
  encoded+=b.strip()
 packed=base64.b64decode(encoded,validate=True);raw=gzip.decompress(packed)
 if len(packed)!=manifest["packet_gzip"]["bytes"] or sha(packed)!=manifest["packet_gzip"]["sha256"] or len(raw)!=manifest["packet_raw"]["bytes"] or sha(raw)!=manifest["packet_raw"]["sha256"]:raise RuntimeError("original packet hash differs")
 packet=json.loads(raw);expected=packet["expected_source_entries"];fm={e["path"]:e for e in expected}
 if packet["prepared_tree"]!=prepared or len(expected)!=14851 or logical(before_rows)!=expected or ls(prepared)!=expected:raise RuntimeError("current full candidate differs from frozen source packet")
 if sha(json.dumps(expected,sort_keys=True,separators=(",",":")).encode())!="17e044e04e9ce741394015852ef7d6fc39e6fd86484fb74ab0a1eb66cd1a7f66":raise RuntimeError("candidate logical inventory hash differs")
 old_target=Path("/data/hepta-utility-36fa-e8-diagnostic-target-v1");parent=Path("/data");target=Path(P["target"])
 def resource(path):
  try:
   s=path.lstat();v={"path":str(path),"exists":True,"device":s.st_dev,"inode":s.st_ino,"mode":oct(s.st_mode&0o7777),"uid":s.st_uid,"mtime_ns":s.st_mtime_ns,"is_symlink":stat.S_ISLNK(s.st_mode),"is_directory":stat.S_ISDIR(s.st_mode)}
   if stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode):
    x=os.statvfs(path);v.update(free_bytes=x.f_bavail*x.f_frsize,total_bytes=x.f_blocks*x.f_frsize)
   return v
  except FileNotFoundError:return {"path":str(path),"exists":False}
 resources={"observed_at":now(),"old_target":resource(old_target),"data_parent":resource(parent),"new_target_before":resource(target),"lost_cache_cause":"Unknown","prior_build_raw_blob":"04134e8a03570038fc4e63537f4b174a96f7fac5"}
 save(out/"CACHE_RESOURCE_BEFORE.json",resources)
 if not resources["data_parent"]["exists"] or not resources["data_parent"]["is_directory"] or resources["data_parent"]["is_symlink"] or resources["data_parent"]["free_bytes"]<6*1024**3:raise RuntimeError("data parent lacks safe available build space")
 if resources["new_target_before"]["exists"]:raise RuntimeError("new dedicated target unexpectedly exists")
 target.mkdir(mode=0o700);result["new_empty_cache_created"]=True
 after=resource(target)
 if not after["is_directory"] or after["is_symlink"] or after["uid"]!=os.getuid() or any(target.iterdir()):raise RuntimeError("new dedicated target is not private empty directory")
 save(out/"CACHE_RESOURCE_AFTER.json",{"observed_at":now(),"new_target_after":after,"old_target_not_changed":True,"new_empty_cache_created":True})
 result["target"]={"path":str(target),"created_empty":True,"device":after["device"],"inode":after["inode"],"free_bytes_before":after["free_bytes"],"prior_target_observation":resources["old_target"],"rebuild_cost_recorded_in_this_attempt":True,"loss_cause":"Unknown"}
 env=dict(os.environ);env.update(json.loads((records/"MAINTENANCE_STARTED.json").read_text())["environment"])
 env.update(CODEX_REPO_ROOT=str(repo),PYTHONPATH=str(repo/"scripts"),PYTHONDONTWRITEBYTECODE="1",CARGO_NET_OFFLINE="true",CARGO_TERM_COLOR="never",SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE="source-head",CARGO_TARGET_DIR=str(target))
 visible={k:v for k,v in env.items() if k in ["CODEX_REPO_ROOT","PYTHONPATH","PYTHONDONTWRITEBYTECODE","CARGO_NET_OFFLINE","CARGO_TERM_COLOR","SOURCE_SHA","TESTED_SHA","HEPTA_CI_LANE","CARGO_TARGET_DIR","CARGO_BUILD_JOBS","CARGO_INCREMENTAL","CARGO_PROFILE_DEV_DEBUG","CARGO_PROFILE_TEST_DEBUG","RUSTUP_TOOLCHAIN","RUST_MIN_STACK","RUSTY_V8_ARCHIVE","RUSTY_V8_SRC_BINDING_PATH","CARGO_HOME","RUSTUP_HOME","PATH"]}
 save(out/"MAINTENANCE_READY.json",{"at":now(),"source_head":source,"physical_tree":prepared,"source_before":brief(result["source_before"]),"retained_e8_before":brief(retained_summary),"original_failure":result["prior_failed_attempt"],"target":result["target"],"environment_overrides":visible,"qualification":False,"no_reapplication_of_source":True,"no_tests_requested":True})
 os.environ.update(env);sys.path.insert(0,str(repo/"scripts"));os.chdir(repo/"codex-rs")
 from hepta_ci_exec import execute_logged
 def command(label,args,budget):
  state(label,{"command":args,"timeout_seconds":budget,"target":str(target)})
  record={"name":label,"command":args,"timeout_seconds":budget,"requested_at":now()};result["commands"].append(record)
  if label=="fix":result["cargo_command_requested"]=True
  execution=execute_logged(args,out/(label+".log"),timeout_seconds=budget)
  record["execution"]=execution;record["finished_at"]=now();save(out/(label+"-RESULT.json"),record)
  raw=(out/(label+".log")).read_bytes();put(out/(label+".log.gz"),gzip.compress(raw,mtime=0))
  return execution
 version=command("toolchain",["python3","-c","import subprocess; commands=[['rustc','--version','--verbose'],['cargo','--version'],['just','--version'],['cargo','nextest','--version']]; [subprocess.run(c,check=True) for c in commands]"],120)
 if version["returncode"] or version["timed_out"] or version["output_limit_exceeded"]:raise RuntimeError("toolchain command failed")
 fix=command("fix",["just","fix","-p","codex-hepta-intelligence-eval","-p","codex-hepta-agentd"],7200)
 result["source_after_fix"],fix_rows=physical(repo,"source-after-fix")
 fmt=command("fmt",["just","fmt","--base",source],900)
 result["source_after_fmt"],candidate_after=physical(repo,"source-after-fmt")
 if hp.read_bytes()!=head_bytes:raise RuntimeError("detached source HEAD changed")
 final_tree=actual_tree("final");result["final_prepublication_tree"]=final_tree
 final_map={r["path"]:r for r in candidate_after};postimages=[]
 for path in sorted(set(fm)|set(final_map),key=os.fsencode):
  old=fm.get(path);new=final_map.get(path)
  if old and new and old["sha"]==new["blob"] and old["mode"]==new["mode"]:continue
  item={"path":path,"before":old,"after":new}
  if new:
   p=repo/path;b=os.fsencode(os.readlink(p)) if new["mode"]=="120000" else p.read_bytes()
   item["content_base64"]=base64.b64encode(b).decode()
  postimages.append(item)
 put(out/"ACTUAL_MAINTENANCE_POSTIMAGES.json.gz",gzip.compress(json.dumps(postimages,sort_keys=True,separators=(",",":")).encode(),mtime=0))
 diff=git(["diff","--binary",prepared,"--"]);put(out/"ACTUAL_MAINTENANCE_DIFF.patch",diff)
 save(out/"ACTUAL_MAINTENANCE_MANIFEST.json",{"prepared_tree":prepared,"final_tree":final_tree,"source_head":source,"source_inventory":brief(result["source_after_fmt"]),"postimages":[{k:v for k,v in x.items() if k!="content_base64"} for x in postimages],"diff_bytes":len(diff),"diff_sha256":sha(diff)})
 result["actual_maintenance_delta_paths"]=[x["path"] for x in postimages]
 result["commands_passed"]=all(not c["execution"]["returncode"] and not c["execution"]["timed_out"] and not c["execution"]["output_limit_exceeded"] for c in result["commands"])
 result["status"]="prepublication_maintenance_complete" if result["commands_passed"] else "prepublication_maintenance_commands_failed"
 state(result["status"],{"final_tree":final_tree,"delta_paths":result["actual_maintenance_delta_paths"]})
except BaseException as e:
 result["status"]="failed";result["error"]=type(e).__name__+": "+str(e);put(out/"exception.txt",traceback.format_exc())
 try:state("failed",{"error":result["error"]})
 except BaseException:pass
finally:
 try:
  result["source_final_observation"],final_rows=physical(repo,"source-final")
  if head_bytes is not None and hp.read_bytes()!=head_bytes:result["status"]="failed";result["head_changed"]=True
 except BaseException as e:result["source_final_error"]=str(e);result["status"]="failed"
 result["finished_at"]=now();identity=save(out/"RESULT.json",result)
 summary={k:v for k,v in result.items() if k not in ["source_before","source_after_fix","source_after_fmt","source_final_observation","retained_e8_before"]}
 for k in ["source_before","source_after_fix","source_after_fmt","source_final_observation","retained_e8_before"]:
  if k in result:summary[k]=brief(result[k])
 summary["full_original_result"]=identity
 save(out/"RESULT_SUMMARY.json",summary);print(json.dumps(summary,sort_keys=True),flush=True)
 if lock:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
raise SystemExit(0 if result["status"]=="prepublication_maintenance_complete" else 1)

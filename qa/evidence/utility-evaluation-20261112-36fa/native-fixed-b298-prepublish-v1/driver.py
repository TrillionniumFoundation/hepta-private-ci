from pathlib import Path
from datetime import datetime,timezone
import base64,fcntl,gzip,hashlib,json,os,shutil,stat,subprocess,sys,traceback
sys.dont_write_bytecode=True
P=INPUT;repo=Path(P["repo"]);records=Path(P["evidence_root"]);out=records/"final-b298-prepublish-maintenance-v1";packet_dir=records/"final-b298-candidate-packet-v1"
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
result={"started_at":now(),"status":"preparing","source_parent":source,"fixed_upstream":fixed,"prepared_tree":prepared,"qualification":False,"tests_started":False,"source_applied":False,"cargo_command_requested":False,"source_mutations_started":False,"source_completed_paths":[],"full_history_fsck":{"exit_code":3,"preserved_failure":True,"result_blob":"9eb09ebd5806ca99550b4cf81efde63c3ef86e0a"},"commands":[]}
lock=None;before_rows=None;expected=None;head_bytes=None;candidate_after=None
try:
 if os.geteuid()==0:raise RuntimeError("ordinary operator required")
 scope_path=records/"canonical-b298-object-import-v1/fsck-scope-v1/RESULT.json"
 scope_raw=scope_path.read_bytes()
 if sha(scope_raw)!="8ff08f150d355c25b9b1d51cf77c1091476910f25a296fedd691d889a7fb6071":raise RuntimeError("reviewed tip object scope result differs")
 scope=json.loads(scope_raw);put(out/"TIP_OBJECT_SCOPE_ORIGINAL.json",scope_raw)
 if scope["status"]!="read_only_scope_observation_retained" or scope["object_inventory"]["missing"] or scope["imported_244_objects"]["missing"]:raise RuntimeError("fixed-tip object scope not complete")
 for name in ("current_e8","fixed_726","fixed_b298"):
  if not scope["snapshots"][name]["all_required_objects_present"] or scope["snapshots"][name]["missing_objects"]:raise RuntimeError("tip files unavailable")
 if scope["snapshots"]["fixed_b298"]["commit"]!=fixed or scope["snapshots"]["fixed_b298"]["tree"]!="906546af39b07474f0b9d046a6e780b6d3342743":raise RuntimeError("wrong fixed tip")
 prior=json.loads((records/"e8b6-new-binary-diagnostics-v2/RESULT.json").read_text())
 if prior["status"]!="diagnostic_runs_retained" or len(prior["stages"])!=2 or any(not s["test_started"] for s in prior["stages"]):raise RuntimeError("original diagnostics are not terminal")
 lock=open(records/"REVIEW_SOURCE.lock","rb");fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 active=[]
 for proc in Path("/proc").iterdir():
  if not proc.name.isdigit():continue
  try:
   if proc.stat().st_uid!=os.getuid():continue
   comm=(proc/"comm").read_text().strip();cwd=os.readlink(proc/"cwd");exe=os.readlink(proc/"exe")
   if (comm in ("cargo","rustc","cargo-nextest","just","gdb") and cwd.startswith(str(repo))) or exe==P["pinned_diagnostic_binary"]:active.append({"pid":int(proc.name),"comm":comm,"cwd":cwd,"exe":exe})
  except (OSError,PermissionError):pass
 save(out/"NATIVE_TERMINAL_PRECONDITION.json",{"matching_live_processes":active,"prior_diagnostics_finished_at":prior["finished_at"]})
 if active:raise RuntimeError("own native process is still live")
 state("checking_original_and_retained_source")
 result["source_before"],before_rows=physical(repo,"source-before")
 exact_old(result["source_before"],before_rows)
 retained_summary,retained_rows=physical(Path(P["retained_repo"]),"retained-e8-before")
 exact_old(retained_summary,retained_rows)
 if retained_rows!=before_rows:raise RuntimeError("independent retained source differs")
 result["retained_e8_before"]=retained_summary
 hp=Path(git(["rev-parse","--path-format=absolute","--git-path","HEAD"]).decode().strip());ip=Path(git(["rev-parse","--path-format=absolute","--git-path","index"]).decode().strip())
 head_bytes=hp.read_bytes();index_bytes=ip.read_bytes()
 if head_bytes!=source.encode()+b"\n":raise RuntimeError("review checkout is not detached exact e8")
 put(out/"ORIGINAL_HEAD",head_bytes);put(out/"ORIGINAL_INDEX",index_bytes)
 original_manifest=(packet_dir/"MANIFEST.json").read_bytes()
 if oid("blob",original_manifest)!="582d161baa468c4bcabb0d9c1b38f6db3b9d1541":raise RuntimeError("packet manifest differs")
 manifest=json.loads(original_manifest);put(out/"ORIGINAL_PACKET_MANIFEST.json",original_manifest)
 encoded=b""
 for part in manifest["parts"]:
  p=packet_dir/part["name"];st=p.lstat()
  if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise RuntimeError("packet part not original regular file")
  b=p.read_bytes()
  if len(b)!=part["bytes"] or sha(b)!=part["sha256"] or oid("blob",b)!=part["git_blob_sha"]:raise RuntimeError("encoded packet part differs")
  encoded+=b.strip()
 compressed=base64.b64decode(encoded,validate=True)
 if len(compressed)!=manifest["packet_gzip"]["bytes"] or sha(compressed)!=manifest["packet_gzip"]["sha256"] or oid("blob",compressed)!=manifest["packet_gzip"]["git_blob_sha"]:raise RuntimeError("packet gzip differs")
 raw=gzip.decompress(compressed)
 if len(raw)!=manifest["packet_raw"]["bytes"] or sha(raw)!=manifest["packet_raw"]["sha256"] or oid("blob",raw)!=manifest["packet_raw"]["git_blob_sha"]:raise RuntimeError("packet raw differs")
 packet=json.loads(raw)
 if packet["source_parent"]!=source or packet["fixed_upstream"]!=fixed or packet["prepared_tree"]!=prepared:raise RuntimeError("candidate identity differs")
 expected=packet["expected_source_entries"]
 if expected!=sorted(expected,key=lambda e:os.fsencode(e["path"])) or len(expected)!=14851 or len({e["path"] for e in expected})!=14851:raise RuntimeError("candidate inventory differs")
 expected_bytes=json.dumps(expected,sort_keys=True,separators=(",",":")).encode()
 if sha(expected_bytes)!="17e044e04e9ce741394015852ef7d6fc39e6fd86484fb74ab0a1eb66cd1a7f66":raise RuntimeError("logical candidate inventory hash differs")
 base_rows=ls(fixed+"^{tree}")
 if len(base_rows)!=14842:raise RuntimeError("fixed baseline file count differs")
 bm={e["path"]:e for e in base_rows};fm={e["path"]:e for e in expected};supplied={}
 for c in packet["changes"]:
  base=bm.get(c["path"])
  if (base["sha"] if base else None)!=c["base_blob"] or (base and base["mode"]!=c["mode"]):raise RuntimeError("reviewed baseline blob differs "+c["path"])
  b=base64.b64decode(c["postimage_base64"],validate=True);z=c["post"]
  if len(b)!=z["bytes"] or sha(b)!=z["sha256"] or oid("blob",b)!=z["git_blob_sha"]:raise RuntimeError("reviewed postimage differs")
  if fm[c["path"]]["sha"]!=z["git_blob_sha"] or fm[c["path"]]["mode"]!=c["mode"]:raise RuntimeError("postimage inventory differs")
  supplied[z["git_blob_sha"]]=b;bm[c["path"]]={"path":c["path"],"sha":z["git_blob_sha"],"mode":c["mode"],"type":"blob"}
 if len(packet["changes"])!=40 or sorted(bm.values(),key=lambda e:os.fsencode(e["path"]))!=expected:raise RuntimeError("40path integration differs from complete candidate")
 tree_objects=[]
 for obj in packet["new_tree_objects"]:
  b=base64.b64decode(obj["data_base64"],validate=True)
  if obj["type"]!="tree" or len(b)!=obj["bytes"] or sha(b)!=obj["sha256"] or oid("tree",b)!=obj["sha"]:raise RuntimeError("candidate tree object differs")
  tree_objects.append((obj,b))
 if len(tree_objects)!=9:raise RuntimeError("candidate tree count differs")
 state("candidate_input_verified")
 # Exact reviewed object writes only; HEAD, index and source are still unchanged here.
 for s,b in supplied.items():
  if git(["hash-object","-t","blob","-w","--stdin"],b).decode().strip()!=s or git(["cat-file","blob",s])!=b:raise RuntimeError("candidate blob import differs")
 for obj,b in tree_objects:
  if git(["hash-object","-t","tree","-w","--stdin"],b).decode().strip()!=obj["sha"] or git(["cat-file","tree",obj["sha"]])!=b:raise RuntimeError("candidate tree import differs")
 if ls(prepared)!=expected:raise RuntimeError("full imported candidate tree differs")
 oldmap={x["path"]:x for x in before_rows};plan=[];contents={};backups=[]
 for path in sorted(set(oldmap)|set(fm),key=os.fsencode):
  old=oldmap.get(path);new=fm.get(path)
  if old and new and old["blob"]==new["sha"] and old["mode"]==new["mode"]:continue
  if new:
   b=supplied.get(new["sha"])
   if b is None:b=git(["cat-file","blob",new["sha"]])
   if oid("blob",b)!=new["sha"]:raise RuntimeError("candidate material bytes differ")
   contents[path]=b
  if old:
   p=repo/path
   b=os.fsencode(os.readlink(p)) if old["mode"]=="120000" else p.read_bytes()
   if len(b)!=old["bytes"] or sha(b)!=old["sha256"] or oid("blob",b)!=old["blob"]:raise RuntimeError("existing preimage changed")
   backups.append({**old,"content_base64":base64.b64encode(b).decode()})
  plan.append({"path":path,"before":old,"after":new,"after_bytes":len(contents[path]) if new else None,"after_sha256":sha(contents[path]) if new else None})
 put(out/"SOURCE_TRANSITION_BACKUPS.json.gz",gzip.compress(json.dumps(backups,sort_keys=True,separators=(",",":")).encode(),mtime=0))
 save(out/"SOURCE_TRANSITION_PLAN.json",plan)
 # All affected bytes and the complete tree have been verified before source edits.
 state("applying_prepared_source",{"transition_paths":len(plan)})
 result["source_mutations_started"]=True
 for step in plan:
  path=step["path"];dst=repo/path;safe_parent(dst)
  if step["before"] is not None:
   st=dst.lstat()
   if step["before"]["mode"]=="120000":
    if not stat.S_ISLNK(st.st_mode):raise RuntimeError("preimage kind changed")
   elif not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise RuntimeError("preimage not private regular file")
   current_bytes=os.fsencode(os.readlink(dst)) if step["before"]["mode"]=="120000" else dst.read_bytes()
   if len(current_bytes)!=step["before"]["bytes"] or sha(current_bytes)!=step["before"]["sha256"]:raise RuntimeError("source preimage changed immediately before write")
  elif dst.exists() or dst.is_symlink():raise RuntimeError("new path unexpectedly exists")
  new=step["after"]
  if new is None:
   dst.unlink();result["source_completed_paths"].append(path);continue
  b=contents[path]
  if step["before"] is None:
   if new["mode"]=="120000":os.symlink(os.fsdecode(b),dst)
   else:
    fd=os.open(dst,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o755 if new["mode"]=="100755" else 0o644)
    with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
   result["source_completed_paths"].append(path);continue
  temp=dst.parent/(".hepta-36fa-candidate-"+dst.name+".tmp")
  if new["mode"]=="120000":os.symlink(os.fsdecode(b),temp)
  else:
   fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o755 if new["mode"]=="100755" else 0o644)
   with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
  os.replace(temp,dst);result["source_completed_paths"].append(path)
 # Stage the exact reviewed tree only; keep the detached original e8 HEAD.
 git(["read-tree",prepared]);result["source_applied"]=True
 if hp.read_bytes()!=head_bytes:raise RuntimeError("original HEAD changed")
 result["source_after_apply"],applied_rows=physical(repo,"source-after-apply")
 if logical(applied_rows)!=expected or result["source_after_apply"]["index_tree"]!=prepared:raise RuntimeError("applied physical source differs")
 result["transition_paths"]=len(plan);result["prepared_physical_inventory_sha256"]=result["source_after_apply"]["physical_inventory_sha256"]
 env=dict(os.environ);env.update(json.loads((records/"MAINTENANCE_STARTED.json").read_text())["environment"])
 env.update(CODEX_REPO_ROOT=str(repo),PYTHONPATH=str(repo/"scripts"),PYTHONDONTWRITEBYTECODE="1",CARGO_NET_OFFLINE="true",CARGO_TERM_COLOR="never",SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE="source-head",CARGO_TARGET_DIR=P["target"])
 target=Path(env["CARGO_TARGET_DIR"]);st=target.lstat()
 if not stat.S_ISDIR(st.st_mode) or target.is_symlink() or st.st_uid!=os.getuid():raise RuntimeError("dedicated target unavailable")
 space=os.statvfs(target)
 if space.f_bavail*space.f_frsize<6*1024**3:raise RuntimeError("dedicated target lacks6GiB")
 save(out/"MAINTENANCE_STARTED.json",{"at":now(),"source_head":source,"source_tree":prepared,"source_identity":"Dirty prepublication candidate with detached e8 HEAD and prepared candidate index; not an e8 or new-head qualification","target":str(target),"free_bytes":space.f_bavail*space.f_frsize,"environment_overrides":{k:v for k,v in env.items() if k in ["CODEX_REPO_ROOT","PYTHONPATH","PYTHONDONTWRITEBYTECODE","CARGO_NET_OFFLINE","CARGO_TERM_COLOR","SOURCE_SHA","TESTED_SHA","HEPTA_CI_LANE","CARGO_TARGET_DIR","CARGO_BUILD_JOBS","CARGO_INCREMENTAL","CARGO_PROFILE_DEV_DEBUG","CARGO_PROFILE_TEST_DEBUG","RUSTUP_TOOLCHAIN","RUST_MIN_STACK","RUSTY_V8_ARCHIVE","RUSTY_V8_SRC_BINDING_PATH","CARGO_HOME","RUSTUP_HOME","PATH"]}})
 os.environ.update(env);sys.path.insert(0,str(repo/"scripts"));os.chdir(repo/"codex-rs")
 from hepta_ci_exec import execute_logged
 def command(label,args,budget):
  state(label,{"command":args,"timeout_seconds":budget})
  result["commands"].append({"name":label,"command":args,"timeout_seconds":budget,"started_at":now()})
  if label=="fix":result["cargo_command_requested"]=True
  execution=execute_logged(args,out/(label+".log"),timeout_seconds=budget)
  result["commands"][-1]["execution"]=execution;result["commands"][-1]["finished_at"]=now()
  save(out/(label+"-RESULT.json"),result["commands"][-1])
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
 save(out/"ACTUAL_MAINTENANCE_MANIFEST.json",{"prepared_tree":prepared,"final_tree":final_tree,"source_head":source,"source_inventory":result["source_after_fmt"],"postimages":[{k:v for k,v in x.items() if k!="content_base64"} for x in postimages],"diff_bytes":len(diff),"diff_sha256":sha(diff)})
 result["actual_maintenance_delta_paths"]=[x["path"] for x in postimages]
 result["commands_passed"]=all(not e["execution"]["returncode"] and not e["execution"]["timed_out"] and not e["execution"]["output_limit_exceeded"] for e in result["commands"])
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
 result["finished_at"]=now();save(out/"RESULT.json",result);print(json.dumps(result,sort_keys=True),flush=True)
 if lock:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
raise SystemExit(0 if result["status"]=="prepublication_maintenance_complete" else 1)

from pathlib import Path
from datetime import datetime,timezone
import base64,fcntl,gzip,hashlib,json,os,re,stat,subprocess,sys,traceback
sys.dont_write_bytecode=True
P=INPUT;repo=Path(P["repo"]);out=Path(P["out"]);records=Path(P["evidence_root"])
old_head="e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd"
before_tree="faf047faf110c20115453766329bd2a66f303df7"
before_inventory="399f9c4ec265e00eab812a1b1328606aff45d41c9063e257f36d1721d58b2dff"
old_index_tree="a8c41e56f1f8685444022692d1a636ec61b44e70"
allowed={"CALLERS.toml","qa/b4-no-bypass/test_original_evaluation_retention_guard_source_closure.py",".github/blob-size-allowlist.txt"}
genv=dict(os.environ);genv.update(GIT_OPTIONAL_LOCKS="0",GIT_NO_LAZY_FETCH="1")
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(kind,b):return hashlib.sha1(kind.encode()+b" "+str(len(b)).encode()+b"\0"+b).hexdigest()
def put(path,b,mode=0o400):
 if isinstance(b,str):b=b.encode()
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
 return {"path":str(path),"bytes":len(b),"sha256":sha(b),"git_blob_sha":oid("blob",b)}
def save(name,x):return put(out/name,json.dumps(x,sort_keys=True,indent=2)+"\n")
def git(args,data=None,env=genv):
 r=subprocess.run(["git","-C",str(repo),*args],input=data,env=env,capture_output=True,timeout=180)
 if r.returncode:raise RuntimeError("git "+repr(args)+" failed: "+r.stderr.decode(errors="replace"))
 return r.stdout
def tree_rows(tree):
 rows=[]
 for raw in git(["ls-tree","-r","--full-tree","-z",tree]).split(b"\0"):
  if not raw:continue
  meta,path=raw.split(b"\t",1);mode,kind,h=meta.decode().split()
  if kind!="blob":raise RuntimeError("unexpected non-blob tree member")
  rows.append({"path":os.fsdecode(path),"mode":mode,"blob":h})
 return sorted(rows,key=lambda r:os.fsencode(r["path"]))
def snapshot(label):
 names=sorted(set(git(["ls-files","-z"]).split(b"\0")+git(["ls-files","--others","--exclude-standard","-z"]).split(b"\0"))-{b""})
 rows=[]
 for raw in names:
  p=repo/os.fsdecode(raw);s=p.lstat()
  if stat.S_ISLNK(s.st_mode):b=os.fsencode(os.readlink(p));mode="120000"
  elif stat.S_ISREG(s.st_mode):b=p.read_bytes();mode="100755" if s.st_mode&0o111 else "100644"
  else:raise RuntimeError("unexpected source member "+str(p))
  rows.append({"path":os.fsdecode(raw),"mode":mode,"bytes":len(b),"sha256":sha(b),"blob":oid("blob",b)})
 encoded=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
 inventory=put(out/(label+".files.json.gz"),gzip.compress(encoded,mtime=0))
 status=git(["status","--porcelain=v1","--untracked-files=all"])
 value={"head":git(["rev-parse","HEAD"]).decode().strip(),"head_tree":git(["rev-parse","HEAD^{tree}"]).decode().strip(),"files":len(rows),"inventory_sha256":sha(encoded),"status_bytes":len(status),"status_sha256":sha(status),"inventory_file":inventory}
 put(out/(label+".status.txt"),status);save(label+".json",value)
 return value,rows
def logical(rows):return [{"path":r["path"],"mode":r["mode"],"blob":r["blob"]} for r in rows]
def safe_regular(path):
 current=repo
 for name in path.relative_to(repo).parts[:-1]:
  current=current/name;s=current.lstat()
  if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode):raise RuntimeError("source parent is not a real directory")
 s=path.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1:raise RuntimeError("source target is not private regular file")
 return s
out.mkdir(mode=0o700)
put(out/"driver.py",P["driver"]);save("INPUT.json",P)
result={"started_at":now(),"status":"preparing","qualification":False,"cargo_started":False,"tests_started":False,"source_parent":old_head,"before_tree":before_tree,"expected_final_tree":P["expected_tree"],"completed_paths":[]}
lock=None;before=None;head_path=None;head_bytes=None
try:
 if os.geteuid()==0 or re.fullmatch("[0-9a-f]{40}",P["expected_tree"]) is None or re.fullmatch("[0-9a-f]{64}",P["expected_inventory_sha256"]) is None:raise RuntimeError("ordinary operator and frozen source identities required")
 previous=(records/"final-b298-prepublish-maintenance-v2/RESULT.json").read_bytes()
 if sha(previous)!="16b444ef1b727062153dbb16e57bd489413fecc834e3107fb8f5fce4a67f58e6":raise RuntimeError("original maintenance terminal differs")
 terminal=json.loads(previous)
 if terminal["status"]!="prepublication_maintenance_complete" or not terminal["commands_passed"] or terminal["tests_started"] or terminal["final_prepublication_tree"]!=before_tree:raise RuntimeError("maintenance prerequisite failed")
 lock=(records/"REVIEW_SOURCE.lock").open("rb");fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 active=[]
 for proc in Path("/proc").iterdir():
  if not proc.name.isdigit():continue
  try:
   if proc.stat().st_uid!=os.getuid():continue
   comm=(proc/"comm").read_text().strip();cwd=os.readlink(proc/"cwd")
   if comm in ("cargo","rustc","cargo-nextest","just","gdb") and cwd.startswith(str(repo)):active.append({"pid":int(proc.name),"comm":comm,"cwd":cwd})
  except OSError:pass
 save("NATIVE_TERMINAL_PRECONDITION.json",{"observed_at":now(),"matching_live_native_processes":active})
 if active:raise RuntimeError("own source native process remains live")
 before,before_rows=snapshot("source-before")
 if before["head"]!=old_head or before["files"]!=14851 or before["inventory_sha256"]!=before_inventory or logical(before_rows)!=tree_rows(before_tree):raise RuntimeError("source no longer equals frozen formatted candidate")
 head_path=Path(git(["rev-parse","--path-format=absolute","--git-path","HEAD"]).decode().strip());head_bytes=head_path.read_bytes()
 if head_bytes!=old_head.encode()+b"\n":raise RuntimeError("source HEAD is not exact detached original head")
 put(out/"ORIGINAL_HEAD",head_bytes)
 index_path=Path(git(["rev-parse","--path-format=absolute","--git-path","index"]).decode().strip());index_bytes=index_path.read_bytes();put(out/"ORIGINAL_INDEX",index_bytes)
 expected_index=tree_rows(old_index_tree);actual_index=[]
 for raw in git(["ls-files","--stage","-z"]).split(b"\0"):
  if not raw:continue
  meta,path=raw.split(b"\t",1);mode,h,stage=meta.decode().split()
  if stage!="0":raise RuntimeError("unmerged source index")
  actual_index.append({"path":os.fsdecode(path),"mode":mode,"blob":h})
 if sorted(actual_index,key=lambda r:os.fsencode(r["path"]))!=expected_index:raise RuntimeError("original staged a8 index differs")
 packet_bytes=P["packet_base64_text"].encode()
 if len(packet_bytes)!=459385 or sha(packet_bytes)!="0c7810eccb628e7c85f5634e6f863354aed8c1c2d7cd639cc0e517d165f17167" or oid("blob",packet_bytes)!="77d30701c6e8e51d90e48fd3b6017e9ad092947a":raise RuntimeError("reviewed source packet differs")
 put(out/"POSTIMAGES.json.gz.b64",packet_bytes)
 packed=base64.b64decode(packet_bytes.strip(),validate=True);raw=gzip.decompress(packed)
 if len(packed)!=344536 or sha(packed)!="bcf3525570e55337aa3b76504f214d8dd0c93ff317dbd1e251c1ce8fce0b76f9" or len(raw)!=1701607 or sha(raw)!="2fa7e9ec86f82e68c78c765fd1547566f3ce085d82f873bb5a038dc3e8422d45":raise RuntimeError("packet decoded identities differ")
 packet=json.loads(raw)
 if packet["format"]!="hepta.retention-rustfmt-marker-sync.packet.v1" or packet["baseline_prepared_tree"]!=old_index_tree or len(packet["files"])!=3 or {f["path"] for f in packet["files"]}!=allowed:raise RuntimeError("packet scope differs")
 for path,identity in packet["native_formatted_Rust_inputs"].items():
  b=(repo/path).read_bytes()
  if len(b)!=identity["bytes"] or sha(b)!=identity["sha256"] or oid("blob",b)!=identity["git_blob_sha"]:raise RuntimeError("formatted Rust guard input differs")
 mapping={r["path"]:dict(r) for r in before_rows};backups=[];postimages=[]
 for f in packet["files"]:
  if f["mode"]!="100644":raise RuntimeError("unexpected source mode")
  path=repo/f["path"];s=safe_regular(path);b=path.read_bytes()
  if (s.st_mode&0o111) or len(b)!=f["before"]["bytes"] or sha(b)!=f["before"]["sha256"] or oid("blob",b)!=f["before"]["git_blob_sha"]:raise RuntimeError("source preimage differs")
  post=base64.b64decode(f["postimage_base64"],validate=True)
  if len(post)!=f["after"]["bytes"] or sha(post)!=f["after"]["sha256"] or oid("blob",post)!=f["after"]["git_blob_sha"]:raise RuntimeError("source postimage differs")
  backups.append({"path":f["path"],"content_base64":base64.b64encode(b).decode(),"identity":f["before"]});postimages.append((f,path,post))
  mapping[f["path"]]={"path":f["path"],"mode":"100644","bytes":len(post),"sha256":sha(post),"blob":oid("blob",post)}
 expected_rows=sorted(mapping.values(),key=lambda r:os.fsencode(r["path"]))
 expected_raw=json.dumps(expected_rows,sort_keys=True,separators=(",",":")).encode()
 if len(expected_rows)!=14851 or sha(expected_raw)!=P["expected_inventory_sha256"]:raise RuntimeError("full final inventory differs from root freeze")
 put(out/"ACTUAL_PREIMAGES.json.gz",gzip.compress(json.dumps(backups,sort_keys=True,separators=(",",":")).encode(),mtime=0))
 ixenv={**genv,"GIT_INDEX_FILE":str(out/"EXPECTED_FINAL.index")};git(["read-tree",before_tree],env=ixenv)
 for f,path,post in postimages:
  h=git(["hash-object","-t","blob","-w","--stdin"],post).decode().strip()
  if h!=f["after"]["git_blob_sha"]:raise RuntimeError("stored source blob differs")
  git(["update-index","--add","--cacheinfo",f["mode"],h,f["path"]],env=ixenv)
 actual_tree=git(["write-tree"],env=ixenv).decode().strip()
 if actual_tree!=P["expected_tree"] or logical(expected_rows)!=tree_rows(actual_tree):raise RuntimeError("whole final tree differs from root freeze")
 for f,path,post in postimages:
  safe_regular(path);current=path.read_bytes()
  if sha(current)!=f["before"]["sha256"] or oid("blob",current)!=f["before"]["git_blob_sha"]:raise RuntimeError("source changed immediately before apply")
  temporary=path.parent/(".hepta-utility-36fa-marker-"+str(os.getpid())+".tmp")
  put(temporary,post,0o644);os.replace(temporary,path);result["completed_paths"].append(f["path"])
  save("action-"+str(len(result["completed_paths"]))+".json",{"at":now(),"path":f["path"],"before":f["before"],"after":f["after"],"atomic_replace_complete":True})
 after,after_rows=snapshot("source-after-apply")
 if after["head"]!=old_head or after["files"]!=14851 or after["inventory_sha256"]!=P["expected_inventory_sha256"] or after_rows!=expected_rows or head_path.read_bytes()!=head_bytes:raise RuntimeError("actual full applied source differs")
 before_map={x["path"]:x for x in before_rows}
 changed=[r["path"] for r in after_rows if r!=before_map[r["path"]]]
 if set(changed)!=allowed:raise RuntimeError("actual changed source scope differs")
 if index_path.read_bytes()!=index_bytes:raise RuntimeError("default index changed before explicit staging")
 git(["read-tree",actual_tree])
 result["index_tree_after"]=git(["write-tree"]).decode().strip()
 if result["index_tree_after"]!=actual_tree or git(["diff","--name-only"]):raise RuntimeError("actual final index or unstaged content differs")
 final,final_rows=snapshot("source-after-staging")
 if final_rows!=expected_rows or final["head"]!=old_head or head_path.read_bytes()!=head_bytes:raise RuntimeError("final staging changed source or HEAD")
 result.update(status="three_nonrust_markers_applied",source_before=before,source_after=final,actual_tree=actual_tree,actual_changed_paths=changed,Rust_inputs_unchanged=True,source_ref_changed=False)
except BaseException as e:
 result.update(status="failed",error=type(e).__name__+": "+str(e));put(out/"exception.txt",traceback.format_exc())
finally:
 try:
  observed,observed_rows=snapshot("source-final-observation");result["source_final_observation"]=observed
  if head_bytes is not None and head_path.read_bytes()!=head_bytes:result.update(status="failed",unexpected_head_change=True)
 except BaseException as e:result.update(status="failed",source_final_error=str(e))
 result["finished_at"]=now();identity=save("RESULT.json",result)
 print(json.dumps({"status":result["status"],"result":identity,"actual_tree":result.get("actual_tree"),"completed_paths":result["completed_paths"],"qualification":False},sort_keys=True),flush=True)
 if lock:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
raise SystemExit(0 if result["status"]=="three_nonrust_markers_applied" else 1)

from pathlib import Path
from datetime import datetime,timezone
import base64,fcntl,gzip,hashlib,json,os,re,stat,subprocess,sys,traceback
P=INPUT;repo=Path(P["repo"]);out=Path(P["out"]);records=Path(P["evidence_root"])
old_head="e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd";fixed_parent="b29869e856d08db1bfb066116a9c443376ccc57d"
tree="313ee34febc8ccc54c611ab56286e289518c63cb";inventory="c7f8f0a34ef5e5c7ed7bac0ea3cc2b70a06af9e4bc974204a841db1a03eaa49f"
env=dict(os.environ);env.update(GIT_OPTIONAL_LOCKS="0",GIT_NO_LAZY_FETCH="1")
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(t,b):return hashlib.sha1(t.encode()+b" "+str(len(b)).encode()+b"\0"+b).hexdigest()
def put(name,b):
 if isinstance(b,str):b=b.encode()
 p=out/name;fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
 return {"path":str(p),"bytes":len(b),"sha256":sha(b),"git_blob_sha":oid("blob",b)}
def save(name,x):return put(name,json.dumps(x,sort_keys=True,indent=2)+"\n")
def git(args,data=None):
 r=subprocess.run(["git","-C",str(repo),*args],input=data,env=env,capture_output=True,timeout=180)
 if r.returncode:raise RuntimeError("git "+repr(args)+" failed: "+r.stderr.decode(errors="replace"))
 return r.stdout
def tree_rows(t):
 rows=[]
 for raw in git(["ls-tree","-r","--full-tree","-z",t]).split(b"\0"):
  if not raw:continue
  meta,path=raw.split(b"\t",1);mode,kind,h=meta.decode().split()
  if kind!="blob":raise RuntimeError("unsupported source object")
  rows.append({"path":os.fsdecode(path),"mode":mode,"blob":h})
 return sorted(rows,key=lambda r:os.fsencode(r["path"]))
def index_rows():
 rows=[]
 for raw in git(["ls-files","--stage","-z"]).split(b"\0"):
  if not raw:continue
  meta,path=raw.split(b"\t",1);mode,h,stage=meta.decode().split()
  if stage!="0":raise RuntimeError("unmerged index")
  rows.append({"path":os.fsdecode(path),"mode":mode,"blob":h})
 return sorted(rows,key=lambda r:os.fsencode(r["path"]))
def snapshot(label):
 names=sorted(set(git(["ls-files","-z"]).split(b"\0")+git(["ls-files","--others","--exclude-standard","-z"]).split(b"\0"))-{b""})
 rows=[]
 for raw in names:
  path=repo/os.fsdecode(raw);s=path.lstat()
  if stat.S_ISLNK(s.st_mode):b=os.fsencode(os.readlink(path));mode="120000"
  elif stat.S_ISREG(s.st_mode):b=path.read_bytes();mode="100755" if s.st_mode&0o111 else "100644"
  else:raise RuntimeError("unsupported physical source")
  rows.append({"path":os.fsdecode(raw),"mode":mode,"bytes":len(b),"sha256":sha(b),"blob":oid("blob",b)})
 raw=json.dumps(rows,sort_keys=True,separators=(",",":")).encode();gz=put(label+".files.json.gz",gzip.compress(raw,mtime=0))
 status=git(["status","--porcelain=v1","--untracked-files=all"]);put(label+".status.txt",status)
 summary={"head":git(["rev-parse","HEAD"]).decode().strip(),"tree":git(["rev-parse","HEAD^{tree}"]).decode().strip(),"files":len(rows),"inventory_sha256":sha(raw),"status_bytes":len(status),"status_sha256":sha(status),"gzip":gz}
 save(label+".json",summary);return summary,rows
out.mkdir(mode=0o700);put("driver.py",P["driver"]);save("INPUT.json",P)
result={"status":"preparing","started_at":now(),"source_sha":P["source"],"source_tree":tree,"qualification":False,"tests_started":False,"cargo_started":False,"head_alignment_performed":False,"worktree_written":False}
lock=None;before=None;index_path=None;index_bytes=None;head_path=None
try:
 if os.geteuid()==0 or re.fullmatch("[0-9a-f]{40}",P["source"]) is None or P["source"] in (old_head,fixed_parent):raise RuntimeError("ordinary operator and distinct canonical source required")
 prior=(records/"final-b298-marker-sync-v1/RESULT.json").read_bytes()
 if sha(prior)!="0d20ea32be400a5d21740cb587b8d6f28238b534a923d4daf68d4a5847c7556a":raise RuntimeError("marker application terminal differs")
 previous=json.loads(prior)
 if previous["status"]!="three_nonrust_markers_applied" or previous["actual_tree"]!=tree or previous["index_tree_after"]!=tree or previous["tests_started"] or previous["cargo_started"]:raise RuntimeError("marker source prerequisite failed")
 lock=(records/"REVIEW_SOURCE.lock").open("rb");fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 active=[]
 for p in Path("/proc").iterdir():
  if not p.name.isdigit():continue
  try:
   if p.stat().st_uid!=os.getuid():continue
   comm=(p/"comm").read_text().strip();cwd=os.readlink(p/"cwd")
   if comm in ("cargo","rustc","cargo-nextest","just","gdb") and cwd.startswith(str(repo)):active.append({"pid":int(p.name),"comm":comm,"cwd":cwd})
  except OSError:pass
 save("NATIVE_TERMINAL_PRECONDITION.json",{"at":now(),"matching_live_native_processes":active})
 if active:raise RuntimeError("own native process remains live")
 before,before_rows=snapshot("source-before")
 if before["head"]!=old_head or before["files"]!=14851 or before["inventory_sha256"]!=inventory:raise RuntimeError("physical prepared source differs")
 logical=[{"path":r["path"],"mode":r["mode"],"blob":r["blob"]} for r in before_rows]
 expected=tree_rows(tree)
 if logical!=expected or index_rows()!=expected:raise RuntimeError("prepared tree or default index differs")
 head_path=Path(git(["rev-parse","--path-format=absolute","--git-path","HEAD"]).decode().strip())
 if head_path.read_bytes()!=old_head.encode()+b"\n":raise RuntimeError("HEAD is not exact detached original source")
 put("ORIGINAL_HEAD",head_path.read_bytes())
 index_path=Path(git(["rev-parse","--path-format=absolute","--git-path","index"]).decode().strip());index_bytes=index_path.read_bytes();put("ORIGINAL_INDEX",index_bytes)
 raw=base64.b64decode(P["raw_commit_base64"],validate=True)
 if len(raw)!=P["raw_commit_bytes"] or sha(raw)!=P["raw_commit_sha256"] or oid("commit",raw)!=P["source"]:raise RuntimeError("authentic canonical raw object differs")
 header=raw.split(b"\n\n",1)[0].splitlines()
 if [x[5:].decode() for x in header if x.startswith(b"tree ")]!=[tree] or [x[7:].decode() for x in header if x.startswith(b"parent ")]!=[old_head,fixed_parent]:raise RuntimeError("canonical parent order or tree differs")
 for parent in [old_head,fixed_parent]:
  if git(["cat-file","-t",parent]).strip()!=b"commit":raise RuntimeError("canonical parent object unavailable")
 put("CANONICAL_COMMIT.raw",raw)
 stored=git(["hash-object","-t","commit","-w","--stdin"],raw).decode().strip()
 if stored!=P["source"] or git(["cat-file","commit",stored])!=raw:raise RuntimeError("canonical object roundtrip differs")
 result["imported_commit_sha"]=stored
 if index_path.read_bytes()!=index_bytes or head_path.read_bytes()!=old_head.encode()+b"\n":raise RuntimeError("HEAD or index changed before alignment")
 git(["update-ref","--no-deref","HEAD",P["source"],old_head]);result["head_alignment_performed"]=True
 after,after_rows=snapshot("source-after")
 if after_rows!=before_rows or after["head"]!=P["source"] or after["tree"]!=tree or after["status_bytes"] or after["inventory_sha256"]!=inventory or index_rows()!=expected or index_path.read_bytes()!=index_bytes:raise RuntimeError("canonical alignment is not exact clean unchanged source and index")
 result.update(status="canonical_head_aligned_source_clean",source_before=before,source_after=after,default_index_bytes_unchanged=True,source_bytes_unchanged=True)
except BaseException as e:
 result.update(status="failed",error=type(e).__name__+": "+str(e));put("exception.txt",traceback.format_exc())
finally:
 try:
  observed,rows=snapshot("source-final-observation");result["source_final_observation"]=observed
  if result["status"]=="canonical_head_aligned_source_clean" and (observed["head"]!=P["source"] or observed["tree"]!=tree or observed["status_bytes"] or observed["inventory_sha256"]!=inventory):result.update(status="failed",final_source_mismatch=True)
 except BaseException as e:result.update(status="failed",source_final_error=str(e))
 result["finished_at"]=now();identity=save("RESULT.json",result)
 print(json.dumps({"status":result["status"],"result":identity,"source_sha":P["source"],"tree":tree,"qualification":False},sort_keys=True),flush=True)
 if lock:fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
raise SystemExit(0 if result["status"]=="canonical_head_aligned_source_clean" else 1)

from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlsplit
import fcntl,gzip,hashlib,json,os,re,stat,subprocess,sys
sys.dont_write_bytecode=True
repo=Path("/home/qian-qi/hepta-utility-36fa-review-19aa")
root=Path("/home/qian-qi/hepta-utility-36fa-evidence")
out=root/"a96-origin-object-fetch-v1"
source="c0f78493f815780f68b9bf5e390a21314d79311f";source_tree="313ee34febc8ccc54c611ab56286e289518c63cb";inventory="c7f8f0a34ef5e5c7ed7bac0ea3cc2b70a06af9e4bc974204a841db1a03eaa49f"
tip="a96d1b821d10ed3d9e99dd06c5141f9f242ae318"
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,b):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
def save(p,v):write(p,(json.dumps(v,indent=2,sort_keys=True)+"\n").encode())
env=dict(os.environ);env.update(GIT_OPTIONAL_LOCKS="0",GIT_TERMINAL_PROMPT="0")
def git(*args,check=True):
 p=subprocess.run(["git",*args],cwd=repo,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if check and p.returncode:raise RuntimeError("local git read failed: "+args[0]+" exit "+str(p.returncode))
 return p
def safe_text(b):
 text=b.decode(errors="replace")
 text=re.sub(r"((?:https?|ssh)://)[^/\s'\"<>]+@",r"\1[REDACTED_USERINFO]@",text)
 text=re.sub(r"(?im)^(authorization|proxy-authorization):.*$",r"\1: [REDACTED]",text)
 return text
def snap(label):
 names=sorted(set(git("ls-files","-z").stdout.split(b"\0")+git("ls-files","--others","--exclude-standard","-z").stdout.split(b"\0"))-{b""});rows=[]
 for raw in names:
  p=repo/os.fsdecode(raw);m=p.lstat()
  if stat.S_ISLNK(m.st_mode):data=os.fsencode(os.readlink(p));mode="120000"
  elif stat.S_ISREG(m.st_mode):data=p.read_bytes();mode="100755" if m.st_mode&0o111 else "100644"
  else:raise RuntimeError("unsupported source type")
  rows.append({"path":os.fsdecode(raw),"mode":mode,"bytes":len(data),"sha256":sha(data),"blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()})
 b=json.dumps(rows,sort_keys=True,separators=(",",":")).encode();write(out/(label+".files.json.gz"),gzip.compress(b,mtime=0))
 index=Path(git("rev-parse","--git-path","index").stdout.decode().strip())
 if not index.is_absolute():index=repo/index
 v={"commit":git("rev-parse","HEAD").stdout.decode().strip(),"tree":git("rev-parse","HEAD^{tree}").stdout.decode().strip(),"index_diff_to_head":git("diff","--cached","--raw","--no-renames","HEAD","--").stdout.decode(),"index_bytes_sha256":sha(index.read_bytes()),"status":git("status","--porcelain=v1","--untracked-files=all").stdout.decode(),"files":len(rows),"inventory_bytes":len(b),"inventory_sha256":sha(b),"refs":git("for-each-ref","--format=%(refname) %(objectname)").stdout.decode()}
 save(out/(label+".json"),v)
 if v["commit"]!=source or v["tree"]!=source_tree or v["index_diff_to_head"] or v["status"] or v["files"]!=14851 or v["inventory_sha256"]!=inventory:raise RuntimeError("current source not exact clean c0f")
 return v
def object_scope():
 p=git("cat-file","-e",tip+"^{commit}",check=False)
 if p.returncode:return {"commit":tip,"commit_present":False,"probe_returncode":p.returncode,"probe_stderr":safe_text(p.stderr)}
 raw=git("cat-file","commit",tip).stdout
 if hashlib.sha1(b"commit "+str(len(raw)).encode()+b"\0"+raw).hexdigest()!=tip:raise RuntimeError("authentic commit hash mismatch")
 write(out/"A96_COMMIT.raw",raw)
 tree=git("rev-parse",tip+"^{tree}").stdout.decode().strip();listing=git("ls-tree","-rz","--full-tree",tip).stdout
 entries=[]
 for item in listing.split(b"\0"):
  if item:
   header,path=item.split(b"\t",1);mode,kind,obj=header.decode().split();entries.append({"mode":mode,"type":kind,"sha":obj,"path":os.fsdecode(path)})
 required=sorted({tip,tree,*[x["sha"] for x in entries]})
 p=subprocess.run(["git","cat-file","--batch-check=%(objectname) %(objecttype) %(objectsize)"],cwd=repo,env=env,input=("\n".join(required)+"\n").encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if p.returncode:raise RuntimeError("fixed tip object inventory failed")
 lines=p.stdout.decode().splitlines();missing=[s for s in lines if s.endswith(" missing")]
 write(out/"A96_LEAF_LIST.json",(json.dumps(entries,indent=2,sort_keys=True)+"\n").encode());write(out/"A96_REQUIRED_BATCH_CHECK.log",p.stdout)
 return {"commit":tip,"commit_present":True,"tree":tree,"file_count":len(entries),"required_commit_tree_and_unique_leaf_objects":len(required),"missing_objects":missing,"scope":"Exact commit content hash and full leaf listing, plus object presence/type/size; no whole-history fsck and no claim of complete independent rehash of every leaf."}
out.mkdir(exist_ok=False);before=None
r={"kind":"fixed_same_repository_object_fetch","qualification":False,"source_sha":source,"source_tree":source_tree,"target_commit":tip,"started_at":datetime.now(timezone.utc).isoformat(),"fetch_started":False,"cargo_or_tests_started":False,"status":"preparing"}
try:
 if os.geteuid()==0:raise RuntimeError("ordinary user required")
 lock=(root/"REVIEW_SOURCE.lock").open("a+");fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
 diagnostic=json.loads((root/"c0f-panel-first-signal-v1/RESULT.json").read_text())
 if diagnostic["status"]!="first_crash_diagnostic_retained" or diagnostic["source_sha"]!=source or diagnostic["source_before"]!=diagnostic["source_after"]:raise RuntimeError("single panel diagnostic not in verified terminal state")
 before=snap("source-before")
 prior=[]
 for pattern in ["*SOURCE*IMPORT*.json","*source*import*.json","*PUSH*.json","*push*.json"]:
  for p in root.glob(pattern):
   if p.is_file() and not p.is_symlink() and p.stat().st_size<=65536:
    raw=p.read_bytes()
    try:
     v=json.loads(raw);fields={k:v[k] for k in ["status","error","source_sha","source_tree","started_at","finished_at"] if isinstance(v,dict) and k in v}
     prior.append({"path":str(p),"bytes":len(raw),"sha256":sha(raw),"selected_fields":json.loads(safe_text(json.dumps(fields).encode()))})
    except (ValueError,UnicodeError):prior.append({"path":str(p),"bytes":len(raw),"sha256":sha(raw),"selected_fields":"not a JSON object with selected metadata"})
 save(out/"PRIOR_LOCAL_METADATA.json",prior)
 p=git("remote","get-url","--all","origin",check=False)
 urls=p.stdout.decode().splitlines()
 if p.returncode or len(urls)!=1:raise RuntimeError("configured single origin unavailable; use canonical object transport")
 raw_url=urls[0];parsed=urlsplit(raw_url);host=parsed.hostname;path=parsed.path;protocol=parsed.scheme;userinfo=bool(parsed.username or parsed.password)
 if not protocol:
  m=re.fullmatch(r"([^@]+)@([^:]+):(.+)",raw_url)
  if m:protocol="scp-style-ssh";host=m.group(2);path="/"+m.group(3);userinfo=True
 normalized=path.rstrip("/")
 if normalized.endswith(".git"):normalized=normalized[:-4]
 verified=protocol in ("https","ssh","scp-style-ssh") and host=="github.com" and normalized.lower()=="/trillionniumfoundation/hepta-private-ci"
 origin={"remote_name":"origin","protocol":protocol,"host":host,"repository_path":normalized if verified else "[unverified path withheld]","userinfo_present_not_disclosed":userinfo,"verified_same_repository":verified}
 save(out/"ORIGIN_REDACTED.json",origin);r["origin"]=origin
 if not verified:raise RuntimeError("configured origin is not a verified GitHub same-repository endpoint; no fetch performed")
 existing=git("cat-file","-e",tip+"^{commit}",check=False)
 if existing.returncode==0:
  r["object_scope"]=object_scope();r["status"]="already_available_without_fetch"
 else:
  command=["git","-c","gc.auto=0","-c","maintenance.auto=0","fetch","--no-tags","--no-recurse-submodules","--no-auto-maintenance","origin",tip]
  r["fetch_command"]=command;r["fetch_timeout_seconds"]=180;r["fetch_started"]=True
  save(out/"FETCH_STARTED.json",{"command":command,"timeout_seconds":180,"at":datetime.now(timezone.utc).isoformat(),"source_sha":source,"environment_overrides":{"GIT_OPTIONAL_LOCKS":"0","GIT_TERMINAL_PROMPT":"0"},"network_configuration_changed":False,"branch_ref_updates_requested":False,"allowed_git_metadata":"new fetched objects and FETCH_HEAD"})
  started=datetime.now(timezone.utc)
  try:
   result=subprocess.run(command,cwd=repo,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
   run={"returncode":result.returncode,"timed_out":False};stdout=result.stdout;stderr=result.stderr
  except subprocess.TimeoutExpired as e:run={"returncode":None,"timed_out":True};stdout=e.stdout or b"";stderr=e.stderr or b""
  run.update(started_at=started.isoformat(),finished_at=datetime.now(timezone.utc).isoformat(),stdout_bytes=len(stdout),stdout_sha256=sha(stdout),stderr_bytes=len(stderr),stderr_sha256=sha(stderr),log_encoding="UTF-8 replacement decoding with URL userinfo and Authorization header redaction")
  write(out/"fetch.stdout.redacted.log",safe_text(stdout).encode());write(out/"fetch.stderr.redacted.log",safe_text(stderr).encode());save(out/"FETCH_RESULT.json",run);r["fetch"]=run
  r["object_scope"]=object_scope()
  if run["timed_out"]:r["status"]="fetch_timed_out"
  elif run["returncode"]!=0:r["status"]="fetch_failed"
  elif not r["object_scope"]["commit_present"] or r["object_scope"]["missing_objects"]:r["status"]="fetch_completed_but_tip_incomplete"
  else:r["status"]="fixed_tip_objects_available"
except Exception as e:r.update(status="preparation_or_fetch_failed",error=type(e).__name__+": "+str(e))
finally:
 try:
  after=snap("source-after");r["source_after"]=after
  if before is None:r.update(source_comparison="unknown_missing_before")
  elif before!=after:r.update(status="source_or_refs_changed",source_comparison="different")
  else:r.update(source_comparison="equal")
 except Exception as e:r.update(status="final_source_check_failed",final_source_error=str(e),source_comparison="unknown_missing_after")
 r["source_before"]=before;r["finished_at"]=datetime.now(timezone.utc).isoformat();save(out/"RESULT.json",r);print(json.dumps(r,sort_keys=True),flush=True)
raise SystemExit(0 if r["status"] in ("fixed_tip_objects_available","already_available_without_fetch") else 1)

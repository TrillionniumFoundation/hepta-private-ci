from pathlib import Path
from datetime import datetime,timezone
import base64,fcntl,gzip,hashlib,json,os,stat,subprocess
repo=Path(INPUT["repo"])
records=Path("/home/qian-qi/hepta-utility-36fa-evidence")
out=records/"canonical-e8b6fe2a-alignment-v1"
source=INPUT["source"];tree=INPUT["tree"]
prior=records/"review-integrate-726-maintenance-v1"
record={"status":"running","source_sha":source,"source_tree":tree,"started_at":datetime.now(timezone.utc).isoformat(),"source_bytes_changed":False,"behavioral_tests_started":False}
def git(*args,data=None):return subprocess.check_output(["git",*args],cwd=repo,input=data)
def sha(data):return hashlib.sha256(data).hexdigest()
def blob(data):return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
def save(path,value):write(path,(json.dumps(value,indent=2,sort_keys=True)+"\n").encode())
def verify_source():
 rows=[];expected={}
 for item in git("ls-tree","-rz",tree).split(b"\0"):
  if not item:continue
  meta,name=item.split(b"\t",1);mode,kind,bid=meta.decode().split()
  if kind!="blob" or mode not in ("100644","100755","120000"):raise RuntimeError("unsupported canonical source type")
  path=os.fsdecode(name);expected[path]=(mode,bid)
 names=set(os.fsdecode(x) for x in git("ls-files","-z").split(b"\0") if x)|set(os.fsdecode(x) for x in git("ls-files","--others","--exclude-standard","-z").split(b"\0") if x)
 if names!=set(expected):raise RuntimeError("source pathname inventory differs from canonical tree")
 for path,(mode,bid) in sorted(expected.items()):
  p=repo/path;meta=p.lstat()
  if stat.S_ISLNK(meta.st_mode):data=os.fsencode(os.readlink(p));actual_mode="120000"
  elif stat.S_ISREG(meta.st_mode):data=p.read_bytes();actual_mode="100755" if meta.st_mode&0o111 else "100644"
  else:raise RuntimeError("unsupported source type")
  if actual_mode!=mode or blob(data)!=bid:raise RuntimeError("actual source differs from canonical tree "+path)
  rows.append({"path":path,"mode":mode,"blob":bid,"bytes":len(data),"sha256":sha(data)})
 raw=(json.dumps(rows,sort_keys=True,separators=(",",":"))+"\n").encode()
 return raw,{"files":len(rows),"sha256":sha(raw),"bytes":len(raw)}
out.mkdir(exist_ok=False)
lock=(records/"REVIEW_SOURCE.lock").open("a+")
try:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if os.geteuid()==0:raise RuntimeError("ordinary user required")
 terminal=json.loads((prior/"RESULT.json").read_text())
 objects=json.loads((records/"upstream-726-object-import-v1/RESULT.json").read_text())
 if terminal["status"]!="integrated_preparation_ready" or terminal["candidate_tree"]!=tree or objects["status"]!="passed":raise RuntimeError("source preparation/object import prerequisite missing")
 if git("rev-parse","HEAD").decode().strip()!="19aa601fa09321f1b6d1b3ff3b4d422908004e48" or subprocess.run(["git","symbolic-ref","-q","HEAD"],cwd=repo,stdout=subprocess.DEVNULL).returncode!=1:raise RuntimeError("expected detached base differs")
 packet=INPUT["canonical_commit_packet"]
 if packet["sha"]!=source or packet["tree"]!=tree or packet["parents"]!=["19aa601fa09321f1b6d1b3ff3b4d422908004e48","726af8f4a345a2ffb148b971f3fa16c71436862d"]:raise RuntimeError("canonical packet identity differs")
 raw=base64.b64decode(packet["raw_commit_base64"],validate=True)
 if len(raw)!=969 or sha(raw)!="60ce053e6b3452a071a5cb73deae2265a4733ba8eefe39672bf688e39d6cfbcf" or hashlib.sha1(b"commit "+str(len(raw)).encode()+b"\0"+raw).hexdigest()!=source:raise RuntimeError("authentic canonical commit differs")
 lines=raw.split(b"\n\n",1)[0].splitlines()
 if lines[0]!=("tree "+tree).encode() or [x[7:].decode() for x in lines if x.startswith(b"parent ")]!=packet["parents"]:raise RuntimeError("canonical raw header differs")
 for parent in packet["parents"]:git("cat-file","-e",parent+"^{commit}")
 if git("cat-file","-t",tree).decode().strip()!="tree":raise RuntimeError("final prepared tree absent")
 save(out/"CANONICAL_COMMIT_PACKET.json",packet);write(out/"CANONICAL_COMMIT.raw",raw)
 before_bytes,before=verify_source();write(out/"SOURCE_BEFORE.json.gz",gzip.compress(before_bytes,mtime=0));record["source_before_inventory"]=before
 observed=git("hash-object","-t","commit","-w","--stdin",data=raw).decode().strip()
 if observed!=source or git("cat-file","commit",source)!=raw:raise RuntimeError("canonical object readback differs")
 record["head_before"]=git("rev-parse","HEAD").decode().strip();record["status_before"]=git("status","--porcelain=v1","--untracked-files=all").decode()
 git("read-tree",source)
 git("update-ref","--no-deref","HEAD",source,record["head_before"])
 if git("rev-parse","HEAD").decode().strip()!=source or git("rev-parse","HEAD^{tree}").decode().strip()!=tree or git("status","--porcelain=v1","--untracked-files=all"):raise RuntimeError("canonical HEAD/index alignment is not clean")
 after_bytes,after=verify_source();write(out/"SOURCE_AFTER.json.gz",gzip.compress(after_bytes,mtime=0));record["source_after_inventory"]=after
 if before_bytes!=after_bytes:raise RuntimeError("source bytes changed during canonical alignment")
 record.update(status="passed",head_after=source,tree_after=tree,clean=True,authentic_commit_bytes_verified=True)
except Exception as error:record.update(status="failed",error=type(error).__name__+": "+str(error))
finally:
 record["finished_at"]=datetime.now(timezone.utc).isoformat();save(out/"RESULT.json",record);print(json.dumps({"canonical_alignment":record},sort_keys=True),flush=True);fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
if record["status"]!="passed":raise SystemExit(1)

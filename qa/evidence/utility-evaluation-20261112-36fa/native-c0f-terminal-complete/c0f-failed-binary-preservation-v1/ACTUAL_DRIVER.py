from pathlib import Path
from datetime import datetime, timezone
import fcntl,gzip,hashlib,json,os,shutil,stat,subprocess,sys
sys.dont_write_bytecode=True
repo=Path(INPUT["repo"]);target=Path(INPUT["target"]);out=Path(INPUT["records"])
source=INPUT["source"];tree=INPUT["tree"];native=Path(INPUT["native"])
record={"kind":"failed_native_binary_preservation_and_readonly_input_audit","status":"running","started_at":datetime.now(timezone.utc).isoformat(),"source_sha":source,"source_tree":tree,"cargo_or_tests_launched":False,"qualification":False,"binaries":[]}
def sha(data):return hashlib.sha256(data).hexdigest()
def blob(data):return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def write(p,data,mode=0o400):
 p.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
 with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
def save(p,v):write(p,(json.dumps(v,indent=2,sort_keys=True)+"\n").encode())
genv=dict(os.environ,GIT_OPTIONAL_LOCKS="0")
def git(*args):return subprocess.check_output(["git",*args],cwd=repo,env=genv)
def snapshot(label):
 rows=[]
 names=sorted(set(git("ls-files","-z").split(b"\0")+git("ls-files","--others","--exclude-standard","-z").split(b"\0"))-{b""})
 for raw in names:
  p=repo/os.fsdecode(raw);m=p.lstat()
  if stat.S_ISLNK(m.st_mode):data=os.fsencode(os.readlink(p));mode="120000"
  elif stat.S_ISREG(m.st_mode):data=p.read_bytes();mode="100755" if m.st_mode&0o111 else "100644"
  else:raise RuntimeError("unsupported source kind")
  rows.append({"path":os.fsdecode(raw),"mode":mode,"bytes":len(data),"sha256":sha(data),"blob":blob(data)})
 raw=json.dumps(rows,sort_keys=True,separators=(",",":")).encode();packed=gzip.compress(raw,mtime=0)
 write(out/(label+".files.json.gz"),packed)
 value={"commit":git("rev-parse","HEAD").decode().strip(),"tree":git("rev-parse","HEAD^{tree}").decode().strip(),"status":git("status","--porcelain=v1","--untracked-files=all").decode(),"files":len(rows),"inventory_sha256":sha(raw),"inventory_bytes":len(raw),"gzip_bytes":len(packed),"gzip_sha256":sha(packed)}
 if value["commit"]!=source or value["tree"]!=tree or value["status"] or value["files"]!=14851 or value["inventory_sha256"]!=INPUT["inventory_sha256"]:raise RuntimeError("source is not exact clean frozen c0f")
 save(out/(label+".json"),value)
 return value,rows
out.mkdir(parents=True,exist_ok=False)
write(out/"ACTUAL_DRIVER.py",DRIVER.encode());save(out/"INPUT.json",INPUT)
before=None
try:
 if os.geteuid()==0:raise RuntimeError("ordinary uid required")
 lock=(Path(INPUT["evidence"])/"REVIEW_SOURCE.lock").open("rb");fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
 terminal=(native/"RESULT.json").read_bytes();t=json.loads(terminal)
 if t.get("source_sha")!=source or t.get("status") not in ("passed","failed") or not t.get("finished_at") or t.get("source_change") is not False or t.get("source_before")!=t.get("source_after"):raise RuntimeError("completed clean original native prerequisite absent")
 write(out/"ORIGINAL_NATIVE_RESULT.json",terminal)
 before,rows=snapshot("source-before");record["source_before"]=before
 crate="codex-rs/hepta-intelligence-eval";expected={r["path"]:r for r in INPUT["control_manifest"]["frozen_eval_crate_blobs"]};actual={r["path"]:r for r in rows if r["path"].startswith(crate+"/")}
 differences=[]
 for path in sorted(set(actual)|set(expected)):
  a=actual.get(path);e=expected.get(path)
  if a is None or e is None or (a["mode"],a["bytes"],a["blob"])!=(e["mode"],e["bytes"],e["git_blob_sha1"]):differences.append({"path":path,"actual":a,"expected":e})
 crate_tree=git("rev-parse","HEAD:"+crate).decode().strip()
 audit={"source_sha":source,"eval_crate_tree":crate_tree,"expected_crate_tree":INPUT["control_manifest"]["base_source"]["eval_crate_tree"],"actual_file_count":len(actual),"expected_file_count":len(expected),"equal":not differences and len(actual)==65 and crate_tree==INPUT["control_manifest"]["base_source"]["eval_crate_tree"],"differences":differences,"actual_rows":[actual[k] for k in sorted(actual)],"scope":"Physical bytes/modes and current committed eval subtree only; this is not a new counterexample execution and does not assert every dependency outside the 65-file subtree is identical."}
 save(out/"EVAL65_AUDIT.json",audit);record["eval65_equal"]=audit["equal"]
 if target.is_symlink() or not target.is_dir():raise RuntimeError("exact dedicated Cargo target is unavailable")
 disk=os.statvfs(target);save(out/"TARGET_RUNTIME.json",{"path":str(target),"device":target.stat().st_dev,"inode":target.stat().st_ino,"available_bytes":disk.f_bavail*disk.f_frsize,"gdb":shutil.which("gdb"),"uid":os.geteuid()})
 candidates=[];observations=[]
 for pattern in ("codex_hepta_agentd-*","codex_hepta_intelligence_eval-*"):
  for path in sorted((target/"debug/deps").glob(pattern)):
   if path.is_symlink() or not path.is_file():continue
   with path.open("rb") as f:m=os.fstat(f.fileno());magic=f.read(4)
   observations.append({"path":str(path),"bytes":m.st_size,"mode":oct(stat.S_IMODE(m.st_mode)),"elf":magic==bytes([127,69,76,70])})
   if magic==bytes([127,69,76,70]) and m.st_mode&0o111:candidates.append(path)
 save(out/"OBSERVED_ARTIFACTS.json",observations)
 if not any(p.name.startswith("codex_hepta_agentd-") for p in candidates):raise RuntimeError("actual failed agentd ELF not present; no rebuild attempted")
 total=sum(p.stat().st_size for p in candidates)
 if disk.f_bavail*disk.f_frsize<2*total+1024**3:raise RuntimeError("insufficient free space for create-only retention")
 (out/"bin").mkdir(mode=0o700)
 for p in candidates:
  fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW);dst=out/"bin"/p.name;digest=hashlib.sha256();n=0
  with os.fdopen(fd,"rb") as src:
   m0=os.fstat(src.fileno())
   if not stat.S_ISREG(m0.st_mode):raise RuntimeError("artifact is not regular")
   dest_fd=os.open(dst,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o500)
   with os.fdopen(dest_fd,"wb") as dest:
    while True:
     part=src.read(1024*1024)
     if not part:break
     digest.update(part);n+=len(part);dest.write(part)
    dest.flush();os.fsync(dest.fileno())
   m1=os.fstat(src.fileno())
  fields=("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")
  if any(getattr(m0,k)!=getattr(m1,k) for k in fields) or n!=m0.st_size:raise RuntimeError("artifact changed during read/copy")
  with dst.open("rb") as f:copied=hashlib.file_digest(f,"sha256").hexdigest()
  if copied!=digest.hexdigest() or dst.stat().st_size!=n:raise RuntimeError("retained artifact mismatch")
  record["binaries"].append({"source":str(p),"retained":str(dst),"bytes":n,"sha256":copied,"source_device":m0.st_dev,"source_inode":m0.st_ino,"source_mtime_ns":m0.st_mtime_ns,"source_ctime_ns":m0.st_ctime_ns,"source_mode":oct(stat.S_IMODE(m0.st_mode)),"copy_readback_equal":True})
 save(out/"RETAINED_BINARIES.json",record["binaries"])
 tip=INPUT["next_upstream"];probe=subprocess.run(["git","cat-file","-e",tip+"^{commit}"],cwd=repo,env=genv,capture_output=True)
 availability={"commit":tip,"commit_present":probe.returncode==0,"probe_returncode":probe.returncode,"probe_stderr":probe.stderr.decode(errors="replace"),"network_fetch_performed":False,"refs_or_source_changed":False}
 if probe.returncode==0:
  commit=git("cat-file","commit",tip);availability["commit_raw_bytes"]=len(commit);availability["commit_raw_sha256"]=sha(commit)
  if hashlib.sha1(b"commit "+str(len(commit)).encode()+b"\0"+commit).hexdigest()!=tip:raise RuntimeError("next upstream raw commit hash mismatch")
  treeid=commit.splitlines()[0].decode().split(" ",1)[1];availability["tree"]=treeid
  listing=subprocess.run(["git","ls-tree","-r","-t","-z",tip],cwd=repo,env=genv,capture_output=True)
  availability.update(tree_listing_returncode=listing.returncode,tree_listing_stderr=listing.stderr.decode(errors="replace"))
  if listing.returncode==0:
   entries=listing.stdout;ids={tip,treeid};entry_rows=[]
   for item in entries.split(b"\0"):
    if not item:continue
    meta,path=item.split(b"\t",1);mode,kind,oid=meta.decode().split();ids.add(oid);entry_rows.append({"path":os.fsdecode(path),"mode":mode,"type":kind,"object":oid})
   checked=subprocess.check_output(["git","cat-file","--batch-check"],cwd=repo,env=genv,input=("".join(i+"\n" for i in sorted(ids))).encode()).decode().splitlines()
   missing=[line for line in checked if line.endswith(" missing")]
   availability.update(required_object_count=len(ids),missing=missing,required_objects_present=not missing,leaf_count=sum(r["type"]=="blob" for r in entry_rows),scope="current tip objects only; no full-history fsck or full a96 blob-byte rehash claimed")
   save(out/"NEXT_UPSTREAM_TIP_ENTRIES.json",entry_rows)
  else:availability.update(required_objects_present=False,scope="commit present; complete tip-tree enumeration failed; no checkout/fetch performed")
 save(out/"NEXT_UPSTREAM_AVAILABILITY.json",availability);record["next_upstream_availability"]=availability
 after,_=snapshot("source-after");record["source_after"]=after
 if before!=after:raise RuntimeError("source changed during preservation")
 record["status"]="retained_original_failed_binaries"
except Exception as error:record.update(status="preservation_failed",error=type(error).__name__+": "+str(error))
finally:
 record["finished_at"]=datetime.now(timezone.utc).isoformat()
 save(out/"RESULT.json",record);print(json.dumps(record,sort_keys=True),flush=True)
raise SystemExit(0 if record["status"]=="retained_original_failed_binaries" else 1)

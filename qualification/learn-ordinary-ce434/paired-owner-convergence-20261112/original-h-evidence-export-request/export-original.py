from pathlib import Path
import hashlib,json,os,re,stat,subprocess,time
repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
source="441de918b863dd15b2faeae920017c1b4b08f59d"
parent="36dd13e597268505b0d1b25b01c9cc429166e108"
base=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/unified-441de918b863-validation-v1")
recovery=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/dependency-recovery-441de918-v1")
out=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/git-export-441-source-recovery-v1")
branch="codex/learn-441-original-h-evidence-ce434-20261112-v1"
prefix="qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/validation-441-terminal/"
env=dict(os.environ);env["PYTHONDONTWRITEBYTECODE"]="1"
def git(*args,input=None):
 return subprocess.check_output(["git",*args],cwd=repo,env=env,input=input).decode().strip()
def remote(*args,input=None):
 return git("-c","http.proxy=socks5h://127.0.0.1:11080","-c","http.lowSpeedLimit=1","-c","http.lowSpeedTime=30",*args,input=input)
def digest(b):return hashlib.sha256(b).hexdigest()
def read(path):
 before=path.lstat()
 if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=os.getuid() or before.st_size>1048576:raise RuntimeError("unexpected evidence file type/ownership/size: "+str(path))
 b=path.read_bytes();after=path.lstat()
 if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise RuntimeError("evidence changed during original read")
 return b
if git("rev-parse","HEAD")!=source or git("status","--porcelain=v1","--untracked-files=all"):raise RuntimeError("fixed source must remain clean")
if out.exists() or out.is_symlink():raise RuntimeError("dedicated export exists; reconcile the same original request")
forward=Path("/home/qian-qi/.config/systemd/user/hepta-pocket4-socks.service").read_text()
if re.findall(r"(?:^|\s)-D\s+([^\s]+)",forward)!=["127.0.0.1:11080"]:raise RuntimeError("existing forward differs")
out.mkdir(mode=0o700,parents=False)
report={"state":"starting","source_sha":source,"parent_commit":parent,"branch":branch,"files":[],"ordinary_acceptance":{"positive":0,"no_update":0,"fresh_C":0,"daemon_root_cold_restart":0},"native_tests_executed":0}
def save():
 p=out/"result.pending.json"
 with p.open("w") as f:json.dump(report,f,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
 p.replace(out/"result.json")
try:
 save()
 pins=[
 ("outer-result.json",base/"result.json",2258,"f9723cb6de17d952c365b3e2706806a4312c1b39a0b14a68dd671ada6121688e"),
 ("source-suite.json",base/"source-suite.json",130164,"a628f9b0bc2b03a4b4ae3542a15d3d57b79949d924080d8bdf73f02c2c17c666"),
 ("source-suite.log",base/"source-suite.log",384649,"579750613553fa90ce30c2fc4965e8760b964ef80d84ef633515d5ece15010d4"),
 ("native-preparation.log",base/"original-full-native.log",776,"823146a6b41291c97afbe5346bcae5f57326fbb2f70617bc94faf40109865728"),
 ("dependency-recovery-pty.log",Path("/home/qian-qi/.local/state/hepta-runtime-mac-worker/terminals/dpty-708de59b312ce3cf5137d8baabd416e4ccbcfaac5d6519d2da1680ac9e0ad3cb/output.log"),3584,"f69587a190b9fe2a5921875906d6357972966df665fe24f2040ffdb4d1e1e6b5"),
 ("dependency-download.log",recovery/"download.log",0,"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
 ]
 pending=[]
 for name,path,size,checksum in pins:
  b=read(path)
  if len(b)!=size or digest(b)!=checksum:raise RuntimeError("known original evidence digest differs: "+name)
  pending.append((name,path,b))
 for name,path in [
  ("dependency-recovery.json",recovery/"result.json"),
  ("original-pty.log",Path("/home/qian-qi/.local/state/hepta-runtime-mac-worker/terminals/dpty-1d46822c034d54c18ceb3f3f0e5c6ce18d19cf066c4b6e7ae3f67a98a81ba59a/output.log")),
  ("selected-exception-windows.json",Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/diagnostics-441de918-exact-errors-v1/selected-exception-windows.json"))
 ]:
  b=read(path)
  if name=="original-pty.log":
   if len(b)!=523 or digest(b[:302])!="b8acb969e9c2a9471e162dcc99477a92869fb8b082bd768f724c22d321b4c924" or digest(b[302:])!="45679af02b82cf3ab88e0ebbfc0131a8bf72752057669839b0463b695df27e57":raise RuntimeError("original PTY chunks differ")
  elif name=="dependency-recovery.json":
   r=json.loads(b)
   if r["state"]!="original-assets-recovered-and-full-hash-verified" or r["source_after"]!=source or r["source_status_after"] or r["environment"]["CARGO_TARGET_DIR"]!="/data/hepta-learn-ce434-runtime-20261112-v1/target":raise RuntimeError("dependency recovery is not the observed original success")
  elif name=="selected-exception-windows.json":
   r=json.loads(b)
   if r["source_log"]["sha256"]!=pins[2][3] or r["source_json"]["sha256"]!=pins[1][3] or len(r["blocks"])!=11:raise RuntimeError("exception windows not bound to original evidence")
  pending.append((name,path,b))
 report["state"]="verified-original-file-bytes";save()
 if remote("ls-remote","--heads","origin","refs/heads/"+branch):raise RuntimeError("export branch already exists; preserve it")
 remote("fetch","--no-tags","origin",parent)
 original_index=env.get("GIT_INDEX_FILE")
 env["GIT_INDEX_FILE"]=str(out/"export.index")
 git("read-tree",parent)
 for name,path,b in pending:
  blob=git("hash-object","-w","--stdin",input=b)
  expected=hashlib.sha1(("blob "+str(len(b))+"\0").encode()+b).hexdigest()
  if blob!=expected:raise RuntimeError("git blob does not match actual original evidence")
  target=prefix+name
  git("update-index","--add","--cacheinfo","100644,"+blob+","+target)
  report["files"].append({"path":target,"original_path":str(path),"bytes":len(b),"sha256":digest(b),"git_blob":blob})
 manifest={"schema":"original-441-host-evidence-export-v1","source_sha":source,"parent":parent,"files":report["files"],"method":"Read complete stable original files, require original known size/hash pins, create Git blobs and an independent index; never change checkout or raw files.","source_tests":{"tests_run":423,"failures":5,"errors":69,"skipped":0},"native_tests_executed":0,"ordinary_acceptance":report["ordinary_acceptance"],"not_included":"No unrelated /data directory listing, secrets, credentials, arbitrary host files or production authority material."}
 b=(json.dumps(manifest,indent=2)+"\n").encode()
 blob=git("hash-object","-w","--stdin",input=b)
 if blob!=hashlib.sha1(("blob "+str(len(b))+"\0").encode()+b).hexdigest():raise RuntimeError("manifest identity mismatch")
 git("update-index","--add","--cacheinfo","100644,"+blob+","+prefix+"export-manifest.json")
 tree=git("write-tree");report["tree"]=tree
 message="LEARN: retain complete original 441 H source failure and dependency recovery evidence\n\nActual source423: 5 failures, 69 errors, zero skips. Native preparation stopped before compilation; original pinned public V8 pair later recovered with exact full hashes. No ordinary acceptance or new authority.\n"
 commit=git("commit-tree",tree,"-p",parent,input=message.encode());report["commit"]=commit
 report["state"]="commit-created-push-pending";save()
 result=remote("push","--porcelain","origin",commit+":refs/heads/"+branch);report["push_output"]=result
 observed=remote("ls-remote","--heads","origin","refs/heads/"+branch)
 if observed.split()[0]!=commit:raise RuntimeError("published exact ref differs")
 if original_index is None:env.pop("GIT_INDEX_FILE",None)
 else:env["GIT_INDEX_FILE"]=original_index
 report["source_after"]=git("rev-parse","HEAD");report["source_status_after"]=git("status","--porcelain=v1","--untracked-files=all")
 if report["source_after"]!=source or report["source_status_after"]:raise RuntimeError("source changed during evidence export")
 report["state"]="published-original-evidence";save()
except BaseException as error:
 report.update(state="failed",error_type=type(error).__name__,error=str(error));save();raise
print(json.dumps(report,indent=2),flush=True)

from pathlib import Path
import hashlib,json,os,re,stat,subprocess,time
repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
source="c7f5d1950713e592a120807a06b700cd229c35b0"
base=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/unified-c7f5d1950713-validation-v1")
native=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/live-owners-full-c7f5d1950713-v1")
out=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/source-export-c7f5d1950713-v1")
branch="codex/learn-c7-source-evidence-ce434-20261112-v1"
prefix="qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-source/"
env=dict(os.environ)
def git(*args,input=None):return subprocess.check_output(["git",*args],cwd=repo,env=env,input=input).decode().strip()
def remote(*args):return git("-c","http.proxy=socks5h://127.0.0.1:11080","-c","http.lowSpeedLimit=1","-c","http.lowSpeedTime=30",*args)
def sha(b):return hashlib.sha256(b).hexdigest()
def read(p,maximum=1048576):
 with p.open("rb") as stream:
  s=os.fstat(stream.fileno())
  if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_uid!=os.getuid() or s.st_size>maximum:raise RuntimeError("unexpected original evidence size/type")
  b=stream.read(maximum+1);after=os.fstat(stream.fileno())
  if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or len(b)>maximum:raise RuntimeError("evidence changed during read")
  return b
if out.exists() or out.is_symlink():raise RuntimeError("original source export path exists; reconcile the same request")
if git("rev-parse","HEAD")!=source or git("status","--porcelain=v1","--untracked-files=all"):raise RuntimeError("fixed source differs")
deadline=time.monotonic()+900
outer_bytes=None;step=None
while time.monotonic()<deadline:
 if (base/"result.json").is_file():
  observed=read(base/"result.json");outer=json.loads(observed)
  if outer["source_sha"]!=source:raise RuntimeError("outer source differs")
  step=next((s for s in outer["steps"] if s["name"]=="source-suite"),None)
  if step is not None:outer_bytes=observed;break
 time.sleep(10)
if outer_bytes is None:raise RuntimeError("source result still pending after this bounded observation; no tests rerun")
suite_bytes=read(base/"source-suite.json");suite=json.loads(suite_bytes)
log=read(base/"source-suite.log")
if len(log)!=step["bytes"] or sha(log)!=step["sha256"]:raise RuntimeError("complete original source log differs from actual outer result")
if suite["expected_methods"]!=423 or suite["tests_run"]!=423:raise RuntimeError("actual source case inventory differs")
passed=suite["passed"] and suite["failures"]==0 and suite["errors"]==0 and suite["skipped"]==0
if (step["exit_code"]==0)!=bool(passed):raise RuntimeError("source outcome and original exit differ")
pending=[("outer-as-observed.json",outer_bytes),("source-suite.json",suite_bytes),("source-suite.log",log)]
native_observation=None
if (native/"result.json").is_file():
 b=read(native/"result.json");native_observation=json.loads(b)
 if native_observation["source_sha"]!=source:raise RuntimeError("native observation has another source")
 pending.append(("native-as-observed.json",b))
 if native_observation["state"] in ("helper-failed","helper-verification-failed","failed","passed"):
  for name in ("helper-build.driver.log","helper-verify.driver.log"):
   p=native/name
   if p.is_file() and p.stat().st_size<=1048576:pending.append(("native-"+name,read(p)))
if git("rev-parse","HEAD")!=source or git("status","--porcelain=v1","--untracked-files=all"):raise RuntimeError("fixed source changed during observation")
forward=Path("/home/qian-qi/.config/systemd/user/hepta-pocket4-socks.service").read_text()
if re.findall(r"(?:^|\s)-D\s+([^\s]+)",forward)!=["127.0.0.1:11080"]:raise RuntimeError("existing forward differs")
out.mkdir(mode=0o700)
if remote("ls-remote","--heads","origin","refs/heads/"+branch):raise RuntimeError("source evidence branch exists")
original_index=env.get("GIT_INDEX_FILE");env["GIT_INDEX_FILE"]=str(out/"evidence.index")
git("read-tree",source)
records=[]
for name,b in pending:
 blob=git("hash-object","-w","--stdin",input=b)
 if blob!=hashlib.sha1(("blob "+str(len(b))+"\0").encode()+b).hexdigest():raise RuntimeError("blob not actual evidence bytes")
 git("update-index","--add","--cacheinfo","100644,"+blob+","+prefix+name)
 records.append({"path":prefix+name,"bytes":len(b),"sha256":sha(b),"git_blob":blob})
manifest={"schema":"original-c7-source-checkpoint-export-v1","source_sha":source,"source_tree":git("rev-parse","HEAD^{tree}"),"observed_unix_ms":int(time.time()*1000),"source_result":{k:suite[k] for k in ("expected_methods","tests_run","failures","errors","skipped","elapsed_seconds","passed")},"source_step":step,"native_state_as_observed":native_observation["state"] if native_observation else "no-original-result-yet","native_finished":native_observation is not None and native_observation["state"] in ("helper-failed","helper-verification-failed","failed","passed"),"files":records,"scope":"Complete finished original source-suite files; native JSON is an independent point-in-time observation and cannot be treated as final if not terminal. No test rerun, source edit, daemon stop or new authority.","ordinary_acceptance":{"positive":0,"no_update":0,"fresh_C":0,"daemon_root_cold_restart":0}}
b=(json.dumps(manifest,indent=2)+"\n").encode();blob=git("hash-object","-w","--stdin",input=b)
git("update-index","--add","--cacheinfo","100644,"+blob+","+prefix+"export-manifest.json")
tree=git("write-tree");commit=git("commit-tree",tree,"-p",source,input=b"LEARN: retain actual fixed-c7 source result and native state observation\n")
(out/"commit.json").write_text(json.dumps({"commit":commit,"tree":tree,"branch":branch,"manifest":manifest},indent=2)+"\n")
remote("push","--porcelain","origin",commit+":refs/heads/"+branch)
if remote("ls-remote","--heads","origin","refs/heads/"+branch).split()[0]!=commit:raise RuntimeError("published evidence ref differs")
if original_index is None:env.pop("GIT_INDEX_FILE",None)
else:env["GIT_INDEX_FILE"]=original_index
if git("rev-parse","HEAD")!=source or git("status","--porcelain=v1","--untracked-files=all"):raise RuntimeError("checkout changed during evidence publication")
print(json.dumps({"state":"source-evidence-published","commit":commit,"tree":tree,"branch":branch,"source":manifest["source_result"],"native_state":manifest["native_state_as_observed"]}),flush=True)

from pathlib import Path
import base64,hashlib,json,os,re,stat,subprocess,time
repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
source="c7f5d1950713e592a120807a06b700cd229c35b0"
tree="2f6faa8fc5a3bf2a8e923748a45ec8d56a4a3d1b"
base=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/unified-c7f5d1950713-validation-v1")
native=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/live-owners-full-c7f5d1950713-v1")
out=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/native-export-c7f5d1950713-v1")
branch="codex/learn-c7-native-evidence-ce434-20261112-v1"
prefix="qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/"
env=dict(os.environ)
def git(*args,input=None):
 return subprocess.check_output(["git",*args],cwd=repo,env=env,input=input).decode().strip()
def remote(*args):
 return git("-c","http.proxy=socks5h://127.0.0.1:11080","-c","http.lowSpeedLimit=1","-c","http.lowSpeedTime=30",*args)
def sha(b):return hashlib.sha256(b).hexdigest()
def identity(s):
 return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def read(p,maximum=67108864):
 before=p.lstat()
 if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=os.getuid() or before.st_size>maximum:
  raise RuntimeError("original evidence type/owner/size differs")
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
 with os.fdopen(fd,"rb") as stream:
  first=os.fstat(stream.fileno())
  if identity(first)!=identity(before):raise RuntimeError("original evidence replaced before read")
  b=stream.read(maximum+1)
  after=os.fstat(stream.fileno())
 if identity(first)!=identity(after) or identity(first)!=identity(p.lstat()) or len(b)!=first.st_size:
  raise RuntimeError("original evidence changed during bounded read")
 return b
def clean():
 if git("rev-parse","HEAD")!=source or git("rev-parse","HEAD^{tree}")!=tree or git("status","--porcelain=v1","--untracked-files=all"):
  raise RuntimeError("fixed source changed")
def snapshot():
 outer_bytes=read(base/"result.json",1048576)
 native_bytes=read(native/"result.json",1048576)
 outer=json.loads(outer_bytes);state=json.loads(native_bytes)
 if outer["source_sha"]!=source or state["source_sha"]!=source or state["source_tree"]!=tree:
  raise RuntimeError("original result source differs")
 finished=outer["state"] in ("passed","failed")
 if finished and not any(s["name"]=="original-full-native" for s in outer.get("steps",[])):
  raise RuntimeError("outer terminal lacks actual original native step")
 return outer_bytes,native_bytes,outer,state,finished
if out.exists() or out.is_symlink():raise RuntimeError("evidence observer exists; reconcile original key")
clean()
forward=Path("/home/qian-qi/.config/systemd/user/hepta-pocket4-socks.service").read_text()
if re.findall(r"(?:^|\s)-D\s+([^\s]+)",forward)!=["127.0.0.1:11080"]:
 raise RuntimeError("existing forward differs")
out.mkdir(mode=0o700)
if remote("ls-remote","--heads","origin","refs/heads/"+branch):
 raise RuntimeError("new evidence branch already exists")
previous=source
def publish(label,s):
 global previous
 outer_bytes,native_bytes,outer,state,finished=s
 clean()
 pending=[("outer-as-observed.json",outer_bytes),("native-as-observed.json",native_bytes)]
 omitted=[]
 fixed=[
  ("outer-native.log",base/"original-full-native.log"),
  ("outer-self-test.log",base/"caller-scanner-self-test.log"),
  ("v8-private-input-readback.json",native/"v8-private-input-readback.json"),
  ("helper-build.driver.log",native/"helper-build.driver.log"),
  ("helper-verify.driver.log",native/"helper-verify.driver.log"),
  ("focused-native.driver.log",native/"focused-native.driver.log"),
  ("focused-junit.driver.log",native/"focused-junit.driver.log"),
  ("focused-native.json",native/"focused-native.json"),
  ("focused-native.junit.xml",native/"focused-native.junit.xml"),
  ("focused-native.junit.summary.json",native/"focused-native.junit.summary.json"),
  ("helpers-manifest.json",native/"helpers/manifest.json"),
  ("helpers-env.json",native/"helpers/env.json"),
  ("helpers-codex-hepta-infer-worker-host.jsonl",native/"helpers/codex-hepta-infer-worker-host.jsonl"),
  ("helpers-codex-hepta-infer-worker-host.stderr.log",native/"helpers/codex-hepta-infer-worker-host.stderr.log")]
 for name,path in fixed:
  if not path.exists():continue
  try:raw=read(path)
  except (OSError,RuntimeError) as error:
   if finished:raise
   omitted.append({"name":name,"state":"not-captured-stably","error_type":type(error).__name__});continue
  pending.append((name,raw))
 actual={name:raw for name,raw in pending}
 execution=None
 if "focused-native.json" in actual:
  execution=json.loads(actual["focused-native.json"])
  name=execution.get("log_file")
  if name is not None:
   if not isinstance(name,str) or not re.fullmatch(r"focused-native\.json\.[0-9a-f]{32}\.log",name):
    raise RuntimeError("original execution log name differs")
   try:raw=read(native/name)
   except (OSError,RuntimeError) as error:
    if finished:raise
    omitted.append({"name":"focused-native.execution.log","state":"not-captured-stably","error_type":type(error).__name__})
   else:
    if finished and (len(raw)!=execution.get("log_bytes") or sha(raw)!=execution.get("log_sha256")):
     raise RuntimeError("original execution full log hash differs")
    pending.append(("focused-native.execution.log",raw))
 if finished:
  step=next(x for x in outer["steps"] if x["name"]=="original-full-native")
  if "outer-native.log" not in actual or len(actual["outer-native.log"])!=step["bytes"] or sha(actual["outer-native.log"])!=step["sha256"]:
   raise RuntimeError("full outer native log differs")
  if "native_result_file" in outer and (len(native_bytes)!=outer["native_result_file"]["bytes"] or sha(native_bytes)!=outer["native_result_file"]["sha256"]):
   raise RuntimeError("final native JSON differs from outer pin")
 original_index=env.get("GIT_INDEX_FILE")
 env["GIT_INDEX_FILE"]=str(out/(label+".index"))
 try:
  git("read-tree",previous)
  records=[]
  def insert(path,raw):
   blob=git("hash-object","-w","--stdin",input=raw)
   if blob!=hashlib.sha1(("blob "+str(len(raw))+"\0").encode()+raw).hexdigest():raise RuntimeError("evidence blob differs")
   git("update-index","--add","--cacheinfo","100644,"+blob+","+path)
   return {"path":path,"bytes":len(raw),"sha256":sha(raw),"git_blob":blob}
  for name,raw in pending:
   record={"name":name,"original_bytes":len(raw),"original_sha256":sha(raw),"complete_file":True,"parts":[]}
   path=prefix+label+"/"+name
   if len(raw)<=524288:
    raw.decode("utf-8")
    record["encoding"]="utf-8"
    record["parts"].append(insert(path,raw))
   else:
    record["encoding"]="base64-parts"
    for index,start in enumerate(range(0,len(raw),393216)):
     record["parts"].append(insert(path+".part-"+str(index).zfill(4)+".base64",base64.b64encode(raw[start:start+393216])+b"\n"))
   records.append(record)
  manifest={"schema":"original-c7-native-observation-v1","source_sha":source,"source_tree":tree,"observed_unix_ms":int(time.time()*1000),"label":label,"original_outer_terminal":finished,"outer_state":outer["state"],"native_state":state["state"],"files":records,"omitted_unstable_inflight_files":omitted,"scope":"Reads only original owned qualification files. Initial snapshot is not terminal. No tests rerun, source edit, process signal or production authority. A bounded observer timeout cannot imply native failure or no effect.","ordinary_acceptance":{"positive":0,"no_update":0,"fresh_C":0,"daemon_root_cold_restart":0}}
  manifest_bytes=(json.dumps(manifest,indent=2)+"\n").encode()
  insert(prefix+label+"/export-manifest.json",manifest_bytes)
  result_tree=git("write-tree")
  commit=git("commit-tree",result_tree,"-p",previous,input=("LEARN: retain original C7 native "+label+" evidence\n").encode())
 finally:
  if original_index is None:env.pop("GIT_INDEX_FILE",None)
  else:env["GIT_INDEX_FILE"]=original_index
 clean()
 (out/(label+".json")).write_text(json.dumps({"commit":commit,"tree":result_tree,"branch":branch,"manifest":manifest},indent=2)+"\n")
 observed=remote("ls-remote","--heads","origin","refs/heads/"+branch)
 if previous==source:
  if observed:raise RuntimeError("new evidence branch was concurrently created")
 elif not observed or observed.split()[0]!=previous:raise RuntimeError("evidence branch moved")
 remote("push","--porcelain","origin",commit+":refs/heads/"+branch)
 if remote("ls-remote","--heads","origin","refs/heads/"+branch).split()[0]!=commit:raise RuntimeError("published evidence differs")
 previous=commit
 clean()
 print(json.dumps({"state":"evidence-published","label":label,"commit":commit,"tree":result_tree,"native_state":state["state"],"outer_terminal":finished}),flush=True)
first=snapshot()
publish("terminal" if first[-1] else "initial",first)
if first[-1]:raise SystemExit(0)
deadline=time.monotonic()+7200
while time.monotonic()<deadline:
 time.sleep(10)
 try:current=snapshot()
 except (FileNotFoundError,RuntimeError):continue
 if current[-1]:
  publish("terminal",current)
  raise SystemExit(0)
publish("observer-timeout",snapshot())
raise SystemExit(2)

from pathlib import Path
from datetime import datetime,timezone,timedelta
import fcntl,hashlib,json,os,stat,subprocess,sys,time
sys.dont_write_bytecode=True
payload=json.load(sys.stdin)
root=Path("/home/qian-qi/hepta-utility-36fa-evidence")
repo=Path("/home/qian-qi/hepta-utility-36fa-review-19aa")
build=root/"e8b6-new-build-diagnostic-v4"
out=root/"e8b6-new-binary-diagnostics-v1";out.mkdir(exist_ok=False)
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,b):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
def save(p,v):write(p,(json.dumps(v,sort_keys=True,indent=2)+"\n").encode())
r={"status":"waiting_actual_build","source_sha":"e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd","source_tree":"b607ff5f50812c5e0f932d7dae18d4c74f1269cb","build_job_id":"1a1cf93ac8c-2564-1a5b","build_records":str(build),"started_at":datetime.now(timezone.utc).isoformat(),"qualification":False,"tests_started":False,"cargo_launched_by_this_job":False,"stages":[]}
try:
 if os.geteuid()==0:raise RuntimeError("ordinary user required")
 for name,key in [("panel-driver.py","panel"),("deep-driver.py","deep")]:
  entry=payload[key];b=entry["source"].encode()
  if sha(b)!=entry["sha256"]:raise RuntimeError("frozen diagnostic driver hash differs")
  compile(b,str(out/name),"exec");write(out/name,b)
 save(out/"DRIVER_INPUT.json",payload)
 started_raw=(build/"BUILD_STARTED.json").read_bytes()
 if len(started_raw)!=4188 or sha(started_raw)!="554d98dbec476193b4f85c2767740b5610dffca31e971ffcd684929542e291d8":raise RuntimeError("actual build admission identity differs")
 started=json.loads(started_raw);deadline=datetime.fromisoformat(started["started_at"])+timedelta(seconds=7900)
 save(out/"STARTED.json",{**r,"wait_deadline":deadline.isoformat(),"per_diagnostic_limit_seconds":60,"RUST_MIN_STACK":"8388608","deep_pause_seconds":55,"ASLR_preserved":True,"debuginfod":False})
 print(json.dumps({"event":"waiting_actual_build_result","source_sha":r["source_sha"],"build_job_id":r["build_job_id"]}),flush=True)
 while not (build/"RESULT.json").is_file():
  if datetime.now(timezone.utc)>=deadline:raise RuntimeError("build terminal result unavailable within original bounded dependency window")
  time.sleep(2)
 raw=(build/"RESULT.json").read_bytes();built=json.loads(raw);write(out/"BUILD_RESULT_ORIGINAL.json",raw)
 if built.get("status")!="new_build_diagnostic_ready":raise RuntimeError("actual diagnostic build did not succeed: "+str(built.get("status"))+": "+str(built.get("error")))
 if built["source_sha"]!=r["source_sha"] or built["source_tree"]!=r["source_tree"] or built["source_before"]!=built["source_after"] or built["tests_executed"]!=0:raise RuntimeError("actual build source/zero-test identity differs")
 if built["source_after"]["inventory_sha256"]!="efdf0a2b8aa9879d3ae03c256ac24a23263a195c306f25d9815b05a4af702d56":raise RuntimeError("actual physical source digest differs")
 binary_row=json.loads((build/"BINARY.json").read_text());binary=Path(binary_row["pinned_executable"])
 if binary.parent!=build/"bin" or binary.is_symlink():raise RuntimeError("pinned path differs")
 meta=binary.stat();data=binary.read_bytes()
 if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or data[:4]!=b"\x7fELF" or len(data)!=binary_row["bytes"] or sha(data)!=binary_row["sha256"]:raise RuntimeError("actual pinned ELF differs")
 lock=(root/"REVIEW_SOURCE.lock").open("a+");fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
 active=[]
 for p in Path("/proc").iterdir():
  if not p.name.isdigit():continue
  try:
   if p.stat().st_uid!=os.geteuid():continue
   name=(p/"comm").read_text().strip()
   if name not in ("cargo","rustc","cargo-nextest","just"):continue
   cwd=os.readlink(p/"cwd")
   if cwd.startswith((str(repo),"/data/hepta-utility-36fa-e8-diagnostic-target-v1")):active.append({"pid":int(p.name),"comm":name,"cwd":cwd})
  except (FileNotFoundError,ProcessLookupError,PermissionError):pass
 save(out/"CARGO_TERMINAL_PRECONDITION.json",{"matching_live_processes":active,"build_finished_at":built["finished_at"]})
 if active:raise RuntimeError("own Cargo still active after recorded build result")
 r["status"]="running_authorized_diagnostics"
 for name,script,records in [("panel","panel-driver.py","e8b6-panel-stack-debug-v2"),("deep","deep-driver.py","e8b6-deep-deadline-debug-v1")]:
  command=["/usr/bin/python3",str(out/script),str(build)]
  save(out/(name+"-STARTED.json"),{"at":datetime.now(timezone.utc).isoformat(),"command":command,"per_debugger_timeout_seconds":60,"scope":"Diagnostic only, not test-suite qualification"})
  print(json.dumps({"event":"diagnostic_started","stage":name,"command":command}),flush=True)
  with (out/(name+".stdout")).open("xb") as stdout,(out/(name+".stderr")).open("xb") as stderr:execution=subprocess.run(command,cwd="/home/qian-qi",stdout=stdout,stderr=stderr)
  result_path=root/records/"RESULT.json"
  if not result_path.is_file():raise RuntimeError(name+" diagnostic result unavailable")
  result_raw=result_path.read_bytes();result=json.loads(result_raw);write(out/(name+"-RESULT_ORIGINAL.json"),result_raw)
  r["stages"].append({"name":name,"returncode":execution.returncode,"records":str(root/records),"result_bytes":len(result_raw),"result_sha256":sha(result_raw),"status":result.get("status"),"test_started":result.get("test_started"),"observed_stop_signals":result.get("observed_stop_signals")})
  r["tests_started"]=r["tests_started"] or bool(result.get("test_started"))
  print(json.dumps({"event":"diagnostic_finished",**r["stages"][-1]}),flush=True)
  if result.get("source_before") is None or result["source_before"]!=result.get("source_after") or result["source_before"]["commit"]!=r["source_sha"] or result["source_before"]["inventory_sha256"]!="efdf0a2b8aa9879d3ae03c256ac24a23263a195c306f25d9815b05a4af702d56":raise RuntimeError(name+" current source evidence differs")
  if not result.get("test_started"):raise RuntimeError(name+" test was not actually started; retain precondition diagnosis")
  leftover=[]
  for p in Path("/proc").iterdir():
   if not p.name.isdigit():continue
   try:
    if p.stat().st_uid==os.geteuid() and os.readlink(p/"exe")==str(binary):leftover.append(int(p.name))
   except (FileNotFoundError,ProcessLookupError,PermissionError):pass
  save(out/(name+"-INFERIOR_EXIT_OBSERVATION.json"),{"matching_live_pinned_binary_pids":leftover,"at":datetime.now(timezone.utc).isoformat(),"no_pid_cancelled":True})
  if leftover:raise RuntimeError("diagnostic inferior remains live; do not start subsequent case")
 r["status"]="diagnostic_runs_retained"
except Exception as error:r.update(status="diagnostic_pipeline_stopped",error=type(error).__name__+": "+str(error))
r["finished_at"]=datetime.now(timezone.utc).isoformat();save(out/"RESULT.json",r);print(json.dumps(r,sort_keys=True),flush=True)
raise SystemExit(0 if r["status"]=="diagnostic_runs_retained" else 1)

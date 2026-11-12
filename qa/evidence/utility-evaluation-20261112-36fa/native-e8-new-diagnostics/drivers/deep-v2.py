from pathlib import Path
from datetime import datetime,timezone
import fcntl,gzip,hashlib,json,os,re,resource,stat,subprocess,sys
sys.dont_write_bytecode=True
root=Path("/home/qian-qi/hepta-utility-36fa-evidence")
repo=Path("/home/qian-qi/hepta-utility-36fa-review-19aa")
out=root/"e8b6-deep-deadline-debug-v2"
build_records=Path(sys.argv[1])
source="e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd";tree="b607ff5f50812c5e0f932d7dae18d4c74f1269cb";inv="efdf0a2b8aa9879d3ae03c256ac24a23263a195c306f25d9815b05a4af702d56"
case="runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources"
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,b):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
def save(p,v):write(p,(json.dumps(v,indent=2,sort_keys=True)+"\n").encode())
def git(*args):return subprocess.check_output(["git",*args],cwd=repo,env={**os.environ,"GIT_OPTIONAL_LOCKS":"0"})
def snap(label):
 rows=[];names=sorted(set(git("ls-files","-z").split(b"\0")+git("ls-files","--others","--exclude-standard","-z").split(b"\0"))-{b""})
 for raw in names:
  p=repo/os.fsdecode(raw);m=p.lstat()
  if stat.S_ISLNK(m.st_mode):b=os.fsencode(os.readlink(p));mode="120000"
  elif stat.S_ISREG(m.st_mode):b=p.read_bytes();mode="100755" if m.st_mode&0o111 else "100644"
  else:raise RuntimeError("unexpected source type")
  rows.append({"path":os.fsdecode(raw),"mode":mode,"bytes":len(b),"sha256":sha(b),"blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()})
 raw=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
 v={"commit":git("rev-parse","HEAD").decode().strip(),"tree":git("rev-parse","HEAD^{tree}").decode().strip(),"status":git("status","--porcelain=v1","--untracked-files=all").decode(),"files":len(rows),"inventory_sha256":sha(raw)}
 write(out/(label+".files.json.gz"),gzip.compress(raw,mtime=0));save(out/(label+".json"),v)
 if v["commit"]!=source or v["tree"]!=tree or v["status"] or len(rows)!=14741 or sha(raw)!=inv:raise RuntimeError("diagnostic source not exact e8")
 return v
out.mkdir(exist_ok=False)
r={"status":"preparing","source_sha":source,"source_tree":tree,"case":case,"label":"NEW_BUILD_DIAGNOSTIC","qualification":"One bounded deep-readback debugger diagnostic; pause at 55 seconds and capture all threads within the original 60-second budget, not qualification","started_at":datetime.now(timezone.utc).isoformat(),"test_started":False}
before=None
try:
 if os.geteuid()==0:raise RuntimeError("ordinary user required")
 lock=(root/"REVIEW_SOURCE.lock").open("a+");fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
 native=json.loads((root/"native-e8b6fe2a-v1/RESULT.json").read_text());control=json.loads((root/"countercontrol-e8b6fe2a-v1/RESULT.json").read_text())
 if native["status"]!="failed" or native["source_sha"]!=source or native["source_before"]!=native["source_after"] or control["status"]!="expected_regression_observed":raise RuntimeError("original jobs not in known terminal states")
 if build_records.parent!=root or re.fullmatch(r"e8b6-new-build-diagnostic-v[0-9]+",build_records.name) is None or build_records.is_symlink():raise RuntimeError("unexpected build-record directory")
 build_raw=(build_records/"RESULT.json").read_bytes();built=json.loads(build_raw)
 if built["status"]!="new_build_diagnostic_ready" or built["source_sha"]!=source or built["source_tree"]!=tree or built["source_before"]!=built["source_after"] or built["tests_executed"]!=0:raise RuntimeError("new two-package diagnostic build is not verified terminal")
 if built["package_selection"]!=["codex-hepta-agentd","codex-hepta-intelligence-eval"]:raise RuntimeError("new build package selection differs")
 write(out/"BUILD_RESULT_ORIGINAL.json",build_raw)
 row=json.loads((build_records/"BINARY.json").read_text())
 if row["source_sha"]!=source or row["source_tree"]!=tree or row["label"]!="NEW_BUILD_DIAGNOSTIC":raise RuntimeError("new binary source identity differs")
 binary=Path(row["pinned_executable"])
 if binary.parent!=build_records/"bin" or binary.name!="codex_hepta_agentd-new-build" or binary.is_symlink():raise RuntimeError("unexpected new pinned binary path")
 meta=binary.stat();data=binary.read_bytes()
 if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or not meta.st_mode&0o111 or len(data)!=row["bytes"] or sha(data)!=row["sha256"] or data[:4]!=b"\x7fELF":raise RuntimeError("new pinned binary changed")
 r["build_records"]=str(build_records);r["original_run_binary_available"]=False;r["historical_artifact_scope"]=built["historical_artifact_scope"]
 just=(repo/"justfile").read_text()
 if 'rust_min_stack := "8388608"' not in just or "RUST_MIN_STACK={{ rust_min_stack }}" not in just:raise RuntimeError("original recipe stack contract changed")
 before=snap("source-before")
 env=dict(os.environ);env.update(json.loads((root/"MAINTENANCE_STARTED.json").read_text())["environment"]);env.update(json.loads((root/"native-e8b6fe2a-v1/focused/helpers/env.json").read_text()))
 env.update(SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE="source-head",CODEX_REPO_ROOT=str(repo),PYTHONPATH=str(repo/"scripts"),PYTHONDONTWRITEBYTECODE="1",RUST_MIN_STACK="8388608",NEXTEST_PROFILE="local",CARGO_TERM_COLOR="never")
 env["CARGO_TARGET_DIR"]=built["environment"]["CARGO_TARGET_DIR"]
 r["environment_delta_from_original_focused"]=built["environment_delta_from_original_focused"]
 helper=Path(env["CARGO_BIN_EXE_hepta-joint-propose"]);helper_data=helper.read_bytes()
 if helper.is_symlink() or not helper.is_file() or len(helper_data)!=1439936 or sha(helper_data)!="0a144016bc0f95c570b8fefcfb3eaa2f87171aa0ef2c888c971990f348813c4f":raise RuntimeError("original source-pinned runtime helper differs or is unavailable")
 r["runtime_helper"]={"path":str(helper),"bytes":len(helper_data),"sha256":sha(helper_data)}
 r["execution_difference"]="Direct GDB invocation of exact libtest --exact case; not the nextest runner or original run binary"
 os.environ.update(env)
 r["original_stack_contract"]={"RUST_MIN_STACK":env["RUST_MIN_STACK"],"source":"exact e8 justfile lines 8 and 89","rlimit_before":resource.getrlimit(resource.RLIMIT_STACK),"adjusted_rlimit":False}
 r["binary"]=row;r["cwd"]=str(repo/"codex-rs/hepta-agentd");r["environment"]={k:env.get(k) for k in ["RUST_MIN_STACK","NEXTEST_PROFILE","CARGO_TARGET_DIR","RUSTUP_TOOLCHAIN","CODEX_REPO_ROOT",*json.loads((root/"native-e8b6fe2a-v1/focused/helpers/env.json").read_text()).keys()]}
 gdb_script="""set pagination off
set confirm off
set print frame-arguments none
set disable-randomization off
set debuginfod enabled off
set startup-with-shell off
handle SIGSEGV stop print nopass
handle SIGABRT stop print nopass
handle SIGPIPE nostop noprint pass
handle SIGSTOP stop print nopass
python
import gdb,json,os,signal,threading,time
stop_timer=None
stop_fd=None
stop_started=None
def stop_before_deadline():
 global stop_fd
 observation={"delay_seconds":55,"method":"pidfd_send_signal SIGSTOP to this debugger inferior only","requested_at_unix":time.time()}
 try:
  signal.pidfd_send_signal(stop_fd,signal.SIGSTOP,None,0)
  observation["signal_sent"]=True
 except Exception as error:
  observation["signal_sent"]=False;observation["error"]=type(error).__name__+": "+str(error)
 with open(OUTPUT_DEADLINE_JSON,"x") as output:json.dump(observation,output,indent=2,sort_keys=True);output.write("\\n")
def start_bounded_stop(event):
 global stop_timer,stop_fd,stop_started
 if stop_timer is not None:return
 stop_fd=os.pidfd_open(gdb.selected_inferior().pid,0)
 stop_started=time.monotonic()
 stop_timer=threading.Timer(55,stop_before_deadline);stop_timer.daemon=True;stop_timer.start()
def cancel_bounded_stop(event):
 global stop_timer
 if stop_timer is not None:stop_timer.cancel()
gdb.events.cont.connect(start_bounded_stop)
gdb.events.stop.connect(cancel_bounded_stop)
gdb.events.exited.connect(cancel_bounded_stop)
end
run
info program
info threads
thread apply all bt 64
info registers
info frame
info symbol $pc
x/40i $pc-64
info proc mappings
python
import gdb,json,os
inferior=gdb.selected_inferior()
thread=gdb.selected_thread()
sp=int(gdb.parse_and_eval("$sp"))
pc=int(gdb.parse_and_eval("$pc"))
pid=inferior.pid
tid=thread.ptid[1]
signal_info={}
fault_address=None
try:
 signal_info["raw"]=gdb.execute("p $_siginfo",to_string=True)
 signal_info["number"]=int(gdb.parse_and_eval("$_siginfo.si_signo"))
 if signal_info["number"]==11:fault_address=int(gdb.parse_and_eval("$_siginfo._sifields._sigfault.si_addr"));signal_info["fault_address"]=hex(fault_address)
except Exception as error:signal_info["read_error"]=type(error).__name__+": "+str(error)
print(json.dumps({"kernel_signal_info":signal_info},sort_keys=True))
lines=open("/proc/"+str(pid)+"/task/"+str(tid)+"/maps").read().splitlines()
mappings=[]
for line in lines:
 parts=line.split()
 lo,hi=[int(x,16) for x in parts[0].split("-")]
 if lo<=sp<hi or abs(lo-sp)<=65536 or abs(hi-sp)<=65536 or "[stack]" in line or (fault_address is not None and (lo<=fault_address<hi or abs(lo-fault_address)<=65536 or abs(hi-fault_address)<=65536)):
  mappings.append({"start":hex(lo),"end":hex(hi),"bytes":hi-lo,"contains_sp":lo<=sp<hi,"contains_fault_address":fault_address is not None and lo<=fault_address<hi,"line":line})
observation={"pid":pid,"tid":tid,"sp":hex(sp),"pc":hex(pc),"signal_info":signal_info,"near_sp_and_fault_and_named_stack_mappings":mappings,"method":"Read-only /proc thread maps plus stopped-thread registers; no inferior function call"}
print(json.dumps(observation,sort_keys=True))
with open(OUTPUT_STACK_JSON,"x") as f:json.dump(observation,f,indent=2,sort_keys=True);f.write("\\n")
end
quit
""".replace("OUTPUT_STACK_JSON",repr(str(out/"STOPPED_THREAD_STACK.json"))).replace("OUTPUT_DEADLINE_JSON",repr(str(out/"TIME_BOUND_STOP.json")))
 write(out/"commands.gdb",gdb_script.encode())
 command=["/usr/bin/gdb","--batch","--nx","--quiet","-x",str(out/"commands.gdb"),"--args",str(binary),"--exact",case,"--nocapture"]
 save(out/"DEBUG_STARTED.json",{**r,"command":command,"timeout_seconds":60,"at":datetime.now(timezone.utc).isoformat()})
 sys.path.insert(0,str(repo/"scripts"));from hepta_ci_exec import execute_logged
 os.chdir(repo/"codex-rs/hepta-agentd");r["debugger_invocation_started"]=True
 execution=execute_logged(command,out/"gdb.log",timeout_seconds=60)
 r["execution"]=execution;raw=(out/"gdb.log").read_bytes();write(out/"gdb.log.gz",gzip.compress(raw,mtime=0))
 r["raw"]={"bytes":len(raw),"sha256":sha(raw),"gzip_bytes":(out/"gdb.log.gz").stat().st_size,"gzip_sha256":sha((out/"gdb.log.gz").read_bytes())}
 signals=re.findall(r"received signal (SIGSEGV|SIGABRT|SIGSTOP)",raw.decode(errors="replace"));r["observed_stop_signals"]=signals;r["test_started"]=b"running 1 test" in raw
 if execution["timed_out"] or execution["output_limit_exceeded"]:raise RuntimeError("bounded debugger did not complete")
 if not signals or not (out/"STOPPED_THREAD_STACK.json").exists():raise RuntimeError("no captured bounded thread stop")
 if sha(binary.read_bytes())!=row["sha256"]:raise RuntimeError("new pinned binary changed")
 r["status"]="bounded_deep_thread_diagnostic_retained"
except Exception as e:r.update(status="diagnostic_failed",error=type(e).__name__+": "+str(e))
finally:
 os.chdir(repo)
 try:
  after=snap("source-after");r["source_after"]=after
  if before and before!=after:r.update(status="diagnostic_failed",source_changed=True)
 except Exception as e:r.update(status="diagnostic_failed",final_source_error=str(e))
 r["source_before"]=before;r["finished_at"]=datetime.now(timezone.utc).isoformat();save(out/"RESULT.json",r);print(json.dumps(r,sort_keys=True),flush=True)
raise SystemExit(0 if r["status"]=="first_crash_diagnostic_retained" else 1)

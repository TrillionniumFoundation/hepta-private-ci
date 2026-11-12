from pathlib import Path
from datetime import datetime,timezone
import fcntl,gzip,hashlib,json,os,re,resource,stat,subprocess,sys,xml.etree.ElementTree as ET
sys.dont_write_bytecode=True
root=Path("/home/qian-qi/hepta-utility-36fa-evidence")
repo=Path("/home/qian-qi/hepta-utility-36fa-review-19aa")
out=root/"c0f-panel-first-signal-v1"
preservation=root/"c0f-failed-binary-preservation-v1"
native_records=root/"native-c0f78493-v1"
source="c0f78493f815780f68b9bf5e390a21314d79311f";tree="313ee34febc8ccc54c611ab56286e289518c63cb";inv="c7f8f0a34ef5e5c7ed7bac0ea3cc2b70a06af9e4bc974204a841db1a03eaa49f"
case="runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::original_panel_reads_actual_b_and_retention_with_full_original_signatures"
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
 if v["commit"]!=source or v["tree"]!=tree or v["status"] or len(rows)!=14851 or sha(raw)!=inv:raise RuntimeError("diagnostic source not exact c0f")
 return v
out.mkdir(exist_ok=False)
r={"status":"preparing","source_sha":source,"source_tree":tree,"case":case,"label":"ORIGINAL_FAILED_BINARY_DIAGNOSTIC","qualification":False,"scope":"One bounded first-signal debugger diagnostic on a byte-identical retained original c0f failed test binary; not a qualification, repair, new build, or suite rerun","started_at":datetime.now(timezone.utc).isoformat(),"test_started":False}
before=None
try:
 if os.geteuid()==0:raise RuntimeError("ordinary user required")
 lock=(root/"REVIEW_SOURCE.lock").open("a+");fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
 native_raw=(native_records/"RESULT.json").read_bytes()
 if sha(native_raw)!="f7dd374ff8113453f14e99d34ba48b9356d44f969c1f01a6a618819ac2f89540":raise RuntimeError("original native terminal record changed")
 native=json.loads(native_raw)
 if native["status"]!="failed" or native["source_sha"]!=source or native["source_tree"]!=tree or native["source_before"]!=native["source_after"]:raise RuntimeError("original native job is not the known clean terminal failure")
 preserved_raw=(preservation/"RESULT.json").read_bytes()
 if sha(preserved_raw)!="4d372a15a1b0191147184cef7c3df17ff34868c4b31a5c27aad8f478f7bd2329":raise RuntimeError("binary preservation record changed")
 preserved=json.loads(preserved_raw)
 if preserved["status"]!="retained_original_failed_binaries" or preserved["source_sha"]!=source or preserved["source_tree"]!=tree or preserved["source_before"]!=preserved["source_after"] or preserved["cargo_or_tests_launched"]:raise RuntimeError("original failed binary preservation not verified")
 rows=[x for x in preserved["binaries"] if Path(x["retained"]).name=="codex_hepta_agentd-0bb720b95785b5fd"]
 if len(rows)!=1:raise RuntimeError("exact preserved agentd executable absent")
 row=rows[0];binary=Path(row["retained"])
 if binary.parent!=preservation/"bin" or binary.is_symlink() or row["bytes"]!=282318328 or row["sha256"]!="b63053496fb1a8f610445862a6ce980ccb7beead4e08796feaa97ab21813e119" or not row["copy_readback_equal"]:raise RuntimeError("unexpected original retained executable identity")
 meta=binary.stat();data=binary.read_bytes()
 if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or not meta.st_mode&0o111 or len(data)!=row["bytes"] or sha(data)!=row["sha256"] or data[:4]!=bytes([127,69,76,70]):raise RuntimeError("retained original binary changed")
 del data
 original_xml=(native_records/"focused/focused.xml").read_bytes()
 if len(original_xml)!=49808 or sha(original_xml)!="e1e7901986fef0bb4a682156d87eef31b93a54f7e8759e564966dac136e198e7":raise RuntimeError("original focused JUnit changed")
 selected=[c for c in ET.fromstring(original_xml).iter("testcase") if c.attrib.get("name")==case]
 if len(selected)!=1 or selected[0].find("failure") is None or "SIGABRT" not in ET.tostring(selected[0],encoding="unicode") or "stack overflow" not in ET.tostring(selected[0],encoding="unicode"):raise RuntimeError("authorized case is not the known original stack failure")
 original_run=(native_records/"focused/focused.json").read_bytes()
 run=json.loads(original_run)
 if run.get("command_exit_code")!=100:raise RuntimeError("original focused command did not have known exit100")
 write(out/"NATIVE_RESULT_ORIGINAL.json",native_raw);write(out/"PRESERVATION_RESULT_ORIGINAL.json",preserved_raw);write(out/"FOCUSED_RUN_ORIGINAL.json",original_run);write(out/"FOCUSED_JUNIT_ORIGINAL.xml",original_xml)
 r["original_run_binary_available"]=True;r["recompiled"]=False;r["original_failed_case"]={"name":case,"junit_sha256":sha(original_xml),"original_command_exit_code":run["command_exit_code"]}
 just=(repo/"justfile").read_text()
 if 'rust_min_stack := "8388608"' not in just or "RUST_MIN_STACK={{ rust_min_stack }}" not in just:raise RuntimeError("original recipe stack contract changed")
 before=snap("source-before")
 env=dict(os.environ);env.update(json.loads((root/"MAINTENANCE_STARTED.json").read_text())["environment"])
 helper_env_raw=(native_records/"focused/helpers/env.json").read_bytes()
 if sha(helper_env_raw)!="403d4476cd0fde6d54c173721b40fa7d79b31c790cee5fb6889e9370de36c4ec":raise RuntimeError("original helper environment changed")
 helper_env=json.loads(helper_env_raw);env.update(helper_env);write(out/"HELPER_ENV_ORIGINAL.json",helper_env_raw)
 env.update(SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE="source-head",CODEX_REPO_ROOT=str(repo),PYTHONPATH=str(repo/"scripts"),PYTHONDONTWRITEBYTECODE="1",RUST_MIN_STACK="8388608",NEXTEST_PROFILE="local",CARGO_TERM_COLOR="never")
 env.update(CARGO_TARGET_DIR="/data/hepta-utility-36fa-final-native-target-v1",CARGO_NET_OFFLINE="true")
 r["environment_delta_from_original_focused"]={"runner":"Direct GDB/libtest invocation instead of nextest; nextest per-case injected metadata is not reproduced","executable_path":"Verified byte-identical create-only retained copy of the original failed native ELF"}
 helper=Path(env["CARGO_BIN_EXE_hepta-joint-propose"]);helper_data=helper.read_bytes()
 if helper.is_symlink() or not helper.is_file() or len(helper_data)!=1439936 or sha(helper_data)!="0a144016bc0f95c570b8fefcfb3eaa2f87171aa0ef2c888c971990f348813c4f":raise RuntimeError("original source-pinned runtime helper differs or is unavailable")
 r["runtime_helper"]={"path":str(helper),"bytes":len(helper_data),"sha256":sha(helper_data)}
 r["execution_difference"]="Direct GDB invocation of the exact libtest --exact case using the retained original failed binary; diagnostic only, not the nextest runner or a qualification"
 os.environ.update(env)
 r["original_stack_contract"]={"RUST_MIN_STACK":env["RUST_MIN_STACK"],"source":"exact c0f justfile rust_min_stack and test recipe","rlimit_before":resource.getrlimit(resource.RLIMIT_STACK),"adjusted_rlimit":False}
 r["binary"]=row;r["cwd"]=str(repo/"codex-rs/hepta-agentd");r["environment"]={k:env.get(k) for k in ["RUST_MIN_STACK","NEXTEST_PROFILE","CARGO_TARGET_DIR","RUSTUP_TOOLCHAIN","CODEX_REPO_ROOT",*helper_env.keys()]}
 gdb_script="""set pagination off
set confirm off
set print frame-arguments none
set disable-randomization off
set debuginfod enabled off
set startup-with-shell off
handle SIGSEGV stop print nopass
handle SIGABRT stop print nopass
handle SIGPIPE nostop noprint pass
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
""".replace("OUTPUT_STACK_JSON",repr(str(out/"STOPPED_THREAD_STACK.json")))
 write(out/"commands.gdb",gdb_script.encode())
 command=["/usr/bin/gdb","--batch","--nx","--quiet","-x",str(out/"commands.gdb"),"--args",str(binary),"--exact",case,"--nocapture"]
 save(out/"DEBUG_STARTED.json",{**r,"command":command,"timeout_seconds":60,"at":datetime.now(timezone.utc).isoformat()})
 sys.path.insert(0,str(repo/"scripts"));from hepta_ci_exec import execute_logged
 os.chdir(repo/"codex-rs/hepta-agentd");r["debugger_invocation_started"]=True
 execution=execute_logged(command,out/"gdb.log",timeout_seconds=60)
 r["execution"]=execution;raw=(out/"gdb.log").read_bytes();write(out/"gdb.log.gz",gzip.compress(raw,mtime=0))
 r["raw"]={"bytes":len(raw),"sha256":sha(raw),"gzip_bytes":(out/"gdb.log.gz").stat().st_size,"gzip_sha256":sha((out/"gdb.log.gz").read_bytes())}
 signals=re.findall(r"received signal (SIGSEGV|SIGABRT)",raw.decode(errors="replace"));r["observed_stop_signals"]=signals;r["test_started"]=b"running 1 test" in raw
 if execution["timed_out"] or execution["output_limit_exceeded"]:raise RuntimeError("bounded debugger did not complete")
 if not signals or not (out/"STOPPED_THREAD_STACK.json").exists():raise RuntimeError("no captured first crash stop")
 if sha(binary.read_bytes())!=row["sha256"]:raise RuntimeError("retained original binary changed")
 r["status"]="first_crash_diagnostic_retained"
except Exception as e:r.update(status="diagnostic_failed",error=type(e).__name__+": "+str(e))
finally:
 os.chdir(repo)
 try:
  after=snap("source-after");r["source_after"]=after
  if before is None:r.update(source_changed=None,source_comparison="unknown_missing_before")
  elif before!=after:r.update(status="diagnostic_failed",source_changed=True,source_comparison="different")
  else:r.update(source_changed=False,source_comparison="equal")
 except Exception as e:r.update(status="diagnostic_failed",final_source_error=str(e),source_changed=None,source_comparison="unknown_missing_after")
 r["source_before"]=before;r["finished_at"]=datetime.now(timezone.utc).isoformat();save(out/"RESULT.json",r);print(json.dumps(r,sort_keys=True),flush=True)
raise SystemExit(0 if r["status"]=="first_crash_diagnostic_retained" else 1)

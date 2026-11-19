"""Execute the original eleven native scope regressions on one frozen source."""
import fcntl, hashlib, json, os, resource, shutil, signal, subprocess, sys, time, traceback
import xml.etree.ElementTree as ET
from pathlib import Path

BASE=Path("/home/qq/work/hepta-e6-operation-scope-20261118-2e9b")
SRC=BASE/"source"
TARGET=BASE/"native-target"
OUT=BASE/"native-validation-3"
PROTOCOL=BASE/"native3-PROTOCOL.json"
DEPLOYMENT=BASE/"native3-DEPLOYMENT.json"
ORIGINAL_ENV=Path("/home/qq/hepta-learn-ff41-tools/env.json")
LIBCLANG=Path("/usr/lib/x86_64-linux-gnu/libclang-21.so.21")
STDDEF=Path("/usr/lib/gcc/x86_64-linux-gnu/15/include/stddef.h")

def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle,"sha256").hexdigest()

def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2)+"\n")

def inventory():
    rows=[]
    for item in subprocess.check_output(["git","ls-files","-s","-z"],cwd=SRC).split(b"\0"):
        if not item: continue
        _,name=item.split(b"\t",1)
        p=SRC/os.fsdecode(name)
        data=os.fsencode(os.readlink(p)) if p.is_symlink() else p.read_bytes()
        rows.append({"path":os.fsdecode(name),"kind":"symlink" if p.is_symlink() else "regular",
            "mode":p.lstat().st_mode&0o7777,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    raw=(json.dumps(rows,sort_keys=True,separators=(",",":"))+"\n").encode()
    return rows,hashlib.sha256(raw).hexdigest()

def git(*args):
    return subprocess.check_output(["git",*args],cwd=SRC).decode().strip()

assert not OUT.exists(),"native owner namespace already exists"
OUT.mkdir()
started=time.monotonic()
owner_usage=resource.getrusage(resource.RUSAGE_CHILDREN)
owner_self=resource.getrusage(resource.RUSAGE_SELF)
r={"status":"preflight","started_at_ns":str(time.time_ns()),"native_adoption":False,
   "complete_NoUpdate":False,"automatic_retry":False,"original_executor_mutated":False,
   "original_executor_target_reused":False,"own_prior_target_reused":True,
   "cargo_target_dir":str(TARGET),"cost_scope":"The actual just test interval includes this source's compilation and all test descendants. Owner and command windows overlap and are not additive. Child max RSS is not simultaneous whole-system RSS.",
   "unknown_costs":["whole-system concurrent CPU/RSS","physical energy","physical network bytes","physical storage byte-seconds","provider charges"]}
owners=[]
before_files=None
protocol={}
before_usage=None
child=None
try:
    assert os.getuid()==os.geteuid()==1000
    protocol=json.loads(PROTOCOL.read_text())
    deployment=json.loads(DEPLOYMENT.read_text())
    assert sha(PROTOCOL)==deployment["protocol_sha256"]
    assert sha(__file__)==deployment["driver_sha256"]
    for name,p in [("PROTOCOL.json",PROTOCOL),("DEPLOYMENT.json",DEPLOYMENT),("owner.py",Path(__file__))]:
        shutil.copyfile(p,OUT/name)
    assert sha(ORIGINAL_ENV)==protocol["original_environment_file_sha256"]
    assert sha(LIBCLANG)==protocol["libclang_sha256"]
    assert sha(STDDEF)==protocol["stddef_sha256"]
    freeze_path=BASE/protocol["source_freeze_result"]
    assert sha(freeze_path)==protocol["source_freeze_result_sha256"]
    freeze=json.loads(freeze_path.read_text())
    assert freeze["successful"] and freeze["source_clean"] and freeze["scanned_inputs_byte_identical"]
    assert freeze["source"]==protocol["source"] and freeze["tree"]==protocol["tree"]
    assert freeze["source_inventory_sha256"]==protocol["source_inventory_sha256"]
    for p in (BASE/"native-component-owner.lock",TARGET/".hepta-root-native-owner.lock"):
        handle=p.open("a+b")
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        owners.append(handle)
    with (TARGET/"debug/.cargo-lock").open("rb") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(handle,fcntl.LOCK_UN)
    assert git("rev-parse","HEAD")==protocol["source"]
    assert git("rev-parse","HEAD^{tree}")==protocol["tree"]
    assert not git("status","--porcelain","--untracked-files=all")
    before_files,before_digest=inventory()
    assert before_digest==protocol["source_inventory_sha256"]
    save("TRACKED_FILES_BEFORE.json",before_files)
    r.update(source=protocol["source"],tree=protocol["tree"],source_inventory_sha256=before_digest,
        source_files=len(before_files),frozen_at_ns=freeze["frozen_at_ns"],
        protocol_sha256=sha(PROTOCOL),driver_sha256=sha(__file__),deployment=deployment,
        cargo_build_jobs=protocol["cargo_build_jobs"],source_freeze_result_sha256=sha(freeze_path))
    env=dict(os.environ)
    original=json.loads(ORIGINAL_ENV.read_text())
    permitted={"PATH","LIBCLANG_PATH","BINDGEN_EXTRA_CLANG_ARGS","RUSTUP_TOOLCHAIN","RUSTY_V8_ARCHIVE",
        "RUSTY_V8_SRC_BINDING_PATH","RUSTFLAGS","LD_LIBRARY_PATH","CARGO_HOME","RUSTUP_HOME"}
    for key in permitted:
        if key in original: env[key]=original[key]
    for key in list(env):
        if key.startswith("CARGO_PROFILE_") or key.startswith("CARGO_BIN_EXE_"):
            del env[key]
    env.update(RUSTUP_TOOLCHAIN="1.96.0",CARGO_BUILD_JOBS=str(protocol["cargo_build_jobs"]),
        CARGO_INCREMENTAL="0",CARGO_TARGET_DIR=str(TARGET),CARGO_NET_OFFLINE="true",
        PYTHONDONTWRITEBYTECODE="1",GIT_TERMINAL_PROMPT="0")
    env["PATH"]=str(BASE/"tooling/bin")+":/home/qq/.cargo/bin:"+env.get("PATH","/usr/bin:/bin")
    for key in ("GIT_TRACE","GIT_CURL_VERBOSE","GIT_TRACE_CURL"):env.pop(key,None)
    r["compiler_environment"]={k:env[k] for k in ("LIBCLANG_PATH","BINDGEN_EXTRA_CLANG_ARGS","RUSTUP_TOOLCHAIN") if k in env}
    reports=[TARGET/"nextest/local/junit.xml",SRC/"codex-rs/target/nextest/local/junit.xml"]
    r["prior_reports_excluded"]=[]
    for i,p in enumerate(reports):
        if p.exists():
            old=OUT/("excluded-prior-nextest-"+str(i)+".xml")
            previous={"original_path":str(p),"bytes":p.stat().st_size,"sha256":sha(p),"retained_path":str(old)}
            p.rename(old)
            r["prior_reports_excluded"].append(previous)
    argv=protocol["argv"]
    assert argv[:4]==["just","test","--locked","--offline"]
    r.update(status="running",argv=argv,cwd=str(SRC/"codex-rs"),disk_free_bytes_before=shutil.disk_usage(TARGET).free)
    save("RESULT.json",r)
    before_usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    command_start=time.monotonic()
    with (OUT/"command.stdout").open("xb") as stdout,(OUT/"command.stderr").open("xb") as stderr:
        child=subprocess.Popen(argv,cwd=SRC/"codex-rs",env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        r["pid"]=child.pid
        save("RESULT.json",r)
        print(json.dumps({"status":"native-command-started","source":protocol["source"],"pid":child.pid,"expected_native_cases":len(protocol["expected_cases"])}),flush=True)
        timed_out=False
        try:
            code=child.wait(timeout=protocol["timeout_seconds"])
        except subprocess.TimeoutExpired:
            timed_out=True
            os.killpg(child.pid,signal.SIGTERM)
            try: code=child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid,signal.SIGKILL)
                code=child.wait(timeout=10)
    after_usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    r.update(status="completed",command_exit=code,timed_out=timed_out,
        command_wall_seconds=time.monotonic()-command_start,
        command_child_user_cpu_seconds=after_usage.ru_utime-before_usage.ru_utime,
        command_child_system_cpu_seconds=after_usage.ru_stime-before_usage.ru_stime,
        command_child_input_blocks=after_usage.ru_inblock-before_usage.ru_inblock,
        command_child_output_blocks=after_usage.ru_oublock-before_usage.ru_oublock,
        owner_children_max_rss_kib=after_usage.ru_maxrss,
        stdout_sha256=sha(OUT/"command.stdout"),stderr_sha256=sha(OUT/"command.stderr"))
    observed=[p for p in reports if p.exists()]
    r["junit"]=[]
    cases=[]
    for i,p in enumerate(observed):
        retained=OUT/("original-nextest-"+str(i)+".xml")
        shutil.copyfile(p,retained)
        r["junit"].append({"original_path":str(p),"retained_path":str(retained),"bytes":retained.stat().st_size,"sha256":sha(retained)})
        for case in ET.parse(retained).iter("testcase"):
            cases.append({"name":case.attrib["name"],"classname":case.attrib.get("classname"),
                "time":case.attrib.get("time"),"failures":len(case.findall("failure")),
                "errors":len(case.findall("error")),"skipped":len(case.findall("skipped"))})
    expected=protocol["expected_cases"]
    actual=[x["name"] for x in cases]
    r.update(test_cases=cases,native_cases=len(cases),expected_native_cases=len(expected),
        missing_cases=sorted(set(expected)-set(actual)),unexpected_cases=sorted(set(actual)-set(expected)))
    r["all_native_passed"]=(len(observed)==1 and len(cases)==len(expected)
        and sorted(actual)==sorted(expected) and all(not (x["failures"] or x["errors"] or x["skipped"]) for x in cases)
except BaseException as error:
    r.update(status="driver_failed",error=repr(error))
    (OUT/"ERROR.txt").write_text(traceback.format_exc())
finally:
    try:
        after_files,after_digest=inventory()
        save("TRACKED_FILES_AFTER.json",after_files)
        r.update(source_after_sha256=after_digest,source_unchanged=(before_files is not None and before_files==after_files),
            head_unchanged=git("rev-parse","HEAD")==protocol.get("source"),
            tree_unchanged=git("rev-parse","HEAD^{tree}")==protocol.get("tree"),
            source_clean=not git("status","--porcelain","--untracked-files=all"))
        r["compiler_environment_unchanged"]=(sha(ORIGINAL_ENV)==protocol.get("original_environment_file_sha256")
            and sha(LIBCLANG)==protocol.get("libclang_sha256") and sha(STDDEF)==protocol.get("stddef_sha256"))
        r["disk_free_bytes_after"]=shutil.disk_usage(TARGET).free
    except BaseException as error:
        r["source_after_error"]=repr(error)
    end_usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    end_self=resource.getrusage(resource.RUSAGE_SELF)
    r.update(finished_at_ns=str(time.time_ns()),owner_wall_seconds=time.monotonic()-started,
        owner_child_user_cpu_seconds=end_usage.ru_utime-owner_usage.ru_utime,
        owner_child_system_cpu_seconds=end_usage.ru_stime-owner_usage.ru_stime,
        owner_self_user_cpu_seconds=end_self.ru_utime-owner_self.ru_utime,
        owner_self_system_cpu_seconds=end_self.ru_stime-owner_self.ru_stime)
    r["successful"]=(r["status"]=="completed" and r.get("command_exit")==0 and not r.get("timed_out",True)
        and r.get("all_native_passed") is True and r.get("source_unchanged") is True
        and r.get("head_unchanged") is True and r.get("tree_unchanged") is True
        and r.get("source_clean") is True and r.get("compiler_environment_unchanged") is True)
    save("RESULT.json",r)
    for handle in reversed(owners): handle.close()
    print(json.dumps({k:r.get(k) for k in ("status","successful","source","native_cases","command_exit","command_wall_seconds","owner_wall_seconds","error")}),flush=True)
raise SystemExit(0 if r["successful"] else 1)

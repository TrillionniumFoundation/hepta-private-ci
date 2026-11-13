"""Isolated source maintenance only. No tests, qualification, authority or main merge."""
import base64, hashlib, json, os, re, signal, stat, subprocess, sys, time, traceback
from pathlib import Path
C=json.loads(sys.argv[1]); START=time.monotonic(); DEADLINE=START+C["overall_timeout_seconds"]
FINALIZING=False; EVIDENCE_DEADLINE=None
URL="https://github.com/TrillionniumFoundation/hepta-private-ci.git"
assert C["branch"]=="codex/ordinary-owner-maintenance-v7-20261112-af52"
assert C["head"]=="7434600f61293543f11b3ccd2e2c7102e32b3f3c"
assert C["tree"]=="d0a887edbd797583b2ba3d08cd1bb66ea4ae324d"
assert C["source_manifest_blob"]=="b2227120620c86ce7634e97a7b11dd74ab313489"
assert C["packages"]==["codex-hepta-agentd","codex-hepta-learning-artifacts","codex-hepta-intelligence-eval","codex-hepta-contracts","codex-hepta-neuron","codex-hepta-learning-ledger","codex-hepta-fleet","codex-core","codex-app-server","codex-rmcp-client","codex-mcp"]
assert os.getuid()!=0 and os.geteuid()!=0
WORK=Path(C["work_root"])/C["work_name"]; SOURCE=WORK/"source"; RECORDS=WORK/"records"
REFERENCE=Path(C["reference_repository"]); TARGET=Path(C["operator_target"])
assert str(WORK)=="/home/qq/af52-learning-local-decision-20261111/ordinary-future-197-maintenance-v7"
for path in [WORK.parent,REFERENCE,TARGET,Path(C["just_path"]),Path(C["cargo_home"]),Path(C["rustup_home"])]:
    assert path.is_absolute() and path.resolve()==path and ".." not in path.parts,str(path)
WORK.mkdir(mode=0o700); RECORDS.mkdir(mode=0o700); os.umask(0o022)
env=dict(os.environ)
for key in list(env):
    if key.startswith("CARGO_BIN_EXE_") or key.startswith("GIT_CONFIG_"): env.pop(key,None)
for key in ["NEXTEST_PROFILE","NEXTEST_USER_CONFIG_FILE","HEPTA_NEXTTEST_FULL_METADATA","SOURCE_SHA","TESTED_SHA","BASE_SHA","HEPTA_CI_LANE","RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS"]: env.pop(key,None)
env.update({"PATH":C["path"],"GIT_TERMINAL_PROMPT":"0","CARGO_TARGET_DIR":str(TARGET),"RUSTUP_TOOLCHAIN":"1.96.0","CARGO_HOME":C["cargo_home"],"RUSTUP_HOME":C["rustup_home"],"CARGO_INCREMENTAL":"0","CARGO_BUILD_JOBS":"2","CARGO_PROFILE_DEV_DEBUG":"0","CARGO_PROFILE_TEST_DEBUG":"0","CARGO_NET_OFFLINE":"true","PYTHONDONTWRITEBYTECODE":"1","BINDGEN_EXTRA_CLANG_ARGS":"-isystem/usr/lib/gcc/x86_64-linux-gnu/15/include","SOURCE_SHA":C["head"],"TESTED_SHA":C["head"],"HEPTA_CI_LANE":"source-head"})
R={"schema_version":1,"classification":"SOURCE_MAINTENANCE_ONLY_NOT_QUALIFICATION","input":C,"status":"running","steps":[],"errors":[],"ordinary_business_counts":[0,0,0],"tests_run":False,"original_checker_verify_run":False,"native_qualification_run":False,"source_ready":False,"maintenance_checks_passed":False,"publication_status":"not_attempted_root_will_transfer_verified_postimages","completion_unknown":False}
def supervisor_interrupt(signum,frame):
    R["external_interruption_signal"]=signum
    raise InterruptedError("source maintenance supervisor interrupted by signal "+str(signum))
signal.signal(signal.SIGTERM,supervisor_interrupt)
signal.signal(signal.SIGHUP,supervisor_interrupt)
def sha(data): return hashlib.sha256(data).hexdigest()
def blob(data): return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def read_bytes(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        a=os.fstat(fd)
        assert stat.S_ISREG(a.st_mode),"regular file required"
        with os.fdopen(fd,"rb",closefd=False) as f: data=f.read()
        b=os.fstat(fd)
        ident=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
        assert ident(a)==ident(b) and len(data)==a.st_size,"changed original file"
        return data
    finally: os.close(fd)
def save(name,value):
    raw=(json.dumps(value,indent=2,sort_keys=True)+"\n").encode()
    tmp=RECORDS/(name+".tmp"); destination=RECORDS/name
    with open(tmp,"wb") as f: f.write(raw);f.flush();os.fsync(f.fileno())
    tmp.replace(destination)
    return {"path":str(destination),"bytes":len(raw),"sha256":sha(raw),"git_blob":blob(raw)}
def progress(stage):
    R["stage"]=stage;save("progress.json",R)
    print(json.dumps({"stage":stage,"status":R["status"],"records":str(RECORDS)},sort_keys=True),flush=True)
def remaining(maximum):
    value=min(maximum,DEADLINE-time.monotonic())
    if value<=0: raise TimeoutError("source maintenance overall budget exhausted")
    return value
def kill_owned_group_before_reap(p):
    # The exact session/group was just created by us. Kill before reaping its leader.
    # A timeout remains fatal and completion-unknown; this does not certify every descendant's exit.
    try: os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    try: p.wait(timeout=10)
    except subprocess.TimeoutExpired: pass
def command(label,args,timeout,cwd=None,required=True):
    if FINALIZING: raise RuntimeError("new work is forbidden during evidence cleanup")
    start=time.monotonic(); log=RECORDS/(label+".log")
    progress(label);budget=remaining(timeout)
    with open(log,"xb") as output:
        try: p=subprocess.Popen(args,cwd=cwd or SOURCE,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        except BaseException as error:
            R["completion_unknown"]=True
            R.setdefault("child_creation_unknown",[]).append({"label":label,"command":args,"error_type":type(error).__name__,"error":str(error)})
            save("progress.json",R)
            raise
        timeout_hit=False
        try: code=p.wait(timeout=budget)
        except subprocess.TimeoutExpired:
            timeout_hit=True;R["completion_unknown"]=True
            R.setdefault("timed_out_commands",[]).append(label)
            kill_owned_group_before_reap(p);code=p.returncode
        except BaseException as error:
            R["completion_unknown"]=True
            aborted={"label":label,"command":args,"cwd":str(cwd or SOURCE),"log_path":str(log),"error_type":type(error).__name__,"error":str(error),"leader_returncode":p.returncode}
            if p.returncode is None:
                kill_owned_group_before_reap(p)
                aborted["owned_group_kill_requested_before_reap"]=True
            else:
                aborted["group_cleanup_not_attempted_after_leader_reap"]=True
            R.setdefault("aborted_commands",[]).append(aborted)
            save(label+".aborted.json",aborted);save("progress.json",R)
            raise
    step={"label":label,"command":args,"cwd":str(cwd or SOURCE),"exit_code":code,"timed_out":timeout_hit,"elapsed_seconds":time.monotonic()-start,"log_path":str(log),"log_may_be_incomplete":timeout_hit}
    R["steps"].append(step);save(label+".execution.json",step);save("progress.json",R)
    data=read_bytes(log)
    step["log"]={"path":str(log),"bytes":len(data),"sha256":sha(data),"git_blob":blob(data)}
    save(label+".execution.json",step);save("progress.json",R)
    print(json.dumps({"completed":label,"exit_code":code,"timed_out":timeout_hit,"log_bytes":len(data)},sort_keys=True),flush=True)
    if timeout_hit: raise TimeoutError("owned command timed out; no subsequent work/capture/publication may assume completion: "+label)
    if required and code!=0: raise RuntimeError("source maintenance command failed: "+label)
    return code,data
def retain_git_read_failure(argv,directory,kind,output,error,returncode=None):
    number=R.get("git_read_failure_counter",0);R["git_read_failure_counter"]=number+1
    item={"command":argv,"cwd":str(directory),"kind":kind,"returncode":returncode,"during_evidence_cleanup":FINALIZING}
    for stream_name,data in [("stdout",output),("stderr",error)]:
        if data is None:
            item[stream_name]={"captured":False,"reason":"no bytes supplied by the original operation"}
            continue
        if not isinstance(data,bytes):
            item[stream_name]={"captured":False,"reason":"unexpected non-byte operation result","type":type(data).__name__}
            continue
        path=RECORDS/("git-read-failure-%03d.%s.bin"%(number,stream_name))
        with open(path,"xb") as f: f.write(data);f.flush();os.fsync(f.fileno())
        item[stream_name]={"captured":True,"path":str(path),"bytes":len(data),"sha256":sha(data),"git_blob":blob(data)}
    pin=save("git-read-failure-%03d.json"%number,item)
    R.setdefault("git_read_failure_evidence",[]).append(pin);save("progress.json",R)
def git_read(*args,cwd=None):
    if FINALIZING:
        budget=min(30,EVIDENCE_DEADLINE-time.monotonic())
        if budget<=0: raise TimeoutError("separate evidence cleanup budget exhausted")
    else: budget=remaining(120)
    argv=["git","--no-optional-locks",*args]
    try: p=subprocess.Popen(argv,cwd=cwd or SOURCE,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    except BaseException as error:
        R["completion_unknown"]=True
        R.setdefault("child_creation_unknown",[]).append({"command":argv,"cwd":str(cwd or SOURCE),"error_type":type(error).__name__,"error":str(error),"during_evidence_cleanup":FINALIZING})
        save("progress.json",R)
        raise
    try: output,error=p.communicate(timeout=budget)
    except subprocess.TimeoutExpired as exc:
        R["completion_unknown"]=True
        R.setdefault("timed_out_reads",[]).append({"command":argv,"cwd":str(cwd or SOURCE),"during_evidence_cleanup":FINALIZING})
        if p.returncode is None: kill_owned_group_before_reap(p)
        else: R.setdefault("reaped_group_cleanup_unknown",[]).append({"command":argv,"pid":p.pid})
        if p.stdout is not None: p.stdout.close()
        if p.stderr is not None: p.stderr.close()
        retain_git_read_failure(argv,cwd or SOURCE,"timeout",exc.output,exc.stderr,p.returncode)
        raise TimeoutError("bounded owned Git read timed out") from exc
    except BaseException as exc:
        R["completion_unknown"]=True
        if p.returncode is None: kill_owned_group_before_reap(p)
        else: R.setdefault("reaped_group_cleanup_unknown",[]).append({"command":argv,"pid":p.pid})
        if p.stdout is not None: p.stdout.close()
        if p.stderr is not None: p.stderr.close()
        retain_git_read_failure(argv,cwd or SOURCE,"aborted",getattr(exc,"output",None),getattr(exc,"stderr",None),p.returncode)
        raise
    if p.returncode!=0:
        retain_git_read_failure(argv,cwd or SOURCE,"nonzero-exit",output,error,p.returncode)
        raise subprocess.CalledProcessError(p.returncode,argv,output=output,stderr=error)
    return output
def identity(directory):
    return {"head":git_read("rev-parse","HEAD",cwd=directory).decode().strip(),"tree":git_read("rev-parse","HEAD^{tree}",cwd=directory).decode().strip(),"status":git_read("status","--porcelain",cwd=directory).decode()}
TOOLS={"justfile":"a215a76cf407ace9715bca39c20497014e7dd4dc","scripts/format.py":"d4eabe70b68605933240e9129245f7f4cccbde5d","scripts/verify_hepta_callers.py":"7a6709691c372504ca11b5d2a74e14ba819fca8f","scripts/hepta_typed_callers.py":"e23bb8aa42241b429ef5dbce5a4660853b66eb2f"}
def check_tools():
    for path,expected in TOOLS.items(): assert blob(read_bytes(SOURCE/path))==expected,path
def capture(label,original):
    changed=[x.decode() for x in git_read("diff","--name-only","--no-renames","-z","HEAD","--").split(b"\0") if x]
    untracked=[x.decode() for x in git_read("ls-files","--others","--exclude-standard","-z").split(b"\0") if x]
    allowed={x["path"]:x for x in original["files"]}
    outside=sorted(set(changed).difference(allowed))
    patch=git_read("diff","--binary","--full-index","HEAD","--")
    with open(RECORDS/(label+".patch"),"xb") as f: f.write(patch)
    patch_pin={"bytes":len(patch),"sha256":sha(patch),"git_blob":blob(patch)}
    # Preserve the complete dirty roster and patch before refusing unexpected scope.
    observation={"schema_version":1,"stage":label,"tracked_dirty":changed,"untracked":untracked,"outside_fixed_paths":outside,"patch":patch_pin,"publication_allowed":not untracked and not outside}
    save(label+"-scope-observation.json",observation)
    if untracked or outside:
        extras=[]
        directory=RECORDS/("unexpected-"+label);directory.mkdir(mode=0o700)
        for number,relative in enumerate(sorted(set(untracked+outside))):
            p=Path(relative)
            entry={"path":relative}
            if p.is_absolute() or ".." in p.parts:
                entry["not_opened"]="unsafe relative path";extras.append(entry);continue
            path=SOURCE/p
            try:
                st=path.lstat();entry.update({"bytes":st.st_size,"mode":st.st_mode})
                if path.is_symlink(): entry["not_opened"]="symlink"
                elif not stat.S_ISREG(st.st_mode): entry["not_opened"]="not regular"
                elif st.st_size>16*1024*1024: entry["not_copied"]="bounded evidence limit; original remains in isolated source"
                else:
                    data=read_bytes(path);copy=directory/("%03d.bin"%number)
                    with open(copy,"xb") as f: f.write(data)
                    entry.update({"sha256":sha(data),"git_blob":blob(data),"copy_path":str(copy)})
            except BaseException as error: entry["observation_error"]=str(error)
            extras.append(entry)
        save(label+"-unexpected-paths.json",{"paths":extras,"publication_refused":True})
        raise RuntimeError("tool changed paths outside fixed source scope; original dirty evidence retained")
    directory=RECORDS/("postimages-"+label);directory.mkdir(mode=0o700)
    images=[];complete=[]
    for i,item in enumerate(original["files"]):
        path=item["path"];data=read_bytes(SOURCE/path)
        actual={"path":path,"pre":item.get("pre"),"post":blob(data),"bytes":len(data),"sha256":sha(data)}
        complete.append(actual)
        if actual["post"]!=item["post"]:
            copy=directory/("%03d.txt"%i)
            with open(copy,"xb") as f: f.write(data);f.flush();os.fsync(f.fileno())
            images.append({"path":path,"pre_blob":item["post"],"post_blob":actual["post"],"bytes":len(data),"sha256":actual["sha256"],"copy_path":str(copy)})
    result={"schema_version":1,"stage":label,"identity":identity(SOURCE),"original_manifest":C["source_manifest_blob"],"changed":images,"complete_source_manifest":{"schema_version":1,"base_commit":original["base_commit"],"base_tree":original["base_tree"],"files":complete},"patch":patch_pin}
    pin=save(label+"-postimages.json",result)
    R[label+"_postimages"]=pin;save("progress.json",R)
    print(json.dumps({"captured":label,"changed_files":len(images),"manifest":pin},sort_keys=True),flush=True)
    return changed,result

try:
    save("CONFIG.json",C)
    R["reference_before"]=identity(REFERENCE)
    assert R["reference_before"]=={"head":C["reference_head"],"tree":C["reference_tree"],"status":""},"reference changed"
    command("isolated-clone",["git","clone","--shared","--no-checkout","--no-hardlinks",str(REFERENCE),str(SOURCE)],600,cwd=WORK)
    command("fetch-exact-source",["git","-C",str(SOURCE),"fetch","--no-tags",URL,C["head"]],600,cwd=WORK)
    assert git_read("rev-parse",C["head"]+"^{tree}").decode().strip()==C["tree"]
    command("checkout-exact-source",["git","-C",str(SOURCE),"checkout","--detach",C["head"]],600,cwd=WORK)
    R["source_ready"]=True;R["initial_source"]=identity(SOURCE)
    assert R["initial_source"]=={"head":C["head"],"tree":C["tree"],"status":""}
    check_tools()
    raw_manifest=read_bytes(SOURCE/C["source_manifest_path"]);assert blob(raw_manifest)==C["source_manifest_blob"]
    original=json.loads(raw_manifest);assert len(original["files"])==197
    for item in original["files"]: assert blob(read_bytes(SOURCE/item["path"]))==item["post"],item["path"]
    command("format-base-ancestry",["git","merge-base","--is-ancestor",C["format_base"],C["head"]],120)
    _,version=command("operator-rustc",[C["rustc_path"],"-Vv"],60,cwd=SOURCE/"codex-rs")
    assert b"release: 1.96.0\n" in version,"original pinned toolchain differs"
    command("fmt-before",["just","fmt","--base",C["format_base"]],600)
    capture("formatted",original);check_tools()
    package_args=[item for package in C["packages"] for item in ["-p",package]]
    fix_code,_=command("fix-eleven-crates",["just","fix","--locked","--offline",*package_args],C["fix_timeout_seconds"],required=False)
    fmt_code,_=command("fmt-after",["just","fmt","--base",C["format_base"]],600,required=False)
    if fix_code==0 and fmt_code==0:
        bins_code,_=command("bins-check",["cargo","check","--locked","--offline",*package_args,"--bins"],C["bins_timeout_seconds"],cwd=SOURCE/"codex-rs",required=False)
    else: bins_code=None
    changed,final_capture=capture("final",original);check_tools()
    R["maintenance_checks_passed"]=(fix_code==0 and fmt_code==0 and bins_code==0 and not R["completion_unknown"] and not any(step["timed_out"] for step in R["steps"]))
    R["status"]="source-maintenance-passed" if R["maintenance_checks_passed"] else "source-maintenance-failed"
    R["maintenance_results"]={"fix":fix_code,"format_after":fmt_code,"bins":bins_code}
    R["reference_after"]=identity(REFERENCE)
    assert R["reference_after"]==R["reference_before"],"read-only reference changed"
    if R["completion_unknown"]: raise RuntimeError("publication refused after unknown completion")
except BaseException as error:
    R["status"]="source-maintenance-failed"
    R["errors"].append({"type":type(error).__name__,"message":str(error),"traceback":traceback.format_exc()})
    traceback.print_exc()
finally:
    FINALIZING=True;EVIDENCE_DEADLINE=time.monotonic()+120
    R["separate_evidence_cleanup_budget_seconds"]=120
    if R["source_ready"] and not R["completion_unknown"]:
        try:
            R["final_source"]=identity(SOURCE);check_tools()
            if "original" in globals() and "final_postimages" not in R: capture("failure",original)
        except BaseException as error: R["errors"].append({"final_capture_error":str(error)})
    if R["completion_unknown"]: R["final_source_snapshot"]="not_certified_after_unknown_completion"
    try:
        R["reference_after"]=identity(REFERENCE)
        if "reference_before" in R and R["reference_after"]!=R["reference_before"]:
            R["errors"].append({"reference_changed":True});R["status"]="source-maintenance-failed"
    except BaseException as error: R["errors"].append({"reference_read_error":str(error)})
    R["elapsed_seconds"]=time.monotonic()-START
    result=save("RESULT.json",R);progress("finished")
    print(json.dumps({"result":result,"status":R["status"],"published":R.get("published_maintenance_commit"),"errors":R["errors"]},sort_keys=True),flush=True)
sys.exit(0 if R["maintenance_checks_passed"] and not R["completion_unknown"] and not R["errors"] else 1)

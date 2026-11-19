"""Run the existing complete NoUpdate parent on one isolated, frozen source."""
import datetime, fcntl, hashlib, importlib.util, json, os, resource, shutil, signal
import subprocess, sys, time, traceback
from pathlib import Path
BASE=Path("/home/qq/work/hepta-e6-operation-scope-20261118-2e9b")
SRC=BASE/"source"
TARGET=BASE/"native-target-restored-1"
OUT=BASE/"complete-noupdate-6"
PROTOCOL=BASE/"complete-noupdate6-PROTOCOL.json"
DEPLOYMENT=BASE/"complete-noupdate6-DEPLOYMENT.json"
ORIGINAL=Path("/home/qq/hepta-learn-ff41-tools/root_5eeb5d33_completed_chain_v1.py")
ORIGINAL_ENV=Path("/home/qq/hepta-learn-ff41-tools/env.json")
LIBCLANG=Path("/usr/lib/x86_64-linux-gnu/libclang-21.so.21")
STDDEF=Path("/usr/lib/gcc/x86_64-linux-gnu/15/include/stddef.h")
def sha(path):
    with Path(path).open("rb") as stream: return hashlib.file_digest(stream,"sha256").hexdigest()
def save(path,obj):
    Path(path).write_text(json.dumps(obj,indent=2)+"\n")
def exact_inventory():
    rows=[]
    raw=subprocess.check_output(["git","ls-files","-s","-z"],cwd=SRC)
    for item in raw.split(b"\0"):
        if not item: continue
        meta,name=item.split(b"\t",1);path=SRC/os.fsdecode(name)
        if path.is_symlink(): data=os.fsencode(os.readlink(path))
        else: data=path.read_bytes()
        rows.append({"path":os.fsdecode(name),"kind":"symlink" if path.is_symlink() else "regular","mode":path.lstat().st_mode&0o7777,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    return rows
def utc(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
assert not OUT.exists(), "unique NoUpdate execution namespace is already used"
OUT.mkdir()
deployment=json.loads(DEPLOYMENT.read_text())
protocol=json.loads(PROTOCOL.read_text())
assert sha(PROTOCOL)==deployment["protocol_sha256"]
assert sha(__file__)==deployment["driver_sha256"]
assert sha(ORIGINAL)==protocol["original_harness_sha256"]
assert sha(ORIGINAL_ENV)==protocol["original_environment_file_sha256"]
assert sha(LIBCLANG)==protocol["libclang_sha256"]
assert sha(STDDEF)==protocol["stddef_sha256"]
assert sha(BASE/"native-validation-6/RESULT.json")==protocol["prerequisite_result_sha256"]
prior=json.loads((BASE/"native-validation-6/RESULT.json").read_text())
assert prior["successful"] and prior["native_cases"]==11 and prior["source"]==protocol["source"]
assert prior["source_inventory_sha256"]==protocol["source_inventory_sha256"]
caller_file=BASE/"read64-trace-source-closure-1/RESULT.json"
assert sha(caller_file)==protocol["complete_caller_result_sha256"]
caller=json.loads(caller_file.read_text())
assert caller["just_fmt_exit"]==0 and caller["source_tests_successful"] and caller["tests_run"]==196
assert caller["protected_file_sweep"]["passed"] and caller["protected_file_sweep"]["rows"]==892
assert caller["targeted_callers"]["passed"] and caller["targeted_callers"]["expected_boundary_count"]==182
assert caller["full_caller_proof_exit"]==0 and not caller["failures"] and not caller["errors"] and not caller["skipped"]
for path,digest in caller["before_sha256"].items():
    assert sha(SRC/path)==digest and digest==caller["after_format_sha256"][path]
assert sha(BASE/"read64-trace-source-closure-1/full-caller-proof.stdout")==protocol["complete_caller_stdout_sha256"]
for previous in protocol["retained_prior_failures"]:
    assert sha(BASE/previous["path"])==previous["sha256"]
assert os.getuid()==os.geteuid()==1000
assert TARGET.is_dir()
for name,path in [("PROTOCOL.json",PROTOCOL),("DEPLOYMENT.json",DEPLOYMENT),("ORIGINAL_HARNESS.py",ORIGINAL)]:
    shutil.copyfile(path,OUT/name)
spec=importlib.util.spec_from_file_location("original_complete_owner",OUT/"ORIGINAL_HARNESS.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.REPO=SRC;m.TARGET=TARGET;m.OUT=OUT;m.RUN_ID=protocol["run_id"]
m.HEAD=protocol["source"];m.TREE=protocol["tree"]
m.PUBLIC=Path("/var/tmp")/("hepta-native-"+m.RUN_ID)
m.ROOT=Path("/run")/("hepta-daemon-learning-"+m.RUN_ID)
assert not m.PUBLIC.exists() and not m.ROOT.exists()
m.result={
 "status":"preflight","started":utc(),"source":m.HEAD,"tree":m.TREE,
 "protocol_sha256":sha(PROTOCOL),"driver_sha256":sha(__file__),"deployment":deployment,
 "original_harness_sha256":sha(ORIGINAL),"original_executor_mutated":False,
 "target":str(TARGET),"public":str(m.PUBLIC),"root":str(m.ROOT),
 "stages":[],"checks":{},"automatic_retry":False,
 "scope":"One actual original complete evaluated-NoUpdate parent; original A is inside that parent. No Adopt or cold parent is run in this attempt.",
 "qualification_limits":protocol["qualification_limits"],
 "complete_native_NoUpdate":False,"native_owner_adoption":False,"fresh_C_and_cold_fresh_D":False,
 "cost_scope":"Fresh exact-source helper/product/library preparation and the unchanged original just test command are executed in the private restored target. Prior cache acquisition, failed owners, and exact-source native11 costs remain linked and are not relabeled free or new model work. Per-command and whole-owner intervals overlap. RUSAGE_CHILDREN measures reaped descendants; max RSS is not simultaneous system RSS. Physical energy, network, storage byte-seconds and charges remain unknown."
}
m.persist()
owner_start=time.monotonic();owner_usage=resource.getrusage(resource.RUSAGE_CHILDREN);owner_self_usage=resource.getrusage(resource.RUSAGE_SELF)
owners=[];mounts_attempted=False;before_files=None
def bounded_command(name,argv,cwd=None):
    cwd=SRC if cwd is None else cwd
    item={"name":name,"command":argv,"cwd":str(cwd),"started":utc(),"status":"running","launcher_uid":os.getuid()}
    m.result["stages"].append(item);m.persist()
    started=time.monotonic();before=resource.getrusage(resource.RUSAGE_CHILDREN)
    child=None;timed_out=False
    try:
        with (OUT/(name+".stdout.log")).open("xb") as stdout,(OUT/(name+".stderr.log")).open("xb") as stderr:
            child=subprocess.Popen(argv,cwd=cwd,stdout=stdout,stderr=stderr,start_new_session=True)
            item["pid"]=child.pid;item["process_group"]=child.pid;m.persist()
            timeout=7500 if name.endswith("-execution") else 3600
            try: code=child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True
                # This exact process group was created above for this owned command.
                try: os.killpg(child.pid,signal.SIGTERM)
                except PermissionError: subprocess.run(["sudo","-n","kill","-TERM","--",str(-child.pid)],check=False)
                try: code=child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try: os.killpg(child.pid,signal.SIGKILL)
                    except PermissionError: subprocess.run(["sudo","-n","kill","-KILL","--",str(-child.pid)],check=False)
                    code=child.wait(timeout=10)
    except BaseException as error:
        item.update(status="launch_or_wait_failed",error=repr(error))
        raise
    finally:
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        item.update(finished=utc(),elapsed_seconds=time.monotonic()-started,timed_out=timed_out,
          child_user_cpu_seconds=after.ru_utime-before.ru_utime,child_system_cpu_seconds=after.ru_stime-before.ru_stime,
          owner_children_max_rss_kib=after.ru_maxrss,input_blocks=after.ru_inblock-before.ru_inblock,
          output_blocks=after.ru_oublock-before.ru_oublock)
        m.persist()
    item.update(status="completed",exit_code=code);m.persist()
    return code if not timed_out else 124
m.command=bounded_command

# Keep the original harness test function byte-for-byte. In particular, the
# recorder still observes "just test --locked --offline"; no binary-metadata
# invocation or collector adaptation substitutes for the actual parent.
def restore_owned_report_ownership():
    paths=[str(p) for p in (OUT,TARGET,SRC/"codex-rs/target/nextest") if p.exists()]
    script="""import os,pathlib,sys,json
uid,gid=int(sys.argv[1]),int(sys.argv[2])
for value in json.loads(sys.argv[3]):
 root=pathlib.Path(value)
 for p in [root,*root.rglob('*')]:
  st=p.lstat()
  if st.st_uid!=uid or st.st_gid!=gid:os.chown(p,uid,gid,follow_symlinks=False)
"""
    subprocess.run(["sudo","-n","/usr/bin/python3","-c",script,str(os.getuid()),str(os.getgid()),json.dumps(paths)],check=True)
m.restore_ownership=restore_owned_report_ownership

def fix_and_verify_helpers():
    for p in (m.PUBLIC,m.PUBLIC/"helpers",m.PUBLIC/"helpers/bin"):
        assert p.is_dir() and not p.is_symlink()
        p.chmod(0o755)
    manifest=json.loads((m.PUBLIC/"helpers/manifest.json").read_text())
    assert manifest["complete"] and manifest["source_sha"]==m.HEAD and manifest["source_sha_after"]==m.HEAD
    rows=[]
    for name,item in manifest["artifacts"].items():
        p=Path(item["executable"])
        assert p.parent==m.PUBLIC/"helpers/bin" and p.is_file() and not p.is_symlink()
        assert p.stat().st_nlink==1 and sha(p)==item["sha256"] and p.stat().st_size==item["bytes"]
        p.chmod(0o555)
        rows.append({"name":name,"path":str(p),"sha256":sha(p),"bytes":p.stat().st_size,"mode":oct(p.stat().st_mode&0o7777)})
    save(OUT/"public-helper-executable-installation.json",{"rows":rows,"private_ancestors_changed":False})
    helper=["python3","scripts/hepta_cell_test_helpers.py","--package","codex-hepta-infer-worker-host","--output-dir",str(m.PUBLIC/"helpers")]
    return m.verify_and_load_helpers(helper)

def build_and_verify_products():
    if not m.prepare_products():return False
    (m.PUBLIC/"bin").chmod(0o755)
    manifest=json.loads((OUT/"product-manifest.json").read_text())
    assert manifest["head"]==m.HEAD and manifest["tree"]==m.TREE
    for item in manifest["artifacts"].values():
        p=Path(item["pinned"])
        assert p.parent==m.PUBLIC/"bin" and p.stat().st_nlink==1 and not p.is_symlink()
        assert p.stat().st_mode&0o7777==0o555 and sha(p)==item["sha256"]
    return m.snapshot()==m.result["before"]

def prepare_actual_test_executable():
    data=json.loads((OUT/"library-binaries-build-uid1000.stdout.log").read_text())
    binaries=data["rust-binaries"]
    matched=[item for item in binaries.values() if item.get("binary-name")=="codex-hepta-agentd"]
    if not matched and "codex-hepta-agentd" in binaries:matched=[binaries["codex-hepta-agentd"]]
    assert len(matched)==1,("agentd native executable count",len(matched))
    item=matched[0]
    assert item["kind"]=="lib"
    p=Path(item["binary-path"])
    assert p.is_absolute() and p.resolve().is_relative_to(TARGET.resolve())
    before=p.lstat()
    assert not p.is_symlink() and before.st_nlink==1 and before.st_uid==1000
    digest=sha(p)
    # Only the newly compiled, independently owned test ELF gains the exact
    # read/execute bits needed after its original FD opener drops credentials.
    # Every private ancestor keeps its existing mode.
    ancestors=[{"path":str(parent),"mode":oct(parent.stat().st_mode&0o7777),"uid":parent.stat().st_uid}
        for parent in p.parents if parent==BASE or BASE in parent.parents]
    p.chmod(0o555)
    after=p.stat()
    assert digest==sha(p) and before.st_size==after.st_size
    row={"path":str(p),"bytes":after.st_size,"sha256":digest,"device":after.st_dev,"inode":after.st_ino,
        "mtime_ns":str(after.st_mtime_ns),"ctime_ns":str(after.st_ctime_ns),"mode":oct(after.st_mode&0o7777),
        "old_mode":oct(before.st_mode&0o7777),"uid":after.st_uid,"gid":after.st_gid,"ancestors":ancestors}
    save(OUT/"actual-native-executable.json",row)
    return m.snapshot()==m.result["before"]

def dedicated_source_descriptor_probe():
    item=json.loads((OUT/"actual-native-executable.json").read_text())
    payload={"path":item["path"],"child":"neuron_generation_current::initial_root_tests::ordinary::post_a_source::original_independent_b_source_child"}
    probe="""import os,json,sys,ctypes,errno
assert os.geteuid()==0
data=json.loads(sys.argv[1]);fd=os.open(data['path'],os.O_RDONLY|os.O_NOFOLLOW);os.set_inheritable(fd,True)
class Header(ctypes.Structure):_fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int32)]
class Data(ctypes.Structure):_fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
pid=os.fork()
if pid==0:
 c=ctypes.CDLL(None,use_errno=True)
 assert c.prctl(38,1,0,0,0)==0 and c.prctl(47,4,0,0,0)==0
 for cap in range(64):
  present=c.prctl(23,cap,0,0,0)
  if present<0:
   assert cap>0 and ctypes.get_errno()==errno.EINVAL;break
  if present:assert c.prctl(24,cap,0,0,0)==0
 os.setgroups([]);os.setresgid(60001,60001,60001);os.setresuid(60002,60002,60002)
 header=Header(0x20080522,0);caps=(Data*2)()
 assert c.capset(ctypes.byref(header),ctypes.byref(caps))==0
 private_refused=False
 try:os.close(os.open(data['path'],os.O_RDONLY|os.O_NOFOLLOW))
 except OSError as e:private_refused=e.errno==errno.EACCES
 assert private_refused,'private ancestor unexpectedly traversable'
 q='/proc/self/fd/'+str(fd)
 assert os.access(q,os.X_OK,effective_ids=True) and os.access(q,os.R_OK,effective_ids=True)
 print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),'groups':os.getgroups(),'private_path_EACCES':private_refused,'fd_execute_access':True,'command':[q,'--list','--exact',data['child']]}),flush=True)
 os.chdir('/run');os.execve(q,[q,'--list','--exact',data['child']],{'PATH':'/usr/bin:/bin'})
_,status=os.waitpid(pid,0);os.close(fd);code=os.waitstatus_to_exitcode(status)
print(json.dumps({'actual_wait_exit':code}),flush=True)
assert code==0
"""
    if m.command("dedicated-source-descriptor-list",["sudo","-n","/usr/bin/python3","-c",probe,json.dumps(payload)])!=0:return False
    observed=(OUT/"dedicated-source-descriptor-list.stdout.log").read_text()
    assert payload["child"]+": test" in observed and '"private_path_EACCES": true' in observed
    return m.snapshot()==m.result["before"]

def dedicated_helper_access_probe():
    paths=sorted({value for key,value in os.environ.items() if key.startswith("CARGO_BIN_EXE_")})
    assert len(paths)==3 and all(Path(p).is_relative_to(m.PUBLIC) for p in paths)
    probe="""import os,json,sys,ctypes,errno
assert os.geteuid()==0
paths=json.loads(sys.argv[1]);codes=[]
class Header(ctypes.Structure):_fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int32)]
class Data(ctypes.Structure):_fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
for uid in [60001,60002]:
 pid=os.fork()
 if pid==0:
  c=ctypes.CDLL(None,use_errno=True)
  assert c.prctl(38,1,0,0,0)==0 and c.prctl(47,4,0,0,0)==0
  for cap in range(64):
   present=c.prctl(23,cap,0,0,0)
   if present<0:
    assert cap>0 and ctypes.get_errno()==errno.EINVAL;break
   if present:assert c.prctl(24,cap,0,0,0)==0
  os.setgroups([]);os.setresgid(60001,60001,60001);os.setresuid(uid,uid,uid)
  header=Header(0x20080522,0);caps=(Data*2)()
  assert c.capset(ctypes.byref(header),ctypes.byref(caps))==0
  for path in paths:
   row={'uid':uid,'path':path,'read':os.access(path,os.R_OK,effective_ids=True),'execute':os.access(path,os.X_OK,effective_ids=True)}
   print(json.dumps(row),flush=True);assert row['read'] and row['execute']
  os._exit(0)
 _,status=os.waitpid(pid,0);codes.append(os.waitstatus_to_exitcode(status))
assert codes==[0,0],codes
"""
    return m.command("dedicated-uid-helper-access",["sudo","-n","/usr/bin/python3","-c",probe,json.dumps(paths)])==0 and m.snapshot()==m.result["before"]

def pinned_copies_unchanged():
    row=json.loads((OUT/"actual-native-executable.json").read_text())
    p=Path(row["path"]);st=p.stat()
    assert sha(p)==row["sha256"] and st.st_size==row["bytes"] and st.st_mode&0o7777==0o555
    assert (st.st_dev,st.st_ino,str(st.st_mtime_ns),str(st.st_ctime_ns))==(row["device"],row["inode"],row["mtime_ns"],row["ctime_ns"])
    for before in row["ancestors"]:
        st=Path(before["path"]).stat()
        assert oct(st.st_mode&0o7777)==before["mode"] and st.st_uid==before["uid"]
    product=json.loads((OUT/"product-manifest.json").read_text())
    helper=json.loads((OUT/"helper-manifest.json").read_text())
    for item in [*product["artifacts"].values(),*helper["artifacts"].values()]:
        q=Path(item.get("pinned",item.get("executable")))
        assert sha(q)==item["sha256"] and q.stat().st_size==item["bytes"] and q.stat().st_mode&0o7777==0o555
    return True


try:
    for lock in [BASE/"native-component-owner.lock",TARGET/".hepta-root-native-owner.lock"]:
        handle=lock.open("a+b");fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);owners.append(handle)
    with (TARGET/"debug/.cargo-lock").open("rb") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(handle,fcntl.LOCK_UN)
    m.result["before"]=m.snapshot()
    assert m.result["before"]["head"]==m.HEAD and m.result["before"]["tree"]==m.TREE and not m.result["before"]["status"]
    before_files=exact_inventory()
    exact_raw=(json.dumps(before_files,sort_keys=True,separators=(",",":"))+"\n").encode()
    assert hashlib.sha256(exact_raw).hexdigest()==protocol["source_inventory_sha256"], "tracked execution bytes differ from the actual component result"
    save(OUT/"TRACKED_FILES_BEFORE.json",before_files)
    original=json.loads(ORIGINAL_ENV.read_text())
    permitted={"PATH","LIBCLANG_PATH","BINDGEN_EXTRA_CLANG_ARGS","RUSTUP_TOOLCHAIN","RUSTY_V8_ARCHIVE","RUSTY_V8_SRC_BINDING_PATH","RUSTFLAGS","LD_LIBRARY_PATH","CARGO_HOME","RUSTUP_HOME"}
    for key in permitted:
        if key in original: os.environ[key]=original[key]
    for key in list(os.environ):
        if key.startswith("CARGO_PROFILE_") or key.startswith("CARGO_BIN_EXE_"): del os.environ[key]
    os.environ.update(RUSTUP_TOOLCHAIN="1.96.0",CARGO_BUILD_JOBS="2",CARGO_INCREMENTAL="0",
        CARGO_TARGET_DIR=str(TARGET),CARGO_NET_OFFLINE="true",SOURCE_SHA=m.HEAD,TESTED_SHA=m.HEAD,
        HEPTA_CI_LANE="source-head",PYTHONDONTWRITEBYTECODE="1",GIT_TERMINAL_PROMPT="0")
    os.environ["PATH"]=str(BASE/"tooling/bin")+":/home/qq/.cargo/bin:"+os.environ["PATH"]
    for key in ("GIT_CURL_VERBOSE","GIT_TRACE","GIT_TRACE_CURL"): os.environ.pop(key,None)
    for name in ("codex-hepta-agentd","hepta-authority-host","hepta-joint-propose"):
        for variant in (name,name.replace("-","_")):
            os.environ["CARGO_BIN_EXE_"+variant]=str(m.PUBLIC/"unprepared"/name)
    m.result["environment"]={key:os.environ[key] for key in sorted(permitted|{"CARGO_INCREMENTAL","CARGO_BUILD_JOBS","CARGO_TARGET_DIR","CARGO_NET_OFFLINE"}) if key in os.environ}
    m.result["environment_file_sha256"]=sha(ORIGINAL_ENV)
    m.result["cargo_profile_overrides"]={k:v for k,v in os.environ.items() if k.startswith("CARGO_PROFILE_")}
    os.chdir(SRC);sys.path.insert(0,str(SRC/"scripts"))
    from hepta_ci_junit import collect
    m.collect=collect
    m.require_roster()
    assert m.NO_UPDATE_PARENT==protocol["parent"]
    m.PUBLIC.mkdir(mode=0o755);m.PUBLIC.chmod(0o755)
    helper=["python3","scripts/hepta_cell_test_helpers.py","--package","codex-hepta-infer-worker-host","--output-dir",str(m.PUBLIC/"helpers")]
    stages=[
        ("actual-helper-build",lambda:m.build_helpers(helper)),
        ("actual-helper-permissions-and-original-verify",fix_and_verify_helpers),
        ("actual-product-build-and-original-pin",build_and_verify_products),
        ("actual-library-binaries-build",m.prepare_library_binaries),
        ("actual-test-executable-mode",prepare_actual_test_executable),
        ("actual-capless-uid60002-source-descriptor-list",dedicated_source_descriptor_probe),
        ("actual-capless-helper-access",dedicated_helper_access_probe),
    ]
    m.result["status"]="preparing";m.persist()
    for name,action in stages:
        if not m.attempt(name,action): raise RuntimeError("Original native preparation failed: "+name)
    mounts_attempted=True
    if not m.attempt("root-mount-setup",m.setup_mounts): raise RuntimeError("Original protected bind setup failed")
    m.result["status"]="testing";m.persist()
    root_args=["-p","codex-hepta-agentd","-p","codex-hepta-contracts","--lib","--run-ignored","only","--test-threads","1","-E","test(="+m.NO_UPDATE_PARENT+")"]
    passed=m.attempt("ordinary-post-a-no-update",lambda:m.test("ordinary-post-a-no-update",root_args,[m.NO_UPDATE_PARENT]))
    m.result["status"]="completed"
    m.result["complete_native_NoUpdate"]=bool(passed)
    m.result["pinned_and_original_binary_bytes_unchanged"]=pinned_copies_unchanged()
except BaseException as error:
    m.result.update(status="driver_failed",error=repr(error))
    (OUT/"driver-error.log").write_text(traceback.format_exc())
finally:
    if mounts_attempted:
        cleanup=[]
        for name in ("witness-bind","bind"):
            path=str(m.ROOT/name)
            active=[row.split()[4] for row in Path("/proc/self/mountinfo").read_text().splitlines()]
            if path not in active: continue
            p=subprocess.run(["sudo","-n","umount",path],capture_output=True,text=True)
            cleanup.append({"path":path,"exit_code":p.returncode,"stdout":p.stdout,"stderr":p.stderr})
        save(OUT/"mount-cleanup.json",cleanup)
        m.result["mount_cleanup_successful"]=all(row["exit_code"]==0 for row in cleanup)
    else: m.result["mount_cleanup_successful"]=True
    try:
        m.restore_ownership()
        m.result["after"]=m.snapshot()
        m.result["source_unchanged"]=m.result.get("before")==m.result["after"]
        after_files=exact_inventory();save(OUT/"TRACKED_FILES_AFTER.json",after_files)
        m.result["tracked_bytes_unchanged"]=before_files==after_files
    except BaseException as error: m.result["source_readback_error"]=repr(error)
    m.result["compiler_inputs_unchanged"]=(sha(ORIGINAL_ENV)==protocol["original_environment_file_sha256"] and sha(LIBCLANG)==protocol["libclang_sha256"] and sha(STDDEF)==protocol["stddef_sha256"])
    usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    self_usage=resource.getrusage(resource.RUSAGE_SELF)
    m.result["owner_self_user_cpu_seconds"]=self_usage.ru_utime-owner_self_usage.ru_utime
    m.result["owner_self_system_cpu_seconds"]=self_usage.ru_stime-owner_self_usage.ru_stime
    m.result.update(finished=utc(),owner_wall_seconds=time.monotonic()-owner_start,
        owner_child_user_cpu_seconds=usage.ru_utime-owner_usage.ru_utime,
        owner_child_system_cpu_seconds=usage.ru_stime-owner_usage.ru_stime,
        owner_children_max_rss_kib=usage.ru_maxrss)
    m.result["successful"]=(m.result["status"]=="completed" and m.result["complete_native_NoUpdate"]
        and m.result.get("source_unchanged") is True and m.result.get("tracked_bytes_unchanged") is True
        and m.result["compiler_inputs_unchanged"] and m.result["mount_cleanup_successful"] and m.result.get("pinned_and_original_binary_bytes_unchanged") is True
        and all(row.get("passed") is True for row in m.result["checks"].values()))
    m.result["log_inventory"]={}
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name not in ("result.json","result.json.tmp"):
            m.result["log_inventory"][str(path.relative_to(OUT))]={"bytes":path.stat().st_size,"sha256":sha(path)}
    m.persist()
    for handle in reversed(owners): handle.close()
    print(json.dumps({k:m.result.get(k) for k in ("status","successful","complete_native_NoUpdate","source","tree","source_unchanged","tracked_bytes_unchanged","compiler_inputs_unchanged","mount_cleanup_successful","owner_wall_seconds","error")},indent=2),flush=True)
sys.exit(0 if m.result["successful"] else 1)

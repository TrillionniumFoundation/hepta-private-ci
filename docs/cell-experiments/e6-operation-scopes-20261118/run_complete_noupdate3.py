"""Run the existing complete NoUpdate parent on one isolated, frozen source."""
import datetime, fcntl, hashlib, importlib.util, json, os, resource, shutil, signal
import subprocess, sys, time, traceback
from pathlib import Path
BASE=Path("/home/qq/work/hepta-e6-operation-scope-20261118-2e9b")
SRC=BASE/"source"
TARGET=BASE/"native-target"
OUT=BASE/"complete-noupdate-3"
PROTOCOL=BASE/"complete-noupdate3-PROTOCOL.json"
DEPLOYMENT=BASE/"complete-noupdate3-DEPLOYMENT.json"
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
assert sha(BASE/"native-validation-2/RESULT.json")==protocol["prerequisite_result_sha256"]
prior=json.loads((BASE/"native-validation-2/RESULT.json").read_text())
assert prior["successful"] and prior["native_cases"]==11 and prior["source"]==protocol["source"]
assert prior["source_inventory_sha256"]==protocol["source_inventory_sha256"]
assert sha(BASE/"complete-noupdate-1/result.json")==protocol["prior_failed_owner_result_sha256"]
failed=json.loads((BASE/"complete-noupdate-1/result.json").read_text())
assert failed["status"]=="completed" and not failed["successful"] and failed["source_unchanged"] and failed["tracked_bytes_unchanged"] and failed["mount_cleanup_successful"]
assert sha(BASE/"noupdate1-permission-readback.json")==protocol["permission_readback_sha256"]
assert sha(BASE/"complete-noupdate-2/result.json")==protocol["second_failed_owner_result_sha256"]
second=json.loads((BASE/"complete-noupdate-2/result.json").read_text())
assert second["status"]=="completed" and not second["successful"] and second["source_unchanged"] and second["tracked_bytes_unchanged"] and second["mount_cleanup_successful"]
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
 "cost_scope":"Previously completed exact builds are reused and their costs stay in the complete-noupdate-2 owner; no recompilation is claimed in this attempt. New copy/verification costs and bytes are retained. Per-command and whole-owner intervals are nested. RUSAGE_CHILDREN measures reaped descendants; max RSS is the owner lifetime high-water maximum, not simultaneous whole-system RSS. Physical energy, network, storage byte-seconds and charges remain unknown."
}
m.persist()
owner_start=time.monotonic();owner_usage=resource.getrusage(resource.RUSAGE_CHILDREN)
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

def restore_owned_report_ownership():
    # Reuse-build mode never changes the retained compiler artifacts.
    paths=[str(p) for p in (OUT,TARGET/"nextest",SRC/"codex-rs/target/nextest") if p.exists()]
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

PREVIOUS=BASE/"complete-noupdate-2"
PREVIOUS_PUBLIC=Path("/var/tmp/hepta-native-root-e6-scopes-ab12-noupdate-2")
def verify_and_reuse_helpers():
    helper=["python3","scripts/hepta_cell_test_helpers.py","--package","codex-hepta-infer-worker-host","--output-dir",str(PREVIOUS_PUBLIC/"helpers"),"--verify-only"]
    if m.command("reused-original-helper-verify",helper)!=0:return False
    for name in ("env.json","manifest.json"):
        p=PREVIOUS_PUBLIC/"helpers"/name
        assert sha(p)==protocol["prior_preparation_files"]["helper-"+name]
        shutil.copyfile(p,OUT/("helper-"+name))
    environment=json.loads((OUT/"helper-env.json").read_text())
    os.environ.update(environment)
    m.result["reused_helper_build"]={"owner_result_sha256":protocol["second_failed_owner_result_sha256"],"rebuilt":False,"original_cost_in_previous_owner":True}
    return m.snapshot()==m.result["before"]

def verify_and_reuse_products():
    for name in ("product-env.json","product-manifest.json"):
        assert sha(PREVIOUS/name)==protocol["prior_preparation_files"][name]
        shutil.copyfile(PREVIOUS/name,OUT/name)
    manifest=json.loads((OUT/"product-manifest.json").read_text())
    assert manifest["head"]==m.HEAD and manifest["tree"]==m.TREE
    assert set(manifest["artifacts"])=={"codex-hepta-agentd","hepta-authority-host"}
    rows=[]
    for name,item in manifest["artifacts"].items():
        p=Path(item["pinned"]);st=p.lstat()
        assert p==PREVIOUS_PUBLIC/"bin"/name and not p.is_symlink() and st.st_nlink==1
        assert st.st_size==item["bytes"] and st.st_mode&0o7777==0o555 and sha(p)==item["sha256"]
        rows.append({"path":str(p),"sha256":item["sha256"],"bytes":st.st_size,"mode":"0o555","uid":st.st_uid})
    environment=json.loads((OUT/"product-env.json").read_text())
    assert set(environment.values())=={r["path"] for r in rows}
    os.environ.update(environment)
    save(OUT/"reused-original-products.json",{"rows":rows,"rebuilt":False,"original_cost_in_previous_owner":True})
    return m.snapshot()==m.result["before"]

def install_native_binary_copies():
    raw=PREVIOUS/"library-binaries-build-uid1000.stdout.log"
    assert sha(raw)==protocol["prior_preparation_files"]["library-binaries-build-uid1000.stdout.log"]
    metadata=json.loads(raw.read_text())
    assert set(metadata["rust-binaries"])=={"codex-hepta-agentd","codex-hepta-contracts"}
    (m.PUBLIC/"native-bin").mkdir(mode=0o755);(m.PUBLIC/"native-bin").chmod(0o755)
    rows=[]
    for name,item in metadata["rust-binaries"].items():
        original=Path(item["binary-path"])
        assert original.parent==TARGET/"debug/deps" and original.is_file() and not original.is_symlink()
        pinned=m.PUBLIC/"native-bin"/original.name
        digest=hashlib.sha256()
        with original.open("rb") as inp,pinned.open("xb") as out:
            before=os.fstat(inp.fileno())
            assert before.st_nlink==1 and before.st_uid==1000
            for chunk in iter(lambda:inp.read(1024*1024),b""):
                digest.update(chunk);out.write(chunk)
            out.flush();os.fsync(out.fileno());after=os.fstat(inp.fileno())
        assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
        pinned.chmod(0o555)
        assert sha(pinned)==digest.hexdigest() and pinned.stat().st_size==before.st_size
        rows.append({"name":name,"original":str(original),"pinned":str(pinned),"bytes":before.st_size,"sha256":digest.hexdigest(),"original_mode":oct(before.st_mode&0o7777),"pinned_mode":"0o555","original_device":before.st_dev,"original_inode":before.st_ino,"original_mtime_ns":before.st_mtime_ns,"original_ctime_ns":before.st_ctime_ns})
        item["binary-path"]=str(pinned)
    save(OUT/"native-binaries.json",metadata)
    save(OUT/"native-executable-installation.json",{"originals_unchanged":True,"private_ancestors_unchanged":True,"global_umask_unchanged":True,"source_unchanged":True,"rows":rows})
    m.result["native_executable_copies"]=rows
    return m.snapshot()==m.result["before"]

def dedicated_source_descriptor_probe():
    rows=json.loads((OUT/"native-executable-installation.json").read_text())["rows"]
    item=next(row for row in rows if row["name"]=="codex-hepta-agentd")
    payload={"old":item["original"],"new":item["pinned"],"child":"neuron_generation_current::initial_root_tests::ordinary::post_a_source::original_independent_b_source_child"}
    probe="""import os,json,sys,ctypes,errno
assert os.geteuid()==0
data=json.loads(sys.argv[1]);codes=[]
class Header(ctypes.Structure):_fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int32)]
class Data(ctypes.Structure):_fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
for kind in ['old','new']:
 fd=os.open(data[kind],os.O_RDONLY|os.O_NOFOLLOW);os.set_inheritable(fd,True);pid=os.fork()
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
  q='/proc/self/fd/'+str(fd)
  print(json.dumps({'kind':kind,'uid':os.geteuid(),'gid':os.getegid(),'groups':os.getgroups(),'fd_execute_access':os.access(q,os.X_OK,effective_ids=True),'fd_read_access':os.access(q,os.R_OK,effective_ids=True),'command':[q,'--list','--exact',data['child']]}),flush=True)
  try:
   os.chdir('/run');os.execve(q,[q,'--list','--exact',data['child']],{'PATH':'/usr/bin:/bin'})
  except OSError as e:
   print(json.dumps({'kind':kind,'exec_errno':e.errno}),flush=True);os._exit(0 if kind=='old' and e.errno==13 else 1)
 _,status=os.waitpid(pid,0);os.close(fd);code=os.waitstatus_to_exitcode(status);codes.append(code)
 print(json.dumps({'kind':kind,'actual_wait_exit':code}),flush=True)
assert codes==[0,0],codes
"""
    if m.command("dedicated-source-descriptor-list",["sudo","-n","/usr/bin/python3","-c",probe,json.dumps(payload)])!=0:return False
    observed=(OUT/"dedicated-source-descriptor-list.stdout.log").read_text()
    assert payload["child"]+": test" in observed and '"exec_errno": 13' in observed
    assert '"kind": "new"' in observed and '"fd_execute_access": true' in observed
    return m.snapshot()==m.result["before"]

def prepare_fresh_metadata():
    if m.command("fresh-cargo-metadata",["cargo","metadata","--no-deps","--format-version=1","--locked","--offline"],SRC/"codex-rs")!=0:return False
    shutil.copyfile(OUT/"fresh-cargo-metadata.stdout.log",OUT/"cargo-metadata.json")
    data=json.loads((OUT/"cargo-metadata.json").read_text())
    assert data["workspace_root"]==str(SRC/"codex-rs")
    return m.snapshot()==m.result["before"]

def list_exact_reused_parent():
    arguments=["cargo","nextest","list","--locked","--offline","-p","codex-hepta-agentd","-p","codex-hepta-contracts","--lib","--run-ignored","only","-E","test(="+m.NO_UPDATE_PARENT+")","--cargo-metadata",str(OUT/"cargo-metadata.json"),"--binaries-metadata",str(OUT/"native-binaries.json"),"--message-format","json"]
    if m.command("exact-parent-list-from-pinned-binaries",arguments,SRC/"codex-rs")!=0:return False
    data=json.loads((OUT/"exact-parent-list-from-pinned-binaries.stdout.log").read_text())
    matched=[]
    for suite in data["rust-suites"].values():
        for name,item in suite["testcases"].items():
            if item.get("filter-match",{}).get("status")=="matches":matched.append(name)
    save(OUT/"exact-pinned-parent-roster.json",{"matched":matched,"expected":[m.NO_UPDATE_PARENT],"source":m.HEAD,"test_cases_executed":0})
    assert matched==[m.NO_UPDATE_PARENT],matched
    return m.snapshot()==m.result["before"]

def pinned_copies_unchanged():
    rows=json.loads((OUT/"native-executable-installation.json").read_text())["rows"]
    for row in rows:
        for key in ("original","pinned"):
            assert sha(row[key])==row["sha256"] and Path(row[key]).stat().st_size==row["bytes"]
        before=Path(row["original"]).stat()
        assert (before.st_dev,before.st_ino,before.st_mtime_ns,before.st_ctime_ns)==(row["original_device"],row["original_inode"],row["original_mtime_ns"],row["original_ctime_ns"])
        assert oct(before.st_mode&0o7777)==row["original_mode"]
        assert Path(row["pinned"]).stat().st_mode&0o7777==0o555
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
    os.environ.update(RUSTUP_TOOLCHAIN="1.96.0",CARGO_BUILD_JOBS="1",CARGO_INCREMENTAL="0",
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
    stages=[
        ("reverify-original-prepared-helper",verify_and_reuse_helpers),
        ("reverify-original-pinned-products",verify_and_reuse_products),
        ("install-exact-native-binary-copies",install_native_binary_copies),
        ("actual-capless-uid60002-source-descriptor-list",dedicated_source_descriptor_probe),
        ("fresh-current-source-cargo-metadata",prepare_fresh_metadata),
        ("exact-parent-list-from-pinned-binaries",list_exact_reused_parent),
    ]
    m.result["status"]="preparing";m.persist()
    for name,action in stages:
        if not m.attempt(name,action): raise RuntimeError("Original native preparation failed: "+name)
    mounts_attempted=True
    if not m.attempt("root-mount-setup",m.setup_mounts): raise RuntimeError("Original protected bind setup failed")
    m.result["status"]="testing";m.persist()
    root_args=["-p","codex-hepta-agentd","-p","codex-hepta-contracts","--lib","--run-ignored","only","--test-threads","1","-E","test(="+m.NO_UPDATE_PARENT+")","--cargo-metadata",str(OUT/"cargo-metadata.json"),"--binaries-metadata",str(OUT/"native-binaries.json")]
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

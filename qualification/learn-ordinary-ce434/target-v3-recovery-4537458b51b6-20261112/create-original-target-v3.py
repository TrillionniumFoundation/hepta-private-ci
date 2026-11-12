from pathlib import Path
import hashlib,json,os,shutil,stat,subprocess,time
repo=Path("/home/qian-qi/hepta-learn-positive-ce434-4537458b51b6-isolated-v1")
source="4537458b51b6ca936264aecea7cfe384b941d0d1"
tree="8cbd7b269c9c39df4ee3ffcefed8473060696184"
old_repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
old_source="a6717d7228045e6cb60532966f06e6e02c4a6abe"
old_tree="647b9e78151299c1e7de455eae9c530ca93b28c9"
root=Path("/data/hepta-learn-ce434-runtime-20261112-v3")
target=root/"target"
out=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/build-root-recovery-4537458b51b6-v3")
pins=[{"key":"RUSTY_V8_ARCHIVE","path":"/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz","bytes":29366352,"sha256":"a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583"},{"key":"RUSTY_V8_SRC_BINDING_PATH","path":"/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs","bytes":39884,"sha256":"7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506"}]
env=dict(os.environ)
env["GIT_OPTIONAL_LOCKS"]="0"
env["PYTHONDONTWRITEBYTECODE"]="1"
if os.getuid()!=os.geteuid() or os.getuid()==0:raise RuntimeError("original normal user required")
if any(env.get(key) for key in ("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE")):raise RuntimeError("inherited Git location override")
def git_at(worktree,*args):
    command=["git",*args]
    process=subprocess.Popen(command,cwd=worktree,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:stdout,stderr=process.communicate()
    except BaseException:
        try:process.communicate()
        finally:process.wait()
        raise
    process.wait()
    if process.returncode:raise subprocess.CalledProcessError(process.returncode,command,output=stdout,stderr=stderr)
    return stdout.decode("utf-8").strip()
def git(*args):return git_at(repo,*args)
def identity(s):return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def meta(s):return {"device":s.st_dev,"inode":s.st_ino,"mode":oct(s.st_mode),"uid":s.st_uid,"nlink":s.st_nlink}
def hash_owned(path,expected_size=None):
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_nlink!=1:raise RuntimeError("original pin type/owner differs")
    if expected_size is not None and before.st_size!=expected_size:raise RuntimeError("original pin size differs")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as stream:
        first=os.fstat(stream.fileno());digest=hashlib.file_digest(stream,"sha256").hexdigest();last=os.fstat(stream.fileno())
    if identity(before)!=identity(first) or identity(first)!=identity(last) or identity(last)!=identity(path.lstat()):raise RuntimeError("original pin changed during full read")
    return digest,meta(last)
def source_state(worktree,expected_source,expected_tree):
    info=worktree.lstat()
    if not stat.S_ISDIR(info.st_mode) or worktree.resolve(strict=True)!=worktree or info.st_uid!=os.getuid():raise RuntimeError("original owned source directory differs")
    if git_at(worktree,"rev-parse","--show-toplevel")!=str(worktree):raise RuntimeError("original source top-level differs")
    observed_source=git_at(worktree,"rev-parse","HEAD")
    observed_tree=git_at(worktree,"rev-parse","HEAD^{tree}")
    status=git_at(worktree,"status","--porcelain=v1","--untracked-files=all")
    if observed_source!=expected_source or observed_tree!=expected_tree or status:raise RuntimeError("fixed original source changed")
    return {"repo":str(worktree),"source_sha":observed_source,"source_tree":observed_tree,"source_status":status,"directory_identity":meta(info)}
def clean():
    return {"current":source_state(repo,source,tree),"preserved":source_state(old_repo,old_source,old_tree)}
def require_absent(path,message):
    try:path.lstat()
    except FileNotFoundError:return {"path":str(path),"observation":"lstat FileNotFoundError; no statement about parent existence"}
    raise RuntimeError(message)
sources_before=clean()
for path in (root,out):require_absent(path,"exclusive recovery path exists; reconcile exact original request")
prior_target_observations=[require_absent(Path(path),"old target reappeared; preserve and reassess") for path in (
    "/data/hepta-learn-ce434-runtime-20261112-v1/target",
    "/data/hepta-learn-ce434-runtime-20261112-v2/target",
)]
parent=root.parent;ps=parent.lstat();usage=shutil.disk_usage(parent)
print(json.dumps({"schema":"learn.original-build-root-recovery-preflight.v1","source_sha":source,"source_tree":tree,"data_parent":meta(ps),"data_free_bytes_before":usage.free,"prior_target_observations":prior_target_observations,"native_tests_executed":0}),flush=True)
if not stat.S_ISDIR(ps.st_mode) or parent.resolve(strict=True)!=parent or ps.st_uid!=os.getuid() or ps.st_dev!=2067 or ps.st_ino!=2 or usage.free<64*1024**3:raise RuntimeError("observed owned data parent/space differs")
for path,digest in [
 (Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/v8-pinned-150-4-0-v2/manifest.json"),"9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5"),
 (Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/dependency-recovery-441de918-v1/result.json"),"8db2c096ff2c16b8e02f293a67c26939c5de6bf6e0dd69888179c4b0d31ca3fc"),
 (Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/build-root-recovery-e5c7-v2/result.json"),"cbd5597a63f2a13bc771230d14b7c65774409f6169fd941bb6c0575f4d11b8eb")
]:
    if hash_owned(path)[0]!=digest:raise RuntimeError("original recovery/manifest changed")
for pin in pins:
    digest,metadata=hash_owned(Path(pin["path"]),pin["bytes"])
    if digest!=pin["sha256"] or metadata["mode"]!="0o100400":raise RuntimeError("original exact V8 input differs")
    pin["metadata_before"]=metadata
out.mkdir(mode=0o700,parents=False,exist_ok=False)
report={"schema":"learn.original-build-root-recovery.v1","state":"starting","source_sha":source,"source_tree":tree,"uid":os.getuid(),"runtime_root":str(root),"target":str(target),"data_parent":meta(ps),"data_free_bytes_before":usage.free,"original_manifest_sha256":"9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5","original_recovery_sha256":"8db2c096ff2c16b8e02f293a67c26939c5de6bf6e0dd69888179c4b0d31ca3fc","artifacts":pins,"downloaded":False,"copied":False,"existing_paths_removed_or_changed":False,"process_signals":False,"native_tests_executed":0}
report.update(source_worktree_before=sources_before["current"],preserved_source_before=sources_before["preserved"],prior_target_observations=prior_target_observations,historical_target_creation={"source_sha":"e5c7dbd90938f1c9ac39dd3065c69a1b7707d6c4","path":"/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/build-root-recovery-e5c7-v2/result.json","sha256":"cbd5597a63f2a13bc771230d14b7c65774409f6169fd941bb6c0575f4d11b8eb","used_as_new_target_identity":False})
def save():
    pending=out/"result.pending.json"
    with pending.open("w") as stream:json.dump(report,stream,indent=2);stream.write("\n");stream.flush();os.fsync(stream.fileno())
    pending.replace(out/"result.json")
try:
    save()
    root.mkdir(mode=0o700,parents=False,exist_ok=False)
    target.mkdir(mode=0o700,parents=False,exist_ok=False)
    for path in [root,target]:
        s=path.lstat()
        if not stat.S_ISDIR(s.st_mode) or path.resolve(strict=True)!=path or s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o700:raise RuntimeError("new private build target identity differs")
    report.update(root_identity=meta(root.lstat()),target_identity=meta(target.lstat()))
    for pin in pins:
        digest,metadata=hash_owned(Path(pin["path"]),pin["bytes"])
        if digest!=pin["sha256"] or metadata!=pin["metadata_before"]:raise RuntimeError("original input changed during recovery")
        pin["metadata_after"]=metadata
    sources_after=clean()
    if sources_after!=sources_before:raise RuntimeError("original source identity changed during recovery")
    report.update(state="isolated-build-target-created-original-pins-retained",source_after=sources_after["current"]["source_sha"],source_tree_after=sources_after["current"]["source_tree"],source_status_after=sources_after["current"]["source_status"],source_worktree_after=sources_after["current"],preserved_source_after=sources_after["preserved"],finished_unix_ms=int(time.time()*1000))
    save()
except BaseException as error:
    report.update(state="failed",error_type=type(error).__name__)
    try:report["source_observation_after_failure"]=clean()
    except BaseException as source_error:report["source_observation_after_failure_error_type"]=type(source_error).__name__
    save();raise
print(json.dumps({"state":report["state"],"result":str(out/"result.json"),"target":str(target)}),flush=True)

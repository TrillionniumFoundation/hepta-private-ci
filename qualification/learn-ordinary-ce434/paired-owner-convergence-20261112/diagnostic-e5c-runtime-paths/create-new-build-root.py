from pathlib import Path
import hashlib,json,os,shutil,stat,subprocess,time
repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
source="e5c7dbd90938f1c9ac39dd3065c69a1b7707d6c4"
tree="a8fdee9eaa9f9f9dbe1bb25e215e4bf58e846b76"
root=Path("/data/hepta-learn-ce434-runtime-20261112-v2")
target=root/"target"
out=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/build-root-recovery-e5c7-v2")
pins=[{"key":"RUSTY_V8_ARCHIVE","path":"/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz","bytes":29366352,"sha256":"a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583"},{"key":"RUSTY_V8_SRC_BINDING_PATH","path":"/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs","bytes":39884,"sha256":"7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506"}]
def git(*args):return subprocess.check_output(["git",*args],cwd=repo,text=True).strip()
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
def clean():
    if git("rev-parse","HEAD")!=source or git("rev-parse","HEAD^{tree}")!=tree or git("status","--porcelain=v1","--untracked-files=all"):raise RuntimeError("fixed original source changed")
clean()
if root.exists() or root.is_symlink() or out.exists() or out.is_symlink():raise RuntimeError("exclusive recovery path exists; reconcile exact original request")
if Path("/data/hepta-learn-ce434-runtime-20261112-v1/target").exists():raise RuntimeError("old target reappeared; preserve and reassess")
parent=root.parent;ps=parent.lstat();usage=shutil.disk_usage(parent)
if not stat.S_ISDIR(ps.st_mode) or parent.resolve(strict=True)!=parent or ps.st_uid!=os.getuid() or ps.st_dev!=2067 or ps.st_ino!=2 or usage.free<64*1024**3:raise RuntimeError("observed owned data parent/space differs")
for path,digest in [
 (Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/v8-pinned-150-4-0-v2/manifest.json"),"9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5"),
 (Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/dependency-recovery-441de918-v1/result.json"),"8db2c096ff2c16b8e02f293a67c26939c5de6bf6e0dd69888179c4b0d31ca3fc")
]:
    if hash_owned(path)[0]!=digest:raise RuntimeError("original recovery/manifest changed")
for pin in pins:
    digest,metadata=hash_owned(Path(pin["path"]),pin["bytes"])
    if digest!=pin["sha256"] or metadata["mode"]!="0o100400":raise RuntimeError("original exact V8 input differs")
    pin["metadata_before"]=metadata
out.mkdir(mode=0o700,parents=False,exist_ok=False)
report={"schema":"learn.original-build-root-recovery.v1","state":"starting","source_sha":source,"source_tree":tree,"uid":os.getuid(),"runtime_root":str(root),"target":str(target),"data_parent":meta(ps),"data_free_bytes_before":usage.free,"original_manifest_sha256":"9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5","original_recovery_sha256":"8db2c096ff2c16b8e02f293a67c26939c5de6bf6e0dd69888179c4b0d31ca3fc","artifacts":pins,"downloaded":False,"copied":False,"existing_paths_removed_or_changed":False,"process_signals":False,"native_tests_executed":0}
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
    clean()
    report.update(state="isolated-build-target-created-original-pins-retained",source_after=git("rev-parse","HEAD"),source_status_after=git("status","--porcelain=v1","--untracked-files=all"),finished_unix_ms=int(time.time()*1000))
    save()
except BaseException as error:
    report.update(state="failed",error_type=type(error).__name__);save();raise
print(json.dumps({"state":report["state"],"result":str(out/"result.json"),"target":str(target)}),flush=True)

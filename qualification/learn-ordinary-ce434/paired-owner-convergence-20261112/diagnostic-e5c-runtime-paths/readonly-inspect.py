from pathlib import Path
import hashlib,json,os,shutil,stat,subprocess
repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
paths=["/data","/data/hepta-learn-ce434-runtime-20261112-v1","/data/hepta-learn-ce434-runtime-20261112-v1/target","/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins","/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz","/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs","/data/hepta-learn-ce434-runtime-20261112-v2","/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/v8-pinned-150-4-0-v2/manifest.json","/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/v8-pinned-150-4-0-v2/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs","/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/dependency-recovery-441de918-v1/result.json","/home/qian-qi/.cargo/registry","/home/qian-qi/.cargo/git"]
def meta(s):return {"device":s.st_dev,"inode":s.st_ino,"mode":oct(s.st_mode),"uid":s.st_uid,"nlink":s.st_nlink,"bytes":s.st_size,"mtime_ns":s.st_mtime_ns,"ctime_ns":s.st_ctime_ns}
def observe(p):
    record={"path":str(p)}
    try:
        before=p.lstat()
        record["metadata"]=meta(before)
        if stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_uid==os.getuid() and before.st_size<=67108864:
            fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            with os.fdopen(fd,"rb") as stream:
                first=os.fstat(stream.fileno())
                record["sha256"]=hashlib.file_digest(stream,"sha256").hexdigest()
                last=os.fstat(stream.fileno())
            record["stable"]=meta(before)==meta(first)==meta(last)==meta(p.lstat())
        elif stat.S_ISDIR(before.st_mode):
            usage=shutil.disk_usage(p)
            record["filesystem"]={"total":usage.total,"used":usage.used,"free":usage.free}
        record["state"]="observed"
    except OSError as error:
        record.update(state="read-failed",error_type=type(error).__name__,errno=error.errno)
    return record
def git(*args):return subprocess.check_output(["git",*args],cwd=repo,text=True).strip()
report={"schema":"learn.original-e5c-runtime-paths.v1","read_only":True,"uid":os.getuid(),"source_before":git("rev-parse","HEAD"),"source_tree":git("rev-parse","HEAD^{tree}"),"source_clean_before":not bool(git("status","--porcelain=v1","--untracked-files=all")),"paths":[observe(Path(p)) for p in paths]}
report.update(source_after=git("rev-parse","HEAD"),source_clean_after=not bool(git("status","--porcelain=v1","--untracked-files=all")))
print(json.dumps(report,indent=2),flush=True)

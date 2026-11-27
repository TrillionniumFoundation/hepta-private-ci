from pathlib import Path
import hashlib,json,os,re,shutil,stat,subprocess,time

repo=Path("/home/qian-qi/hepta-learn-positive-ce434-4537458b51b6-isolated-v1")
source="4537458b51b6ca936264aecea7cfe384b941d0d1"
tree="8cbd7b269c9c39df4ee3ffcefed8473060696184"
old_repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
old_source="a6717d7228045e6cb60532966f06e6e02c4a6abe"
old_tree="647b9e78151299c1e7de455eae9c530ca93b28c9"
out=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/original-archive-only-recovery-4537458b51b6-v1")
runtime=Path("/data/hepta-learn-ce434-runtime-20261112-v1")
private=runtime/"v8-private-pins"
pinroot=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/v8-pinned-150-4-0-v2")
archive_name="librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz"
binding_name="src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs"
archive_hash="a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583"
binding_hash="7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506"
archive=private/archive_name
binding=private/binding_name
url="https://github.com/openai/codex/releases/download/rusty-v8-v150.4.0/"+archive_name
binding_expected={"device":2067,"inode":40370261,"mode":"0o100400","nlink":1,"uid":1000,"gid":1000,"bytes":39884,"mtime_ns":"1794482968901013685","ctime_ns":"1794482968909814746"}

env=dict(os.environ)
env["GIT_OPTIONAL_LOCKS"]="0"
env["PYTHONDONTWRITEBYTECODE"]="1"
if os.getuid()!=1000 or os.geteuid()!=1000:raise RuntimeError("original normal uid1000 required")
if any(env.get(key) for key in ("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE")):raise RuntimeError("inherited Git location override")
def require(condition,message):
    if not condition:raise RuntimeError(message)
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
def identity(s):
    return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def facts(s):
    return {"device":s.st_dev,"inode":s.st_ino,"mode":oct(s.st_mode),"nlink":s.st_nlink,"uid":s.st_uid,"gid":s.st_gid,"bytes":s.st_size,"mtime_ns":str(s.st_mtime_ns),"ctime_ns":str(s.st_ctime_ns)}
def directory(path,private_mode=False):
    s=path.lstat()
    require(stat.S_ISDIR(s.st_mode) and path.resolve(strict=True)==path and s.st_uid==os.getuid(),"original canonical owned directory differs")
    if private_mode:require(stat.S_IMODE(s.st_mode)==0o700,"original private directory mode differs")
    return {"device":s.st_dev,"inode":s.st_ino,"uid":s.st_uid,"gid":s.st_gid,"mode":oct(s.st_mode)}
def require_absent(path,message):
    try:path.lstat()
    except FileNotFoundError:return
    raise RuntimeError(message)
def hash_owned(path,expected_size=None):
    before=path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and before.st_nlink==1,"original regular owned single-link file required")
    if expected_size is not None:require(before.st_size==expected_size,"original file size differs")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as stream:
        first=os.fstat(stream.fileno());digest=hashlib.file_digest(stream,"sha256").hexdigest();last=os.fstat(stream.fileno())
    require(identity(before)==identity(first)==identity(last)==identity(path.lstat()),"file changed during complete hash")
    return digest,facts(last)
def pinned_bytes(path,expected_hash):
    before=path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and before.st_nlink==1,"original pinned metadata type/owner differs")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as stream:
        first=os.fstat(stream.fileno());raw=stream.read();last=os.fstat(stream.fileno())
    require(identity(before)==identity(first)==identity(last)==identity(path.lstat()) and len(raw)==last.st_size and hashlib.sha256(raw).hexdigest()==expected_hash,"original pinned metadata differs")
    return raw
def source_state(worktree,expected_source,expected_tree):
    root=directory(worktree)
    require(git_at(worktree,"rev-parse","--show-toplevel")==str(worktree),"original source top-level differs")
    value={"repo":str(worktree),"source_sha":git_at(worktree,"rev-parse","HEAD"),"source_tree":git_at(worktree,"rev-parse","HEAD^{tree}"),"status":git_at(worktree,"status","--porcelain=v1","--untracked-files=all"),"directory":root}
    require(value["source_sha"]==expected_source and value["source_tree"]==expected_tree and value["status"]=="","fixed original source differs")
    return value
def clean():
    return {"current":source_state(repo,source,tree),"preserved":source_state(old_repo,old_source,old_tree)}
def original_binding():
    checksum,metadata=hash_owned(binding,39884)
    require(checksum==binding_hash and metadata==binding_expected,"actual original private binding identity or bytes changed")
    return {"path":str(binding),"sha256":checksum,"metadata":metadata}
def original_directories():
    return {str(path):directory(path,True) for path in (runtime,private)}

sources_before=clean()
require_absent(out,"exclusive archive-recovery evidence exists; reconcile original request")
require_absent(archive,"private archive reappeared; preserve it and reassess")
require_absent(pinroot/archive_name,"home archive reappeared; preserve it and reassess original local copy")
for path in (runtime/"target",Path("/data/hepta-learn-ce434-runtime-20261112-v2/target")):
    require_absent(path,"original target reappeared; preserve and reassess")
data=Path("/data");data_before=directory(data);space=shutil.disk_usage(data)
require(data_before["device"]==2067 and data_before["inode"]==2 and space.free>=64*1024**3,"original data identity or64GiB headroom differs")
dirs_before=original_directories()
binding_before=original_binding()
directory(out.parent)
pinbytes=pinned_bytes(pinroot/"manifest.json","9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5")
pin=json.loads(pinbytes)
for path,key in ((repo/"codex-rs/Cargo.lock","cargo_lock_sha256"),(repo/"scripts/codex_package/v8.py","resolver_sha256")):
    require(hash_owned(path)[0]==pin[key],"original dependency source differs")
for key,name,size,checksum in (("RUSTY_V8_ARCHIVE",archive_name,29366352,archive_hash),("RUSTY_V8_SRC_BINDING_PATH",binding_name,39884,binding_hash)):
    record=pin["artifacts"][key]
    require(record["path"]==str(pinroot/name) and pin["environment"][key]==str(pinroot/name) and record["bytes"]==size and record["sha256"]==checksum,"original pair manifest differs")
history=[
 (Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/dependency-recovery-441de918-v1/result.json"),"8db2c096ff2c16b8e02f293a67c26939c5de6bf6e0dd69888179c4b0d31ca3fc"),
 (Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/build-root-recovery-e5c7-v2/result.json"),"cbd5597a63f2a13bc771230d14b7c65774409f6169fd941bb6c0575f4d11b8eb"),
]
for path,expected_hash in history:pinned_bytes(path,expected_hash)
forward=Path("/home/qian-qi/.config/systemd/user/hepta-pocket4-socks.service").read_text()
require(re.findall(r"(?:^|\s)-D\s+([^\s]+)",forward)==["127.0.0.1:11080"],"existing original forward differs")

out.mkdir(mode=0o700,parents=False,exist_ok=False)
out_identity=directory(out,True)
partial=out/(archive_name+".partial")
report={"schema":"learn.original-archive-only-restoration.v1","state":"preflight-verified","source_sha":source,"source_tree":tree,"source_before":sources_before,"data_parent":data_before,"data_free_bytes_before":space.free,"existing_private_directories_before":dirs_before,"binding_before":binding_before,"binding_written":False,"binding_copied":False,"binding_chmodded":False,"binding_preserved":False,"archive_path":str(archive),"archive_url":url,"official_asset_id":493388485,"expected_archive_bytes":29366352,"expected_archive_sha256":archive_hash,"new_archive_created":False,"new_archive_identity":None,"private_directories_created":False,"v1_target_created":False,"preexisting_files_overwritten":False,"old_receipts_rewritten":False,"historical_receipts":[{"path":str(path),"sha256":checksum} for path,checksum in history],"steps":[],"new_signals_by_outer":[],"native_tests_executed":0,"ordinary_acceptance":0}
def save():
    pending=out/"result.pending.json"
    with pending.open("w") as stream:json.dump(report,stream,indent=2);stream.write("\n");stream.flush();os.fsync(stream.fileno())
    pending.replace(out/"result.json")
try:
    save()
    require_absent(partial,"exclusive new partial already exists")
    command=["/usr/bin/curl","--fail","--location","--silent","--show-error","--proto","=https","--proto-redir","=https","--tlsv1.2","--socks5-hostname","127.0.0.1:11080","--connect-timeout","20","--max-time","300","--max-redirs","5","--max-filesize","29366352","--output",str(partial),url]
    report.update(state="downloading-exact-original-public-asset",download_command=command);save()
    print(json.dumps({"state":report["state"],"result":str(out/"result.json")}),flush=True)
    started=time.monotonic()
    log=out/"download.log"
    with log.open("xb") as stream:
        process=subprocess.Popen(command,cwd=repo,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
        try:process.wait()
        except BaseException:
            process.wait()
            raise
    log_hash,log_meta=hash_owned(log)
    report["steps"].append({"name":"download-exact-original-public-asset","exit_code":process.returncode,"seconds":time.monotonic()-started,"log_bytes":log_meta["bytes"],"log_sha256":log_hash});save()
    require(process.returncode==0,"original asset download failed; preserve new partial and log")
    received_hash,received_meta=hash_owned(partial,29366352)
    require(received_hash==archive_hash,"downloaded original archive bytes differ")
    report["received_archive"]={"path":str(partial),"bytes":29366352,"sha256":received_hash,"metadata":received_meta}
    require(directory(out,True)==out_identity and original_directories()==dirs_before and directory(data)==data_before,"original directory identity changed")
    require(original_binding()==binding_before and clean()==sources_before,"original binding or source changed before install")
    require_absent(archive,"private archive appeared during download; never overwrite it")
    require_absent(pinroot/archive_name,"home archive reappeared; preserve it and reassess original local copy")
    private_fd=os.open(private,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        ps=os.fstat(private_fd)
        require({"device":ps.st_dev,"inode":ps.st_ino,"uid":ps.st_uid,"gid":ps.st_gid,"mode":oct(ps.st_mode)}==dirs_before[str(private)],"actual private directory descriptor differs")
        incoming_fd=os.open(partial,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        with os.fdopen(incoming_fd,"rb") as incoming:
            first=os.fstat(incoming.fileno())
            require(facts(first)==received_meta,"verified new partial was replaced")
            archive_fd=os.open(archive_name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=private_fd)
            with os.fdopen(archive_fd,"w+b") as outgoing:
                report["new_archive_created"]=True
                report["new_archive_identity"]=facts(os.fstat(outgoing.fileno()));save()
                copied=hashlib.sha256();count=0
                for block in iter(lambda:incoming.read(1024*1024),b""):
                    outgoing.write(block);copied.update(block);count+=len(block)
                outgoing.flush();os.fsync(outgoing.fileno())
                last=os.fstat(incoming.fileno())
                require(identity(first)==identity(last)==identity(partial.lstat()) and count==29366352 and copied.hexdigest()==archive_hash,"original archive changed during exclusive install")
                outgoing.seek(0)
                require(hashlib.file_digest(outgoing,"sha256").hexdigest()==archive_hash and os.fstat(outgoing.fileno()).st_size==29366352,"actual new archive fd bytes differ")
                os.fchmod(outgoing.fileno(),0o400);os.fsync(outgoing.fileno())
                installed=facts(os.fstat(outgoing.fileno()))
                require(stat.S_ISREG(os.fstat(outgoing.fileno()).st_mode) and installed["uid"]==os.getuid() and installed["nlink"]==1 and installed["mode"]=="0o100400" and facts(archive.lstat())==installed,"new archive fd is not the canonical original destination")
                report["new_archive_identity"]=installed
        os.fsync(private_fd)
    finally:
        os.close(private_fd)
    final_hash,final_meta=hash_owned(archive,29366352)
    require(final_hash==archive_hash and final_meta==report["new_archive_identity"],"actual installed original archive readback differs")
    binding_after=original_binding()
    require(binding_after==binding_before,"existing binding changed")
    require(original_directories()==dirs_before and directory(data)==data_before,"existing directory identity changed")
    for path,expected_hash in history:pinned_bytes(path,expected_hash)
    pinned_bytes(pinroot/"manifest.json","9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5")
    sources_after=clean()
    require(sources_after==sources_before,"fixed original sources changed")
    for path in (runtime/"target",Path("/data/hepta-learn-ce434-runtime-20261112-v2/target")):
        require_absent(path,"original target appeared; preserve and reassess")
    require_absent(pinroot/archive_name,"home archive reappeared; preserve it and reassess original local copy")
    report.update(state="original-archive-restored-binding-preserved-and-full-hash-verified",archive={"path":str(archive),"bytes":29366352,"sha256":final_hash,"metadata":final_meta},binding_after=binding_after,binding_preserved=True,existing_private_directories_after=original_directories(),source_after=sources_after,finished_unix_ms=int(time.time()*1000))
    save()
except BaseException as error:
    report.update(state="failed",error_type=type(error).__name__,error=str(error))
    try:report["binding_observation_after_failure"]=original_binding()
    except BaseException as observation_error:report["binding_observation_after_failure_error_type"]=type(observation_error).__name__
    try:report["sources_observation_after_failure"]=clean()
    except BaseException as observation_error:report["sources_observation_after_failure_error_type"]=type(observation_error).__name__
    save();raise
print(json.dumps({"state":report["state"],"result":str(out/"result.json"),"archive":str(archive),"binding_preserved":report["binding_preserved"],"native_tests_executed":0}),flush=True)

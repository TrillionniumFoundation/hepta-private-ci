from pathlib import Path
import hashlib,json,os,re,shutil,stat,subprocess,time
repo=Path("/home/qian-qi/hepta-learn-positive-ce434-20261112-3270-v1")
source="441de918b863dd15b2faeae920017c1b4b08f59d"
source_tree="c3390ffc8c18c47f7bb4cbaa24ce4b585645fae2"
evidence=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/dependency-recovery-441de918-v1")
runtime=Path("/data/hepta-learn-ce434-runtime-20261112-v1")
pinroot=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/v8-pinned-150-4-0-v2")
old_private=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111/native/live-owners-full-3270e8e8d310-v1/v8-private-pins")
archive_name="librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz"
binding_name="src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs"
archive_hash="a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583"
binding_hash="7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506"
url="https://github.com/openai/codex/releases/download/rusty-v8-v150.4.0/"+archive_name
def digest(path):
 with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()
def git(*args):return subprocess.check_output(["git",*args],cwd=repo,text=True).strip()
if git("rev-parse","HEAD")!=source or git("rev-parse","HEAD^{tree}")!=source_tree or git("status","--porcelain=v1","--untracked-files=all"):raise RuntimeError("fixed clean source changed")
if evidence.exists() or runtime.exists() or evidence.is_symlink() or runtime.is_symlink():raise RuntimeError("new request paths exist; reconcile this exact request")
data=Path("/data");s=data.lstat()
if not stat.S_ISDIR(s.st_mode) or data.resolve(strict=True)!=data or not os.access(data,os.W_OK|os.X_OK):raise RuntimeError("existing /data is not an accessible real directory")
space=shutil.disk_usage(data)
if space.free<64*1024**3:raise RuntimeError("existing data storage no longer has the reviewed build headroom")
pinbytes=(pinroot/"manifest.json").read_bytes()
if hashlib.sha256(pinbytes).hexdigest()!="9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5":raise RuntimeError("original manifest changed")
pin=json.loads(pinbytes)
if pin["cargo_lock_sha256"]!=digest(repo/"codex-rs/Cargo.lock") or pin["resolver_sha256"]!=digest(repo/"scripts/codex_package/v8.py"):raise RuntimeError("original source dependency identity differs")
forward=Path("/home/qian-qi/.config/systemd/user/hepta-pocket4-socks.service").read_text()
if re.findall(r"(?:^|\s)-D\s+([^\s]+)",forward)!=["127.0.0.1:11080"]:raise RuntimeError("existing forward differs")
for key,name,size,checksum in [("RUSTY_V8_ARCHIVE",archive_name,29366352,archive_hash),("RUSTY_V8_SRC_BINDING_PATH",binding_name,39884,binding_hash)]:
 record=pin["artifacts"][key]
 if record["path"]!=str(pinroot/name) or pin["environment"][key]!=str(pinroot/name) or record["bytes"]!=size or record["sha256"]!=checksum:raise RuntimeError("original pair manifest differs")
original_binding=old_private/binding_name
bs=original_binding.lstat()
if not stat.S_ISREG(bs.st_mode) or bs.st_uid!=os.getuid() or bs.st_nlink!=1 or bs.st_size!=39884 or digest(original_binding)!=binding_hash:raise RuntimeError("existing original binding identity differs")
evidence.mkdir(mode=0o700,parents=False)
report={"state":"preflight-verified","source_sha":source,"source_tree":source_tree,"runtime_root":str(runtime),"evidence":str(evidence),"uid":os.getuid(),"data_parent":{"uid":s.st_uid,"mode":oct(s.st_mode),"device":s.st_dev,"inode":s.st_ino,"free_bytes":space.free,"total_bytes":space.total},"original_manifest_sha256":hashlib.sha256(pinbytes).hexdigest(),"original_manifest_unchanged":True,"archive_url":url,"official_asset_id":493388485,"expected_archive_bytes":29366352,"expected_archive_sha256":archive_hash,"steps":[],"native_tests_executed":0,"ordinary_acceptance":{"positive":0,"no_update":0,"fresh_C":0,"daemon_root_cold_restart":0}}
def save():
 p=evidence/"result.pending.json"
 with p.open("w") as stream:json.dump(report,stream,indent=2);stream.write("\n");stream.flush();os.fsync(stream.fileno())
 p.replace(evidence/"result.json")
try:
 save()
 runtime.mkdir(mode=0o700)
 private=runtime/"v8-private-pins";private.mkdir(mode=0o700)
 target=runtime/"target";target.mkdir(mode=0o700)
 partial=private/(archive_name+".partial")
 command=["/usr/bin/curl","--fail","--location","--silent","--show-error","--proto","=https","--proto-redir","=https","--tlsv1.2","--socks5-hostname","127.0.0.1:11080","--connect-timeout","20","--max-time","300","--max-redirs","5","--max-filesize","29366352","--output",str(partial),url]
 report["state"]="downloading-exact-original-public-asset";report["download_command"]=command;save()
 print(json.dumps({"state":report["state"],"result":str(evidence/"result.json")}),flush=True)
 started=time.monotonic()
 with (evidence/"download.log").open("xb") as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False)
 report["steps"].append({"name":"download-exact-original-public-asset","exit_code":r.returncode,"seconds":time.monotonic()-started,"log_bytes":(evidence/"download.log").stat().st_size,"log_sha256":digest(evidence/"download.log")})
 save()
 if r.returncode:raise RuntimeError("original asset download failed; preserve partial and original log")
 ars=partial.lstat()
 if not stat.S_ISREG(ars.st_mode) or ars.st_uid!=os.getuid() or ars.st_nlink!=1 or ars.st_size!=29366352 or digest(partial)!=archive_hash:raise RuntimeError("received original archive failed complete byte verification")
 archive=private/archive_name
 if archive.exists() or archive.is_symlink():raise RuntimeError("private archive destination exists")
 partial.replace(archive);archive.chmod(0o400)
 binding=private/binding_name
 with original_binding.open("rb") as incoming,binding.open("xb") as outgoing:
  shutil.copyfileobj(incoming,outgoing);outgoing.flush();os.fsync(outgoing.fileno())
 binding.chmod(0o400)
 if digest(binding)!=binding_hash or binding.stat().st_size!=39884:raise RuntimeError("private binding copy differs")
 report["artifacts"]=[{"key":key,"path":str(path),"bytes":path.stat().st_size,"sha256":digest(path),"uid":path.stat().st_uid,"mode":oct(path.stat().st_mode),"nlink":path.stat().st_nlink} for key,path in [("RUSTY_V8_ARCHIVE",archive),("RUSTY_V8_SRC_BINDING_PATH",binding)]]
 report["environment"]={"RUSTY_V8_ARCHIVE":str(archive),"RUSTY_V8_SRC_BINDING_PATH":str(binding),"CARGO_TARGET_DIR":str(target)}
 report["source_after"]=git("rev-parse","HEAD");report["source_status_after"]=git("status","--porcelain=v1","--untracked-files=all")
 if report["source_after"]!=source or report["source_status_after"]:raise RuntimeError("source changed during dependency recovery")
 report["state"]="original-assets-recovered-and-full-hash-verified";save()
except BaseException as error:
 report.update(state="failed",error_type=type(error).__name__,error=str(error));save();raise
print(json.dumps(report,indent=2),flush=True)

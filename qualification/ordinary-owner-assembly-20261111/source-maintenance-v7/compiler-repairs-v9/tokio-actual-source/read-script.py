import hashlib,json,stat,tomllib
from pathlib import Path
def blob(raw): return hashlib.sha1(b"blob "+str(len(raw)).encode()+bytes([0])+raw).hexdigest()
def read(path,limit):
    before=path.lstat();assert stat.S_ISREG(before.st_mode) and not path.is_symlink() and before.st_size<=limit
    raw=path.read_bytes();after=path.lstat()
    assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    return raw,{"path":str(path),"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"git_blob":blob(raw),"version":[str(getattr(after,x)) for x in ("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")]}
lock,lp=read(Path("/home/qq/af52-learning-local-decision-20261111/ordinary-future-197-maintenance-v8/source/codex-rs/Cargo.lock"),4*1024*1024)
assert lp["git_blob"]=="025813e20504f31d12dae2092a0807a1a4066419"
packages=[p for p in tomllib.loads(lock.decode())["package"] if p["name"]=="tokio" and p["version"]=="1.53.3"]
assert len(packages)==1 and packages[0]["checksum"]=="ce3335fa71841cda333a58d7615b03901380ecf09d59b3296d21f8bbac0dde4e"
raw,pin=read(Path("/home/qq/.cargo/registry/src/index.crates.io-1949cf8c6b5b557f/tokio-1.53.3/src/io/async_fd.rs"),2*1024*1024)
assert pin["bytes"]==62421 and pin["git_blob"]=="3463439c9987132b95eb218119e7fe1fa93199b3" and pin["sha256"]=="0d9365deaa40f8d069770308a105aad31fe527ea593acf95c40265407d9f143d"
print(json.dumps({"schema_version":1,"kind":"actual-locked-tokio-source-byte-comparison","classification":"READ_ONLY_DEPENDENCY_EVIDENCE_NOT_QUALIFICATION","lock":lp,"package":packages[0],"actual_source":pin,"fixed_upstream":{"repository":"tokio-rs/tokio","commit":"a85c3f5baa298a6b554fd3700daf0342289881af","path":"tokio/src/io/async_fd.rs","git_blob":"3463439c9987132b95eb218119e7fe1fa93199b3"},"actual_source_length_git_sha256_all_match_fixed_upstream":True,"cargo_checksum_file_not_present_in_prior_read":True,"no_checksum_file_or_environment_created_or_modified":True},sort_keys=True),flush=True)

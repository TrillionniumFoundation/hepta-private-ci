#!/usr/bin/env python3
"""Retain the current failed-maintenance index; no Git, Cargo or source writes."""
import base64, datetime, gzip, hashlib, json, os, pathlib, signal, stat, sys, traceback
INDEX=pathlib.Path("/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1/.git/index")
OUT=pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/index-readonly-retention-v1")
EXPECTED_SIZE=2072488
EXPECTED_SHA="b19fab7a860a4281331096bd6a9c2ab5b6b9ef95ff8411e9f757cd1373380f15"
JOB="1a1d10d8ad0-2564-1bff"
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()
def blob(b): return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def jb(v): return (json.dumps(v,sort_keys=True,separators=(",",":"))+"\n").encode()
def meta(s):
    return dict(device=s.st_dev,inode=s.st_ino,mode=stat.S_IMODE(s.st_mode),uid=s.st_uid,
                nlink=s.st_nlink,bytes=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)
def dirs(path):
    for p in reversed([path,*path.parents]):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode): raise RuntimeError("non-real directory: "+str(p))
def read_index():
    dirs(INDEX.parent); before=INDEX.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid!=1000 or before.st_nlink!=1 or before.st_size>8388608:
        raise RuntimeError("index is not a bounded owned single-link regular file")
    fd=os.open(INDEX,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as f:
        opened=os.fstat(f.fileno()); data=f.read(8388609); ended=os.fstat(f.fileno())
    after=INDEX.lstat()
    observations=[meta(x) for x in (before,opened,ended,after)]
    if len(data)>8388608 or len(data)!=before.st_size or any(x!=observations[0] for x in observations):
        raise RuntimeError("index changed during stable read: "+json.dumps(observations,sort_keys=True))
    return data,observations
artifacts=[]
def write(name,b):
    if pathlib.Path(name).name!=name: raise RuntimeError("one-level record")
    p=OUT/name
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(b); f.flush(); os.fsync(f.fileno())
    if p.read_bytes()!=b: raise RuntimeError("created record readback mismatch")
    item=dict(name=name,bytes=len(b),sha256=sha(b),git_blob=blob(b));artifacts.append(item);return item
def timeout(signum,frame): raise TimeoutError("bounded read-only index retention")
result=dict(format="hepta-readonly-current-index-retention-v1",started_at=now(),source_index=str(INDEX),
            related_maintenance_job=JOB,expected_final_index_bytes=EXPECTED_SIZE,
            expected_final_index_sha256=EXPECTED_SHA,status="UNKNOWN",qualification=False,
            git_commands=0,cargo_commands=0,source_writes=False,
            limitation="The earlier index body is not present in its metadata-only archive. This captures the current index and does not replace the original final observation.")
created=False
try:
    signal.signal(signal.SIGALRM,timeout);signal.alarm(40)
    if os.getuid()!=1000: raise RuntimeError("configured operator UID mismatch")
    dirs(OUT.parent)
    os.mkdir(OUT,0o700);created=True
    write("ACTUAL_DRIVER.py",_source)
    raw,first=read_index();result["initial_read_metadata"]=first
    result["raw_index"]=write("index.actual.bin",raw)
    gz=gzip.compress(raw,mtime=0)
    if gzip.decompress(gz)!=raw: raise RuntimeError("gzip mismatch")
    result["gzip"]=write("index.actual.bin.gz",gz);result["parts"]=[]
    for i,offset in enumerate(range(0,len(gz),262144),1):
        part=gz[offset:offset+262144]
        row=write("index.actual.bin.gz.part-%03d.b64"%i,base64.b64encode(part)+b"\n")
        row.update(decoded_offset=offset,decoded_bytes=len(part),decoded_sha256=sha(part))
        result["parts"].append(row)
    again,last=read_index();result["final_read_metadata"]=last
    result["final_read_sha256"]=sha(again)
    result["stable_across_retention"]=first[0]==last[0] and raw==again
    result["matches_original_final"]=len(raw)==EXPECTED_SIZE and sha(raw)==EXPECTED_SHA
    if not result["stable_across_retention"]:
        result["changed_recheck_bytes"]=write("index.recheck.bin",again)
        result["status"]="UNKNOWN_CURRENT_INDEX_CHANGED"
    elif not result["matches_original_final"]:
        result["status"]="UNKNOWN_CURRENT_DIFFERS_FROM_ORIGINAL_FINAL"
    else: result["status"]="CURRENT_INDEX_RETAINED_AND_MATCHES_ORIGINAL_FINAL"
except BaseException as e:
    result.update(status="UNKNOWN",error=repr(e),traceback=traceback.format_exc())
finally:
    signal.alarm(0);result["finished_at"]=now()
    if created:
        try:
            write("ARTIFACTS.json",jb({"files":list(artifacts),"result":"RESULT.json"}))
            write("RESULT.json",jb(result))
        except BaseException as e:result.update(status="UNKNOWN",retention_error=repr(e))
    print(json.dumps(result,sort_keys=True),flush=True)
sys.exit(0 if result["status"]=="CURRENT_INDEX_RETAINED_AND_MATCHES_ORIGINAL_FINAL" else 1)

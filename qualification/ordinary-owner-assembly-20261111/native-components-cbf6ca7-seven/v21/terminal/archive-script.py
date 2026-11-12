import hashlib,io,json,os,stat,subprocess,tarfile,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
WORK=Path("/home/qq/af52-learning-local-decision-20261111/ordinary-cbf6ca7-seven-final-v21")
SOURCE=WORK/"source"; RECORDS=WORK/"records"; OUT=WORK/"terminal-archive-v1"
EXPECTED="cbf6ca7dd619589be3e9e98755f185d34d0f7413"
TREE="c3c131a738f99022bfb5e72bb53ef44c064ad350"
sha=lambda b:hashlib.sha256(b).hexdigest()
def original(path):
    assert path.is_relative_to(RECORDS)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        a=os.fstat(fd)
        assert stat.S_ISREG(a.st_mode) and a.st_nlink==1 and a.st_size<=32*1024*1024
        chunks=[]
        while True:
            b=os.read(fd,65536)
            if not b:break
            chunks.append(b)
        b=b"".join(chunks);z=os.fstat(fd)
        assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns)
        assert len(b)==a.st_size
        return b,{"device":a.st_dev,"inode":a.st_ino,"bytes":len(b),"mtime_ns":a.st_mtime_ns,"ctime_ns":a.st_ctime_ns,"sha256":sha(b)}
    finally:os.close(fd)
assert WORK.resolve()==WORK and RECORDS.resolve()==RECORDS and SOURCE.resolve()==SOURCE
assert subprocess.check_output(["git","rev-parse","HEAD"],cwd=SOURCE,text=True,timeout=30).strip()==EXPECTED
assert subprocess.check_output(["git","rev-parse","HEAD^{tree}"],cwd=SOURCE,text=True,timeout=30).strip()==TREE
assert subprocess.check_output(["git","status","--porcelain"],cwd=SOURCE,text=True,timeout=30)==""
raw,progress_pin=original(RECORDS/"progress.json");progress=json.loads(raw)
assert progress["source_sha"]==EXPECTED and progress["source_tree"]==TREE
assert progress["status"]=="failed-native-components"
assert progress["current_stage"]=="finished-or-awaiting-original"
assert not progress.get("completion_unknown") and not progress.get("pending_terminal_observations")
OUT.mkdir(mode=0o700)
def write_new(name,data):
    p=OUT/name
    assert p.parent==OUT
    with p.open("xb") as f:f.write(data);f.flush();os.fsync(f.fileno())
    return {"path":str(p),"bytes":len(data),"sha256":sha(data)}
def asjson(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
summary={k:v for k,v in progress.items() if k in ("schema","classification","source_sha","source_tree","format_base","status","current_stage","errors","cleanup","ordinary_counts","root_counts","reference_before","reference_after","before_tests","after_tests","after_maintenance","ordinary_complete_chains","positive_adoption_chains","ordinary_no_update_rollback_chains","independent_consumer_accepted","physical_daemon_root_restart_accepted","predecessor_results_used","known_failure_exemptions","maintenance_patch")}
summary["original_progress"]=progress_pin
summary["steps"]=[{k:v for k,v in s.items() if k in ("name","status","exit_code","elapsed_seconds","timed_out","returncode","execution","command_exit_code","duration_seconds","log","launch")} for s in progress.get("steps",[])]
summary_pin=write_new("terminal-summary.json",asjson(summary))
execution_pins={}
for name in ("ordinary","root","caller-full-verify","same-source-helper-postverify"):
    b,p=original(RECORDS/(name+".execution.json"));d=json.loads(b)
    assert d["tested_sha"]==EXPECTED and d["source_sha"]==EXPECTED and not d["timed_out"]
    execution_pins[name]=p
failed=[]
for suite,expected_sha,expected_cases,expected_failed in (
    ("ordinary","6fcbaabdb9c7839a462b5b4e7a298d06d3a060af6a6aedcb855582ce4f76a9fc",1997,0),
    ("root","2b3b65cd95780158779700541501097a09c1e9aac2218866accd56f45036f33b",17,1)):
    b,p=original(RECORDS/(suite+".junit.xml"));assert sha(b)==expected_sha
    xml=ET.fromstring(b);cases=xml.findall(".//testcase")
    assert len(cases)==expected_cases
    failures=[c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    assert len(failures)==expected_failed
    for i,c in enumerate(failures):
        entry={"suite":suite,"testcase":c.attrib,"junit":p,"failure_nodes":[{"tag":n.tag,"attributes":n.attrib,"text":n.text} for n in c if n.tag in ("failure","error")],"output":{}}
        for tag in ("system-out","system-err"):
            t=c.findtext(tag) or "";data=t.encode()
            pin=write_new(suite+"-failure-"+str(i).zfill(2)+"."+tag+".txt",data)
            lines=t.splitlines()
            relevant=[{"line":j+1,"text":line} for j,line in enumerate(lines) if any(w in line.lower() for w in ("panicked","unavailable","elapsed","request_started","expired","deadline","assertion","error:","fault","cache_age","original_cache"))]
            entry["output"][tag]={"original":pin,"diagnostic_matches":relevant}
        failed.append(entry)
failure_pin=write_new("failed-testcases.json",asjson({"source_sha":EXPECTED,"source_tree":TREE,"derived_from_original_junit":True,"cases":failed}))
files=[];payload={};total=0
for parent,dirs,names in os.walk(RECORDS,followlinks=False):
    dirs.sort()
    for n in dirs:
        p=Path(parent)/n
        assert stat.S_ISDIR(p.lstat().st_mode) and not p.is_symlink()
    for n in sorted(names):
        p=Path(parent)/n;b,pin=original(p);relative=p.relative_to(RECORDS).as_posix()
        pin={"name":"records/"+relative,**pin};files.append(pin);payload[pin["name"]]=b;total+=len(b)
        assert total<=128*1024*1024
files.sort(key=lambda x:x["name"])
index={"schema_version":1,"source_sha":EXPECTED,"source_tree":TREE,"original_records_path":str(RECORDS),"files":files,"file_count":len(files),"total_original_bytes":total,"original_files_modified":False,"qualification_rerun":False,"refs_changed":False}
index_bytes=asjson(index);payload["ARCHIVE_INDEX.json"]=index_bytes
names=sorted(payload)
def tar_pack(selected):
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode="w:xz",format=tarfile.PAX_FORMAT,preset=6) as t:
        for n in selected:
            b=payload[n];info=tarfile.TarInfo(n);info.size=len(b);info.mtime=0;info.mode=0o444;info.uid=0;info.gid=0
            t.addfile(info,io.BytesIO(b))
    packed=buf.getvalue()
    with tarfile.open(fileobj=io.BytesIO(packed),mode="r:xz") as t:
        assert t.getnames()==selected
        for member in t:assert t.extractfile(member).read()==payload[member.name]
    return packed
buf=io.BytesIO()
with zipfile.ZipFile(buf,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for n in names:
        zi=zipfile.ZipInfo(n,date_time=(1980,1,1,0,0,0));zi.compress_type=zipfile.ZIP_DEFLATED;zi.external_attr=0o100444<<16
        z.writestr(zi,payload[n])
zipped=buf.getvalue()
with zipfile.ZipFile(io.BytesIO(zipped)) as z:
    assert z.namelist()==names
    for n in names:assert z.read(n)==payload[n]
included=[];excluded=[]
for n in names:
    b=payload[n]
    try:
        b.decode("utf-8")
        if b"\0" in b:raise ValueError("NUL bytes")
        included.append(n)
    except (UnicodeDecodeError,ValueError):
        excluded.append({"name":n,"bytes":len(b),"sha256":sha(b),"reason":"Binary original remains in both complete original archives"})
archive_zip=write_new("original-records.zip",zipped)
archive_full=write_new("original-records.tar.xz",tar_pack(names))
archive_text=write_new("original-text-records.tar.xz",tar_pack(included))
index_pin=write_new("archive-index.json",index_bytes)
text_index=write_new("text-archive-index.json",asjson({"included":[{"name":n,"bytes":len(payload[n]),"sha256":sha(payload[n])} for n in included],"excluded_binary_copies":excluded,"exact_roundtrip_verified":True,"source_archive":archive_full}))
for p in files:
    b,pin=original(RECORDS/p["name"].removeprefix("records/"))
    assert pin=={k:v for k,v in p.items() if k!="name"} and b==payload[p["name"]]
assert subprocess.check_output(["git","status","--porcelain"],cwd=SOURCE,text=True,timeout=30)==""
receipt={"schema_version":1,"source_sha":EXPECTED,"source_tree":TREE,"status":"failed-native-components","progress":progress_pin,"terminal_summary":summary_pin,"execution_records":execution_pins,"failed_testcases":failure_pin,"complete_zip":archive_zip,"complete_tar_xz":archive_full,"text_tar_xz":archive_text,"archive_index":index_pin,"text_index":text_index,"original_file_count":len(files),"text_entry_count":len(included),"binary_original_count":len(excluded),"exact_roundtrip_verified":True,"original_files_modified":False,"qualification_rerun":False,"refs_changed":False}
receipt_pin=write_new("archive-receipt.json",asjson(receipt))
print(json.dumps({"receipt":receipt_pin,"artifacts":receipt,"failed":[{"suite":x["suite"],"testcase":x["testcase"],"failure_nodes":x["failure_nodes"]} for x in failed]},ensure_ascii=False,sort_keys=True),flush=True)

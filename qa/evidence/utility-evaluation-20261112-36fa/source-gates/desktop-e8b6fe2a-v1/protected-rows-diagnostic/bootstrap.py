import base64,gzip,hashlib,json,os,pathlib,subprocess,sys,time
from datetime import datetime,timezone
payload=json.load(sys.stdin)
packet=payload["packet_base64_gzip"].encode()
script=payload["script_text"].encode()
assert len(packet)==393153 and hashlib.sha256(packet).hexdigest()=="3bf44cb6146472a608833e6af241df1ef7614a282e92c1ce115b4566dfb90671"
decoded=gzip.decompress(base64.b64decode(packet.strip(),validate=True))
assert len(decoded)==1430175 and hashlib.sha256(decoded).hexdigest()=="16a603cb704471effbca78312ed34504b55c0baea00e124689dddc2dabd1e255"
data=json.loads(decoded)
assert data["base_commit"]=="e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd" and data["base_tree"]=="b607ff5f50812c5e0f932d7dae18d4c74f1269cb"
target=[f for f in data["files"] if f["path"]=="CALLERS.toml"]
assert len(target)==1
manifest=base64.b64decode(target[0]["postimage_base64"],validate=True)
assert len(manifest)==1039720 and hashlib.sha256(manifest).hexdigest()=="529c421f3580b87f3eedbea2b53f93fa2f39e45ea478dcbbb69b69e91a95723d"
assert len(script)==6312 and hashlib.sha256(script).hexdigest()=="b0781a9bd491e5ab6038e784102a817c026932bbb85986b942ef8b3b5f3a2cc0"
root=pathlib.Path("/home/qian-qi/hepta-utility-36fa-source-gates-e8b6fe2a-v1")
records=pathlib.Path("/home/qian-qi/hepta-utility-36fa-protected-rows-e8b-v1")
assert not records.exists() and root.is_dir() and root.resolve()!=records.resolve()
records.mkdir(mode=0o700)
def create(name,data):
    path=records/name
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
    try:
        with os.fdopen(fd,"wb",closefd=False) as f:
            f.write(data);f.flush();os.fsync(f.fileno())
    finally:os.close(fd)
    return path
def encode(value):return (json.dumps(value,indent=2,sort_keys=True)+"\n").encode()
def identity(path):
    b=path.read_bytes()
    return {"path":str(path),"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob_sha":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
script_path=create("diagnose_protected_rows.py",script)
manifest_path=create("CALLERS.toml",manifest)
command=["/usr/bin/python3","-B",str(script_path),"--root",str(root),"--manifest",str(manifest_path)]
create("run-start.json",encode({"identity":"hepta-utility-36fa-protected-rows-e8b-v1","at":datetime.now(timezone.utc).isoformat(),"source_sha":"e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd","source_tree":"b607ff5f50812c5e0f932d7dae18d4c74f1269cb","command":command,"timeout_seconds":600,"script":identity(script_path),"external_manifest":identity(manifest_path),"source_gate_job_unchanged":"1a1cf209cdd-2564-199e","scope":"Read-only protected-row diagnostic only; no full gate, source write, ref change or Cargo."}))
started=time.monotonic();timed_out=False
with (records/"diagnostic.json").open("xb") as out,(records/"diagnostic.stderr.log").open("xb") as err:
    try:
        result=subprocess.run(command,cwd=records,env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",GIT_OPTIONAL_LOCKS="0"),stdout=out,stderr=err,timeout=600)
        returncode=result.returncode
    except subprocess.TimeoutExpired:
        timed_out=True;returncode=None
    out.flush();os.fsync(out.fileno());err.flush();os.fsync(err.fileno())
raw=(records/"diagnostic.json").read_bytes()
parse_error=None
try:report=json.loads(raw)
except Exception as error:report={};parse_error=repr(error)
compressed=gzip.compress(raw,mtime=0)
archive=create("diagnostic.json.gz.b64",base64.b64encode(compressed)+b"\n")
summary={"identity":"hepta-utility-36fa-protected-rows-e8b-v1","finished_at":datetime.now(timezone.utc).isoformat(),"elapsed_seconds":time.monotonic()-started,"returncode":returncode,"timed_out":timed_out,"scope":"Only the original _verify_protected_files over 381 rows with an external reviewed manifest. Not source-closure, complete caller proof or Rust tests.","full_gate_status":"not_run","reported_status":report.get("status"),"passed_rows":report.get("passed_rows"),"failed_rows":report.get("failed_rows"),"source_inputs_unchanged":report.get("source_inputs_unchanged"),"report_parse_error":parse_error,"raw":identity(records/"diagnostic.json"),"stderr":identity(records/"diagnostic.stderr.log"),"archive":identity(archive),"archive_encoding":"base64 UTF-8 plus LF of gzip mtime=0; decode and gunzip then verify raw bytes/hash","compressed_sha256":hashlib.sha256(compressed).hexdigest()}
create("run-result.json",encode(summary))
print(json.dumps(summary),flush=True)
sys.exit(0 if returncode==0 and not timed_out and report.get("status")=="passed_scoped_diagnostic" and report.get("passed_rows")==381 and report.get("failed_rows")==0 and report.get("source_inputs_unchanged") is True else 1)

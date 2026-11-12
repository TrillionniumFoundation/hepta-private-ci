from pathlib import Path
import datetime,hashlib,json,os,subprocess,time
here=Path(__file__).resolve().parent
root=here/"partial_source"
def inventory():
 return [{"path":str(p.relative_to(root)),"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()} for p in sorted(root.rglob("*")) if p.is_file() for b in [p.read_bytes()]]
def write(name,value):
 (here/name).write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
before=inventory();write("INPUT_INVENTORY.json",before)
argv=["python3","-B","-m","unittest","test_evaluated_published_read_source_closure.EvaluatedOrdinaryRetainedClosureTests","-v"]
started=datetime.datetime.now(datetime.timezone.utc).isoformat();clock=time.monotonic();timed_out=False
with (here/"new18.raw.log").open("xb") as log:
 try:
  result=subprocess.run(argv,cwd=root/"qa/b4-no-bypass",env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"},stdout=log,stderr=subprocess.STDOUT,timeout=600)
  code=result.returncode
 except subprocess.TimeoutExpired:
  code=None;timed_out=True
after=inventory();write("AFTER_INVENTORY.json",after)
raw=(here/"new18.raw.log").read_bytes()
write("RESULT.json",{"format":"hepta-scoped-new-source-attacks-diagnostic-v1","qualification":False,"scope":"18 newly added source mechanism tests only; 73-file actual review projection; complete source closure and caller verification not run","argv":argv,"started_at":started,"finished_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"elapsed_seconds":time.monotonic()-clock,"returncode":code,"timed_out":timed_out,"inputs_unchanged":before==after,"raw":{"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"git_blob_sha":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()},"full_source_closure":"not_run","full_caller":"not_run","rust_tests":"not_run"})
print((here/"RESULT.json").read_text())
print(raw.decode()[-12000:])

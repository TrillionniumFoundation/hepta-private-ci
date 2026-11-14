import hashlib,json,os,pathlib,stat,subprocess,sys,time
KEY="ctrl-fit40-gap-20261111-f7c0ded86bcc-v1"
STAGE=pathlib.Path("/home/qq/"+KEY)
EXPECTED={
 "candidate_coverage.py":("3d44b74354a3a56b69467e1c019606de7f360666d7fa09a8cee4fe2f71c5872b",14398),
 "candidate_coverage_legacy.py":("daba119e74d2f306731c063c30da9a6fb1a8717636ab4061d20e71e138632799",16027),
 "candidate_gap_diagnostic.py":("1da02aea4aabb7e21486110fc0ec545fe9d683e5e0383311df568e33f649753e",16971)}
INPUTS={
 "request":("/home/qq/ctrl-answer-repair-20261110-e323-v1/REQUEST.json","3ea9d00f6dc1be41427272a1f79169d3b2bd4b56d8b1b97ec7693be9c9b4824e",7550),
 "collection":("/home/qq/ndu-portfolio-frozen-20261109-eb02e89/collection-v1/COLLECTION_PLAN.json","7be396821d6a16352b5e71b66f0a374962153c269063134ced06b4ce924d9ee6",39942),
 "records":("/home/qq/ndu-real-runtime-20261107-bc2efaf10cd0/pilot-run-v1/training-content.jsonl","43f1c63fe378a783cc57d475ad1841c4235b7d1eaa335c2e0fdd2126f73d1a85",9496351)}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+"\n").encode()
def write(path,raw):
 with path.open("xb") as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
 if path.read_bytes()!=raw:raise ValueError("RUNNER_WRITE_READBACK")
def inspect(path,expected,size):
 p=pathlib.Path(path);s=p.lstat()
 if not stat.S_ISREG(s.st_mode) or s.st_size!=size:raise ValueError("RUNNER_INPUT_TYPE_OR_SIZE")
 raw=p.read_bytes()
 if len(raw)!=size or sha(raw)!=expected:raise ValueError("RUNNER_INPUT_HASH")
 return {"sha256":expected,"bytes":size,"version":":".join(str(x) for x in (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns))}
start=time.time();wall=time.perf_counter();cpu=time.process_time()
payload=json.loads(sys.stdin.read(1024*1024+1))
if set(payload)!={"sources"} or set(payload["sources"])!=set(EXPECTED):raise ValueError("RUNNER_PAYLOAD_SHAPE")
raws={}
for name,(expected,size) in EXPECTED.items():
 raw=payload["sources"][name].encode()
 if len(raw)!=size or sha(raw)!=expected:raise ValueError("RUNNER_FROZEN_SOURCE_MISMATCH")
 raws[name]=raw
before={k:inspect(*v) for k,v in INPUTS.items()}
STAGE.mkdir(mode=0o700,exist_ok=False)
for name,raw in raws.items():write(STAGE/name,raw)
source_before={k:inspect(STAGE/k,h,n) for k,(h,n) in EXPECTED.items()}
command=[sys.executable,"-I","-B",str(STAGE/"candidate_gap_diagnostic.py"),
 "--request",INPUTS["request"][0],"--request-sha256",INPUTS["request"][1],
 "--coverage-source",str(STAGE/"candidate_coverage.py"),"--coverage-source-sha256",EXPECTED["candidate_coverage.py"][0],
 "--legacy-source",str(STAGE/"candidate_coverage_legacy.py"),"--legacy-source-sha256",EXPECTED["candidate_coverage_legacy.py"][0],
 "--diagnostic-sha256",EXPECTED["candidate_gap_diagnostic.py"][0],"--output",str(STAGE/"result")]
write(STAGE/"LAUNCH.json",encode({"key":KEY,"argv":command,"source_commit":"13de10b55b0f16cf1548dab193fbb8ac11d3b4cd","before":before,"source_before":source_before,"unix_start":start}))
run=subprocess.run(command,cwd=STAGE,capture_output=True,timeout=90,check=False)
write(STAGE/"DIAGNOSTIC_STDOUT.txt",run.stdout);write(STAGE/"DIAGNOSTIC_STDERR.txt",run.stderr)
after={k:inspect(*v) for k,v in INPUTS.items()}
source_after={k:inspect(STAGE/k,h,n) for k,(h,n) in EXPECTED.items()}
if before!=after or source_before!=source_after:raise ValueError("RUNNER_INPUT_OR_SOURCE_CHANGED")
files={}
for relative in ["DIAGNOSTIC_STDOUT.txt","DIAGNOSTIC_STDERR.txt","result/RESULT.json","result/BASELINE_BEFORE/RESULT.json","result/BASELINE_AFTER/RESULT.json"]:
 p=STAGE/relative
 if p.is_file():
  raw=p.read_bytes();files[relative]={"bytes":len(raw),"sha256":sha(raw)}
result_path=STAGE/"result/RESULT.json"
if run.returncode==0:
 result=json.loads(result_path.read_bytes())
 if result["original_rows"]!=200 or result["unique_states"]!=160 or result["new_independent_tasks"]!=0 or result["production_admission"] or result["actor_installed"] or result["policy_efficacy_evaluated"]:raise ValueError("RUNNER_SCOPE_DRIFT")
 for k in ["model_inference_calls","training_steps","ocr_calls","new_observations"]:
  if result["execution"][k]!=0:raise ValueError("RUNNER_CALL_SCOPE_DRIFT")
 if result["execution"]["future_labels_opened"]:raise ValueError("RUNNER_FUTURE_SCOPE_DRIFT")
receipt={"schema":"ctrl.fit40.frozen-gap-run-receipt.v1","operation_key":KEY,"status":"completed" if run.returncode==0 else "rejected","exit_code":run.returncode,"diagnostic_source_commit":"13de10b55b0f16cf1548dab193fbb8ac11d3b4cd","evidence_parent_commit":"602cd5695092a82f876fd122243b971b5b88eee8","inputs_before":before,"inputs_after":after,"source_before":source_before,"source_after":source_after,"unchanged_inputs_and_sources":True,"files":files,"python":sys.version,"unix_start":start,"unix_finished":time.time(),"wrapper_wall_seconds":time.perf_counter()-wall,"wrapper_cpu_seconds":time.process_time()-cpu,"wrapper_cpu_scope":"parent_only_excludes_child","full_physical_cost_observed":False,"new_independent_tasks":0,"model_inference_calls":0,"ocr_calls":0,"training_steps":0,"future_labels_opened":False,"production_admission":False,"adoption_action":"NoUpdate"}
write(STAGE/"RECEIPT.json",encode(receipt))
print(json.dumps({"status":receipt["status"],"exit_code":run.returncode,"operation_key":KEY,"receipt_bytes":(STAGE/"RECEIPT.json").stat().st_size,"receipt_sha256":sha((STAGE/"RECEIPT.json").read_bytes()),"files":files},sort_keys=True),flush=True)
sys.exit(run.returncode)

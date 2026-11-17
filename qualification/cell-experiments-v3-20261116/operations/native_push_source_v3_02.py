"""Resume publication after the observed read-only native Git network failure."""
import json,os,subprocess,time
from pathlib import Path
root=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
work=root/"publication-native-01"
prior=root/"publication-source-operation-01"
ops=root/"publication-source-push-02"
ops.mkdir(exist_ok=False)
failure=json.loads((prior/"FAILED.json").read_text())
rows=failure["completed_commits"]
if len(rows)!=16 or (prior/"PUSH_STARTED.json").exists():
    raise ValueError("the prior operation was not the observed pre-push failure")
if failure["commands"][-1]["argv"][:3]!=["git","ls-remote","origin"]:
    raise ValueError("unexpected prior failing operation")
env=dict(os.environ,GIT_TERMINAL_PROMPT="0")
def capture(argv,timeout=60):
    return subprocess.run(argv,cwd=work,env=env,capture_output=True,text=True,timeout=timeout)
actual=capture(["git","rev-parse","HEAD"])
if actual.returncode or actual.stdout.strip()!=rows[-1]["commit"]:
    raise ValueError("local source head changed")
refs=["refs/heads/"+row["branch"] for row in rows]
for row,ref in zip(rows,refs):
    current=capture(["git","rev-parse","--verify",ref])
    if current.returncode or current.stdout.strip()!=row["commit"]:
        raise ValueError("local stage reference changed")
argv=["git","push","--atomic","--porcelain",*["--force-with-lease="+ref+":" for ref in refs],"origin",*refs]
with (ops/"PUSH_STARTED.json").open("x") as f:
    json.dump({"argv":argv,"commits":rows,"expected_remote_refs":"absent; protected by empty-value lease","remote_deletions":False,"started_at_ns":time.time_ns()},f,indent=2)
started=time.perf_counter()
try:
    r=capture(argv)
    result={"status":"PUSH_SUCCEEDED" if r.returncode==0 else "PUSH_FAILED","exit_code":r.returncode,"stdout":r.stdout,"stderr":r.stderr,"wall_seconds":time.perf_counter()-started,"commits":rows,"next_step":"verify exact remote refs through GitHub connector"}
except subprocess.TimeoutExpired as error:
    result={"status":"PUSH_ACKNOWLEDGEMENT_UNKNOWN","wall_seconds":time.perf_counter()-started,"commits":rows,"next_step":"read exact remote refs before any mutation"}
with (ops/"RESULT.json").open("x") as f:json.dump(result,f,indent=2);f.write("\n")
print(json.dumps(result))

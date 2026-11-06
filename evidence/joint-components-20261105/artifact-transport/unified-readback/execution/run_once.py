"""Run the single reviewed cloud byte consumer; preserve real streams and exit."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

OWN=Path(__file__).resolve().parent
request_raw=(OWN/'request.json').read_bytes();request=json.loads(request_raw)
assert hashlib.sha256(Path(request['argv'][2]).read_bytes()).hexdigest()==request['verifier_sha256']
started_utc=datetime.now(timezone.utc).isoformat();started=time.monotonic()
with (OWN/'stdout.log').open('xb') as stdout, (OWN/'stderr.log').open('xb') as stderr:
    process=subprocess.Popen(request['argv'],cwd=request['cwd'],stdout=stdout,stderr=stderr)
    with (OWN/'actual-launch.json').open('x') as f:
        json.dump({'schema':'actual-cloud-consumer-launch-v1','pid':process.pid,'started_utc':started_utc,
                   'request_sha256':hashlib.sha256(request_raw).hexdigest(),'argv':request['argv']},f,sort_keys=True,indent=2)
        f.write('\n');f.flush();os.fsync(f.fileno())
    code=process.wait()
    stdout.flush();stderr.flush();os.fsync(stdout.fileno());os.fsync(stderr.fileno())
elapsed=time.monotonic()-started
streams={}
for name in ['stdout.log','stderr.log']:
    b=(OWN/name).read_bytes();streams[name]={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
receipt={'schema':'actual-cloud-consumer-terminal-v1','request_sha256':hashlib.sha256(request_raw).hexdigest(),
         'pid':process.pid,'started_utc':started_utc,'completed_utc':datetime.now(timezone.utc).isoformat(),
         'elapsed_seconds':elapsed,'exit_code':code,'streams':streams,'automatic_retry':False,
         'native_execution':False,'new_remote_calls':0}
with (OWN/'terminal.json').open('x') as f:
    json.dump(receipt,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
fd=os.open(OWN,os.O_RDONLY|os.O_DIRECTORY)
try:os.fsync(fd)
finally:os.close(fd)
print(json.dumps(receipt,sort_keys=True),flush=True)
raise SystemExit(code)

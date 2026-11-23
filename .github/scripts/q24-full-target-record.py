"""Preserve all original test logs and the unedited relevant BEP events per arm."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

arm=sys.argv[1]
out=Path(os.environ['RUNNER_TEMP'])/'q24-full'/arm
events=out/'bep.json'
if not events.is_file(): raise SystemExit("Missing build-event protocol stream")
samples=[]
with events.open() as stream, (out/'test-events.jsonl').open('w') as trim:
    for line in stream:
        entry=json.loads(line)
        if any(k in entry for k in ('testResult','testSummary','buildFinished','finished','aborted')):
            trim.write(line)
        if 'testResult' in entry: samples.append(entry)
events.unlink()
console=out/'console.log'
credential=os.getenv('BUILDBUDDY_API_KEY')
if console.is_file() and credential:
    console.write_bytes(console.read_bytes().replace(credential.encode(), b'[redacted]'))
target='//codex-rs/hepta-agentd:hepta-agentd-unit-tests'
live=[e for e in samples if e['id']['testResult'].get('label')==target]
base=Path(os.environ['BAZEL_OUTPUT_BASE'])/'execroot'
roots=list(base.glob('*/bazel-out/x86_64-unknown-linux-musl-*/testlogs/codex-rs/hepta-agentd/hepta-agentd-unit-tests'))
if len(roots)!=1: raise SystemExit(f"Unexpected original testlog locations: {roots}")
logroot=roots[0]
items=[]
for f in sorted(logroot.rglob('*')):
    if f.is_file() and (f.suffix in ('.log','.xml') or f.name in ('test.log','test.xml')):
        dest=out/'logs'/f.relative_to(logroot)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(f,dest)
        items.append({'path':str(dest.relative_to(out)),'bytes':dest.stat().st_size,
                      'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
report={'arm':arm,'bazel_status':int((out/'exit.txt').read_text()),'outputs':items,
        'bep_results':[{'id':e['id']['testResult'],'result':e['testResult']} for e in live]}
(out/'record.json').write_text(json.dumps(report,indent=2)+'\n')
print('target',target,'BEP executions',len(live),'retained outputs',len(items))
if {e['id']['testResult'].get('shard') for e in live}!={1,2,3,4}: raise SystemExit('Missing actual shard')
for e in live:
    v=e['testResult']
    meta=v.get('executionInfo',{})
    if v.get('cachedLocally') or meta.get('cachedRemotely'): raise SystemExit('Cached test execution')
    print(e['id']['testResult'],v['status'],meta)
if len([i for i in items if re.fullmatch('logs/shard_[1-4]_of_4/test.log',i['path'])])!=4:
    raise SystemExit('Original shard logs incomplete')

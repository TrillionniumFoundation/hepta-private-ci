"""Audit physical evidence and result provenance only; do not rerun gates."""
from pathlib import Path
import gzip
import hashlib
import json
R=Path(__file__).resolve().parent
M=json.loads((R/'ARTIFACTS.json').read_bytes())
def identity(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
actual={str(p.relative_to(R)) for p in R.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
assert actual=={x['path'] for x in M['files']}|{'ARTIFACTS.json'}
for x in M['files']:
 b=(R/x['path']).read_bytes();assert identity(b)=={k:x[k] for k in ('bytes','sha256','blob')},x['path']
 if 'logical_original' in x:assert identity(gzip.decompress(b))==x['logical_original'],x['path']
for prefix,kind in [('version-qa/evidence/actual-attempt-01','version'),('version-qa/evidence/actual-attempt-02','version'),('cohort-qa/source-qa-attempt-01','cohort'),('cohort-qa/source-qa-attempt-02','cohort')]:
 p=R/prefix;d=json.loads((p/('result.json' if kind=='version' else 'RESULT.json')).read_bytes());assert identity((p/'source-qa.raw.log').read_bytes())==d['log' if kind=='version' else 'raw_log']
 a,b=('source-before.json','source-after.json') if kind=='version' else ('inputs.before.json','inputs.after.json');assert (p/a).read_bytes()==(p/b).read_bytes()
q1=json.loads((R/'version-qa/evidence/actual-attempt-01/result.json').read_bytes());q2=json.loads((R/'version-qa/evidence/actual-attempt-02/result.json').read_bytes())
assert (q1['tests_run'],q1['failures'],q1['errors'])==(57,3,0)
assert (q2['tests_run'],q2['failures'],q2['errors'])==(57,0,0)
c1=json.loads((R/'cohort-qa/source-qa-attempt-01/RESULT.json').read_bytes());c2=json.loads((R/'cohort-qa/source-qa-attempt-02/RESULT.json').read_bytes())
assert c1['tests']==154 and not c1['failures'] and len(c1['errors'])==2
assert c2['tests']==154 and not c2['failures'] and not c2['errors'] and not c2['skipped']
f=json.loads((R/'merged-lib-format/manifest.actual.json').read_bytes());assert f['returncode']==0 and not f['format_changed'] and f['files'][0]['before']==f['files'][0]['after']
p=json.loads((R/'PROGRESS.json').read_bytes());assert all(v==0 for v in p['qualification_counts'].values())
print(json.dumps({'status':'PACKAGE_BYTES_AND_OBSERVED_RESULTS_VERIFIED','indexed_files':len(M['files']),'physical_files':len(actual),'native_run_by_verifier':False,'source_gate_rerun':False,'qualification_added':0},indent=2))

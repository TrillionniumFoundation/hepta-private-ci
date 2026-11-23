from pathlib import Path
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
p=Path(__file__).resolve().parent
artifact=p/'original-musl-three-runs.zip'
sha=lambda x:hashlib.sha256(x).hexdigest()
expected='37d5dea14affc7c2c1c6dcda6887f411fcd3dccdaf950b72de3ddcdfabab0685'
case='suite::v2::app_list::list_apps_emits_updates_and_returns_after_both_lists_load'
assert sha(artifact.read_bytes())==expected
result=dict(repair_commit='b051b0c1a52f80bc85d7f0cbc8561e2668ac8075',verification_commit='1746341e25a04cf00d980d79b55e81a10e4bacd9',workflow_run=45113800491,workflow_job=137491893819,artifact_id=14790702718,artifact_sha256=expected,original_case=case,sharding_disabled=True,maximum_attempts_per_run=1,platform='x86_64-unknown-linux-musl',runs=[])
with zipfile.ZipFile(artifact) as z:
 assert set(z.namelist())=={f'run_{i}_of_3/test.{kind}' for kind in ('log','xml') for i in range(1,4)}
 for i in range(1,4):
  raw=z.read(f'run_{i}_of_3/test.log');log=raw.decode();xml=z.read(f'run_{i}_of_3/test.xml');t=ET.fromstring(xml).find('testsuite')
  pattern=r'test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; 1024 filtered out; finished in ([.0-9]+)s'
  m=re.findall(pattern,log);assert len(m)==1
  assert log.count('test '+case+' ... ok')==1 and 'running 1 test\n' in log
  assert t is not None and [t.get(k) for k in ('tests','failures','errors')]==['1','0','0']
  assert len(t.findall('testcase'))==1 and t.find('testcase').get('status')=='run'
  assert log.strip() in t.find('system-out').text
  result['runs'].append({'index':i,'individual_test_seconds':float(m[0]),'stdout_sha256':sha(raw),'xml_sha256':sha(xml)})
(p/'hosted_result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))

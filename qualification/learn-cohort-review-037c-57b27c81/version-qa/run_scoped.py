"""Run only the four requested suites against the physical actual-source overlay."""
import datetime
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parent
OVERLAY=ROOT/'overlay'
NAMES=(
 'test_evaluated_version_source_closure',
 'test_evaluated_published_read_source_closure',
 'test_evaluated_retention_source_closure',
 'test_retained_version_issuer_source_closure',
)
sys.dont_write_bytecode=True
sys.path.insert(0,str(OVERLAY/'qa/b4-no-bypass'))
attempt=sys.argv[1]
record=ROOT/'evidence'/attempt
assert not record.exists(),record
record.mkdir()
def identity(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def inventory():
 return [{'path':str(p.relative_to(OVERLAY)),**identity(p.read_bytes())} for p in sorted(OVERLAY.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
before=inventory();(record/'source-before.json').write_text(json.dumps(before,indent=2)+'\n')
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)) for name in NAMES)
assert suite.countTestCases()==57,suite.countTestCases()
start=datetime.datetime.now(datetime.timezone.utc).isoformat();tick=time.monotonic()
with (record/'source-qa.raw.log').open('w') as stream:
 result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
end=datetime.datetime.now(datetime.timezone.utc).isoformat();elapsed=time.monotonic()-tick
after=inventory();(record/'source-after.json').write_text(json.dumps(after,indent=2)+'\n')
assert before==after,'source mutations escaped temporary QA roots'
report={'status':'PASS' if result.wasSuccessful() else 'FAIL','suites':NAMES,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'start_utc':start,'end_utc':end,'seconds':elapsed,'source_unchanged':True,'inventory_count':len(before),'source_inventory_sha256':hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'registry':identity((OVERLAY/'CALLERS.toml').read_bytes()),'log':identity((record/'source-qa.raw.log').read_bytes()),'scope':'physical actual cohort postimages and exact a96 dependencies; four scoped source suites only','native':'UNRUN','ordinary_qualification':0}
(record/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
sys.exit(0 if result.wasSuccessful() else 1)

"""Run only the eight owned source QA suites; preserve every attempt."""
import datetime,hashlib,importlib,json,os,re,sys,tempfile,time,unittest
from pathlib import Path
R=Path(__file__).resolve().parent;O=R/'overlay';sys.dont_write_bytecode=True
sys.path.insert(0,str(O/'qa/b4-no-bypass'));tempfile.tempdir=str(R/'tmp')
names=[p.stem for p in sorted((R/'base/qa/b4-no-bypass').glob('*.py'))]
a=R/'evidence'/sys.argv[1];a.mkdir(exist_ok=False)
def meta(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def inv():return [{'path':str(p.relative_to(O)),**meta(p.read_bytes())} for p in sorted(O.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
before=inv();(a/'before.json').write_text(json.dumps(before,indent=2)+'\n')
s=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(n)) for n in names);count=s.countTestCases();assert count==59,count
started=datetime.datetime.now(datetime.timezone.utc).isoformat();t=time.monotonic()
with (a/'source-qa.raw.log').open('w') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2).run(s)
seconds=time.monotonic()-t;after=inv();(a/'after.json').write_text(json.dumps(after,indent=2)+'\n');assert before==after
result={'status':'PASS' if r.wasSuccessful() else 'FAIL','source':'57b27c81d0d5321b873ee751fd0e58e1d905b988','tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'seconds':seconds,'started_utc':started,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'suites':names,'log':meta((a/'source-qa.raw.log').read_bytes()),'input_count':len(before),'source_unchanged':True,'full_source_gate':False,'native':False,'qualification':0}
(a/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));sys.exit(0 if r.wasSuccessful() else 1)

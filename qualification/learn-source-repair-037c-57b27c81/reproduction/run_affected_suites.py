"""Run the 15 failed suites plus the two exact-tuple dependents together."""
from pathlib import Path
import ast,datetime,hashlib,importlib,json,shutil,sys,tempfile,time,unittest

sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent;O=R/'overlay';C=R.parent/'candidate-source-57b-qa-repair-v1'
tempfile.tempdir=str(R/'tmp');sys.path.insert(0,str(O/'qa/b4-no-bypass'))
def meta(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def inventory():return [{'path':str(p.relative_to(O)),**meta(p.read_bytes())} for p in sorted(O.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
own_names={p.name for p in (R/'work/qa/b4-no-bypass').glob('*.py')}
candidate_names={p.name for p in (C/'work/qa/b4-no-bypass').glob('*.py')}
assert len(own_names)==10 and len(candidate_names)==7 and not own_names&candidate_names
dependency_additions=[]
for p in sorted((C/'overlay').rglob('*')):
 if not p.is_file() or '__pycache__' in p.parts:continue
 rel=p.relative_to(C/'overlay');dest=O/rel;b=p.read_bytes()
 if rel.parts[0]=='qa' and p.name in own_names|candidate_names:continue
 if dest.exists():assert dest.read_bytes()==b,str(rel)
 else:dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b);dependency_additions.append({'path':str(rel),**meta(b)})
for name in sorted(candidate_names):
 rel=Path('qa/b4-no-bypass')/name;b=(C/'work'/rel).read_bytes();(O/rel).write_bytes(b);dest=R/'work'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
names=sorted(Path(n).stem for n in own_names|candidate_names)
run=R/'evidence'/sys.argv[1];run.mkdir(exist_ok=False)
(run/'dependency-additions.json').write_text(json.dumps(dependency_additions,indent=2)+'\n')
before=inventory();(run/'before.json').write_text(json.dumps(before,indent=2)+'\n')
s=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(n)) for n in names)
assert s.countTestCases()==147,s.countTestCases()
started=datetime.datetime.now(datetime.timezone.utc).isoformat();t=time.monotonic()
with (run/'source-qa.raw.log').open('w') as out:result=unittest.TextTestRunner(stream=out,verbosity=2).run(s)
seconds=time.monotonic()-t;after=inventory();(run/'after.json').write_text(json.dumps(after,indent=2)+'\n');assert after==before
record={'status':'PASS' if result.wasSuccessful() else 'FAIL','source':'57b27c81d0d5321b873ee751fd0e58e1d905b988','overlay':'Exact 57b product sources and verifier; only three actual registry additions and seventeen QA migrations.','registry':meta((O/'CALLERS.toml').read_bytes()),'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'seconds':seconds,'started_utc':started,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'suites':names,'log':meta((run/'source-qa.raw.log').read_bytes()),'inputs':len(before),'source_unchanged':True,'full_source_gate':False,'fullcaller':False,'native':False,'ordinary_qualification':0}
(run/'result.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2));sys.exit(0 if result.wasSuccessful() else 1)

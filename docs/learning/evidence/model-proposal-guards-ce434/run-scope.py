from pathlib import Path
import importlib.util,json,unittest,hashlib,subprocess,time,sys
root=Path('/workspace/scratch/learn-proposal-ce434-v2'); out=Path('/workspace/scratch/learn-proposal-ce434-guards-evidence-v1'); label=sys.argv[1]
assert not (out/(label+'.log')).exists()
files=sys.argv[2:] or ['test_resident_root_source_closure.py','test_resident_candidate_stage_source_closure.py','test_original_candidate_stage_source_closure.py','test_original_evaluation_host_source_closure.py','test_original_no_update_stage_source_closure.py','test_q24_model_proposal_source_closure.py']
suite=unittest.TestSuite()
for i,f in enumerate(files):
 file, _, selected = f.partition('::')
 spec=importlib.util.spec_from_file_location('model_guard_phase_'+str(i),root/'qa/b4-no-bypass'/file); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 if selected:
  cases=[cls(selected) for cls in vars(m).values() if isinstance(cls,type) and issubclass(cls,unittest.TestCase) and hasattr(cls,selected)];assert len(cases)==1;(suite.addTests(cases))
 else: suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(m))
start=time.monotonic()
with (out/(label+'.log')).open('w') as log: result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
b=(out/(label+'.log')).read_bytes();report={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'tree':subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=root,text=True).strip(),'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'seconds':time.monotonic()-start,'raw_bytes':len(b),'raw_sha256':hashlib.sha256(b).hexdigest(),'files':files,'working_tree':subprocess.check_output(['git','status','--short'],cwd=root,text=True)}
(out/(label+'.json')).write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report))
for t,e in result.failures+result.errors: print(str(t)[:200],e.splitlines()[-1][:320])
raise SystemExit(0 if result.wasSuccessful() else 1)

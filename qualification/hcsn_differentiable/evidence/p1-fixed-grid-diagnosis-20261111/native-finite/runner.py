import hashlib,json,os,platform,resource,sys,time,unittest
from pathlib import Path
t0,c0=time.perf_counter(),time.process_time()
import torch,numpy,mpmath
torch.set_num_threads(1)
manifest=json.loads(Path("SOURCE-MANIFEST.json").read_text())
def hashes():
 return {r["path"]:hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() for r in manifest["files"]}
before=hashes()
assert before=={r["path"]:r["sha256"] for r in manifest["files"]}
suite=unittest.defaultTestLoader.loadTestsFromName("qualification.hcsn_differentiable.tests.test_training_domain_finite")
result=unittest.TextTestRunner(verbosity=2,stream=sys.stdout).run(suite)
report={"schema":"hcsn-integrated-finite-test-v1","base_head":manifest["base_head"],"source_before":before,"source_after":hashes(),"tests_run":result.testsRun,"errors":len(result.errors),"failures":len(result.failures),"skipped":len(result.skipped),"passed":result.wasSuccessful(),"python":sys.version,"torch":torch.__version__,"numpy":numpy.__version__,"mpmath":mpmath.__version__,"platform":platform.platform(),"wall_seconds":time.perf_counter()-t0,"cpu_seconds":time.process_time()-c0,"max_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,"threads":torch.get_num_threads(),"scope":"Full finite-schedule test module against complete hashed import closure, not full repository CI or trained-state qualification","scientific_admission":"HOLD"}
Path("RESULT.json").write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n")
print(json.dumps(report,sort_keys=True))
sys.exit(not result.wasSuccessful())

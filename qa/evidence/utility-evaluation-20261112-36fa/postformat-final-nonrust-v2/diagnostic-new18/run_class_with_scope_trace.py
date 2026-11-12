from pathlib import Path
import hashlib,importlib,json,sys,unittest
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here/"partial_source/qa/b4-no-bypass"))
module=importlib.import_module("test_evaluated_published_read_source_closure")
cls=module.EvaluatedOrdinaryRetainedClosureTests
original=cls.actual_scopes
calls=[];covered=set()
def key(path,guard):return path+"::"+json.dumps(guard["selector"],sort_keys=True,separators=(",",":"))
expected={key(path,guard) for path,guards in module.ORDINARY_SCOPE_GUARDS.items() for guard in guards}
def observed(self,path,source):
 row={"path":path,"source_sha256":hashlib.sha256(source.encode()).hexdigest(),"exact_actual_source":source==(module.ROOT/path).read_text(),"scopes":[key(path,g) for g in module.ORDINARY_SCOPE_GUARDS.get(path,())],"status":"started"}
 calls.append(row)
 try:
  value=original(self,path,source)
 except BaseException as error:
  row.update(status="raised",error_type=type(error).__name__)
  raise
 else:
  row["status"]="returned"
  if row["exact_actual_source"]:covered.update(row["scopes"])
  return value
cls.actual_scopes=observed
result=None
try:
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(cls)
 assert suite.countTestCases()==18
 result=unittest.TextTestRunner(verbosity=2).run(suite)
finally:
 cls.actual_scopes=original
 payload={"format":"hepta-new18-transparent-actual-scope-observation-v2","qualification":False,"instrumentation":"Same actual_scopes function; one wrapper forwards every argument, return and exception; after successful original return records guard identities for byte-identical actual input. No verification verdict or source cache.","expected_paths":len(module.ORDINARY_SCOPE_GUARDS),"expected_scope_count":len(expected),"observed_complete_actual_scope_count":len(covered),"all_actual_scopes_observed":covered==expected,"missing_actual_scopes":sorted(expected-covered),"unexpected_scopes":sorted(covered-expected),"class_restored_to_original_function":cls.actual_scopes is original,"calls":calls,"tests_run":None if result is None else result.testsRun,"test_result_successful":None if result is None else result.wasSuccessful()}
 (here/"ACTUAL_SCOPE_COVERAGE.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
raise SystemExit(0 if result is not None and result.wasSuccessful() and covered==expected else 1)

import json,sys,time,unittest
from pathlib import Path
out=Path(sys.argv[1])
class Recording(unittest.TextTestResult):
    def __init__(self,*a,**k):super().__init__(*a,**k);self.cases=[]
    def addSuccess(self,test):super().addSuccess(test);self.cases.append({'id':test.id(),'status':'passed'})
    def addFailure(self,test,err):super().addFailure(test,err);self.cases.append({'id':test.id(),'status':'failure'})
    def addError(self,test,err):super().addError(test,err);self.cases.append({'id':test.id(),'status':'error'})
    def addSkip(self,test,reason):super().addSkip(test,reason);self.cases.append({'id':test.id(),'status':'skipped','reason':reason})
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err is not None:self.cases.append({'id':test.id(),'subtest':str(subtest),'status':'subtest_failure' if issubclass(err[0],test.failureException) else 'subtest_error'})
start=time.monotonic()
suite=unittest.TestLoader().discover('qa/b4-no-bypass',pattern='test_*source_closure.py')
expected=suite.countTestCases()
if expected != 423: raise RuntimeError('frozen full source-suite method inventory changed')
result=unittest.TextTestRunner(verbosity=2,resultclass=Recording).run(suite)
summary={'expected_methods':expected,'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'elapsed_seconds':time.monotonic()-start,'passed':result.wasSuccessful(),'cases':result.cases}
(out/'source-suite.json').write_text(json.dumps(summary,indent=2)+'\n')
raise SystemExit(0 if result.wasSuccessful() and result.testsRun==expected and not result.skipped else 1)

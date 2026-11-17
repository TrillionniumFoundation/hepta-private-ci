"""Offline CPU engineering entry; never a real research job."""
import argparse,hashlib,json,os,sys,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
WORKSPACE=Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
RUNTIME=Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
HELPERS=WORKSPACE/"e1e2-operation-helpers-04"
SOURCE=WORKSPACE/"candidate-qwen-03"
def verify():
    manifest=json.loads((ROOT/"ENGINEERING_SOURCE_MANIFEST.json").read_text())
    for name,item in manifest["files"].items():
        path=ROOT/name
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest()==item["sha256"],name
        assert path.stat().st_size==item["bytes"],name
    return manifest
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite",choices=("behavior","tensor"),required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--case")
    args=parser.parse_args()
    assert args.output.is_relative_to(ROOT) and args.output==args.output.resolve()
    assert os.environ.get("CUDA_VISIBLE_DEVICES")==""
    assert os.environ.get("HF_HUB_OFFLINE")==os.environ.get("TRANSFORMERS_OFFLINE")=="1"
    assert Path(sys.executable)==RUNTIME/"venv/bin/python"
    assert sys.flags.isolated and sys.dont_write_bytecode
    manifest=verify()
    sys.path.insert(0,str(ROOT))
    import research_sft_contract_v1 as contract
    h=contract.bind_helpers(HELPERS)
    h.io.workspace_guard(WORKSPACE,ROOT,SOURCE,HELPERS,args.output)
    sources=h.io.read(WORKSPACE/"operations/QWEN_SOURCE_02.json",h.io.SOURCE_MANIFEST_SHA)
    h.io.verify_inventory(SOURCE,sources["files"],exact=True)
    h.io.bootstrap(SOURCE)
    h.io.runtime_guard(RUNTIME,h.io.read(WORKSPACE/"probe-qwen-parent-03/RUNTIME.json"))
    import research_sft_execution_v1 as worker
    import run_research_sft_v1 as runner
    worker.configure(HELPERS);runner.configure(HELPERS)
    os.environ["RESEARCH_ENGINEERING_OUTPUT"]=str(args.output)
    module,cls,count=(("test_research_sft_v1","ResearchBehaviorTests",12) if args.suite=="behavior"
                      else ("test_research_sft_tensor_v1","ResearchTensorTests",1))
    name=module+"."+cls+("."+args.case if args.case else "")
    suite=unittest.defaultTestLoader.loadTestsFromName(name)
    assert suite.countTestCases()==(1 if args.case else count)
    observed=[]
    class Recorded(unittest.TextTestResult):
        def addSuccess(self,test):
            super().addSuccess(test);observed.append({"test":test.id(),"status":"PASS"})
        def addFailure(self,test,error):
            super().addFailure(test,error);observed.append({"test":test.id(),"status":"FAIL"})
        def addError(self,test,error):
            super().addError(test,error);observed.append({"test":test.id(),"status":"ERROR"})
        def addSkip(self,test,reason):
            super().addSkip(test,reason);observed.append({"test":test.id(),"status":"SKIP","reason":reason})
    before=h.io.usage()
    result=unittest.TextTestRunner(verbosity=2,resultclass=Recorded).run(suite)
    verify()
    report=h.io.sealed({
        "schema":"hepta.research-sft-engineering-result.v1","suite":args.suite,
        "tests_run":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
        "skipped":len(result.skipped),"passed":result.wasSuccessful() and not result.skipped,
        "cases":observed,"source_manifest_sha256":h.io.file_hash(ROOT/"ENGINEERING_SOURCE_MANIFEST.json"),
        "source_files":manifest["files"],"cost":h.io.cost(before),"cuda_visible_devices":"",
        "torch_imported":"torch" in sys.modules,"tensor_library_missing_is_not_pass":True,
        "real_research_fits":0,"real_model_generations":0,"actual_authored_verifier_calls":0,
        "pretrained_model_loaded":False,"synthetic_receipts_are_not_experiment_evidence":True,
        "cpu_tensor_fixture_expected":args.suite=="tensor","automatic_retry":False,
        "completed_at_ns":time.time_ns(),**contract.SCOPE})
    h.io.write_new(args.output/"RESULT.json",report)
    print(h.io.canonical({k:report[k] for k in ("suite","tests_run","failures","errors","skipped","passed")}).decode(),flush=True)
    return 0 if report["passed"] else 1
if __name__=="__main__":
    raise SystemExit(main())

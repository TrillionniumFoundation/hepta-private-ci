"""Own bounded offline CPU engineering children. No actual Qwen launch."""
import argparse,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PYTHON="/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python"
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    with path.open("xb") as stream:
        stream.write(json.dumps(value,sort_keys=True,allow_nan=False,indent=2).encode()+b"\n")
        stream.flush();os.fsync(stream.fileno())
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id",required=True)
    p.add_argument("--suite",choices=("both","behavior","tensor"),default="both")
    p.add_argument("--case")
    args=p.parse_args()
    assert args.run_id.isascii() and args.run_id.isalnum() and len(args.run_id)<=16
    assert args.case is None or (args.suite!="both" and args.case.startswith("test_") and args.case.isidentifier())
    assert str(Path(sys.executable))==PYTHON and sys.flags.isolated and sys.dont_write_bytecode
    assert ROOT.parent==Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
    assert ROOT.name=="research-sft-v1-engineering-01"
    output=ROOT/("engineering-results-"+args.run_id);output.mkdir(exist_ok=False)
    manifest_path=ROOT/"ENGINEERING_SOURCE_MANIFEST.json"
    manifest=json.loads(manifest_path.read_text())
    for name,item in manifest["files"].items():
        assert sha(ROOT/name)==item["sha256"] and (ROOT/name).stat().st_size==item["bytes"]
    env={**os.environ,"CUDA_VISIBLE_DEVICES":"","HF_HUB_OFFLINE":"1","TRANSFORMERS_OFFLINE":"1",
         "HF_HUB_DISABLE_TELEMETRY":"1","TOKENIZERS_PARALLELISM":"false",
         "OMP_NUM_THREADS":"2","OPENBLAS_NUM_THREADS":"2","MKL_NUM_THREADS":"2"}
    before=time.time_ns()
    write(output/"STARTED.json",{"schema":"hepta.research-sft-engineering-operation.v1",
        "started_at_ns":before,"source_manifest_sha256":sha(manifest_path),
        "suite":args.suite,"case":args.case,"python":PYTHON,"child_timeout_seconds":300,
        "automatic_retry":False,"cuda_visible_devices":"","offline":True,
        "actual_research_work_authorized":False})
    rows=[]
    for suite in (("behavior","tensor") if args.suite=="both" else (args.suite,)):
        d=output/suite;d.mkdir()
        command=[PYTHON,"-I","-B",str(ROOT/"engineering_entry_v1.py"),"--suite",suite,"--output",str(d)]
        if args.case:command+=["--case",args.case]
        write(d/"LAUNCH.json",{"argv":command,"timeout_seconds":300,
                              "started_at_ns":time.time_ns(),"automatic_retry":False})
        with (d/"stdout.log").open("xb") as stdout,(d/"stderr.log").open("xb") as stderr:
            process=subprocess.Popen(command,stdout=stdout,stderr=stderr,env=env,start_new_session=True)
            timed_out=False
            try:process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                timed_out=True;os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
            except BaseException:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
                raise
        row={"suite":suite,"pid":process.pid,"exit_code":process.returncode,"timed_out":timed_out,
             "stdout_sha256":sha(d/"stdout.log"),"stderr_sha256":sha(d/"stderr.log"),
             "completed_at_ns":time.time_ns(),
             "result_sha256":sha(d/"RESULT.json") if (d/"RESULT.json").is_file() else None}
        write(d/"EXIT.json",row);rows.append(row);print(json.dumps(row,sort_keys=True),flush=True)
    for name,item in manifest["files"].items():assert sha(ROOT/name)==item["sha256"]
    complete=all(row["exit_code"]==0 and not row["timed_out"] and row["result_sha256"] for row in rows)
    write(output/"RESULT.json",{"status":"CPU_ENGINEERING_COMPLETE" if complete else "CPU_ENGINEERING_FAILED_PRESERVED",
        "source_manifest_sha256":sha(manifest_path),"children":rows,"real_research_fits":0,
        "real_model_generations":0,"gpu_used":False,"pretrained_model_loaded":False,
        "automatic_retry":False,"started_at_ns":before,"completed_at_ns":time.time_ns()})
    print(json.dumps({"output":str(output),"passed":bool(complete)},sort_keys=True),flush=True)
    return 0 if complete else 1
if __name__=="__main__":
    raise SystemExit(main())

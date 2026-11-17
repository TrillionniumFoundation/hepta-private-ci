"""Postrun OS-pipe recheck of the already executed frozen wrapper notification."""
from pathlib import Path
import ast,hashlib,json,os,types,time
ROOT=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
P=ROOT/"parent03-preparation-01/launch_qwen_parent03_owned.py"
def main():
 raw=P.read_bytes();assert hashlib.sha256(raw).hexdigest()=="c23067f8109e1dce9260331b46ddf3681b7135e26fc95d07c85d11456e544398"
 node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=="notify")
 reader,writer=os.pipe()
 namespace={"os":os,"json":json,"sys":types.SimpleNamespace(stdout=types.SimpleNamespace(fileno=lambda:writer))}
 exec(compile(ast.Module(body=[node],type_ignores=[]),str(P),"exec"),namespace)
 namespace["notify"]({"test":"readable"})
 assert os.read(reader,4096)==b'{"test": "readable"}\n'
 os.close(reader)
 namespace["notify"]({"test":"closed reader"})
 os.close(writer)
 report={"schema":"hepta.qwen-owned-notify-postrun-engineering.v3","status":"PASS","created_at_ns":time.time_ns(),"wrapper_sha256":hashlib.sha256(raw).hexdigest(),"test_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"real_readable_pipe_checked":True,"real_closed_pipe_checked":True,"raised_to_caller":False,"postrun_recheck":True,"original_local_stdout_receipt_recovered":False,"model_calls":0,"child_processes_started":0,"original_files_modified":False}
 out=ROOT/"parent03-preparation-01/OWNED_NOTIFY_POSTRUN_RECHECK.json"
 with out.open("x") as f:json.dump(report,f,sort_keys=True,separators=(",",":"));f.write("\n")
 print(json.dumps(report))
if __name__=="__main__":main()

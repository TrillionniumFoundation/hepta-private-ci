import json,pathlib,subprocess
root=pathlib.Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
rows=[]
for pid in (45883,89193):
 result=subprocess.run(["/bin/ps","-p",str(pid),"-o","pid=,ppid=,pgid=,lstart=,etime=,comm="],capture_output=True,timeout=10)
 rows.append({"pid":pid,"exit_code":result.returncode,"stdout":result.stdout.decode(),"stderr":result.stderr.decode()})
result=subprocess.run(["/opt/homebrew/bin/python3","-I","-B",str(root/"operations/observe_research_run_02.py"),"--label","38"],capture_output=True,timeout=50)
value={"mac_owned_transport_observations":rows,"fresh_readback_exit":result.returncode,"fresh_readback_stdout":result.stdout.decode(),"fresh_readback_stderr":result.stderr.decode(),"new_model_or_training_calls":0,"no_process_signals":True}
path=root/"operations/RESEARCH02_CONTROLLER_LOSS_READBACK_01.json"
with path.open("x") as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write("\n")
print(json.dumps(value,sort_keys=True))

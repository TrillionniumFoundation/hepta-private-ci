import pathlib,os,json,time,ast
pid=2228309
base=pathlib.Path("/proc")/str(pid)
report={"schema":"hepta.bounded-process-identity-observation.v1","pid":pid,"observed_at_ns":time.time_ns(),"environment_read":False,"inline_code_retained":False,"signals_sent":False}
try:
 raw=(base/"stat").read_text();fields=raw.rsplit(")",1)[1].split()
 report.update(state=fields[0],ppid=int(fields[1]),process_group_id=int(fields[2]),session_id=int(fields[3]),start_time_ticks=int(fields[19]),clock_ticks_per_second=os.sysconf("SC_CLK_TCK"),cwd=os.readlink(base/"cwd"))
 args=(base/"cmdline").read_bytes().split(b"\0")
 text=[v.decode("utf-8","replace") for v in args if v]
 report["executable"]=text[0] if text else None
 report["invocation_mode"]="inline_python" if "-c" in text else "python_module" if "-m" in text else "script_or_other"
 allowed=("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/","/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/")
 candidates=[v for v in text[1:] if v.startswith(allowed) and v.endswith(".py") and len(v)<1024 and "\n" not in v]
 if "-c" in text:
  ix=text.index("-c")
  if ix+1<len(text) and len(text[ix+1].encode())<=65536:
   try:
    tree=ast.parse(text[ix+1])
    candidates.extend(node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.startswith(allowed) and node.value.endswith(".py") and len(node.value)<1024 and "\n" not in node.value)
   except (SyntaxError,ValueError,RecursionError):report["inline_path_parse"]="unavailable"
 report["task_script_paths"]=sorted(set(candidates))
except FileNotFoundError:
 report["state"]="not_present_at_observation"
print(json.dumps(report,sort_keys=True))

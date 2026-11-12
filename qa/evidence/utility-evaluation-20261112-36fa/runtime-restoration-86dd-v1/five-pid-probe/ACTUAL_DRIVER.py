import datetime,json,os,sys
from pathlib import Path
PIDS={1856522:"cargo",1858250:"rustc",1858427:"rustc",1858461:"rustc",1858469:"rustc"}
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def one(pid,expected):
 p=Path("/proc")/str(pid);r={"pid_reference":pid,"original_comm":expected,"observed_at":stamp()}
 try:
  raw=(p/"stat").read_text();end=raw.rfind(")");fields=raw[end+2:].split();r.update(comm=raw[raw.find("(")+1:end],state=fields[0],ppid=int(fields[1]),startticks=int(fields[19]))
  lines=(p/"status").read_text().splitlines();uids=next(x for x in lines if x.startswith("Uid:")).split()[1:];r["uids"]=[int(x) for x in uids]
  if r["uids"][0]!=1000:
   r["observation"]="current_uid_differs; no further metadata read";return r
  for name in ("cwd","exe"):
   try:r[name]=os.readlink(p/name)
   except OSError as e:r[name+"_error"]={"type":type(e).__name__,"errno":e.errno}
  try:r["cgroup"]=(p/"cgroup").read_text()
  except OSError as e:r["cgroup_error"]={"type":type(e).__name__,"errno":e.errno}
  try:
   later=(p/"stat").read_text();tail=later[later.rfind(")")+2:].split();r["after"]={"state":tail[0],"ppid":int(tail[1]),"startticks":int(tail[19])};r["startticks_stable_during_probe"]=r["startticks"]==r["after"]["startticks"]
  except OSError as e:r["after_error"]={"type":type(e).__name__,"errno":e.errno}
  r["observation"]="current_pid_metadata_only"
 except FileNotFoundError:r["observation"]="pid_disappeared_during_or_before_probe"
 except (OSError,ValueError,IndexError,StopIteration) as e:r.update(observation="metadata_read_error",error_type=type(e).__name__,errno=getattr(e,"errno",None))
 return r
started=stamp();rows=[one(pid,comm) for pid,comm in PIDS.items()]
print(json.dumps({"format":"hepta-runtime-blocking-five-pids-readonly-probe-v1","started_at":started,"finished_at":stamp(),"operator_uid":os.getuid(),"clock_ticks_per_second":os.sysconf("SC_CLK_TCK"),"source_process_preflight_blob":"f93f03b5b195ba56c196242b4cfc1f9d5b882215","source_failure_result_blob":"88be32de12e28d39b685a7812bff9e217d4a192a","processes":rows,"scope":"Only five previously observed PID references; no args/env, signals, external-task waits, source/material/cache reads or writes; earlier PID startticks were not captured, so identity continuity since the original preflight is not asserted.","main_restoration_retried":False,"cargo_or_tests_started":False,"qualification":False},sort_keys=True,indent=2),flush=True)

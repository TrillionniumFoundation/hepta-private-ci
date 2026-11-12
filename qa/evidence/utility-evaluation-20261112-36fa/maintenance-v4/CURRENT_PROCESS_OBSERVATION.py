import os,pathlib,json,datetime,signal,time

def timed_out(signum,frame):
    raise TimeoutError("bounded current process observation")
signal.signal(signal.SIGALRM,timed_out)
signal.alarm(30)

def active_build_processes():
    active=[];unreadable=[]
    for item in pathlib.Path("/proc").iterdir():
        if not item.name.isdecimal():continue
        try:
            name=(item/"comm").read_text().strip()
            if name not in ("cargo","cargo-clippy","clippy-driver","rustc","rustfmt","just","uv","ruff"):
                continue
            status=(item/"status").read_text()
            uid_line=next(x for x in status.splitlines() if x.startswith("Uid:"))
            uid=int(uid_line.split()[1])
            if uid!=os.getuid():continue
            active.append({"pid":int(item.name),"comm":name,"uid":uid})
        except FileNotFoundError:
            continue
        except (OSError,StopIteration,ValueError) as error:
            unreadable.append({"pid":int(item.name),"error":type(error).__name__})
    return {"active_matching_processes":active,"unreadable_matching_processes":unreadable,
            "scope":"Same-UID process names only; no environment/argument values or credentials inspected; no processes killed."}

def detail(pid):
    p=pathlib.Path("/proc")/str(pid)
    def once():
        raw=(p/"stat").read_text(); end=raw.rfind(") "); fields=raw[end+2:].split()
        status=(p/"status").read_text()
        uids=[int(x) for x in next(x for x in status.splitlines() if x.startswith("Uid:")).split()[1:]]
        return {"pid":pid,"state":fields[0],"ppid":int(fields[1]),"startticks":int(fields[19]),"uids":uids,"comm":(p/"comm").read_text().strip(),"exe":os.readlink(p/"exe"),"cwd":os.readlink(p/"cwd"),"cgroup":(p/"cgroup").read_text()}
    try:
        first=once(); second=once()
        keys=("pid","ppid","startticks","uids","comm","exe","cwd","cgroup")
        return {"first":first,"second":second,"identity_stable":all(first[k]==second[k] for k in keys)}
    except Exception as e:
        result={"pid":pid,"metadata_error":type(e).__name__,"metadata_error_text":str(e),"classification":"unknown"}
        try:
            raw=(p/"stat").read_text();end=raw.rfind(") ");fields=raw[end+2:].split()
            result["stat_still_exists"]={"state":fields[0],"startticks":int(fields[19])}
        except FileNotFoundError:
            result["classification"]="gone_at_recheck"
        except Exception as x:
            result["stat_recheck_error"]=type(x).__name__
        return result

result={"format":"hepta-current-maintenance-concurrency-readonly-v1","started_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"historical_job":"1a1d15cdf42-2564-1c3a","historical_pid_array_retained":False,"scope":"New current process observation only; it does not identify the original 20:04 failure PIDs. No args, environment, foreign source files, process control, Cargo, or source writes.","uid":os.getuid()}
try:
    observed=active_build_processes()
    result["current_guard_observation"]=observed
    active=observed["active_matching_processes"]
    result["metadata_details"]=[detail(row["pid"]) for row in active[:64]]
    result["metadata_details_truncated"]=len(active)>64
    result["current_original_guard_would_accept"]=not active and not observed["unreadable_matching_processes"]
    result["status"]="read_only_observation_complete"
except Exception as error:
    result["error"]=repr(error);result["status"]="read_only_observation_failed"
finally:
    signal.alarm(0)
    result["finished_at"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(json.dumps(result,sort_keys=True,indent=2),flush=True)
raise SystemExit(0 if result["status"]=="read_only_observation_complete" else 1)

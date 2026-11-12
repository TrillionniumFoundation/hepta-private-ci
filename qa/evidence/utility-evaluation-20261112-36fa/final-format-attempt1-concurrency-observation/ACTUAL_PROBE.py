import os,pathlib,json,datetime,signal

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


result={"format":"hepta-finalfmt-current-concurrency-readonly-v1","started_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"historical_job":"1a1d1c33b57-2564-1c77","historical_process_pin":{"bytes":226,"sha256":"0d482b0daec3e2d12b617e6e3bf61bc043fa96ca40b7f1be29aba8cc89fdbbb8","git_blob":"1938147d303b32ebb174fec6a6d2952aedfe8f9e"},"scope":"Current original-guard proc comm/UID only. No args, environment, metadata detail, source, process control, Cargo or source writes. Does not infer historical process continuity or task completion.","uid":os.getuid()}
try:
    observed=active_build_processes()
    result["current_guard_observation"]=observed
    result["current_original_guard_would_accept"]=not observed["active_matching_processes"] and not observed["unreadable_matching_processes"]
    result["status"]="read_only_observation_complete"
except Exception as error:
    result["error"]=repr(error);result["status"]="read_only_observation_failed"
finally:
    signal.alarm(0)
    result["finished_at"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(json.dumps(result,sort_keys=True,indent=2),flush=True)
raise SystemExit(0 if result["status"]=="read_only_observation_complete" else 1)

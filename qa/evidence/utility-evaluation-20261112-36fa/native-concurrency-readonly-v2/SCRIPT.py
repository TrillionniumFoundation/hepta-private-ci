import os
import pathlib
import json
import datetime

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


assert os.getuid() == os.geteuid() == 1000
started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
observed = active_build_processes()
print(json.dumps({"format": "hepta-original-global-concurrency-readonly-v1", "started_at": started_at, "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "original_guard_observation": observed, "qualification": False, "commands_or_writes_or_signals": False, "native_or_restore_dispatched": False}, sort_keys=True))

import hashlib,json,os,subprocess,time
from pathlib import Path
JOB="1a1ad12b87d-fc05-5860"
UNIT="hepta-runtime-job-"+JOB+".service"
INVOCATION="bbdf19f871bc45bb87164d5954a434f6"
ORIGINAL_PID=548793
OUT=Path("/home/qian-qi/work/hepta-joint-h1-owned-release-20261105-93bfc-01.json")
properties=["Id","LoadState","ActiveState","SubState","ControlGroup","MainPID","ExecMainPID","ExecMainCode","ExecMainStatus","Result","InvocationID"]
argv=["systemctl","--user","show",UNIT,"--no-pager","--property="+",".join(properties)]
started=time.monotonic_ns()
result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20,check=False)
raw=result.stdout
if len(raw)>65536 or len(result.stderr)>65536:
    raise ValueError("unexpected oversized systemd observation")
fields={}
for line in raw.decode().splitlines():
    if "=" in line:
        key,value=line.split("=",1)
        fields[key]=value
failures=[]
terminal=(fields.get("LoadState")=="not-found" and fields.get("ActiveState")=="inactive") or (
    fields.get("LoadState")=="loaded" and fields.get("ActiveState") in ("inactive","failed")
    and fields.get("SubState") in ("dead","failed","exited"))
if not terminal:
    failures.append("exact systemd unit is not proven terminal")
if fields.get("InvocationID") and fields["InvocationID"]!=INVOCATION:
    failures.append("systemd invocation differs from observed original invocation")
fallback="/user.slice/user-1000.slice/user@1000.service/app.slice/"+UNIT
paths={fallback}
if fields.get("ControlGroup"):
    observed=fields["ControlGroup"]
    if not observed.startswith("/") or Path(observed).name!=UNIT or ".." in Path(observed).parts:
        raise ValueError("unexpected exact unit ControlGroup")
    paths.add(observed)
groups=[]
for relative in sorted(paths):
    group=Path("/sys/fs/cgroup"+relative)
    exists=group.exists()
    actual_files=[]
    pids=set()
    if exists:
        targets=set([group/"cgroup.procs",*group.glob("**/cgroup.procs")])
        if (group/"cgroup.events").exists():
            targets.add(group/"cgroup.events")
        for path in sorted(targets):
            try:
                data=path.read_bytes()
            except FileNotFoundError:
                actual_files.append(dict(path=str(path),disappeared_during_snapshot=True))
                continue
            if len(data)>1024*1024:
                raise ValueError("oversized owned cgroup metadata")
            actual_files.append(dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),text=data.decode()))
            if path.name=="cgroup.procs":
                pids.update(int(value) for value in data.split())
    if pids:
        failures.append("owned descendants still listed in exact cgroup")
    groups.append(dict(path=str(group),exists=exists,owned_pids=sorted(pids),actual_files=actual_files))
proc=Path("/proc")/str(ORIGINAL_PID)
try:
    proc_raw=(proc/"stat").read_text()
    columns=proc_raw.rpartition(")")[2].split()
    root_observation=dict(pid=ORIGINAL_PID,present=True,state=columns[0],parent_pid=int(columns[1]),start_ticks=columns[19])
    failures.append("original ExecMainPID number still exists; no start-tick identity was supplied")
except FileNotFoundError:
    root_observation=dict(pid=ORIGINAL_PID,present=False)
document=dict(schema="hepta-H1-exact-owned-unit-release-observation-v1",job_id=JOB,expected_unit=UNIT,
    expected_original_invocation=INVOCATION,observed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
    systemctl=dict(command=argv,exit_code=result.returncode,elapsed_ns=time.monotonic_ns()-started,fields=fields,
        stdout=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),text=raw.decode()),
        stderr=dict(bytes=len(result.stderr),sha256=hashlib.sha256(result.stderr).hexdigest(),text=result.stderr.decode())),
    exact_cgroups=groups,original_root_process=root_observation,owned_processes_clear=not failures,
    failures=failures,mutations_performed=False,processes_killed=False,cargo_or_cost_or_compression_started=False,
    scope="only the exact previously observed runtime unit, its reported and known user cgroup paths, nested cgroup.procs, and the original ExecMainPID number")
data=(json.dumps(document,indent=2,sort_keys=True)+"\n").encode()
with OUT.open("xb") as stream:
    stream.write(data)
print(json.dumps(dict(path=str(OUT),bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),owned_processes_clear=document["owned_processes_clear"],failures=failures,systemd=fields,cgroups=[dict(path=x["path"],exists=x["exists"],owned_pids=x["owned_pids"]) for x in groups],original_root_process=root_observation)),flush=True)
raise SystemExit(0 if document["owned_processes_clear"] else 1)

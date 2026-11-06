#!/usr/bin/env python3
import hashlib, json, os, time
from pathlib import Path
BASE=Path("/home/qian-qi/work/chain-joint-20261105-93bfc-w1-native-C4")
COMMIT="8df4b21d893906570d48f5beafabb3b31e0aefbc"
TREE="6f5aaa2af0432e27e24b6bd2ad18013ab4423d14"
OUTPUT=BASE/"C4-cost-window-release.json"
phases=[("collector","1a1acdb5dc1-fc05-5751"),("legal-v3","1a1acdfc3c9-fc05-5767"),("reused-v3","1a1ad02a53b-fc05-5805"),("false-trace-full-limb","1a1ad0f6922-fc05-5850")]
rows=[]
failures=[]
for phase,job in phases:
    manifest_path=BASE/phase/"manifest.json"
    raw=manifest_path.read_bytes()
    manifest=json.loads(raw)
    if (manifest.get("commit"),manifest.get("tree"),manifest.get("passed"))!=(COMMIT,TREE,True):
        failures.append(phase+": manifest not exact passed C4")
    identity=manifest.get("runtime_process")
    suffix="/user.slice/user-1000.slice/user@1000.service/app.slice/hepta-runtime-job-"+job+".service"
    if identity:
        lines=identity["cgroup"].splitlines()
        observed=[line.split(":",2)[2] for line in lines if line.startswith("0::")]
        if observed!=[suffix]:
            raise ValueError("recorded cgroup differs from exact durable unit")
    group=Path("/sys/fs/cgroup"+suffix)
    exists=group.exists()
    pids=set()
    if exists:
        for file in set([group/"cgroup.procs",*group.glob("**/cgroup.procs")]):
            if file.exists():
                pids.update(int(value) for value in file.read_text().split())
    matching_root=False
    root_observation=None
    if identity:
        proc=Path("/proc")/str(identity["pid"])
        try:
            fields=(proc/"stat").read_text().rpartition(")")[2].split()
            matching_root=fields[19]==str(identity["start_ticks"])
            root_observation=dict(pid=identity["pid"],observed_start_ticks=fields[19],expected_start_ticks=str(identity["start_ticks"]),same_identity=matching_root)
        except FileNotFoundError:
            root_observation=dict(pid=identity["pid"],identity_absent=True)
    if pids or matching_root:
        failures.append(phase+": owned process still present")
    rows.append(dict(phase=phase,job_id=job,manifest_sha256=hashlib.sha256(raw).hexdigest(),
        manifest_passed=manifest.get("passed"),completed_utc=manifest.get("completed_utc"),
        exact_owned_cgroup=str(group),cgroup_exists=exists,owned_descendant_pids=sorted(pids),
        runtime_process=identity,root_observation=root_observation,
        source_before=manifest.get("source_before"),source_after=manifest.get("source_after")))
result=dict(schema="trnm-c4-cost-window-owned-process-release-v1",observed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
    source_commit=COMMIT,source_tree=TREE,phases=rows,failures=failures,released=not failures,
    scope="exact previously owned runtime cgroups, including child cgroups, and recorded coordinator PID/start-tick identities; no processes killed",
    later_native_started=False,large_raw_archive_compression_started=False)
raw=(json.dumps(result,indent=2,sort_keys=True)+"\n").encode()
with OUTPUT.open("xb") as stream:
    stream.write(raw)
print(json.dumps(dict(path=str(OUTPUT),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),released=result["released"],failures=failures,
    phases=[dict(phase=x["phase"],cgroup_exists=x["cgroup_exists"],owned_descendant_pids=x["owned_descendant_pids"],root_observation=x["root_observation"]) for x in rows])),flush=True)
raise SystemExit(0 if result["released"] else 1)

import hashlib
import json
import subprocess
import time
from pathlib import Path

JOB = "1a1add12f68-fc05-5aec"
UNIT = "hepta-runtime-job-" + JOB + ".service"
INVOCATION = "66c7afe0c13c4bdc93017184de2d96e6"
ORIGINALS = (("ExecMainPID", 1083983, None),)
OUT = Path("/home/qian-qi/work/hepta-h3-archive-owned-release-20261105-93bfc-01.json")
properties = ["Id", "LoadState", "ActiveState", "SubState", "ControlGroup", "MainPID",
              "ExecMainPID", "ExecMainCode", "ExecMainStatus", "Result", "InvocationID"]
argv = ["systemctl", "--user", "show", UNIT, "--no-pager", "--property=" + ",".join(properties)]
started = time.monotonic_ns()
result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
if len(result.stdout) > 65536 or len(result.stderr) > 65536:
    raise ValueError("unexpected oversized systemd observation")
fields = dict(line.split("=", 1) for line in result.stdout.decode().splitlines() if "=" in line)
failures = []
terminal = (fields.get("LoadState") == "not-found" and fields.get("ActiveState") == "inactive") or (
    fields.get("LoadState") == "loaded" and fields.get("ActiveState") in ("inactive", "failed")
    and fields.get("SubState") in ("dead", "failed", "exited"))
if not terminal:
    failures.append("exact systemd unit is not proven terminal")
if fields.get("InvocationID") and fields["InvocationID"] != INVOCATION:
    failures.append("systemd invocation differs from observed original invocation")
fallback = "/user.slice/user-1000.slice/user@1000.service/app.slice/" + UNIT
paths = {fallback}
if fields.get("ControlGroup"):
    observed = fields["ControlGroup"]
    if not observed.startswith("/") or Path(observed).name != UNIT or ".." in Path(observed).parts:
        raise ValueError("unexpected exact unit ControlGroup")
    paths.add(observed)
groups = []
for relative in sorted(paths):
    group = Path("/sys/fs/cgroup" + relative)
    exists = group.exists()
    actual_files, pids = [], set()
    if exists:
        targets = set([group / "cgroup.procs", *group.glob("**/cgroup.procs")])
        if (group / "cgroup.events").exists():
            targets.add(group / "cgroup.events")
        for path in sorted(targets):
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                actual_files.append(dict(path=str(path), disappeared_during_snapshot=True))
                continue
            if len(data) > 1024 * 1024:
                raise ValueError("oversized owned cgroup metadata")
            actual_files.append(dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                     text=data.decode()))
            if path.name == "cgroup.procs":
                pids.update(int(value) for value in data.split())
            elif path.name == "cgroup.events":
                events = dict(line.split() for line in data.decode().splitlines())
                if events.get("populated") != "0":
                    failures.append("exact owned cgroup populated flag is not zero")
    if pids:
        failures.append("owned descendants still listed in exact cgroup")
    groups.append(dict(path=str(group), exists=exists, owned_pids=sorted(pids), actual_files=actual_files))
roots = []
for role, pid, expected_ticks in ORIGINALS:
    proc = Path("/proc") / str(pid)
    try:
        data = (proc / "stat").read_bytes()
        columns = data.decode().rpartition(")")[2].split()
        actual_ticks = int(columns[19])
        same_identity = expected_ticks is None or actual_ticks == expected_ticks
        observation = dict(role=role, pid=pid, expected_start_ticks=expected_ticks, present=True,
                           same_original_identity=same_identity, state=columns[0], parent_pid=int(columns[1]),
                           start_ticks=actual_ticks, raw_stat=dict(bytes=len(data),
                           sha256=hashlib.sha256(data).hexdigest(), text=data.decode()))
        if same_identity:
            failures.append(role + " original identity remains (unknown start ticks fail closed)")
    except FileNotFoundError:
        observation = dict(role=role, pid=pid, expected_start_ticks=expected_ticks, present=False,
                           same_original_identity=False)
    roots.append(observation)
document = dict(schema="hepta-H3-archive-exact-owned-unit-release-observation-v1", job_id=JOB,
    expected_unit=UNIT, expected_original_invocation=INVOCATION,
    observed_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    original_authoritative_terminal=dict(state="succeeded", exit_code=0, timed_out=False,
                                         at_unix_ms=1793917793069),
    systemctl=dict(command=argv, exit_code=result.returncode, elapsed_ns=time.monotonic_ns()-started,
        fields=fields, stdout=dict(bytes=len(result.stdout), sha256=hashlib.sha256(result.stdout).hexdigest(),
                                   text=result.stdout.decode()),
        stderr=dict(bytes=len(result.stderr), sha256=hashlib.sha256(result.stderr).hexdigest(),
                    text=result.stderr.decode())),
    exact_cgroups=groups, original_root_processes=roots, owned_processes_clear=not failures,
    failures=failures, mutations_performed=False, processes_killed=False,
    cargo_or_cost_or_compression_started=False,
    scope="Only the exact previously observed runtime unit, its reported and known user cgroup paths, "
          "nested cgroup.procs, and its original process identity. A removed unit's default Result "
          "does not replace the authoritative archive terminal; this release grants no new native evidence.")
data = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
with OUT.open("xb") as output:
    output.write(data)
print(json.dumps(dict(path=str(OUT), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
    owned_processes_clear=document["owned_processes_clear"], failures=failures, systemd=fields,
    cgroups=[dict(path=row["path"], exists=row["exists"], owned_pids=row["owned_pids"]) for row in groups],
    original_root_processes=roots)), flush=True)
raise SystemExit(0 if document["owned_processes_clear"] else 1)

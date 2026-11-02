"""Linux full-worker CPU admission, cooperative deadlines and explicit cost ledgers.

The fit worker is one process (threads are counted); spawning subprocesses is an
unsupported contract and is rejected when observed. This is instrumentation for
audited research workers, not a security sandbox. A successful return code alone
never establishes CPU admission or actual matched expenditure.
"""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


ENV_SPEC = "HCSN_JOINT_BUDGET_SPEC"


def cpu_seconds():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n")


@dataclass(frozen=True)
class BudgetSpec:
    nominal_cpu_seconds: float
    tolerance_fraction: float = 0.02
    match_fraction: float = 0.10
    pair_gap_fraction: float = 0.10
    export_reserve_seconds: float = 0.30
    wall_seconds: float = 60.0
    poll_seconds: float = 0.005
    termination_grace_seconds: float = 0.10

    def validate(self):
        if not all(math.isfinite(x) for x in asdict(self).values()):
            raise ValueError("budget fields must be finite")
        if self.nominal_cpu_seconds <= 0 or self.wall_seconds <= 0:
            raise ValueError("positive CPU and wall limits required")
        if not 0 <= self.tolerance_fraction <= .10 or not 0 <= self.match_fraction <= .25:
            raise ValueError("invalid predeclared tolerance or matching band")
        if not 0 <= self.pair_gap_fraction <= .25:
            raise ValueError("invalid predeclared paired matching gap")
        if not 0 < self.export_reserve_seconds < self.nominal_cpu_seconds:
            raise ValueError("export reserve must be positive and below nominal budget")
        if not .001 <= self.poll_seconds <= .1 or not .01 <= self.termination_grace_seconds <= 1:
            raise ValueError("bounded monitoring and termination intervals required")
        return self

    @property
    def cpu_limit(self):
        return self.nominal_cpu_seconds * (1+self.tolerance_fraction)


class BudgetCheckpoint:
    """Checkpoint against process CPU since exec, including pre-import CPU."""
    def __init__(self, spec, shared_cpu_seconds=0.):
        self.spec = spec.validate()
        self.shared_cpu_seconds = float(shared_cpu_seconds)
        if not math.isfinite(self.shared_cpu_seconds) or not 0 <= self.shared_cpu_seconds < spec.nominal_cpu_seconds:
            raise ValueError("shared preparation already exhausts the nominal budget")

    @classmethod
    def from_env(cls):
        value = json.loads(os.environ[ENV_SPEC])
        return cls(BudgetSpec(**value["spec"]), value["shared_cpu_seconds"])

    @property
    def used_cpu_seconds(self):
        return self.shared_cpu_seconds + cpu_seconds()

    @property
    def remaining_work_cpu_seconds(self):
        return max(0., self.spec.nominal_cpu_seconds-self.used_cpu_seconds-self.spec.export_reserve_seconds)

    def can_continue(self, minimum_work_cpu_seconds=0.):
        if not math.isfinite(minimum_work_cpu_seconds) or minimum_work_cpu_seconds < 0:
            raise ValueError("minimum work must be finite and nonnegative")
        return self.remaining_work_cpu_seconds > minimum_work_cpu_seconds


def proc_cpu(pid):
    # /proc stat fields utime/stime include all threads of this process.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(fields[11])+int(fields[12]))/os.sysconf("SC_CLK_TCK")


def group_process_count(group):
    count = 0
    for path in Path("/proc").iterdir():
        if path.name.isdigit():
            try:
                fields = (path/"stat").read_text().rsplit(")", 1)[1].split()
                count += int(fields[2]) == group
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
    return count


def exec_child(handshake, command):
    """Same-process exec; bridge a PID namespace with an outer /proc mount."""
    value = json.loads(os.environ[ENV_SPEC])
    spec = BudgetSpec(**value["spec"]).validate()
    seconds = max(1, math.ceil(spec.cpu_limit-value["shared_cpu_seconds"]))
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds+1))
    raw = Path("/proc/self/stat").read_text()
    fields = raw.rsplit(")", 1)[1].split()
    write_new(handshake, dict(proc_host_pid=int(raw.split(" ", 1)[0]),
                              proc_host_parent_pid=int(fields[1]), proc_host_group=int(fields[2]),
                              namespace_pid=os.getpid()))
    os.execvpe(command[0], command, os.environ)


def run_limited(command, spec, output_dir, shared_receipt=None, consumers=1):
    """Run one fresh fit exec; reject every observed or final CPU overrun."""
    spec.validate()
    if os.name != "posix" or not Path("/proc/self/stat").exists():
        raise RuntimeError("this implementation requires Linux /proc and wait4")
    if not isinstance(consumers, int) or consumers < 1 or not command:
        raise ValueError("positive frozen consumer count and nonempty argv required")
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    shared, shared_sha, shared_monitor = 0., None, 0.
    if shared_receipt is not None:
        raw = Path(shared_receipt).read_bytes()
        record = json.loads(raw)
        if record["schema"] != "joint-budget-receipt-v1" or not record["admissible"]:
            raise ValueError("shared preparation must have an admitted complete receipt")
        shared, shared_sha = float(record["standalone_cpu_seconds"]), hashlib.sha256(raw).hexdigest()
        if record.get("source_sha256") != source_sha:
            raise ValueError("shared preparation uses a different budget instrumentation source")
        shared_monitor = record["supervisor_cpu_before_receipt_seconds"] + record.get("shared_monitor_cpu_seconds", 0.)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    if shared >= spec.nominal_cpu_seconds:
        record = dict(schema="joint-budget-receipt-v1", command=command, spec=asdict(spec),
                      returncode=None, launched=False, admissible=False,
                      rejection_reason="shared_preparation_exhausts_nominal_budget",
                      shared_receipt_sha256=shared_sha, shared_cpu_seconds=shared, consumers=consumers,
                      worker_cpu_seconds=0., standalone_cpu_seconds=shared,
                      amortized_cpu_seconds=shared/consumers, actual_cpu_in_match_band=False)
        write_new(out/"RECEIPT.json", record)
        return record
    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    env[ENV_SPEC] = json.dumps(dict(spec=asdict(spec), shared_cpu_seconds=shared))
    handshake = (out/"HOST_PID.json").resolve()
    launcher = [sys.executable, str(Path(__file__).resolve()), "--exec-child", str(handshake), "--", *command]
    parent_host_pid = int(Path("/proc/self/stat").read_text().split(" ", 1)[0])
    start, supervisor_cpu = time.monotonic(), cpu_seconds()
    reason, terminated, kill_sent, last_group_check = None, None, False, -1.
    samples, identity = [], None
    with (out/"stdout.log").open("x") as stdout, (out/"stderr.log").open("x") as stderr:
        process = subprocess.Popen(launcher, stdout=stdout, stderr=stderr, env=env, start_new_session=True)
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                break
            elapsed = time.monotonic()-start
            if identity is None and handshake.exists():
                try:
                    identity = json.loads(handshake.read_text())
                except json.JSONDecodeError:
                    pass
                if identity is not None and identity["proc_host_parent_pid"] != parent_host_pid:
                    raise RuntimeError("PID handshake does not identify this launcher's child")
            try:
                measured = proc_cpu(identity["proc_host_pid"]) if identity is not None else 0.
            except (FileNotFoundError, ProcessLookupError):
                continue
            if identity is not None and elapsed-last_group_check >= .05:
                last_group_check = elapsed
                if group_process_count(identity["proc_host_group"]) > 1 and reason is None:
                    reason = "unsupported_subprocess_observed"
            if shared+measured > spec.cpu_limit and reason is None:
                reason = "live_cpu_limit_exceeded"
            if elapsed > spec.wall_seconds and reason is None:
                reason = "wall_limit_exceeded"
            if reason is not None and terminated is None:
                terminated = time.monotonic()
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if terminated is not None and not kill_sent and time.monotonic()-terminated > spec.termination_grace_seconds:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                kill_sent = True
            if not samples or elapsed-samples[-1][0] >= .1:
                samples.append([elapsed, measured])
            time.sleep(spec.poll_seconds)
    wall = time.monotonic()-start
    if wall > spec.wall_seconds:
        reason = reason or "final_wall_limit_exceeded"
    worker = usage.ru_utime+usage.ru_stime
    total = shared+worker
    if total > spec.cpu_limit:
        reason = reason or "final_cpu_limit_exceeded"
    if process.returncode != 0:
        reason = reason or "worker_nonzero_returncode"
    if identity is None:
        reason = reason or "missing_pid_handshake"
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_sha:
        reason = reason or "budget_instrumentation_source_changed"
    admitted = reason is None
    record = dict(schema="joint-budget-receipt-v1", command=command, spec=asdict(spec), launched=True,
                  returncode=process.returncode, admissible=admitted, rejection_reason=reason,
                  shared_receipt_sha256=shared_sha, shared_cpu_seconds=shared, consumers=consumers,
                  shared_monitor_cpu_seconds=shared_monitor,
                  worker_user_cpu_seconds=usage.ru_utime, worker_system_cpu_seconds=usage.ru_stime,
                  worker_cpu_seconds=worker, standalone_cpu_seconds=total,
                  amortized_cpu_seconds=worker+shared/consumers,
                  actual_cpu_in_match_band=admitted and abs(total-spec.nominal_cpu_seconds) <= spec.nominal_cpu_seconds*spec.match_fraction,
                  wall_seconds=wall, maximum_resident_kib=usage.ru_maxrss,
                  supervisor_cpu_before_receipt_seconds=cpu_seconds()-supervisor_cpu,
                  supervisor_scope="monitor interval only, excludes launcher imports and final receipt serialization/exit",
                  samples_wall_worker_cpu=samples, worker_threads_included=True,
                  nominal_worker_work_allowance_before_startup_seconds=spec.nominal_cpu_seconds-shared-spec.export_reserve_seconds,
                  source_sha256=source_sha,
                  pid_identity=identity, exec_wrapper_cpu_in_worker=True,
                  limitations="audited single process; no GPU/energy accounting; observed subprocesses rejected, not a security sandbox")
    write_new(out/"RECEIPT.json", record)
    return record


def match_group(receipts):
    """Require the registered actual-expenditure band and within-fit spread."""
    if not receipts:
        raise ValueError("nonempty paired group required")
    specs = [r["spec"] for r in receipts]
    if any(s != specs[0] for s in specs):
        raise ValueError("paired workers must use exactly the same frozen budget specification")
    values = [r["standalone_cpu_seconds"] for r in receipts]
    gap = max(values)-min(values)
    allowed = specs[0]["nominal_cpu_seconds"]*specs[0]["pair_gap_fraction"]
    return dict(matched=all(r["actual_cpu_in_match_band"] for r in receipts) and gap <= allowed,
                standalone_cpu_seconds=values, actual_gap_seconds=gap, maximum_gap_seconds=allowed)


def cost_ledger(receipts):
    """Settle one shared preparation across its actually launched consumers."""
    if not receipts or not all(r.get("launched", False) for r in receipts):
        raise ValueError("ledger requires every declared consumer to have actually launched")
    identities = {(r["shared_receipt_sha256"], r["shared_cpu_seconds"], r["consumers"]) for r in receipts}
    if len(identities) != 1 or receipts[0]["consumers"] != len(receipts):
        raise ValueError("declared and actual shared consumers do not agree")
    shared = receipts[0]["shared_cpu_seconds"]
    workers = [r["worker_cpu_seconds"] for r in receipts]
    supervisor = [r["supervisor_cpu_before_receipt_seconds"] for r in receipts]
    return dict(actual_consumers=len(receipts), shared_once_cpu_seconds=shared,
                standalone_cpu_seconds=[shared+x for x in workers],
                amortized_cpu_seconds=[shared/len(receipts)+x for x in workers],
                physical_worker_plus_shared_cpu_seconds=shared+sum(workers),
                observed_monitor_cpu_seconds=receipts[0]["shared_monitor_cpu_seconds"]+sum(supervisor),
                physical_plus_observed_monitor_cpu_seconds=shared+sum(workers)+receipts[0]["shared_monitor_cpu_seconds"]+sum(supervisor),
                scope="supervisor imports/receipt serialization/exit and any outer campaign launcher are not measured here")


def main():
    if len(sys.argv) >= 5 and sys.argv[1] == "--exec-child" and sys.argv[3] == "--":
        exec_child(sys.argv[2], sys.argv[4:])
        raise AssertionError("exec returned")
    p = argparse.ArgumentParser()
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--shared-receipt", type=Path)
    p.add_argument("--consumers", type=int, default=1)
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = a.command[1:] if a.command[:1] == ["--"] else a.command
    result = run_limited(command, BudgetSpec(**json.loads(a.spec.read_text())), a.out, a.shared_receipt, a.consumers)
    print(json.dumps({k: result[k] for k in ("admissible", "rejection_reason", "standalone_cpu_seconds", "actual_cpu_in_match_band")}))
    raise SystemExit(0 if result["admissible"] else 2)


if __name__ == "__main__":
    main()

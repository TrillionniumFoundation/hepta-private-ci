"""Execution06 explicit process entrypoints and registered cwd isolation.

New integration over context-reconstructed adapters. Every exec worker enters
this wrapper before its unchanged scientific entrypoint. Tests use tiny process
fixtures only; no synthetic fixture is accepted through a production CLI flag.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "experiments.parameter_field_fullstudy_20261029."
WORKERS = {PREFIX + name for name in ("run_v2", "architecture_run_v2", "endpoint_v2")}
ANALYSIS, FINALIZER = PREFIX + "analysis_launch_v2", PREFIX + "finalize_v2"
EPISODE = "execution06_detached_20261030"
POLICY_SCHEMA = "hepta.fullstudy.cwd-policy.5"
START_SCHEMA = "hepta.execution06.supervisor-start-policy.1"
OPS_PREFIX = "operational/parameter_field_recovery06/"
RUNTIME_SOURCES = tuple(OPS_PREFIX + name + ".py" for name in (
    "cwd_runner", "resource_backpressure", "owned_children", "controller",
    "ancestry", "producer_adapter", "historical_costs", "wait4_launcher", "daemon_bootstrap")) + (
    "operational/parameter_field_recovery04/durable_archive.py",
) + tuple("experiments/parameter_field_fullstudy_20261029/" + name + ".py" for name in (
    "resource_v2", "resource_io_v2", "run_v2", "architecture_run_v2", "endpoint_v2",
    "launch_v2", "controller_envelope_v2", "analysis_launch_v2", "finalize_v2",
    "architecture_store", "replay_terminals", "report_results"))
POLICY_KEYS = {"schema", "execution_episode", "source_root", "raw_root", "ops_root", "python",
               "empty_cwd", "source_files", "worker_modules", "analysis_module", "amendment",
               "producer_config", "capacity_wait_seconds"}
IDENTITY_KEYS = {"pid", "parent_pid", "pgid", "sid", "start_ticks"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exception_chain(error):
    """Retain bounded original causes when a text/gzip close raises again."""
    records, seen, current = [], set(), error
    while current is not None and id(current) not in seen and len(records) < 8:
        seen.add(id(current))
        records.append({"error_type": type(current).__name__, "message": str(current)[:2048]})
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return {"errors": records, "truncated_or_cyclic": current is not None}


def file_identity(path):
    value = Path(path).lstat()
    require(stat.S_ISREG(value.st_mode), "Metadata must be a regular nonsymlink file")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def descriptor(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, "Metadata path is not canonical absolute")
    before = file_identity(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    require(file_identity(path) == before, "Metadata changed while hashing")
    return {"path": str(path), "bytes": before[2], "sha256": digest}


def checked(item):
    require(isinstance(item, dict) and set(item) == {"path", "bytes", "sha256"}, "Exact metadata descriptor required")
    require(type(item["bytes"]) is int and item["bytes"] >= 0 and descriptor(item["path"]) == item,
            "Registered descriptor bytes differ: " + str(item.get("path")))
    return Path(item["path"])


def read_json(item):
    path = checked(item)
    require(item["bytes"] <= 8 * 1024 * 1024, "Operational configuration exceeds its 8 MiB bound")
    payload = path.read_bytes()
    require(len(payload) == item["bytes"] and hashlib.sha256(payload).hexdigest() == item["sha256"],
            "Metadata changed before JSON parsing")
    return json.loads(payload)


def write_new(path, value):
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    require(len(payload) <= 64 * 1024, "Wrapper receipt exceeds 64 KiB bound")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    space = os.statvfs(path.parent)
    allocation = ((len(payload) + space.f_frsize - 1) // space.f_frsize) * space.f_frsize
    require(space.f_bavail * space.f_frsize >= 256 * 1024 ** 2 + allocation and space.f_favail >= 2000,
            "Wrapper receipt would consume registered physical reserve")
    with path.open("xb") as stream:
        require(stream.write(payload) == len(payload), "Partial wrapper receipt write")
        stream.flush()
        os.fsync(stream.fileno())
    return descriptor(path.absolute())


def flags(argv):
    result, index = {}, 0
    while index < len(argv):
        key = argv[index]
        require(isinstance(key, str) and key.startswith("--") and key not in result,
                "Invalid or duplicated original flag")
        if key in ("--execute", "--child", "--resume-admission", "--recover-zero-work"):
            result[key] = True
            index += 1
        else:
            require(index + 1 < len(argv) and not argv[index + 1].startswith("--"), "Missing original flag value")
            result[key] = argv[index + 1]
            index += 2
    return result


def identity(pid):
    value = Path(f"/proc/{pid}/stat").read_text()
    fields = value[value.rfind(")") + 2:].split()
    require(int(value.split(" ", 1)[0]) == pid and len(fields) >= 20, "Invalid Linux process identity")
    return {"pid": pid, "parent_pid": int(fields[1]), "pgid": int(fields[2]),
            "sid": int(fields[3]), "start_ticks": int(fields[19])}


def empty_directory(policy):
    source, cwd = Path(policy["source_root"]).resolve(), Path(policy["empty_cwd"])
    require(cwd.is_absolute() and cwd.resolve(strict=True) == cwd and cwd.is_dir()
            and not cwd.is_relative_to(source), "Worker cwd must exist canonically outside source")
    require(not any(cwd.iterdir()), "Registered worker cwd is not empty")
    return cwd


def validate_policy(path, expected):
    item = descriptor(Path(path).absolute())
    require(item["sha256"] == expected, "Cwd policy bytes differ")
    policy = read_json(item)
    require(POLICY_KEYS <= set(policy) and policy["schema"] == POLICY_SCHEMA
            and policy["execution_episode"] == EPISODE, "Unregistered cwd policy")
    require(Path(policy["source_root"]) == ROOT and ROOT.name == "fullstudy_recovery06_git", "Wrong source root")
    require(Path(policy["raw_root"]) == ROOT.parent / "fullstudy_execution06_durable_raw"
            and Path(policy["ops_root"]) == ROOT.parent / "fullstudy_execution06_ops"
            and Path(policy["empty_cwd"]) == Path(policy["ops_root"]) / "empty_cwd", "Wrong execution06 roots")
    require(os.path.abspath(sys.executable) == policy["python"],
            "Use the registered interpreter path without resolving its venv symlink")
    require(len(policy["worker_modules"]) == 3 and set(policy["worker_modules"]) == WORKERS
            and policy["analysis_module"] == ANALYSIS, "Worker module population differs")
    require(type(policy["capacity_wait_seconds"]) is int and policy["capacity_wait_seconds"] == 300,
            "Registered capacity wait must remain 300 seconds")
    require(set(RUNTIME_SOURCES) <= set(policy["source_files"]), "Wrapper source closure is incomplete")
    for name, expected_sha in policy["source_files"].items():
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe source path")
        target = ROOT / relative
        require(target.resolve(strict=True).is_relative_to(ROOT)
                and descriptor(target)["sha256"] == expected_sha, "Cwd adapter source binding differs: " + name)
    checked(policy["amendment"])
    producer = read_json(policy["producer_config"])
    require({"producer_map", "import_receipt", "fresh_registration"} <= set(producer)
            and producer.get("schema") == "hepta.execution06.producer-config.1"
            and producer.get("execution_episode") == EPISODE, "Missing or unregistered producer configuration")
    checked(producer["producer_map"])
    checked(producer["import_receipt"])
    fresh = producer["fresh_registration"]
    require(fresh["execution_episode"] == EPISODE and fresh["source_root"] == policy["source_root"]
            and fresh["raw_root"] == policy["raw_root"] and fresh["profile"] == policy["amendment"],
            "Producer configuration differs from current roots/profile")
    initial = read_json(fresh["source_freeze"])
    require(initial["registered_commit"] == fresh["registered_commit"]
            and initial["execution_episode"] == EPISODE
            and all(initial["source_files"].get(name) == policy["source_files"][name] for name in RUNTIME_SOURCES),
            "Initial producer source freeze does not bind the installed runtime source")
    # Initial A/C freezes precede producer_map/config and policy. Their source
    # bytes are frozen; later evidence is bound by this independently pinned
    # policy and the subsequent OPS/followup freezes, without a hash cycle.
    empty_directory(policy)
    return policy


class SupervisorGuard:
    """Read-only shared deadline, unchanged startup identity, and OOM baseline."""

    def __init__(self, policy, policy_path, policy_sha, profile_reader):
        self.policy, self.profile_reader = policy, profile_reader
        self.own_identity = identity(os.getpid())
        path = Path(policy["ops_root"]) / "supervisor_run/START_POLICY.json"
        self.start_descriptor = descriptor(path)
        self.start_identity = file_identity(path)
        self.start = read_json(self.start_descriptor)
        value = self.start
        require(value["schema"] == START_SCHEMA and value["execution_episode"] == EPISODE
                and all(value[key] == policy[key] for key in ("source_root", "raw_root", "ops_root")),
                "Supervisor startup policy identity differs")
        require(value["cwd_policy"] == descriptor(Path(policy_path).absolute())
                and value["cwd_policy"]["sha256"] == policy_sha, "Supervisor did not bind this exact cwd policy")
        require(set(value["supervisor_identity"]) == IDENTITY_KEYS
                and all(type(v) is int and v >= 0 for v in value["supervisor_identity"].values()),
                "Supervisor identity must contain exact integer fields")
        require(set(value["oom_baseline"]) == {"oom", "oom_kill"}
                and all(type(v) is int and v >= 0 for v in value["oom_baseline"].values()),
                "Supervisor OOM baseline differs")
        require(all(type(value[key]) in (int, float) and math.isfinite(value[key])
                    for key in ("started_monotonic", "deadline_monotonic"))
                and value["started_monotonic"] <= time.monotonic()
                and math.isclose(value["deadline_monotonic"] - value["started_monotonic"], 43200.0,
                                 rel_tol=0, abs_tol=1e-6), "Supervisor absolute 12-hour window differs")
        self.initial_profile = self.health()

    def health(self):
        require(file_identity(self.start_descriptor["path"]) == self.start_identity
                and descriptor(self.start_descriptor["path"]) == self.start_descriptor,
                "Supervisor startup policy changed")
        require(identity(os.getpid()) == self.own_identity, "Wrapper process identity changed")
        owner = self.start["supervisor_identity"]
        observed_owner = identity(owner["pid"])
        require(observed_owner == owner, "Supervisor process identity changed: " + json.dumps(
            {"expected": owner, "observed": observed_owner}, sort_keys=True))
        require(time.monotonic() <= self.start["deadline_monotonic"], "Original absolute supervisor deadline exhausted")
        profile = self.profile_reader()
        require(all(profile[name] <= self.start["oom_baseline"][name] for name in ("oom", "oom_kill")),
                "OOM counter increased since original supervisor baseline")
        return profile


def invocation(kind, original, original_module=None):
    require(kind in ("controller", "worker", "analysis", "finalizer"), "Unknown wrapper kind")
    parsed = flags(original)
    require(not parsed.get("--resume-admission") and not parsed.get("--recover-zero-work"),
            "Fresh execution06 cannot enter legacy resume/recovery")
    if kind == "worker":
        require(original_module in WORKERS, "Explicit registered worker module required")
        if original_module.endswith(".architecture_run_v2"):
            token = "C"
        elif original_module.endswith(".endpoint_v2"):
            require(parsed.get("--phase") in ("A", "B", "C"), "Unknown endpoint phase")
            token = parsed["--phase"] + "_endpoint"
        else:
            phase = parsed.get("--phase")
            require(phase in ("A", "B", "W", "R"), "Unknown worker phase")
            if phase == "W":
                token = "W"
            else:
                require(parsed.get("--seed") in ("17", "29", "43"), "Unknown worker seed")
                token = phase + "-" + parsed["--seed"]
            require(token != "A-17", "Imported A17 cannot spawn a new scientific worker")
        return parsed, token, original_module
    require(original_module is None, "Only worker kind accepts an original module")
    if kind == "analysis":
        return parsed, "ANALYSIS" if parsed.get("--child") else "ANALYSIS_PARENT", ANALYSIS
    if kind == "finalizer":
        evidence = parsed.get("--evidence-id", "verification01")
        require(evidence.isalnum(), "Unsafe finalizer evidence identity")
        return parsed, "FINALIZER-" + evidence, FINALIZER
    return parsed, "CONTROLLER", PREFIX + "controller_envelope_v2"


def bound_arguments(parsed, policy):
    require(Path(parsed["--root"]).resolve() == Path(policy["raw_root"]), "Adapter/child raw root differs")
    require(parsed["--amendment"] == policy["amendment"]["path"]
            and parsed["--amendment-sha256"] == policy["amendment"]["sha256"], "Adapter/child amendment differs")


class CwdSubprocess:
    """Only the controller/analysis object's own Popen site is proxied."""

    def __init__(self, original, policy, policy_path, policy_sha, kind, *, health_check):
        require(kind in ("controller", "analysis") and callable(health_check), "Invalid scoped spawn proxy")
        require(getattr(original, "owner", None) is not None,
                "Owned wait4 proxy must be installed before cwd spawn proxy")
        self.original, self.policy, self.kind = original, policy, kind
        self.policy_path, self.policy_sha = str(Path(policy_path).absolute()), policy_sha
        self.health_check = health_check

    def __getattr__(self, name):
        return getattr(self.original, name)

    def Popen(self, argv, *args, **kwargs):
        self.health_check()
        require(not args and isinstance(argv, list) and 4 <= len(argv) <= 128
                and all(isinstance(x, str) and "\x00" not in x for x in argv)
                and sum(map(len, argv)) <= 32768, "Unexpected/unbounded original Popen signature")
        require(argv[1:3] == ["-B", "-m"] and os.path.abspath(argv[0]) == self.policy["python"],
                "Unexpected original child interpreter/invocation")
        require(set(kwargs) <= {"cwd", "env", "stdout", "stderr"}
                and Path(kwargs.get("cwd", "")).resolve() == Path(self.policy["source_root"]),
                "Unexpected original requested cwd/Popen options")
        module, child_kind = argv[3], "worker" if self.kind == "controller" else "analysis"
        if child_kind == "analysis":
            require(module == ANALYSIS and flags(argv[4:]).get("--child") is True, "Unexpected analysis child module")
        parsed, token, unused = invocation(child_kind, argv[4:], module if child_kind == "worker" else None)
        bound_arguments(parsed, self.policy)
        effective = [argv[0], "-B", str(Path(__file__).resolve()), "--kind", child_kind,
                     "--policy", self.policy_path, "--expected-policy-sha256", self.policy_sha]
        if child_kind == "worker":
            effective += ["--original-module", module]
        effective += ["--", *argv[4:]]
        cwd = empty_directory(self.policy)
        env = dict(kwargs.get("env", os.environ))
        env.update(PYTHONPATH=self.policy["source_root"], PYTHONDONTWRITEBYTECODE="1")
        destination = Path(self.policy["ops_root"]) / "cwd_launches" / token
        destination.mkdir(parents=True, exist_ok=False)
        record = {"schema": "hepta.fullstudy.cwd-launch.5", "job": token,
                  "at_utc": datetime.now(timezone.utc).isoformat(), "policy_sha256": self.policy_sha,
                  "requested_argv": argv, "effective_argv": effective,
                  "requested_cwd": str(kwargs["cwd"]), "effective_cwd": str(cwd),
                  "numeric_and_original_arguments_changed": False, "environment_values_disclosed": False}
        write_new(destination / "REQUEST.json", record)
        try:
            # Production calls arrive here with the owned-child proxy already
            # inside self.original, so identity/receipt failures are tracked.
            process = self.original.Popen(effective, **dict(kwargs, cwd=str(cwd), env=env))
        except BaseException as error:
            try:
                write_new(destination / "SPAWN_FAILED.json", {"error_type": type(error).__name__,
                    "message": str(error)[:4096], "construction_returned_handle": False,
                    "scientific_execution_started_unknown": True})
            except BaseException as receipt_error:
                error.add_note("Cwd spawn failure receipt also failed: " + type(receipt_error).__name__)
            raise
        try:
            write_new(destination / "STARTED.json", {**record, "pid": process.pid,
                      "observed_identity": identity(process.pid)})
        except BaseException as error:
            try:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            except BaseException as cleanup_error:
                error.add_note("Owned cwd-launch cleanup also failed: " + type(cleanup_error).__name__)
            raise
        return process


@contextmanager
def isolated_spawns(module, policy, path, expected, kind, health_check):
    original = module.subprocess
    module.subprocess = CwdSubprocess(original, policy, path, expected, kind, health_check=health_check)
    try:
        yield
    finally:
        module.subprocess = original


def dispatch(kind, module_name, original, policy, path, expected, producer, installation, guard, receipt_directory):
    """All ProducerAdapter factories see modules after backpressure installation."""
    from operational.parameter_field_recovery06 import owned_children
    module = importlib.import_module(module_name)
    previous_argv = sys.argv
    sys.argv = [module.__name__, *original]
    binding = {"cwd_policy": descriptor(Path(path).absolute()), "producer_config": policy["producer_config"],
               "supervisor_start_policy": guard.start_descriptor, "execution_episode": EPISODE}
    try:
        if kind == "controller":
            from operational.parameter_field_recovery06.controller import ControllerCore
            core = ControllerCore(producer.import_receipt)
            previous_budget, previous_core = core.StorageBudget, module.core
            core.StorageBudget, module.core = installation["budget_type"], core
            try:
                def execute_envelope():
                    with isolated_spawns(core, policy, path, expected, "controller", guard.health):
                        return module.main()
                return owned_children.run_controller(core, execute_envelope, receipt_directory / "owned_children", binding=binding)
            finally:
                module.core, core.StorageBudget = previous_core, previous_budget
        if kind == "worker":
            if module_name.endswith(".run_v2"):
                module = producer.for_runner(module)
            elif module_name.endswith(".endpoint_v2"):
                module = producer.for_endpoint(module)
            return module.main()
        if kind == "finalizer":
            return producer.for_finalizer(module).main()
        module = producer.for_analysis_launcher(module)
        if flags(original).get("--child"):
            from operational.parameter_field_recovery06.historical_costs import apply_cost_adapter
            parsed = flags(original)
            inputs = descriptor(Path(parsed["--inputs"]).absolute())
            require(inputs["sha256"] == parsed["--expected-sha256"], "Analysis inputs differ")
            with apply_cost_adapter(inputs):
                return module.main()
        def execute_analysis():
            with isolated_spawns(module, policy, path, expected, "analysis", guard.health):
                return module.main()
        return owned_children.run_controller(module, execute_analysis, receipt_directory / "owned_children", binding=binding)
    finally:
        sys.argv = previous_argv


def run_registered(kind, policy, path, expected, original, original_module=None):
    parsed, token, module_name = invocation(kind, original, original_module)
    bound_arguments(parsed, policy)
    require(Path.cwd().resolve() == empty_directory(policy), "Adapter must run from the registered empty cwd")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from operational.parameter_field_recovery06 import resource_backpressure as backpressure
    from operational.parameter_field_recovery06.producer_adapter import ProducerAdapter
    guard = SupervisorGuard(policy, path, expected, backpressure.RESOURCE.memory_profile)
    freeze = read_json(descriptor(Path(parsed["--freeze"]).absolute()))
    require(all(freeze["source_files"].get(name) == policy["source_files"][name] for name in RUNTIME_SOURCES),
            "Entrypoint freeze omits or changes registered wrapper runtime sources")
    run_id = str(os.getpid()) + "-" + str(guard.own_identity["start_ticks"])
    receipts = Path(policy["ops_root"]) / "wrapper_runs" / token / run_id
    receipts.mkdir(parents=True, exist_ok=False)
    started, cpu = time.monotonic(), time.process_time()
    metadata = {"schema": "hepta.execution06.wrapper-run.1", "execution_episode": EPISODE,
                "kind": kind, "job": token, "original_module": module_name, "original_arguments": original,
                "process_identity": guard.own_identity, "cwd_policy": descriptor(Path(path).absolute()),
                "producer_config": policy["producer_config"], "supervisor_start_policy": guard.start_descriptor,
                "process_entry_memory_profile": guard.initial_profile,
                "shared_oom_baseline": guard.start["oom_baseline"],
                "shared_deadline_monotonic": guard.start["deadline_monotonic"],
                "started_monotonic": started, "original_arguments_changed": False,
                "scientific_completion_claim": False}
    write_new(receipts / "START.json", metadata)
    budget_policy = None
    try:
        budget_policy = backpressure.BackpressurePolicy(
            root=policy["raw_root"], journal_directory=Path(policy["ops_root"]) / "resource_backpressure" / token / run_id,
            source_root=policy["source_root"], expected_sources=policy["source_files"],
            deadline_monotonic=guard.start["deadline_monotonic"], oom_baseline=guard.start["oom_baseline"],
            health_check=guard.health, max_wait_seconds=policy["capacity_wait_seconds"])
        with backpressure.installed(budget_policy) as installation:
            config = read_json(policy["producer_config"])
            producer = ProducerAdapter(config["producer_map"], config["import_receipt"], config["fresh_registration"])
            result = dispatch(kind, module_name, original, policy, path, expected, producer, installation, guard, receipts)
        guard.health()
    except BaseException as error:
        successful_exit = isinstance(error, SystemExit) and error.code in (None, 0)
        terminal = {**metadata, "wrapper_call_returned_successfully": successful_exit,
                    "wall_seconds": time.monotonic() - started, "own_cpu_seconds": time.process_time() - cpu,
                    "wait_count": 0 if budget_policy is None else budget_policy.wait_count,
                    "capacity_wait_wall_seconds": 0 if budget_policy is None else budget_policy.wait_wall_seconds,
                    "error_type": type(error).__name__, "message": str(error)[:4096],
                    "exception_chain": exception_chain(error)}
        try:
            if successful_exit:
                guard.health()
            write_new(receipts / ("COMPLETE.json" if successful_exit else "FAILED.json"), terminal)
        except BaseException as receipt_error:
            if successful_exit:
                raise
            error.add_note("Wrapper terminal receipt also failed: " + type(receipt_error).__name__)
        raise
    write_new(receipts / "COMPLETE.json", {**metadata, "wrapper_call_returned_successfully": True,
              "wall_seconds": time.monotonic() - started, "own_cpu_seconds": time.process_time() - cpu,
              "wait_count": budget_policy.wait_count, "capacity_wait_wall_seconds": budget_policy.wait_wall_seconds})
    return result


def main(argv=None):
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", required=True, choices=("controller", "worker", "analysis", "finalizer"))
    parser.add_argument("--original-module", choices=sorted(WORKERS))
    parser.add_argument("--policy", required=True)
    parser.add_argument("--expected-policy-sha256", required=True)
    parser.add_argument("original_arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    require(args.original_arguments and args.original_arguments[0] == "--", "Explicit original-argument boundary is required")
    policy = validate_policy(args.policy, args.expected_policy_sha256)
    return run_registered(args.kind, policy, args.policy, args.expected_policy_sha256,
                          args.original_arguments[1:], args.original_module)


if __name__ == "__main__":
    main()

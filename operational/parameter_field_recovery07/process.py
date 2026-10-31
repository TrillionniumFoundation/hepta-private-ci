"""Execution07 identities, bounded receipts, and single-owner Linux wait4."""

from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time

EPISODE = "execution07_actions_20261031"
PREFIX = "experiments.parameter_field_fullstudy_20261029."
GIB = 1024**3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def descriptor(path):
    path = Path(path)
    require(
        path.is_absolute() and path.resolve(strict=True) == path,
        "Expected a canonical absolute path",
    )
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "Expected a regular nonsymlink file")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.lstat()
    require(
        (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        "File changed while hashing",
    )
    return {"path": str(path), "bytes": before.st_size, "sha256": digest}


def checked(value):
    require(
        isinstance(value, dict) and set(value) == {"path", "bytes", "sha256"},
        "Exact descriptor required",
    )
    require(
        type(value["bytes"]) is int
        and value["bytes"] >= 0
        and descriptor(value["path"]) == value,
        "Descriptor differs",
    )
    return Path(value["path"])


def read(path):
    item = path if isinstance(path, dict) else descriptor(Path(path))
    path = checked(item)
    require(item["bytes"] <= 32 * 1024**2, "Metadata exceeds bounded JSON size")
    payload = path.read_bytes()
    require(
        len(payload) == item["bytes"]
        and hashlib.sha256(payload).hexdigest() == item["sha256"],
        "Metadata changed before parsing",
    )

    def pairs(items):
        value = {}
        for key, row in items:
            require(key not in value, "Duplicate metadata key")
            value[key] = row
        return value

    def constant(unused):
        raise ValueError("Nonfinite metadata value")

    return json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)


def write(path, value, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    require(len(payload) <= 32 * 1024**2, "Receipt exceeds bounded JSON size")
    space = os.statvfs(path.parent)
    require(
        space.f_bavail * space.f_frsize >= 256 * 1024**2 + len(payload)
        and space.f_favail >= 2000,
        "Receipt would consume original physical reserve",
    )
    target = path.with_name(path.name + ".pending") if replace else path
    with target.open("xb") as stream:
        require(stream.write(payload) == len(payload), "Partial receipt write")
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(target, path)
    return descriptor(path)


def regular_tree(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "Missing regular tree")
    for base, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            require(
                not (Path(base) / name).is_symlink(), "Linked directory in evidence"
            )
        for name in sorted(files):
            path = Path(base) / name
            require(stat.S_ISREG(path.lstat().st_mode), "Nonregular evidence file")
            yield path


def load_config(path, expected):
    item = descriptor(Path(path).absolute())
    require(item["sha256"] == expected, "Configuration SHA differs")
    config = read(item)
    require(
        config.get("schema") == "hepta.fullstudy.execution07.configuration.1"
        and config.get("execution_episode") == EPISODE,
        "Wrong execution07 configuration",
    )
    source, ops, raw, cas = (
        Path(config[key]) for key in ("source_root", "ops_root", "raw_root", "cas_root")
    )
    require(
        all(p.is_absolute() and p.resolve() == p for p in (source, ops, raw, cas))
        and cas == raw.with_name(raw.name + "_cas")
        and not any(
            a == b or a.is_relative_to(b) for a in (ops, raw, cas) for b in (source,)
        )
        and not any(
            a == b or a.is_relative_to(b)
            for a, b in ((ops, raw), (raw, ops), (cas, ops))
        ),
        "Execution paths must be separate canonical roots",
    )
    require(
        Path(__file__).resolve()
        == source / "operational/parameter_field_recovery07/process.py",
        "Operational implementation loaded from another source root",
    )
    pins = config["descriptors"]
    require(
        {
            "amendment",
            "initial_queue",
            "controller_freeze",
            "runtime_receipt",
            "registration_driver",
        }
        <= set(pins),
        "Configuration source closure is incomplete",
    )
    for row in list(pins.values()) + config.get("initial_metadata", []):
        checked(row)
    empty = Path(config["empty_cwd"])
    require(
        empty.is_dir()
        and empty.resolve() == empty
        and not any(empty.iterdir())
        and not any(empty.is_relative_to(p) for p in (source, raw, cas)),
        "Working directory is not isolated and empty",
    )
    require(
        Path(config["active_queue"]).parent == ops,
        "Active queue must be at the registered OPS root",
    )
    source_check(config)
    return config, item


def source_check(config):
    frozen = read(config["descriptors"]["controller_freeze"])
    root = Path(config["source_root"])
    for name, digest in frozen["source_files"].items():
        path = root / name
        require(
            not Path(name).is_absolute()
            and ".." not in Path(name).parts
            and descriptor(path)["sha256"] == digest,
            "Frozen source differs: " + name,
        )
    own = "operational/parameter_field_recovery07/"
    require(
        {
            own + n + ".py"
            for n in (
                "process",
                "queue",
                "controller",
                "worker",
                "supervisor",
                "terminal",
                "registration",
                "analysis_worker",
                "artifact_transport",
            )
        }
        <= set(frozen["source_files"]),
        "Execution07 runtime source closure is incomplete",
    )
    return frozen["source_files"]


class Guard:
    def __init__(self, config, config_desc):
        self.config, self.config_desc = config, config_desc
        self.policy_desc = descriptor(
            Path(config["ops_root"]) / "supervisor_run/START_POLICY.json"
        )
        self.policy = read(self.policy_desc)
        require(
            self.policy.get("schema") == "hepta.execution07.supervisor-start-policy.1"
            and self.policy.get("execution_episode") == EPISODE
            and self.policy.get("pipeline_config") == config_desc
            and self.policy["deadline_monotonic"] - self.policy["started_monotonic"]
            == 12 * 3600,
            "Invalid fixed supervisor policy",
        )
        self.owned = importlib.import_module(
            "operational.parameter_field_recovery06.owned_children"
        )
        self.resource = importlib.import_module(PREFIX + "resource_v2")
        self.health()

    def health(self):
        require(
            time.monotonic() < self.policy["deadline_monotonic"],
            "Original twelve-hour deadline exhausted",
        )
        identity = self.policy["supervisor_identity"]
        require(
            self.owned.proc_identity(identity["pid"]) == identity,
            "Supervisor identity is no longer live",
        )
        value = self.resource.memory_profile()
        require(
            value["limit"] == 8 * GIB,
            "Registered independent eight-GiB cgroup is absent",
        )
        require(
            all(
                value[k] <= self.policy["oom_baseline"][k] for k in ("oom", "oom_kill")
            ),
            "Cgroup OOM counters increased",
        )
        return value

    def verify(self):
        checked(self.config_desc)
        checked(self.policy_desc)
        source_check(self.config)
        self.health()


@contextmanager
def adapter(config, guard, label):
    module = importlib.import_module(
        "operational.parameter_field_recovery06.resource_backpressure"
    )
    directory = Path(config["ops_root"]) / "resource_backpressure" / label
    directory.mkdir(parents=True, exist_ok=False)
    write(
        directory / "DELEGATION.json",
        {
            "schema": "hepta.execution07.resource-delegation.1",
            "execution_episode": EPISODE,
            "component": descriptor(Path(module.__file__).resolve()),
            "component_event_schema": "hepta.execution06.resource-backpressure-event.1",
            "component_schema_is_implementation_version_not_execution_episode": True,
            "supervisor_policy": guard.policy_desc,
            "pipeline_config": guard.config_desc,
            "scientific_source_unchanged": True,
        },
    )
    policy = module.BackpressurePolicy(
        root=config["raw_root"],
        journal_directory=directory / "events",
        source_root=config["source_root"],
        expected_sources=source_check(config),
        deadline_monotonic=guard.policy["deadline_monotonic"],
        oom_baseline=guard.policy["oom_baseline"],
        health_check=guard.health,
        max_wait_seconds=300,
    )
    with module.installed(policy):
        yield


class Terminated(BaseException):
    pass


def run_owned(
    argv, *, directory, cwd, env, log, health, binding, on_spawn=None, append=None
):
    """One real direct child; nonzero exit is returned, never promoted to completion."""
    owned = importlib.import_module(
        "operational.parameter_field_recovery06.owned_children"
    )
    owner = owned.OwnedChildren(
        directory,
        {
            "execution_episode": EPISODE,
            "component_schema_is_implementation_version_not_execution_episode": True,
            **binding,
        },
    )
    error, result, child = None, None, None
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        raise Terminated("Execution07 received termination signal " + str(signum))

    signal.signal(signal.SIGTERM, terminate)
    selector = selectors.DefaultSelector()
    try:
        health()
        child = owner.spawn(
            subprocess.Popen,
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if on_spawn:
            on_spawn(child)
        os.set_blocking(child.stdout.fileno(), False)
        selector.register(child.stdout, selectors.EVENT_READ)
        closed, count = False, 0
        while child.poll() is None or not closed:
            health()
            for key, unused in selector.select(timeout=0.2):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    closed = True
                else:
                    count += len(chunk)
                    require(
                        count <= 4 * 1024**2,
                        "Child log exceeded original four-MiB limit",
                    )
                    if append:
                        append(log, chunk)
                    else:
                        with Path(log).open("ab") as stream:
                            stream.write(chunk)
                            stream.flush()
                            os.fsync(stream.fileno())
        health()
        result = dict(child.wait4)
    except BaseException as caught:
        error = caught
    finally:
        selector.close()
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            closure = owner.close(
                error, None if result is None else result["exit_code"]
            )
        except BaseException as cleanup:
            if error is None:
                error = cleanup
            else:
                error.add_note("Owned cleanup also failed: " + str(cleanup))
        finally:
            signal.signal(signal.SIGTERM, previous)
    if error is not None:
        raise error
    require(
        closure["accounting_complete_for_attempted_direct_workers"]
        and closure["attempt_count"] == closure["returned_children"] == 1,
        "Owned child accounting is incomplete",
    )
    return {
        **result,
        "wait4_receipt": child.wait4_receipt,
        "ownership_closure": descriptor(Path(directory) / "CLOSURE.json"),
    }

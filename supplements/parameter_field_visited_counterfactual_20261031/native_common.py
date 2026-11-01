"""Strict native experiment identities, resources, and actual owned receipts."""

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import resource
import stat
import time

from . import counterfactual as k

EPISODE = "visited_counterfactual_fixed_tape_20261031"
SCHEMA = "hepta.visited-counterfactual.execution-contract.1"
OWN = Path(__file__).resolve().parent
ADDON = OWN.parents[1]
ROOT = Path("/work/visited_counterfactual")
SOURCE = Path("/work/source")
ASSETS = Path("/work/assets")
PROSPECTIVE_COMMIT = "1f19242236f5037b02f464dddc68984eab4588a6"
PROSPECTIVE = {
    "PROSPECTIVE_PLAN.json": {"bytes": 18324, "sha256": "f84cab71c8722d03b69ef07bc85f0048b31ad72f1e9941472750e21082bf0551"},
    "README.md": {"bytes": 24866, "sha256": "9dcccd293c5f66c3a181453699c649cca514abd9b3f30ebe4afabd5269c03e96"},
    "counterfactual.py": {"bytes": 24254, "sha256": "1ea5883ac9175b6ae4691d072818f31297ff096aac41786bb8f7433ecc334809"},
    "test_counterfactual.py": {"bytes": 15130, "sha256": "b820215a0b5ccabd05ab06ccf42e56b279e0c9ab3f66b1647f04ee056c789bcc"},
}
PATHS = tuple(dict.fromkeys(row["path_id"] for row in k.PARENTS.values()))
GIB = 1024**3


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            k.need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def reject(unused):
        raise ValueError("Nonfinite JSON constant")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def descriptor(path):
    path = Path(path)
    k.need(path.is_absolute() and path.resolve(strict=True) == path
           and stat.S_ISREG(path.lstat().st_mode), "Expected canonical regular file")
    before = path.stat()
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        k.need(identity(before) == identity(os.fstat(stream.fileno())) == identity(path.stat()),
               "File changed while hashing")
    return {"path": str(path), "bytes": before.st_size, "sha256": digest}


def checked(item):
    k.need(type(item) is dict and set(item) == {"path", "bytes", "sha256"}
           and type(item["bytes"]) is int and item["bytes"] >= 0, "Invalid literal descriptor")
    k.sha(item["sha256"])
    k.need(descriptor(item["path"]) == item, "Pinned literal bytes differ")
    return Path(item["path"])


def read(item, maximum=32 * 1024**2):
    path = checked(item)
    k.need(item["bytes"] <= maximum, "JSON input exceeds registered bound")
    raw = path.read_bytes()
    k.need(len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"],
           "JSON bytes changed before parse")
    return strict_json(raw)


def write(path, value):
    path = Path(path)
    k.need(path.is_absolute() and path.resolve() == path, "Output path is not canonical")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    k.need(len(raw) <= 32 * 1024**2, "Receipt exceeds registered bound")
    with path.open("xb") as stream:
        k.need(stream.write(raw) == len(raw), "Partial receipt write")
        stream.flush()
        os.fsync(stream.fileno())
    return descriptor(path)


def resources_checked(value):
    fields = {"cgroup_memory_bytes", "max_workers", "task_wall_seconds", "task_cpu_seconds",
              "shard_wall_seconds", "shard_cpu_seconds", "minimum_remaining_disk_bytes",
              "minimum_remaining_inodes", "maximum_task_bytes", "maximum_shard_bytes"}
    k.need(type(value) is dict and set(value) == fields
           and all(type(item) is int and item > 0 for item in value.values()),
           "Every new resource bound must be explicit and positive")
    k.need(value["cgroup_memory_bytes"] == 8 * GIB and value["max_workers"] in (1, 2)
           and value["shard_wall_seconds"] <= value["task_wall_seconds"]
           and value["shard_cpu_seconds"] <= value["task_cpu_seconds"]
           and value["minimum_remaining_disk_bytes"] >= 256 * 1024**2
           and value["minimum_remaining_inodes"] >= 2000
           and value["maximum_task_bytes"] >= 9511067776
           and value["maximum_shard_bytes"] <= value["maximum_task_bytes"],
           "New resources cannot truncate the fixed population or reuse the old one-GiB cap")
    return value


def actual_actions_identity():
    result = {key: os.environ.get(name) for key, name in (
        ("repository", "GITHUB_REPOSITORY"), ("run_id", "GITHUB_RUN_ID"),
        ("run_attempt", "GITHUB_RUN_ATTEMPT"), ("head_sha", "GITHUB_SHA"), ("job", "GITHUB_JOB"))}
    k.need(result["repository"] == "TrillionniumFoundation/hepta-private-ci"
           and all(type(result[key]) is str and result[key].isdigit() and int(result[key]) > 0
                   for key in ("run_id", "run_attempt"))
           and re.fullmatch("[0-9a-f]{40}", result["head_sha"] or "")
           and type(result["job"]) is str and bool(result["job"]),
           "Current real GitHub Actions identity is required")
    return result


def portable():
    return tuple(importlib.import_module("supplements.parameter_field_deployment_activity_execution08_20261101." + name)
                 for name in ("portable_common", "adapter", "portable_gate"))


def load_contract(path, expected):
    item = descriptor(Path(path).absolute())
    k.need(item["sha256"] == expected, "External new-experiment contract SHA differs")
    value = read(item, 4 * 1024**2)
    k.need(set(value) == {"schema", "execution_episode", "phase", "prospective_commit", "addon",
                         "portable_binding", "resources", "resource_qualification", "preparation_plan"}
           and value["schema"] == SCHEMA and value["execution_episode"] == EPISODE
           and value["phase"] == "original_fixed_tape" and value["prospective_commit"] == PROSPECTIVE_COMMIT,
           "Unknown or changed new-experiment contract")
    resources_checked(value["resources"])
    addon = value["addon"]
    k.need(set(addon) == {"registered_commit", "files"}, "Missing new executable source closure")
    prefix = str(OWN.relative_to(ADDON)) + "/"
    required = {prefix + path.name for path in OWN.iterdir()
                if path.suffix in (".py", ".json", ".md", ".mjs", ".yml")}
    required |= {prefix + "action.yml", prefix + "native_action.mjs",
                 ".github/workflows/parameter-field-visited-counterfactual.yml"}
    k.need(required <= set(addon["files"]), "Native execution source closure is incomplete")
    c, unused, unused_gate = portable()
    c.source_identity(ADDON, addon["registered_commit"], addon["files"], exact_head=False)
    c.source_identity(ADDON, PROSPECTIVE_COMMIT,
                      {prefix + name: pin for name, pin in PROSPECTIVE.items()}, exact_head=False)
    binding, binding_item = c.load_binding(value["portable_binding"]["path"], value["portable_binding"]["sha256"])
    k.need(binding_item == value["portable_binding"], "Original portable binding bytes differ")
    checked(value["resource_qualification"])
    checked(value["preparation_plan"])
    return value, item, binding


def owned_receipts(directory, expected_binding, argv=None):
    directory = Path(directory)
    items = {name: descriptor(directory / name) for name in
             ("INTENT.json", "001.INTENT.json", "001.START.json", "001.WAIT4.json", "CLOSURE.json")}
    intent, attempt, start, waited, closure = (read(items[name]) for name in items)
    binding = closure.get("binding", {})
    k.need(intent.get("schema") == "hepta.execution06.owned-children.intent.1"
           and closure.get("schema") == "hepta.execution06.owned-children.closure.1"
           and all(binding.get(key) == value for key, value in expected_binding.items())
           and binding.get("component_schema_is_implementation_version_not_execution_episode") is True
           and intent["binding"] == binding
           and intent["controller_identity"] == closure["controller_identity"],
           "Owned cost attribution belongs to another task")
    k.need(closure.get("all_returned_direct_children_reaped") is True
           and closure.get("accounting_complete_for_attempted_direct_workers") is True
           and closure.get("attempt_count") == closure.get("returned_children") == 1
           and len(closure.get("attempts", [])) == len(closure.get("children", [])) == 1
           and closure["children"][0].get("wait4") == waited
           and closure["children"][0].get("wait4_receipt") == items["001.WAIT4.json"]
           and closure["children"][0].get("wait4_unavailable") is None
           and closure["children"][0].get("identity") == waited.get("identity")
           and closure["children"][0].get("pid") == waited.get("pid")
           and start.get("identity") == waited.get("identity") and start.get("attempt") == 1
           and start.get("argv") == attempt.get("argv") and start.get("cwd") == attempt.get("cwd")
           and start.get("wait4_owner_pid") == intent["controller_identity"]["pid"]
           and start.get("process_groups_changed") is False
           and closure.get("original_exception") is None and closure.get("receipt_errors") == []
           and closure.get("cleanup_errors") == [] and closure.get("construction_wait4_unavailable") is False,
           "Owned wait4 did not close successfully")
    k.need(waited.get("exit_code") == 0 and type(waited.get("pid")) is int and waited["pid"] > 0
           and all(type(waited.get(key)) in (int, float) and math.isfinite(waited[key]) and waited[key] >= 0
                   for key in ("wall_seconds", "cpu_seconds", "user_cpu_seconds", "system_cpu_seconds", "peak_rss_bytes"))
           and math.isclose(waited["cpu_seconds"], waited["user_cpu_seconds"] + waited["system_cpu_seconds"], abs_tol=1e-9)
           and waited["identity"]["parent_pid"] == intent["controller_identity"]["pid"]
           and waited["identity"]["pid"] == waited["pid"]
           and attempt["number"] == closure["attempts"][0]["number"] == 1
           and closure["attempts"][0]["returned_child"] is True
           and closure["attempts"][0]["construction_entered"] is True
           and all(closure["attempts"][0][key] == attempt[key] for key in ("argv", "cwd", "executable"))
           and math.isclose(closure["direct_workers_cpu_seconds"], waited["cpu_seconds"], abs_tol=1e-9)
           and (argv is None or attempt["argv"] == argv), "Failed or mismatched real owned process")
    return {"files": items, "cpu_seconds": waited["cpu_seconds"], "wall_seconds": waited["wall_seconds"],
            "peak_rss_bytes": waited["peak_rss_bytes"], "pid": waited["pid"], "argv": attempt["argv"]}


def closed_wait4(directory, contract_item, phase, argv=None):
    return owned_receipts(directory, {"execution_episode": EPISODE, "execution_contract": contract_item, "phase": phase}, argv)


def process_cpu():
    current, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return current.ru_utime + current.ru_stime + children.ru_utime + children.ru_stime


def cgroup():
    node = Path("/sys/fs/cgroup")
    k.need((node / "memory.max").read_text().strip() == str(8 * GIB), "A real finite eight-GiB cgroup is required")
    events = dict(line.split() for line in (node / "memory.events").read_text().splitlines())
    return {key: int(events[key]) for key in ("oom", "oom_kill")}


class Health:
    def __init__(self, resources, scope, root, *, started=None, cpu_started=None, oom=None):
        self.resources, self.scope, self.root = resources_checked(resources), scope, Path(root)
        k.need(scope in ("task", "shard"), "Unknown resource scope")
        self.started = time.monotonic() if started is None else started
        self.cpu_started = process_cpu() if cpu_started is None else cpu_started
        self.oom = cgroup() if oom is None else oom
        self.check_at, self.bytes = -math.inf, 0

    def __call__(self, additional=0):
        k.need(type(additional) is int and additional >= 0, "Invalid pending byte count")
        k.need(time.monotonic() - self.started < self.resources[self.scope + "_wall_seconds"]
               and process_cpu() - self.cpu_started < self.resources[self.scope + "_cpu_seconds"],
               "Registered new experiment time/CPU ceiling exhausted")
        k.need(cgroup() == self.oom, "New experiment observed an OOM counter change")
        existing = self.root if self.root.exists() else self.root.parent
        space = os.statvfs(existing)
        k.need(space.f_bavail * space.f_frsize >= self.resources["minimum_remaining_disk_bytes"] + additional
               and space.f_favail >= self.resources["minimum_remaining_inodes"], "New physical reserve exhausted")
        if additional or time.monotonic() - self.check_at >= 1:
            self.bytes = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file()) if self.root.exists() else 0
            self.check_at = time.monotonic()
        k.need(self.bytes + additional <= self.resources["maximum_" + self.scope + "_bytes"],
               "New evidence scope exceeded its separately registered capacity")

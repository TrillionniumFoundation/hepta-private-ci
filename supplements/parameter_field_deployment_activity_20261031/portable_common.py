"""Strict identities and canonical paths for the separately registered replay."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import time

OWN = Path(__file__).resolve().parent
ADDON = OWN.parents[1]
SOURCE = Path("/work/source")
ASSETS = Path("/work/assets")
PREPARATION = Path("/work/preparation")
RUN = Path("/work/execution07")
OUTPUT = Path("/work/deployment_activity")
EPISODE = "deployment_activity_replay_20261031"
SOURCE_EPISODE = "execution07_actions_20261031"
GIB = 1024**3
PINS = {
    "pipeline_config": RUN / "ops/registrations/initial/PIPELINE_CONFIG.json",
    "primary_complete": RUN / "ops/COMPLETE.json",
    "manifest": RUN / "raw/evidence_v2/verification07/MANIFEST.json",
    "verified": RUN / "raw/evidence_v2/verification07/VERIFIED.json",
    "terminal_closure": RUN / "ops/TERMINAL_CLOSURE.json",
    "postseal_complete": RUN / "postseal/COMPLETE.json",
    "lifecycle_complete": RUN / "pipeline_measurement/COMPLETE.json",
}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def reject(unused):
        raise ValueError("Nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def relative(value):
    need(type(value) is str and value and len(value) <= 4096, "Invalid logical path")
    path = PurePosixPath(value)
    need(
        not path.is_absolute()
        and str(path) == value
        and ".." not in path.parts
        and "\\" not in value
        and "\x00" not in value
        and ":" not in value,
        "Noncanonical logical path",
    )
    return path


def fingerprint(path):
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode), "Expected a regular nonlinked file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def descriptor(path):
    path = Path(path)
    need(
        path.is_absolute() and path.resolve(strict=True) == path,
        "Expected canonical absolute file",
    )
    before = fingerprint(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        need(
            tuple(
                getattr(os.fstat(stream.fileno()), key)
                for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            )
            == before,
            "Opened file identity changed",
        )
    need(fingerprint(path) == before, "File changed while hashing")
    return {"path": str(path), "bytes": before[2], "sha256": digest}


def descriptor_shape(item):
    need(
        type(item) is dict
        and set(item) == {"path", "bytes", "sha256"}
        and type(item["path"]) is str
        and Path(item["path"]).is_absolute()
        and type(item["bytes"]) is int
        and item["bytes"] >= 0
        and type(item["sha256"]) is str
        and re.fullmatch("[0-9a-f]{64}", item["sha256"]),
        "Malformed external descriptor",
    )


def checked(item):
    descriptor_shape(item)
    need(descriptor(Path(item["path"])) == item, "Bound bytes differ: " + item["path"])
    return Path(item["path"])


def read(item, maximum=32 * 1024**2):
    path = checked(item)
    need(item["bytes"] <= maximum, "JSON exceeds registered read bound")
    raw = path.read_bytes()
    need(
        len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"],
        "Input changed before decoding",
    )
    return strict_json(raw)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    need(len(raw) <= 32 * 1024**2, "Receipt exceeds bound")
    with path.open("xb") as stream:
        need(stream.write(raw) == len(raw), "Partial receipt write")
        stream.flush()
        os.fsync(stream.fileno())
    return descriptor(path)


def git(root, *args):
    return subprocess.run(
        ["git", "-c", "safe.directory=" + str(root), "-C", str(root), *args],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout


def source_identity(root, commit, files, *, exact_head):
    need(
        re.fullmatch("[0-9a-f]{40}", commit or "") and type(files) is dict and files,
        "Missing registered source commit or inventory",
    )
    head = git(root, "rev-parse", "HEAD").decode().strip()
    if exact_head:
        need(head == commit, "Original source checkout HEAD differs")
    else:
        git(root, "merge-base", "--is-ancestor", commit, head)
    need(
        not git(
            root, "status", "--porcelain", "--untracked-files=all", "--ignored=matching"
        ).strip(),
        "Source checkout is not pristine",
    )
    for name, item in files.items():
        relative(name)
        need(
            type(item) is dict
            and set(item) == {"bytes", "sha256"}
            and type(item["bytes"]) is int
            and item["bytes"] >= 0
            and type(item["sha256"]) is str
            and re.fullmatch("[0-9a-f]{64}", item["sha256"]),
            "Invalid source pin",
        )
        actual = descriptor(root / name)
        need(
            {k: actual[k] for k in item} == item,
            "Current registered source bytes differ",
        )
        raw = git(root, "show", commit + ":" + name)
        need(
            len(raw) == item["bytes"]
            and hashlib.sha256(raw).hexdigest() == item["sha256"],
            "Source pin does not match its registered Git blob",
        )
    return {"registered_commit": commit, "actual_checkout_head": head, "files": files}


def load_binding(path, expected):
    item = descriptor(Path(path).absolute())
    need(item["sha256"] == expected, "External binding SHA differs")
    value = read(item, 1024 * 1024)
    need(
        set(value) == {"schema", "provider", "producer_job", "pins", "addon"}
        and value["schema"] == "hepta.parameter-field.deployment-replay-binding.1",
        "Unknown replay binding schema",
    )
    from .provider import validate_request

    validate_request(value["provider"])
    need(
        type(value["producer_job"]) is str and value["producer_job"],
        "Original producer job missing",
    )
    need(
        set(value["pins"]) == set(PINS),
        "Exact original completion pin population required",
    )
    for name, pin in value["pins"].items():
        descriptor_shape(pin)
        need(
            pin["path"] == str(PINS[name]),
            "Original completion is outside canonical path",
        )
    addon = value["addon"]
    need(
        set(addon) == {"registered_commit", "files"}, "Unknown additive source binding"
    )
    names = {str(path.relative_to(ADDON)) for path in OWN.glob("*.py")}
    names |= {
        str((OWN / name).relative_to(ADDON))
        for name in ("PROSPECTIVE_PLAN.json", "ADMISSION_PLAN.json")
    }
    names.add(".github/workflows/parameter-field-deployment-activity.yml")
    need(
        names <= set(addon["files"]), "Additive executable source closure is incomplete"
    )
    source_identity(ADDON, addon["registered_commit"], addon["files"], exact_head=False)
    admission = read(descriptor(OWN / "ADMISSION_PLAN.json"))
    need(
        admission["parent_prospective_commit"]
        == "0ef83d0cbb0c50d147df93badc348c99555e357a",
        "Original prospective registration changed",
    )
    protected = {
        str((OWN / name).relative_to(ADDON)): pin
        for name, pin in admission["parent_prospective_files"].items()
    }
    need(
        set(admission["parent_prospective_files"])
        == {"activity.py", "test_activity.py", "PROSPECTIVE_PLAN.json", "README.md"},
        "Original four-file prospective population changed",
    )
    source_identity(
        ADDON, admission["parent_prospective_commit"], protected, exact_head=False
    )
    return value, item


def original_source(binding):
    commit = binding["provider"]["head_sha"]
    need(
        git(SOURCE, "rev-parse", "HEAD").decode().strip() == commit,
        "Wrong original source checkout",
    )
    need(
        not git(
            SOURCE,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--ignored=matching",
        ).strip(),
        "Original source checkout has changed",
    )
    return commit


def health(deadline, baseline_oom):
    need(time.monotonic() < deadline, "Replay operational deadline exceeded")
    node = Path("/sys/fs/cgroup")
    need(
        (node / "memory.max").read_text().strip() == str(8 * GIB),
        "Replay requires the actual finite eight-GiB cgroup",
    )
    events = dict(
        line.split() for line in (node / "memory.events").read_text().splitlines()
    )
    need(
        {key: int(events[key]) for key in ("oom", "oom_kill")} == baseline_oom,
        "Replay cgroup observed a new out-of-memory event",
    )
    space = os.statvfs(OUTPUT)
    need(
        space.f_bavail * space.f_frsize >= 256 * 1024**2 and space.f_favail >= 2000,
        "Replay exhausted the original physical reserve",
    )

"""Execution07 metadata identities. No model/data decoder is imported here."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


EPISODE = "execution07_actions_20261031"
SCHEMA = "hepta.fullstudy.execution07.configuration.1"
ORDER = ("A-17", "A-29", "A-43", "C", "B-17", "B-29", "B-43", "W",
         "R-17", "R-29", "R-43", "A_endpoint", "B_endpoint", "C_endpoint")
OWN = Path(__file__).resolve().parent
SOURCE = OWN.parents[1]
PREFIX = "experiments/parameter_field_fullstudy_20261029/"
PROTOCOL_SHA = "2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55"


def need(condition, message):
    if not condition:
        raise ValueError(message)


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, "Duplicate JSON key")
            value[key] = item
        return value
    def constant(_):
        raise ValueError("Nonfinite JSON constant")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def regular(path):
    path = Path(path).absolute()
    need(path.resolve(strict=True) == path and path.is_file() and not path.is_symlink(),
         "Missing or noncanonical regular file: " + str(path))
    return path


def descriptor(path):
    path = regular(path)
    before = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    need(all(getattr(before, k) == getattr(after, k) for k in fields), "File changed during hashing")
    return {"path": str(path), "bytes": after.st_size, "sha256": digest}


def checked(item):
    need(type(item) is dict and set(item) == {"path", "bytes", "sha256"}
         and type(item["bytes"]) is int and item["bytes"] >= 0
         and re.fullmatch(r"[0-9a-f]{64}", item["sha256"] or ""), "Invalid descriptor")
    need(descriptor(item["path"]) == item, "Bound file bytes differ: " + item["path"])
    return Path(item["path"])


def bound(item):
    path = checked(item)
    need(item["bytes"] <= 32 * 1024 * 1024, "Metadata exceeds bound")
    raw = path.read_bytes()
    need(len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"], "Read identity changed")
    return strict_json(raw)


def read(path):
    return bound(descriptor(path))


def write_new(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(encode(value))
        stream.flush()
        os.fsync(stream.fileno())
    return descriptor(path)


def git(root, *args):
    return subprocess.run(["git", "-c", "safe.directory=" + str(root), "-C", str(root), *args],
                          capture_output=True, check=True, timeout=60).stdout


def committed_sources(root, commit, sources):
    root = Path(root).resolve(strict=True)
    need(re.fullmatch(r"[0-9a-f]{40}", commit or ""), "A full committed source identity is required")
    need(git(root, "rev-parse", "HEAD").decode().strip() == commit, "Source HEAD differs from registration")
    need(not git(root, "status", "--porcelain", "--untracked-files=all", "--ignored=matching").strip(),
         "Source checkout has uncommitted or untracked files")
    tree = {}
    for row in git(root, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if row:
            metadata, name = row.split(b"\t", 1)
            mode, kind, digest = metadata.split()
            if kind == b"blob" and mode in (b"100644", b"100755"):
                tree[name.decode()] = digest.decode()
    for name, digest in sources.items():
        relative = Path(name)
        need(not relative.is_absolute() and ".." not in relative.parts and relative.as_posix() == name,
             "Noncanonical source name")
        path = regular(root / name)
        need(descriptor(path)["sha256"] == digest, "Source bytes changed: " + name)
        h = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                h.update(chunk)
        need(tree.get(name) == h.hexdigest(), "Source bytes are outside the declared commit: " + name)
    return tree


def load_config(path, expected_sha256, *, verify_sources=True):
    item = descriptor(path)
    need(item["sha256"] == expected_sha256, "Externally fixed configuration SHA differs")
    config = bound(item)
    need(config.get("schema") == SCHEMA and config.get("execution_episode") == EPISODE
         and config.get("job_order") == list(ORDER) and config.get("imported_jobs") == []
         and config.get("new_scientific_jobs") == list(ORDER), "Wrong episode or fresh job population")
    contract = read(OWN / "INPUT_CONTRACT.json")
    for name in ("source_root", "ops_root", "raw_root", "cas_root", "python", "assets_root"):
        need(config[name] == contract[name], "Registered destination differs: " + name)
    need(Path(config["source_root"]) == SOURCE and config["empty_cwd"] == str(Path(config["ops_root"]) / "empty_cwd"),
         "Configuration is not for this checkout")
    for name in ("amendment", "initial_queue", "controller_freeze", "runtime_receipt", "a_freeze", "c_freeze", "prospective_plan"):
        checked(config["descriptors"][name])
    if verify_sources:
        committed_sources(SOURCE, config["source_commit"], config["source_files"])
    return config, item

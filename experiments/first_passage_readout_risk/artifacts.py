"""Standard-library-only freezing and immutable artifact bookkeeping."""

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREFIX = HERE.relative_to(ROOT).as_posix()
LIMIT = 480_000


def read_json(path):
    return json.loads(Path(path).read_text())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def entry(path, root):
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "bytes": len(data), "sha256": sha(data)}


def write_bytes(path, data):
    if len(data) >= LIMIT:
        raise ValueError("Artifact exceeds the frozen per-file bound: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def write_json(path, value):
    write_bytes(path, json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")


def protocol():
    config = read_json(HERE / "PROTOCOL.json")
    if (config.get("schema"), config.get("namespace")) != (
            "hepta.readout-risk.v2-protocol.v1", "hepta.network.readout-risk.v2.20261030"):
        raise ValueError("Unrecognized registered protocol identity")
    return config


def registered_paths(config):
    return sorted(config["source_paths"] + [row["path"] for row in config["encoders"]])


def current_files(config):
    paths = registered_paths(config)
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate frozen path")
    if any(Path(path).is_absolute() or ".." in Path(path).parts for path in paths):
        raise ValueError("Frozen paths must be relative repository paths")
    proposal = config["proposal"]
    if proposal["path"] not in paths or sha((ROOT / proposal["path"]).read_bytes()) != proposal["sha256"]:
        raise ValueError("The registered proposal identity differs")
    for row in config["encoders"]:
        path = ROOT / row["path"]
        if sha(path.read_bytes()) != row["sha256"]:
            raise ValueError("Frozen encoder checkpoint differs: " + row["path"])
        fit = read_json(path)
        if (fit["seed"], fit["task"], fit["kind"], fit["parameters"]) != (
                row["seed"], "order", "first_passage", 55):
            raise ValueError("Unexpected frozen encoder contract")
        for name, digest in fit["source_sha256"].items():
            if sha((ROOT / "experiments/first_passage_operator" / name).read_bytes()) != digest:
                raise ValueError("Original checkpoint source changed: " + name)
    return [entry(ROOT / path, ROOT) for path in paths]


def freeze_record(config):
    return {"schema": "hepta.readout-risk.v2-freeze.v1", "namespace": config["namespace"],
            "files": current_files(config), "data_generated": False,
            "encoder_executed": False, "head_fits": 0,
            "random_streams": "Only the symbolic ranges/formula in PROTOCOL are frozen; no new identities generated."}


def freeze():
    if (HERE / "RUN_REQUEST.json").exists():
        raise ValueError("A protocol freeze must precede creation of its execution request")
    write_json(HERE / "FREEZE.json", freeze_record(protocol()))
    return entry(HERE / "FREEZE.json", ROOT)


def verify_freeze():
    config, frozen = protocol(), read_json(HERE / "FREEZE.json")
    if canonical(frozen) != canonical(freeze_record(config)):
        raise ValueError("Working source/input bytes differ from the pre-execution freeze")
    return config, frozen


def verify_execution_commit(commit):
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ValueError("A full lowercase published freeze commit is required")
    config, frozen = verify_freeze()
    git = lambda *args: subprocess.check_output(["git", *args], cwd=ROOT)
    lineage = git("rev-list", "--parents", "-n", "1", "HEAD").decode().split()
    if len(lineage) != 2 or lineage[1] != commit:
        raise ValueError("The execution HEAD must have exactly the frozen commit as its parent")
    if git("log", "-1", "--format=%s").decode().strip() != "research: execute frozen readout-risk v2":
        raise ValueError("This is not the dedicated one-shot execution commit")
    changed = git("diff", "--name-status", "--no-renames", commit, "HEAD", "--").decode().splitlines()
    if changed != [f"A\t{PREFIX}/RUN_REQUEST.json"]:
        raise ValueError("The execution commit must only add its new RUN_REQUEST")
    request_path = HERE / "RUN_REQUEST.json"
    request = read_json(request_path)
    expected = {"schema": "hepta.readout-risk.v2-run-request.v1", "namespace": config["namespace"],
                "freeze_commit": commit, "one_shot": True}
    if canonical(request) != canonical(expected) or git("show", f"HEAD:{PREFIX}/RUN_REQUEST.json") != request_path.read_bytes():
        raise ValueError("RUN_REQUEST is not the committed exact execution request")
    for row in frozen["files"] + [entry(HERE / "FREEZE.json", ROOT)]:
        data = git("show", commit + ":" + row["path"])
        if len(data) != row["bytes"] or sha(data) != row["sha256"]:
            raise ValueError("Published parent differs from frozen input: " + row["path"])
    return config, {"freeze_commit": commit, "execution_commit": lineage[0],
                    "freeze_sha256": sha((HERE / "FREEZE.json").read_bytes()),
                    "request_sha256": sha(request_path.read_bytes())}


def manifest(directory):
    rows = [entry(path, directory) for path in sorted(directory.rglob("*")) if path.is_file()]
    if any(row["bytes"] >= LIMIT for row in rows):
        raise ValueError("Output blob exceeds the registered bound")
    write_json(directory / "ARTIFACT_MANIFEST.json", {"schema": "hepta.readout-risk.v2-artifacts.v1", "files": rows})


def verify_artifacts(directory):
    rows = read_json(directory / "ARTIFACT_MANIFEST.json")["files"]
    actual = [entry(path, directory) for path in sorted(directory.rglob("*"))
              if path.is_file() and path.name != "ARTIFACT_MANIFEST.json"]
    if rows != actual:
        raise ValueError("The retained run artifacts differ from their immutable manifest")

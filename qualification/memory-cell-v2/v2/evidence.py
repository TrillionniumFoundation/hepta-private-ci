"""Bind complete run artifacts to exact committed code and fixed source data."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


V1 = "qualification/memory-cell-research"
V2 = "qualification/memory-cell-v2"
HEX40 = re.compile(r"[0-9a-f]{40}")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def fingerprint(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def source_member(name):
    """The same predicate is applied to worktree paths and committed git paths."""
    path = PurePosixPath(name)
    if any(
        p in {"results", "__pycache__"} or p.startswith(".scratch") for p in path.parts
    ):
        return False
    if name.startswith(V1 + "/"):
        return path.suffix == ".py" or path.name in {
            "PROTOCOL.json",
            "requirements.txt",
        }
    if name.startswith(V2 + "/"):
        return (
            path.suffix == ".py"
            or path.name
            in {
                "PROTOCOL.json",
                "MODEL_SOURCE.json",
                "requirements.txt",
                "requirements-report.txt",
            }
            or name.startswith(V2 + "/sources/")
        )
    return False


def checked_path(root, name):
    root = Path(root)
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or str(relative) != name:
        raise ValueError("noncanonical or escaping evidence path")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink in evidence path")
    if not current.is_file():
        raise ValueError("evidence path is not a regular file")
    return current


def _files(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("evidence root must be an ordinary directory")
    result = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlinks are not admitted to evidence inventories")
        if path.is_file():
            result.append(path.relative_to(root).as_posix())
    return sorted(result)


def source_identity(repo, commit=None):
    repo = Path(repo).resolve()
    if commit is None:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip()
    if not HEX40.fullmatch(commit):
        raise ValueError("source must use an exact forty-character git commit")
    names = []
    for prefix in (V1, V2):
        for name in _files(repo / prefix):
            full = prefix + "/" + name
            if source_member(full):
                names.append(full)
    if not names:
        raise ValueError("empty source inventory")
    return {
        "schema": "memory-cell-v2.source.v1",
        "commit": commit,
        "files": {
            name: fingerprint(checked_path(repo, name).read_bytes())
            for name in sorted(names)
        },
    }


def verify_sources(identity, repo, *, development=False):
    repo = Path(repo).resolve()
    if identity.get("schema") != "memory-cell-v2.source.v1" or not HEX40.fullmatch(
        identity.get("commit", "")
    ):
        raise ValueError("invalid source identity")
    current = source_identity(repo, identity["commit"])
    if current != identity:
        raise ValueError("current source bytes/inventory differ from executed source")
    if not development:
        paths = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", identity["commit"], "--", V1, V2],
            cwd=repo,
            text=True,
        ).splitlines()
        if {name for name in paths if source_member(name)} != set(identity["files"]):
            raise ValueError("source inventory differs from claimed commit")
        for name, expected in identity["files"].items():
            raw = subprocess.check_output(
                ["git", "show", f"{identity['commit']}:{name}"], cwd=repo
            )
            if fingerprint(raw) != expected:
                raise ValueError(f"source differs from committed bytes: {name}")
    return {
        "source_files": len(identity["files"]),
        "source_commit": identity["commit"],
        "commit_binding": "uncommitted-development"
        if development
        else "exact-committed-bytes",
    }


def source_snapshot(path, identity, repo):
    """Preserve exact code/data even for an uncommitted development failure."""
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, expected in identity["files"].items():
            raw = checked_path(repo, name).read_bytes()
            if fingerprint(raw) != expected:
                raise ValueError(
                    "source changed while preparing the execution snapshot"
                )
            archive.writestr(name, raw)


def verify_snapshot(path, identity):
    with zipfile.ZipFile(path) as archive:
        if len(archive.namelist()) != len(identity["files"]) or set(
            archive.namelist()
        ) != set(identity["files"]):
            raise ValueError("source snapshot inventory differs")
        for name, expected in identity["files"].items():
            if (
                archive.getinfo(name).file_size != expected["bytes"]
                or fingerprint(archive.read(name)) != expected
            ):
                raise ValueError("source snapshot bytes differ")


def seal_run(directory, identity):
    directory = Path(directory)
    names = _files(directory)
    if "MANIFEST.json" in names:
        raise ValueError("refuse to reseal or overwrite an existing run manifest")
    manifest = {
        "schema": "memory-cell-v2.evidence.v1",
        "source_commit": identity["commit"],
        "source_identity": fingerprint(
            (directory / "source_identity.json").read_bytes()
        ),
        "files": {
            name: fingerprint(checked_path(directory, name).read_bytes())
            for name in names
        },
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "integrity_does_not_establish_efficacy": True,
    }
    write_json(directory / "MANIFEST.json", manifest)
    return fingerprint((directory / "MANIFEST.json").read_bytes())


def verify_run(directory, repo, *, allow_failed=False):
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("evidence root must not be a symlink")
    directory = directory.resolve()
    manifest = json.loads(checked_path(directory, "MANIFEST.json").read_text())
    if manifest.get("schema") != "memory-cell-v2.evidence.v1":
        raise ValueError("unknown evidence schema")
    names = set(_files(directory)) - {"MANIFEST.json"}
    if names != set(manifest["files"]):
        raise ValueError("evidence inventory differs")
    for name, expected in manifest["files"].items():
        if fingerprint(checked_path(directory, name).read_bytes()) != expected:
            raise ValueError(f"evidence byte mismatch: {name}")
    raw_identity = (directory / "source_identity.json").read_bytes()
    identity = json.loads(raw_identity)
    if (
        identity["commit"] != manifest["source_commit"]
        or fingerprint(raw_identity) != manifest["source_identity"]
    ):
        raise ValueError("manifest/source identity mismatch")
    verify_snapshot(checked_path(directory, "source_snapshot.zip"), identity)
    env = json.loads((directory / "environment.json").read_text())
    development = env.get("mode") == "development_only"
    if env.get("mode") not in {"development_only", "frozen_protocol_research"}:
        raise ValueError("unknown execution mode")
    verified = verify_sources(identity, repo, development=development)
    protocol = json.loads((directory / "protocol.json").read_text())
    if (
        fingerprint((directory / "protocol.json").read_bytes())
        != identity["files"][V2 + "/PROTOCOL.json"]
    ):
        raise ValueError("executed protocol is not the frozen protocol")
    seeds = protocol["development_seeds"] if development else protocol["seeds"]
    if env["selected_seeds"] != seeds:
        raise ValueError("execution seeds differ from the frozen mode")
    status = json.loads((directory / "execution_status.json").read_text())
    stages = protocol["stages"]
    if (
        not stages
        or len(set(stages)) != len(stages)
        or any(s not in {"routing", "real", "growth", "external"} for s in stages)
    ):
        raise ValueError("invalid protocol stage inventory")
    if env.get("stage") == "all":
        requested = stages
    elif env.get("stage") in stages:
        requested = [env["stage"]]
    else:
        raise ValueError("unknown requested stage")
    completed = status.get("completed_stages")
    if not isinstance(completed, list) or completed != requested[: len(completed)]:
        raise ValueError("completed stages are not a prefix of requested stages")
    if status["execution"] not in {"completed", "failed", "aborted"}:
        raise ValueError("execution lacks a terminal status")
    result_name = (
        "results.json" if status["execution"] == "completed" else "partial_results.json"
    )
    results = json.loads(checked_path(directory, result_name).read_text())
    if set(results) != set(completed) or (
        status["execution"] == "completed" and completed != requested
    ):
        raise ValueError("result stages differ from the declared completed execution")
    for result in results.values():
        if result.get("development_only") != development or {
            run["seed"] for run in result.get("runs", [])
        } != set(seeds):
            raise ValueError("component result seeds/mode differ from execution")
    if status["execution"] != "completed" and not allow_failed:
        raise ValueError("run did not complete")
    return {
        **verified,
        "verified": True,
        "verified_files": len(names),
        "execution": status["execution"],
        "mode": env["mode"],
        "completed_stages": completed,
        "scientific_efficacy_not_inferred": True,
        "manifest_sha256": fingerprint((directory / "MANIFEST.json").read_bytes())[
            "sha256"
        ],
    }

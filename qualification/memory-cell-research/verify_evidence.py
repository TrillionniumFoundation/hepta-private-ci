"""Verify the exact source and complete file inventory of a MemoryCell run."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def verify(directory, repo):
    directory, repo = Path(directory).resolve(), Path(repo).resolve()
    manifest_path = directory / "MANIFEST.json"
    if manifest_path.is_symlink():
        raise ValueError("root evidence manifest must not be a symlink")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "memory-cell-research.evidence.v1":
        raise ValueError("unknown evidence schema")
    observed = {
        p.relative_to(directory).as_posix()
        for p in directory.rglob("*")
        if p.is_file() and p.relative_to(directory).as_posix() != "MANIFEST.json"
    }
    if observed != set(manifest["files"]):
        raise ValueError("evidence file inventory differs")
    for name, expected in manifest["files"].items():
        path = directory / name
        if path.is_symlink() or not path.resolve().is_relative_to(directory):
            raise ValueError("evidence path escapes its run")
        payload = path.read_bytes()
        if expected != {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }:
            raise ValueError(f"evidence byte mismatch: {name}")
    identity = json.loads((directory / "source_identity.json").read_text())
    if identity["commit"] != manifest["source_commit"] or not re.fullmatch(
        r"[0-9a-f]{40}", identity["commit"]
    ):
        raise ValueError("source commit mismatch")
    package = repo / "qualification/memory-cell-research"
    expected_sources = {
        p.relative_to(repo).as_posix()
        for p in package.rglob("*")
        if p.is_file()
        and (p.suffix == ".py" or p.name in {"PROTOCOL.json", "requirements.txt"})
        and not any(
            part.startswith(".scratch") or part == "results" for part in p.parts
        )
    }
    if not expected_sources or expected_sources != set(identity["files"]):
        raise ValueError("source inventory is empty or incomplete")
    environment = json.loads((directory / "environment.json").read_text())
    development = (
        environment.get("mode") == "development_smoke"
        and environment.get("source_dirty") is True
    )
    if not development:
        tree_paths = subprocess.check_output(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                identity["commit"],
                "--",
                "qualification/memory-cell-research",
            ],
            cwd=repo,
            text=True,
        ).splitlines()
        committed_sources = {
            name
            for name in tree_paths
            if (
                Path(name).suffix == ".py"
                or Path(name).name in {"PROTOCOL.json", "requirements.txt"}
            )
            and not any(
                part.startswith(".scratch") or part == "results"
                for part in Path(name).parts
            )
        }
        if committed_sources != set(identity["files"]):
            raise ValueError("source inventory differs from claimed commit")
    for name, digest in identity["files"].items():
        path = repo / name
        if path.is_symlink() or not path.resolve().is_relative_to(repo):
            raise ValueError("source path escapes repository")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"current source differs from executed source: {name}")
        if not development:
            committed = subprocess.check_output(
                ["git", "show", f"{identity['commit']}:{name}"], cwd=repo
            )
            if hashlib.sha256(committed).hexdigest() != digest:
                raise ValueError(f"execution source is not the claimed commit: {name}")
    if (
        json.loads((directory / "execution_status.json").read_text())["execution"]
        != "completed"
    ):
        raise ValueError("run did not complete")
    return {
        "verified_files": len(observed),
        "source_files": len(identity["files"]),
        "source_commit": identity["commit"],
        "verified": True,
        "commit_binding": "uncommitted-development"
        if development
        else "exact-committed-bytes",
        "scientific_efficacy_not_inferred": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.repo), sort_keys=True))

"""Bounded command receipts and lossless source/evidence verification for cloud pilots."""

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile
import time

LIMIT = 64 * 1024**2


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def verify_source(root, manifest, pin, source_sha):
    root = Path(root).resolve()
    if sha(manifest) != pin:
        raise ValueError("Source manifest differs from external pin")
    data = json.loads(Path(manifest).read_text())
    if (
        data["source_sha"] != source_sha
        or len(source_sha) != 40
        or sum(r["bytes"] for r in data["files"]) > 2 * 1024**2
    ):
        raise ValueError("Wrong source head or source bundle exceeds 2 MiB")
    names = set()
    for row in data["files"]:
        name = PurePosixPath(row["path"])
        path = root / name
        if (
            name.is_absolute()
            or ".." in name.parts
            or str(name) in names
            or path.is_symlink()
            or not path.resolve().is_relative_to(root)
        ):
            raise ValueError("Unsafe or repeated source path")
        if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("Source file differs from the frozen manifest")
        names.add(str(name))
    if any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Source bundle symlinks are forbidden")
    actual = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    if actual != names:
        raise ValueError("Unlisted or absent source bundle file")
    return data


@contextmanager
def command_log(path):
    sys.stdout.flush()
    sys.stderr.flush()
    saved = [os.dup(1), os.dup(2)]
    try:
        with Path(path).open("wb") as stream:
            os.dup2(stream.fileno(), 1)
            os.dup2(stream.fileno(), 2)
            yield
    finally:
        for fd, previous in zip((1, 2), saved, strict=True):
            os.dup2(previous, fd)
            os.close(previous)


class Commands:
    def __init__(self, root, report, deadline):
        self.root, self.report, self.deadline = Path(root), report, deadline

    def execute(self, name, command):
        from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.meter import (
            execute,
        )

        row = next(r for r in self.report["stages"] if r["name"] == name)
        limit = min(
            row["wall_cap_seconds"], self.deadline - time.perf_counter() - 45 - 5
        )
        row.update(command=list(command), actual_wall_limit=limit)
        if limit <= 0:
            row["status"] = "not_started_total_budget_exhausted"
            raise TimeoutError("No total-budget reserve remains for a physical command")
        receipt = self.root / (name + ".meter.json")
        with command_log(self.root / (name + ".log")):
            result = execute(
                command,
                receipt,
                wall_timeout_seconds=limit,
                termination_grace_seconds=1,
            )
        row.update(
            status=result["status"],
            return_code=result["return_code"],
            meter_sha256=sha(receipt),
        )
        write(self.root / "CAMPAIGN.json", self.report)
        print(
            json.dumps(
                {
                    "phase": name,
                    "status": row["status"],
                    "return_code": row["return_code"],
                }
            ),
            flush=True,
        )
        if result["return_code"] != 0 or result["status"] != "completed":
            raise RuntimeError("Physical phase failed: " + name)


def pack_evidence(roots, output, deadline, cap=LIMIT - 1024**2):
    """Lossless CAS: repeated public PNGs retain every path while storing bytes once."""
    index, unique = [], {}
    for label, root in roots.items():
        for path in sorted(Path(root).rglob("*")):
            if path.is_symlink():
                raise ValueError("Evidence symlink is not retained")
            if not path.is_file():
                continue
            identity = sha(path)
            unique.setdefault(identity, path)
            index.append(
                {
                    "path": label + "/" + path.relative_to(root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": identity,
                }
            )
    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        data = json.dumps(
            {"schema": "hepta.lossless-cas-evidence.v1", "files": index}, sort_keys=True
        ).encode()
        member = tarfile.TarInfo("index.json")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
        for identity, path in unique.items():
            if time.perf_counter() >= deadline or Path(output).stat().st_size > cap:
                raise TimeoutError("Evidence packaging time/size cap reached")
            archive.add(path, arcname="blobs/" + identity, recursive=False)
    if Path(output).stat().st_size > cap:
        raise ValueError("Evidence pack exceeds its declared cap")
    return {
        "file_paths": len(index),
        "unique_blobs": len(unique),
        "bytes": Path(output).stat().st_size,
        "sha256": sha(output),
    }


def artifact_manifest(output, request_id):
    output = Path(output)
    files = [
        {
            "path": p.relative_to(output).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": sha(p),
        }
        for p in sorted(output.rglob("*"))
        if p.is_file() and p != output / "artifact-manifest.json"
    ]
    if sum(r["bytes"] for r in files) > LIMIT:
        raise ValueError("Export directory exceeds 64 MiB")
    result = {
        "schema": "hepta-artifact-manifest-v1",
        "request_id": request_id,
        "files": files,
    }
    write(output / "artifact-manifest.json", result)
    return result

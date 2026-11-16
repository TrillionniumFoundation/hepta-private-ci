"""Exact-source receipts for the bounded pretrained service/network trial."""

from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def retain(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(plain(value), stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def source_identity():
    root = Path(__file__).resolve().parents[1]
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in sorted(root.glob("memory_cell*"))
        if directory.is_dir()
        for path in sorted(directory.glob("*.py"))
    }
    return {
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "files_sha256": files,
        "manifest_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def raw_signature(journal):
    return [
        {key: row[key] for key in ("text", "token_ids", "prompt_sha256")}
        for row in journal["rows"]
    ]


def exact(journal, facts):
    values = [
        row["text"].strip() == fact["value"]
        for row, fact in zip(journal["rows"], facts)
    ]
    if len(journal["rows"]) != len(facts) or not facts:
        raise ValueError("complete nonempty generation/fact alignment required")
    return {
        "correct": sum(values),
        "total": len(values),
        "accuracy": sum(values) / len(values),
        "per_source": values,
    }


def wait_for_claim(queue, job_id, future, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = queue.status(job_id)
        if row and row["state"] == "running":
            return row
        if future.done():
            raise RuntimeError("background trainer ended before its claim was observed")
        time.sleep(0.02)
    raise TimeoutError("background training claim not observed within deadline")

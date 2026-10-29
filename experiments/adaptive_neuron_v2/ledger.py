"""Immutable bounded receipts and explicit operation-cost intervals."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import tempfile
import time


MAX_GIT_RECEIPT_BYTES = 512_000


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_exclusive(path, payload):
    """Atomically publish one complete receipt, refusing overwrite or NaN."""
    path = Path(path)
    data = (
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    if len(data) > MAX_GIT_RECEIPT_BYTES:
        raise ValueError(
            "Receipt exceeds the repository limit; retain large raw evidence as an artifact"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"path": str(path), "bytes": len(data), "sha256": sha(path)}


def process_cost():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "self_user_seconds": own.ru_utime,
        "self_system_seconds": own.ru_stime,
        "child_user_seconds": children.ru_utime,
        "child_system_seconds": children.ru_stime,
    }


@contextmanager
def measured_stage(destination, *, identity, scope):
    """Measure the entire yielded interval, retaining failed-stage identity."""
    started = time.perf_counter()
    before = process_cost()
    started_utc = datetime.now(timezone.utc).isoformat()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(
        destination / "START.json",
        {
            "identity": identity,
            "scope": scope,
            "started_at_utc": started_utc,
        },
    )
    facts = {}
    error = None
    try:
        yield facts
    except BaseException as caught:
        error = {"type": type(caught).__name__, "message": str(caught)}
        raise
    finally:
        after = process_cost()
        record = {
            "schema": "hepta.adaptive-neuron.cost-stage.v2",
            "identity": identity,
            "scope": scope,
            "started_at_utc": started_utc,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": time.perf_counter() - started,
            "cpu": {key: after[key] - before[key] for key in before},
            "complete": error is None,
            "error": error,
            "facts": facts,
            "accounting": "This enclosing interval includes child subprocesses. Nested receipts explain its components and must not be added to it again.",
        }
        write_json_exclusive(
            destination / ("COMPLETE.json" if error is None else "FAILED.json"), record
        )

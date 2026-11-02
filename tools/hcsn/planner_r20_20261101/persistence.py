"""Linux atomic query-boundary checkpoints, with acknowledgement after dir fsync."""

import hashlib
import json
import os


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def load(path):
    payload = json.loads(path.read_bytes())
    body = dict(payload)
    digest = body.pop("sha256", None)
    if digest != hashlib.sha256(canonical(body)).hexdigest():
        raise ValueError("Checkpoint envelope checksum mismatch")
    if body.get("schema") != "hcsn-r20-query-checkpoint-v1":
        raise ValueError("Unsupported checkpoint envelope")
    return payload


def persist(path, body, phase_hook=None):
    """Replace one complete checkpoint; only return after durable directory ack.

    Temporary names are fixed per trusted single writer. An orphan temp file
    from a killed writer is replaced on retry. This is not a multiwriter lease.
    Hooks are used only for separately measured process-death controls.
    """
    payload = dict(body)
    payload["sha256"] = hashlib.sha256(canonical(body)).hexdigest()
    raw = canonical(payload)
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if phase_hook is not None:
        phase_hook("file_fsync")
    os.replace(temporary, path)
    if phase_hook is not None:
        phase_hook("replace")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if phase_hook is not None:
        phase_hook("directory_fsync")
    restored = load(path)
    if restored != payload or path.read_bytes() != raw:
        raise RuntimeError("Atomic checkpoint readback changed bytes")
    return restored

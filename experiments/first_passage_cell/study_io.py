"""Atomic bounded evidence files and the source/preparation confirmation gate."""

import errno
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

from .cell import CellParameters, canonical_bytes

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROTOCOL = HERE / "PROTOCOL.json"


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".incomplete")
    with temporary.open("xb") as stream:
        stream.write(canonical_bytes(value) + b"\n")
    os.replace(temporary, path)
    return digest_file(path)


def resolved_path(name):
    path = Path(name)
    return path if path.is_absolute() else REPO / path


def file_record(path):
    path = Path(path).absolute()
    try:
        name = str(path.relative_to(REPO))
    except ValueError:
        name = str(path)
    return {"path": name, "bytes": path.stat().st_size, "sha256": digest_file(path)}


class _ReservedWriter:
    """Do not let gzip write outside this file's already allocated capacity."""

    def __init__(self, stream, capacity):
        self.stream, self.capacity = stream, capacity

    def write(self, data):
        if self.capacity and self.stream.tell() + len(data) > self.capacity:
            raise OSError(errno.ENOSPC, "Evidence exceeded its reserved file capacity")
        return self.stream.write(data)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class GzipLedger:
    """Stream complete episodes; an interrupted file cannot look complete."""

    def __init__(self, path, reserve_bytes=32 * 1024 * 1024):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(self.path)
        self.temporary = self.path.with_suffix(self.path.suffix + ".incomplete")
        if type(reserve_bytes) is not int or reserve_bytes < 0:
            raise ValueError("A nonnegative integer evidence capacity is required")
        self.raw = self.temporary.open("x+b", buffering=0)
        try:
            if reserve_bytes:
                os.posix_fallocate(self.raw.fileno(), 0, reserve_bytes)
        except BaseException:
            self.raw.close()
            self.temporary.unlink()
            raise
        self.stream = gzip.GzipFile(filename="", mode="wb",
                                    fileobj=_ReservedWriter(self.raw, reserve_bytes), mtime=0,
                                    compresslevel=6)
        self.episodes = 0
        self.uncompressed_bytes = 0

    def __enter__(self):
        return self

    def append(self, episode):
        data = canonical_bytes(episode) + b"\n"
        self.stream.write(data)
        self.episodes += 1
        self.uncompressed_bytes += len(data)

    def __exit__(self, kind, value, traceback):
        try:
            self.stream.close()
        finally:
            # fallocate changes physical length, not the write cursor. Only
            # the exact gzip stream is retained; no padded zero tail is hashed.
            position = self.raw.tell()
            try:
                self.raw.truncate(position)
            finally:
                self.raw.close()
        if kind is None:
            os.replace(self.temporary, self.path)


def model_from_file(path):
    receipt = read_json(path)
    values = dict(receipt["selected_parameters"])
    values["weights"] = tuple(values["weights"])
    parameters = CellParameters(**values)
    if parameters.digest() != receipt["model_digest"]:
        raise ValueError("Fitted parameter/model digest mismatch")
    if receipt["active_parameter_count"] not in (6, 7):
        raise ValueError("Unregistered physical parameter budget")
    if receipt.get("protocol_sha256") != digest_file(PROTOCOL):
        raise ValueError("Fitted model belongs to a different protocol")
    return parameters, receipt


def compact_native(receipt, retain_full=False):
    if receipt is None:
        return None
    response = receipt["response"]
    result = {
        "schema": "HeptaFirstPassageCompactNativeV1",
        "action_values": receipt["action_values"],
        "native_candidate_to_action": receipt.get("native_candidate_to_action", {}),
        "binary_sha256": receipt["binary_sha256"],
        "source_manifest_sha256": receipt["source_manifest_sha256"],
        "request_digest": response["request_digest"],
        "snapshot_digest": response["snapshot_digest"],
        "evaluation_digest": response["evaluation_digest"],
        "generation": response["generation"],
        "context": receipt["snapshot"]["context"],
        "recursive_paths": [{"id": path["id"], "values_q32": path["values_q32"],
            "recursive_evidence_digest": path["recursive_evidence_digest"],
            "projection_count": path["projection_count"]} for path in response["paths"]],
        "advisory_candidate_id": response["advisory_candidate_id"],
        "evaluated_candidate_ids": response["evaluated_candidate_ids"],
        "pareto_candidate_ids": response["pareto_candidate_ids"],
        "rejected": response["rejected"],
        "authority": response["authority"], "safety_certificate": response["safety_certificate"],
    }
    for field in ("realized_return", "realized_native_return", "roundoff_bound"):
        if field in receipt:
            result[field] = receipt[field]
    if retain_full:
        result["full_receipt"] = receipt
    return result


def verify_records(records):
    seen = set()
    for record in records:
        path = resolved_path(record["path"]).resolve()
        if path in seen:
            raise ValueError("Duplicate frozen file")
        seen.add(path)
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or digest_file(path) != record["sha256"]):
            raise ValueError("Frozen file mismatch: " + str(path))
    return seen


def verify_freeze(path, prepared, native):
    """No evaluation data generator may run until all identities pass this gate."""
    frozen, protocol = read_json(path), read_json(PROTOCOL)
    prepared = Path(prepared).resolve()
    preparation = prepared / "prepared_manifest.json"
    if (frozen.get("schema") != "HeptaFirstPassageFreezeV1"
            or not re.fullmatch("[0-9a-f]{40}", frozen.get("source_commit", ""))
            or frozen.get("base_commit") != protocol["base_commit"]):
        raise ValueError("Missing or invalid published source freeze")
    if frozen.get("protocol_sha256") != digest_file(PROTOCOL):
        raise ValueError("Frozen protocol mismatch")
    if frozen.get("prepared_manifest_sha256") != digest_file(preparation):
        raise ValueError("Frozen preparation manifest mismatch")
    manifest = read_json(preparation)
    if (manifest.get("schema") != "HeptaFirstPassagePreparedV2"
            or manifest.get("protocol_sha256") != frozen["protocol_sha256"]):
        raise ValueError("Preparation/protocol identity mismatch")
    actual = (digest_file(native.binary), native.source_manifest_sha256)
    expected = (frozen.get("native_binary_sha256"), frozen.get("native_source_manifest_sha256"))
    if actual != expected or actual[0] != native.binary_sha256:
        raise ValueError("Frozen native executable/source identity mismatch")
    native_manifest_identity = (manifest.get("native_binary_sha256"),
                                manifest.get("native_source_manifest_sha256"))
    if actual != native_manifest_identity:
        raise ValueError("Policy preparation used a different native utility implementation")
    frozen_files = verify_records(frozen["files"])
    prepared_files = verify_records(manifest["files"])
    required = {p.resolve() for p in HERE.glob("*.py")}
    required.update({PROTOCOL.resolve(), preparation.resolve(),
                     (HERE / "native_bridge.rs").resolve(),
                     (HERE / "NATIVE_SOURCE_MANIFEST.json").resolve(),
                     native.build_manifest_path.resolve()})
    required.update(prepared_files)
    if not required <= frozen_files:
        missing = sorted(str(p) for p in required - frozen_files)
        raise ValueError("Freeze omits runtime/preparation files: " + str(missing))
    return frozen

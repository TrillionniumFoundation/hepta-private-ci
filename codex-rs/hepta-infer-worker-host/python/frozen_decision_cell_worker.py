"""Private bounded stdin/stdout driver for the existing inference owner.

No network listener, authority issuer, durable store or effect executor. The
supervising owner must authenticate artifacts, serialize requests, enforce hard
cancellation and reconcile unknown work. Model success is not action success.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from decision_cell_encoder import FrozenMdebertaDecisionCellV2, _canonical
from decision_cell_tensors import checked_bytes, strict_json

SCHEMA = "hepta.frozen-encoder-request.v1"
MAX_FRAME = 96 * 1024
MAX_REQUESTS = 1024
MAX_CACHE_BYTES = 16 * 1024 * 1024
COMMAND_SCHEMA = "hepta.frozen-encoder-command.v1"
REPLY_SCHEMA = "hepta.frozen-encoder-reply.v1"


def request(raw: bytes, *, check_deadline: bool = True) -> dict:
    if not 0 < len(raw) <= MAX_FRAME or not raw.endswith(b"\n"):
        raise ValueError("invalid request frame length")
    value = strict_json(raw)
    if set(value) != {"schema", "request_id", "projection_sha256", "deadline_monotonic_ns", "text", "candidates"}:
        raise ValueError("unknown or missing request field")
    if value["schema"] != SCHEMA or not isinstance(value["request_id"], str) or not re.fullmatch(
            r"[A-Za-z0-9._:-]{1,128}", value["request_id"]):
        raise ValueError("invalid request identity")
    deadline = value["deadline_monotonic_ns"]
    if type(deadline) is not int or deadline <= 0 or (check_deadline and not
            time.monotonic_ns() < deadline <= time.monotonic_ns() + 120 * 10**9):
        raise ValueError("invalid process-local request deadline")
    if not isinstance(value["text"], str) or not 0 < len(value["text"].encode()) <= 16384:
        raise ValueError("invalid observation text")
    targets = value["candidates"]
    if not isinstance(targets, list) or len(targets) != 4 or any(
            not isinstance(item, str) or not 0 < len(item.encode()) <= 4096 for item in targets):
        raise ValueError("invalid candidate texts")
    projected = _canonical({"projection_schema": "hepta.decision-cell-text-projection.v1",
                            "texts": (value["text"],), "candidates": (tuple(targets),)})
    if hashlib.sha256(projected).hexdigest() != value["projection_sha256"]:
        raise ValueError("projection content substitution")
    return value


def _identity(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) is not None


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None and value != "0" * 64


class WorkerSession:
    """Bounded volatile observation cache; the existing Neuron owner is durable.

    A lost worker has no absence proof. Lookup never calls the encoder, even for
    a missing operation. Cache exhaustion closes admission, never evicts identities.
    """
    def __init__(self, model, session_id: str):
        if not _identity(session_id):
            raise ValueError("invalid session identity")
        self.model = model
        self.session_id = session_id
        self._records: dict[str, tuple[str, str, bytes]] = {}
        self._bytes = 0

    def handle(self, raw: bytes) -> bytes:
        if not 0 < len(raw) <= MAX_FRAME or not raw.endswith(b"\n"):
            raise ValueError("invalid command frame length")
        command = strict_json(raw)
        if set(command) != {"schema", "session_id", "kind", "invocation_sha256", "request"}:
            raise ValueError("unknown or missing command field")
        if command["schema"] != COMMAND_SCHEMA or command["session_id"] != self.session_id:
            raise ValueError("command session/schema mismatch")
        if command["kind"] not in ("infer", "lookup") or not _digest(command["invocation_sha256"]):
            raise ValueError("invalid command kind/invocation binding")
        request_bytes = _canonical(command["request"])
        value = request(request_bytes, check_deadline=False)
        request_digest = hashlib.sha256(request_bytes).hexdigest()
        key = value["request_id"]
        invocation = command["invocation_sha256"]
        binding = {"schema": REPLY_SCHEMA, "session_id": self.session_id,
            "request_id": key, "request_sha256": request_digest,
            "invocation_sha256": invocation, "projection_sha256": value["projection_sha256"],
            "advisory_only": True, "external_effect": False}
        previous = self._records.get(key)
        if previous is not None:
            if previous[:2] != (request_digest, invocation):
                raise ValueError("request identity reused with changed semantics")
            return previous[2]
        if command["kind"] == "lookup":
            return _canonical({**binding, "status": "unknown", "observation": None})
        request(request_bytes)  # Only fresh admission uses the live deadline.
        if len(self._records) >= MAX_REQUESTS or self._bytes + MAX_FRAME > MAX_CACHE_BYTES:
            raise ValueError("worker result capacity exhausted; reconcile before replacement")
        uncertain = _canonical({**binding, "status": "indeterminate", "observation": None})
        self._records[key] = (request_digest, invocation, uncertain)
        self._bytes += len(uncertain)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                observed = self.model.observe((value["text"],), (tuple(value["candidates"]),),
                    deadline_ns=value["deadline_monotonic_ns"])
            if observed.get("input_sha256") != value["projection_sha256"]:
                raise ValueError("encoder input binding mismatch")
            if observed.get("advisory_only") is not True or observed.get("external_effect") is not False:
                raise ValueError("encoder authority violation")
            if time.monotonic_ns() >= value["deadline_monotonic_ns"]:
                raise TimeoutError("late encoder output")
            result = {**observed,
                "scores": {k: v.tolist() for k, v in observed["scores"].items()},
                "probabilities": {k: v.tolist() for k, v in observed["probabilities"].items()}}
            encoded = _canonical({**binding, "status": "observed", "observation": result})
            if len(encoded) > MAX_FRAME:
                raise ValueError("response frame exceeds bound")
            self._records[key] = (request_digest, invocation, encoded)
            self._bytes += len(encoded) - len(uncertain)
            return encoded
        except (ValueError, TypeError, RuntimeError, TimeoutError, OSError, KeyError, AttributeError):
            # Never run a second time after possible physical inference.
            return uncertain


def serve(session: WorkerSession, source, destination) -> None:
    while True:
        raw = source.readline(MAX_FRAME + 1)
        if not raw:
            return
        try:
            encoded = session.handle(raw)
        except (ValueError, TypeError, UnicodeError):
            encoded = _canonical({"schema": "hepta.frozen-encoder-error.v1",
                "session_id": session.session_id, "command_sha256": hashlib.sha256(raw).hexdigest(),
                "status": "rejected", "advisory_only": True, "external_effect": False})
        destination.write(encoded)
        destination.flush()
        if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
            return  # Framing loss poisons the channel; never parse trailing chunks.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--base-snapshot-sha256", required=True)
    parser.add_argument("--runtime-profile-sha256", required=True)
    args = parser.parse_args()
    manifest = strict_json(checked_bytes(args.manifest, args.manifest_sha256, 256 * 1024))
    profile = manifest["runtime_profile"]
    if hashlib.sha256(_canonical(profile)).hexdigest() != args.runtime_profile_sha256:
        raise ValueError("runtime profile binding mismatch")
    with contextlib.redirect_stdout(sys.stderr):
        model = FrozenMdebertaDecisionCellV2(model_path=args.model_path,
            manifest_path=args.manifest, manifest_sha256=args.manifest_sha256,
            weights_path=args.weights, weights_sha256=args.weights_sha256,
            expected_base_snapshot=args.base_snapshot_sha256,
            expected_runtime_profile=profile)
    try:
        session = WorkerSession(model, args.session_id)
        sys.stdout.buffer.write(_canonical({"schema": "hepta.frozen-encoder-ready.v1",
            "session_id": args.session_id, "head_manifest_sha256": args.manifest_sha256,
            "base_snapshot_digest": args.base_snapshot_sha256,
            "runtime_profile_sha256": args.runtime_profile_sha256,
            "device": "cpu", "advisory_only": True, "external_effect": False}))
        sys.stdout.buffer.flush()
        serve(session, sys.stdin.buffer, sys.stdout.buffer)
    finally:
        model.close()


if __name__ == "__main__":
    main()

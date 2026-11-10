"""Atomic commit and exact cold readback of local numerical deliveries.

The final delivery.json link is the commit point. An intent or a directory alone
is not delivery. This is local file recovery, not a StageOwnerPorts attestation,
CURRENT publication, or permission to adopt a model. The caller retains the
identity independently; a self-consistent directory does not authenticate itself.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


SCHEMA = "hepta-bimodal-local-delivery-v1"
MAX_BYTES = 1_048_576
ASSETS = {"generated.txt", "generated.ppm"}


class DeliveryCommitUncertain(RuntimeError):
    """The commit link may exist; reconcile its original identity before retry."""


def _json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError("Delivery members must be bounded regular files")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Delivery member exceeds its bound")
    return raw


def _sync_directory(path):
    if os.name == "nt":
        # Python cannot fsync a Windows directory. Never advertise power-loss
        # durability there; atomic manifest visibility and readback still apply.
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path, raw):
    """Publish fully flushed bytes without replacing even an empty target."""
    if len(raw) > MAX_BYTES:
        raise ValueError("Delivery member exceeds its bound")
    with tempfile.NamedTemporaryFile(prefix=".hepta-delivery-", dir=path.parent.parent,
                                     delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink()
            raise
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read(path) != raw:
                raise ValueError("Existing delivery member belongs to different bytes")
    finally:
        temporary.unlink()


def prepare_delivery(result, assets):
    """Bind original receipt bytes and both delivered modalities before writing."""
    if (result.get("action") != "SUBMIT" or result.get("production_update") != "no-update"
            or "delivery" in result or not assets or not set(assets) <= ASSETS):
        raise ValueError("Expected an uncommitted local NoUpdate delivery")
    if any(type(raw) is not bytes or not raw or len(raw) > MAX_BYTES
           for raw in assets.values()):
        raise ValueError("Expected bounded nonempty artifact bytes")
    if assets.get("generated.txt", b"") != result["text_utf8"].encode("utf-8"):
        raise ValueError("Text receipt and actual bytes differ")
    image = assets.get("generated.ppm")
    if result["image_sha256"] != (_sha(image) if image is not None else None):
        raise ValueError("Image receipt and actual bytes differ")
    receipt = json.loads(_json(result))
    binding = {"schema": SCHEMA, "files": {
        name: {"bytes": len(raw), "sha256": _sha(raw)}
        for name, raw in sorted(assets.items())}}
    binding["identity"] = _sha(_json({"receipt": receipt, "binding": binding}))
    receipt["delivery"] = binding
    if len(_json(receipt)) > MAX_BYTES:
        raise ValueError("Delivery receipt exceeds its bound")
    return receipt


def _validate(output, raw, expected_identity, *, committed):
    result = json.loads(raw)
    if _json(result) != raw or type(expected_identity) is not str:
        raise ValueError("Expected canonical delivery and independently retained identity")
    binding = result.get("delivery", {})
    files = binding.get("files", {})
    if (binding.get("schema") != SCHEMA or not files or not set(files) <= ASSETS
            or set(binding) != {"schema", "identity", "files"}):
        raise ValueError("Unknown local delivery profile")
    assets = {name: _read(output / name) for name in files}
    original = dict(result)
    del original["delivery"]
    if prepare_delivery(original, assets) != result or binding["identity"] != expected_identity:
        raise ValueError("Delivery bytes or original identity differ")
    allowed = set(files) | {"delivery.intent.json"}
    if committed:
        allowed.add("delivery.json")
    observed = set()
    for path in output.iterdir():
        observed.add(path.name)
        if len(observed) > len(allowed):
            raise ValueError("Unexpected delivery members")
    if observed != allowed:
        raise ValueError("Unexpected or missing delivery members")
    return result


def read_delivery(output, *, expected_identity):
    """Read a committed original result without native dispatch or budget renewal."""
    output = Path(output).absolute()
    if output.is_symlink() or not output.is_dir():
        raise ValueError("Expected an original delivery directory")
    raw = _read(output / "delivery.json")
    if _read(output / "delivery.intent.json") != raw:
        raise ValueError("Commit differs from the retained intent")
    return _validate(output, raw, expected_identity, committed=True)


def commit_delivery(output, result, assets, *, before_commit):
    """Resume only the same retained intent; never regenerate or replace files.

    Pre-commit failures leave a recognizable intent. A commit/flush ambiguity
    requires read_delivery with the same identity, including after expiry.
    before_commit rechecks the existing owner's budget; it grants no new budget.
    """
    output = Path(output).absolute()
    identity = result["delivery"]["identity"]
    raw = _json(result)
    original = dict(result)
    del original["delivery"]
    if prepare_delivery(original, assets) != result:
        raise ValueError("Delivery differs from its retained terminal bytes")
    if output.is_symlink():
        raise ValueError("Delivery destination cannot be a symlink")
    if (output / "delivery.json").exists():
        return read_delivery(output, expected_identity=identity)
    before_commit()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.mkdir()
    except FileExistsError:
        if not output.is_dir() or _read(output / "delivery.intent.json") != raw:
            raise ValueError("Destination is not this retained delivery intent")
    else:
        try:
            _write_once(output / "delivery.intent.json", raw)
        except BaseException:
            if not any(output.iterdir()):
                output.rmdir()
            raise
    for name, payload in assets.items():
        if name not in ASSETS:
            raise ValueError("Unknown delivery asset")
        _write_once(output / name, payload)
    _validate(output, raw, identity, committed=False)
    _sync_directory(output)
    # Persist any newly created destination ancestors before acknowledging its
    # commit. The elapsed work remains inside the original finalization budget.
    for parent in output.parents:
        _sync_directory(parent)
    before_commit()
    try:
        os.link(output / "delivery.intent.json", output / "delivery.json")
        _sync_directory(output)
        return read_delivery(output, expected_identity=identity)
    except BaseException as error:
        raise DeliveryCommitUncertain("Reconcile the original delivery identity") from error

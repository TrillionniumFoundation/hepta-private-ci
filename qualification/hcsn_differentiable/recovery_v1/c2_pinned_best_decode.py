"""Read-only decoding of two SHA-pinned *original* C2 best.pt checkpoints.

This is restricted checkpoint inspection, NOT an interrupted-state recovery,
complete six-run terminal, training replay, independent evaluation or GO.
Only unpickle *after* matching a frozen byte digest, using weights_only=True.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys

NAMES = ("hcsn-s211-lr0.001", "hcsn-s307-lr0.001")
ORIGINAL_JOB = "1a1c74f3308-be2a-75"
DATA_SHA = "0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb"
FIELDS = {"model", "model_configuration", "optimizer", "torch_rng",
          "order_rng", "epochs_completed", "main_updates", "data_manifest_sha256"}
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_BYTES = 32 * 1024 * 1024


class CheckpointHold(ValueError):
    """Evidence must be held, without interpreting the candidate as complete."""


def _duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise CheckpointHold("duplicate inventory JSON key")
        obj[key] = value
    return obj


def _constant(value):
    raise CheckpointHold("nonfinite inventory JSON constant")


def _read_frozen(path: Path, *, limit: int) -> bytes:
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
        raise CheckpointHold("not a bounded nonempty regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, "rb", closefd=False) as stream:
            observed = os.fstat(fd)
            if (observed.st_dev, observed.st_ino, observed.st_size) != (
                before.st_dev, before.st_ino, before.st_size
            ):
                raise CheckpointHold("file changed before read")
            raw = stream.read(limit + 1)
            after = os.fstat(fd)
            if len(raw) != before.st_size or len(raw) > limit or (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
            ) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
                raise CheckpointHold("file changed or exceeded bound")
    finally:
        os.close(fd)
    return raw


def _finite_tensors(obj, torch, *, depth=0):
    if depth > 16:
        raise CheckpointHold("nested optimizer/model state too deep")
    if torch.is_tensor(obj):
        if obj.is_complex() or obj.is_floating_point():
            if not bool(torch.isfinite(obj).all()):
                raise CheckpointHold("nonfinite model or optimizer tensor")
        return 1
    if type(obj) in (dict, OrderedDict):
        return sum(_finite_tensors(x, torch, depth=depth + 1) for x in obj.values())
    if type(obj) in (tuple, list):
        return sum(_finite_tensors(x, torch, depth=depth + 1) for x in obj)
    if type(obj) in (int, float, str, bool, type(None)):
        if type(obj) is float and not (-float("inf") < obj < float("inf")):
            raise CheckpointHold("nonfinite scalar state")
        return 0
    raise CheckpointHold("unexpected state object type")


def decode_pinned(raw: bytes, *, name: str) -> dict:
    """Does not train, model-forward, compare dev sets or replay an optimizer step."""
    if name not in NAMES:
        raise CheckpointHold("unknown frozen C2 attempt identity")
    import torch  # Native environment selected by caller; do not silently install torch.
    try:
        checkpoint = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    except Exception as exc:
        raise CheckpointHold("weights_only checkpoint decoding failed: " + type(exc).__name__) from exc
    if type(checkpoint) is not dict or set(checkpoint) != FIELDS:
        raise CheckpointHold("checkpoint frozen-field schema mismatch")
    model = checkpoint["model"]
    config = checkpoint["model_configuration"]
    opt = checkpoint["optimizer"]
    seed = int(name.split("-")[1][1:])
    if (type(config) is not dict or config.get("arm") != "hcsn"
            or type(config.get("seed")) is not int or config["seed"] != seed):
        raise CheckpointHold("checkpoint arm/seed mismatch")
    if (type(model) not in (dict, OrderedDict) or len(model) != 23 or
            not all(type(k) is str and torch.is_tensor(v) for k, v in model.items())):
        raise CheckpointHold("model tensor schema mismatch")
    if (type(opt) is not dict or set(opt) != {"state", "param_groups"}
            or type(opt["state"]) is not dict or type(opt["param_groups"]) is not list):
        raise CheckpointHold("optimizer state schema mismatch")
    rng = checkpoint["torch_rng"]
    if not torch.is_tensor(rng) or rng.dtype != torch.uint8 or tuple(rng.shape) != (5056,):
        raise CheckpointHold("Torch RNG state schema mismatch")
    if type(checkpoint["order_rng"]) is not tuple or len(checkpoint["order_rng"]) != 3:
        raise CheckpointHold("order RNG state schema mismatch")
    epoch = checkpoint["epochs_completed"]
    updates = checkpoint["main_updates"]
    if type(epoch) is not int or not 0 < epoch <= 200 or type(updates) is not int or updates < epoch:
        raise CheckpointHold("epoch/update counters not within frozen C2 contract")
    if checkpoint["data_manifest_sha256"] != DATA_SHA:
        raise CheckpointHold("frozen data-manifest mismatch")
    _finite_tensors(checkpoint, torch)
    return {"status": "PINNED_BEST_DECODED_NOT_REPLAYED",
            "epochs_completed": epoch, "main_updates": updates,
            "model_tensor_count": len(model),
            "optimizer_state_count": len(opt["state"]),
            "data_manifest_sha256": DATA_SHA, "tensor_finite": True}


def audit(fits_root: Path, inventory_path: Path) -> dict:
    fits_root, inventory_path = Path(fits_root), Path(inventory_path)
    inventory_raw = _read_frozen(inventory_path, limit=1 << 20)
    expected = json.loads(inventory_raw, object_pairs_hook=_duplicates, parse_constant=_constant)
    if (type(expected) is not dict or
            expected.get("schema") != "hcsn-original-c2-fits-readonly-inventory-v1" or
            expected.get("original_job_id") != ORIGINAL_JOB or
            expected.get("original_fits_root") != str(fits_root)):
        raise CheckpointHold("original roster/job/root identity differs")
    entries = expected.get("files")
    if type(entries) is not list or len(entries) != 8:
        raise CheckpointHold("original eight-file inventory missing")
    pinned = {}
    for entry in entries:
        if type(entry) is not dict:
            raise CheckpointHold("malformed original file inventory")
        if entry.get("file") == "best.pt":
            name = entry.get("candidate")
            if name not in NAMES or name in pinned or entry.get("path") != str(fits_root / name / "best.pt"):
                raise CheckpointHold("best.pt path/name not pinned to original roster")
            if (type(entry.get("size_bytes")) is not int or
                    not 0 < entry["size_bytes"] <= MAX_BYTES or
                    type(entry.get("sha256")) is not str or
                    SHA.fullmatch(entry["sha256"]) is None):
                raise CheckpointHold("invalid frozen best.pt identity")
            pinned[name] = entry
    if set(pinned) != set(NAMES):
        raise CheckpointHold("two expected original best.pt identities not frozen")
    rows = []
    for name in NAMES:
        item = pinned[name]
        row = {"name": name, "checkpoint_sha256": item["sha256"],
               "checkpoint_bytes": item["size_bytes"],
               "independent_training_replay": False}
        try:
            raw = _read_frozen(fits_root / name / "best.pt", limit=MAX_BYTES)
            if len(raw) != item["size_bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise CheckpointHold("checkpoint bytes differ from frozen inventory")
            row.update(decode_pinned(raw, name=name))
        except (CheckpointHold, OSError, ValueError) as exc:
            row.update(status="HOLD", error=str(exc))
        rows.append(row)
    return {"schema": "hcsn-c2-original-pinned-best-decode-v1",
            "original_job_id": ORIGINAL_JOB,
            "source_inventory_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "expected_original_attempts": 6, "expected_best_decodes": 2,
            "decoded_best_count": sum(row["status"] == "PINNED_BEST_DECODED_NOT_REPLAYED" for row in rows),
            "rows": rows, "all_six_independently_replayed": False,
            "controller_terminal_confirmed": False,
            "independent_training_replay": False, "scientific_admission": "HOLD_NO_GO",
            "scope": "Frozen-identity weights_only CPU decoding and finite state structure of two best.pt only; not interrupted.pt, optimizer trajectory, or independent B."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fits", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    args = parser.parse_args(argv)
    json.dump(audit(args.fits, args.inventory), sys.stdout, sort_keys=True, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()


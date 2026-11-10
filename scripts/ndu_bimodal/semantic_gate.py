"""Fail-closed, externally pinned *colour-card* text/image delivery gate.

This is not a general semantic evaluator and cannot authorize production adoption.
The expected labels and manifest SHA must be fixed by an independent evaluator
before seeing a candidate's outputs.  A model-generated label is not independent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import unicodedata

PROFILE = "hepta-bimodal-colour-card-semantic-v1"
HEX = re.compile(r"[0-9a-f]{64}\Z")
MAX_MANIFEST = 8192
MAX_DELIVERY = 131072
MAX_IMAGE = 1024 * 1024
MAX_TEXT = 4096


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hex(value: object) -> str:
    if not isinstance(value, str) or HEX.fullmatch(value) is None:
        raise ValueError("expected a complete lowercase SHA-256")
    return value


def _number(value: object, *, min_value: float = 0.0) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or value < min_value:
        raise ValueError("invalid bounded numerical value")
    return float(value)


def _keys(value: object, required: set[str]) -> dict:
    if type(value) is not dict or set(value) != required:
        raise ValueError("unexpected, missing or private manifest fields")
    return value


def _bytes(path: Path, maximum: int) -> bytes:
    """Read a bounded regular file without following a final-component symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
            raise ValueError("not a bounded regular file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            content = stream.read(maximum + 1)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ) or len(content) != before.st_size:
            raise ValueError("source mutated during read")
        return content
    finally:
        os.close(fd)


def _load_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if type(value) is not dict:
        raise ValueError("expected object")
    return value


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _manifest(raw: bytes) -> dict:
    result = _keys(_load_json(raw), {"schema", "task_id", "bindings", "target", "limits"})
    if result["schema"] != PROFILE or type(result["task_id"]) is not str or not (
        1 <= len(result["task_id"]) <= 128
    ):
        raise ValueError("invalid profile or task ID")
    binds = _keys(result["bindings"], {"public_sha256", "checkpoint_sha256", "binary_sha256"})
    for value in binds.values():
        _hex(value)
    target = _keys(result["target"], {"accepted_text", "rgb", "max_channel_error",
                                     "max_mean_absolute_error", "min_pixel_fraction"})
    labels = target["accepted_text"]
    if type(labels) is not list or not 1 <= len(labels) <= 12 or any(
        type(label) is not str or not 1 <= len(label.encode("utf-8")) <= 160
        or not _normalize(label) for label in labels
    ):
        raise ValueError("invalid independently registered text labels")
    if len(set(map(_normalize, labels))) != len(labels):
        raise ValueError("duplicate registered labels")
    rgb = target["rgb"]
    if type(rgb) is not list or len(rgb) != 3 or any(
        type(channel) is not int or not 0 <= channel <= 255 for channel in rgb
    ):
        raise ValueError("invalid reference colour")
    channel_error = target["max_channel_error"]
    if type(channel_error) is not int or not 0 <= channel_error <= 255:
        raise ValueError("invalid channel tolerance")
    if _number(target["max_mean_absolute_error"]) > 255:
        raise ValueError("invalid image mean tolerance")
    fraction = _number(target["min_pixel_fraction"])
    if not 0 <= fraction <= 1:
        raise ValueError("invalid pixel acceptance fraction")
    limits = _keys(result["limits"], {"max_calls", "max_native_wall_seconds",
                                     "max_native_cpu_seconds"})
    if type(limits["max_calls"]) is not int or not 1 <= limits["max_calls"] <= 128:
        raise ValueError("invalid call cap")
    for name in ("max_native_wall_seconds", "max_native_cpu_seconds"):
        if _number(limits[name]) <= 0:
            raise ValueError("invalid positive cost cap")
    return result


def _image_result(raw: bytes, target: dict) -> dict:
    # The existing numeric v4 profile delivers a 16x16 RGB P6 PPM. Other
    # codecs require their own pinned evaluator rather than implicit decoding.
    header = b"P6\n16 16\n255\n"
    if not raw.startswith(header) or len(raw) != len(header) + 16 * 16 * 3:
        return {"valid": False, "mean_absolute_error": None, "pixel_fraction": None,
                "pass": False}
    pixels = raw[len(header):]
    rgb = target["rgb"]
    absolute = [abs(byte - rgb[index % 3]) for index, byte in enumerate(pixels)]
    mean = sum(absolute) / len(absolute)
    accepted = sum(all(absolute[pos + i] <= target["max_channel_error"]
                       for i in range(3)) for pos in range(0, len(pixels), 3))
    fraction = accepted / 256
    return {
        "valid": True,
        "mean_absolute_error": mean,
        "pixel_fraction": fraction,
        "pass": mean <= target["max_mean_absolute_error"]
                and fraction >= target["min_pixel_fraction"],
    }


def evaluate(manifest_path: Path, trusted_manifest_sha256: str, delivery_dir: Path) -> dict:
    raw = _bytes(manifest_path, MAX_MANIFEST)
    if sha256(raw) != _hex(trusted_manifest_sha256):
        raise ValueError("evaluation manifest is not the externally frozen version")
    manifest = _manifest(raw)
    delivery_bytes = _bytes(delivery_dir / "delivery.json", MAX_DELIVERY)
    delivery = _load_json(delivery_bytes)
    bindings = manifest["bindings"]
    if any(delivery.get(key) != value for key, value in bindings.items()):
        raise ValueError("candidate/public/binary identity mismatch")
    if delivery.get("action") != "SUBMIT" or delivery.get("production_update") != "no-update":
        raise ValueError("not a bounded, unadopted terminal delivery")
    text_bytes = _bytes(delivery_dir / "generated.txt", MAX_TEXT)
    image_bytes = _bytes(delivery_dir / "generated.ppm", MAX_IMAGE)
    text = text_bytes.decode("utf-8", errors="strict")
    if delivery.get("text_utf8") != text or delivery.get("image_sha256") != sha256(image_bytes):
        raise ValueError("delivered text/image bytes differ from owner receipt")
    if not text or len(text_bytes) > MAX_TEXT:
        raise ValueError("no bounded textual delivery")
    calls = delivery.get("calls")
    if type(calls) is not list or not calls or len(calls) > 128:
        raise ValueError("incomplete native call ledger")
    wall = cpu = 0.0
    for call in calls:
        if type(call) is not dict or call.get("status") != "passed" or call.get("exit_code") != 0:
            raise ValueError("missing/failed native call receipt")
        if call.get("kind") not in {"observation", "generate", "recompute",
                                    "reuse", "control", "submit"}:
            raise ValueError("unrecognised call category")
        _hex(call.get("request_sha256"))
        _hex(call.get("stdout_sha256"))
        _hex(call.get("stderr_sha256"))
        wall += _number(call.get("wall_seconds"))
        cpu += _number(call.get("child_cpu_seconds"))
    limits = manifest["limits"]
    image = _image_result(image_bytes, manifest["target"])
    text_match = _normalize(text) in set(map(_normalize, manifest["target"]["accepted_text"]))
    cost_match = len(calls) <= limits["max_calls"] and (
        wall <= limits["max_native_wall_seconds"]
        and cpu <= limits["max_native_cpu_seconds"]
    )
    success = bool(text_match and image["pass"] and cost_match)
    return {
        "schema": PROFILE + "-result",
        "task_id": manifest["task_id"],
        "frozen_manifest_sha256": sha256(raw),
        "delivery_sha256": sha256(delivery_bytes),
        "bindings": dict(bindings),
        "output_sha256": {"text": sha256(text_bytes), "image": sha256(image_bytes)},
        "text_exact_match": text_match,
        "image": image,
        "observed_native_cost": {"calls": len(calls), "child_wall_seconds": wall,
                                 "child_cpu_seconds": cpu, "within_declared_cap": cost_match,
                                 "scope": "summed native calls only, not whole training/service cost"},
        "bounded_colour_card_pass": success,
        "decision": "BOUNDED_TASK_PASS" if success else "HOLD_BOUNDED_TASK_FAIL",
        "independent_evaluator_execution_verified": False,
        "whole_resource_budget_verified": False,
        "open_world_semantics_verified": False,
        "production_adoption": False,
        "scientific_acceptance": "HOLD_NO_GO",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--trusted-manifest-sha256", required=True)
    parser.add_argument("--delivery-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.manifest, args.trusted_manifest_sha256, args.delivery_dir)
    data = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    # No overwrite or accidental promotion of a prior result.
    fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
    return 0 if result["bounded_colour_card_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""V9 research handoff: rehash V8 physical material before V5 profile admission.

This module DOES NOT authenticate Hub publishers or prove that an untrusted
physical receipt was produced by its claimed source. No training, promotion,
selection, model download, or authority grant is performed here. The V5 owner
must still authenticate operator material independently and rerun LocalEncoder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from public_stem_material_v8 import (
    RECEIPT, PROBE_TEXTS, probe_input_digest, AdmissionError, canonical, sha,
    strict_json, validate_plan,
)

SCHEMA = "hepta.public-stem-v9-research-handoff.v1"
PROFILE = "hepta.multimodal-pinned-text-encoder.v1"
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
FILE_LIMIT = 1200 * 1024**2


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise AdmissionError(reason)


def _json(path: Path, *, maximum: int = 65536) -> dict:
    require(not path.is_symlink() and path.is_file() and path.stat().st_size <= maximum,
            "missing, linked or oversized V8 receipt")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate receipt JSON key")
            result[key] = value
        return result
    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda _: require(False,"nonfinite receipt"))
    except AdmissionError:
        raise
    except (UnicodeError, ValueError, TypeError) as error:
        raise AdmissionError("invalid V8 receipt encoding") from error
    require(type(value) is dict and raw == canonical(value),
            "noncanonical V8 receipt")
    return value


def _file_digest(path: Path, expected_size: int) -> str:
    require(not path.is_symlink() and path.is_file() and
            type(expected_size) is int and 0 < expected_size <= FILE_LIMIT and
            path.stat().st_size == expected_size,
            "changed material file size or linked material")
    digest = hashlib.sha256()
    measured = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            measured += len(block)
            require(measured <= expected_size, "material grew during rehash")
            digest.update(block)
    require(measured == expected_size, "incomplete material read")
    return digest.hexdigest()


def handoff(plan: dict, material: dict, physical: dict, model_root: Path) -> tuple[dict, dict]:
    """Return an exact V5 profile and an explicitly non-authoritative linkage.

    The receipt is *self-consistent research evidence*, NOT a publisher signature
    or an independent cryptographic proof of physical inference.
    """
    validate_plan(plan)
    require(type(material) is dict and set(material) ==
            {"revision", "file_sha256s", "manifest"},
            "unknown or missing material receipt fields")
    observed = material["file_sha256s"]
    manifest = material["manifest"]
    expected = {item["name"]: item["size"] for item in plan["files"]}
    require(type(observed) is dict and set(observed) == set(expected) and
            all(type(value) is str and HEX64.fullmatch(value) for value in observed.values()),
            "material inventory identity mismatch")
    require(material["revision"] == plan["revision"] and
            type(manifest) is dict and set(manifest) == {"revision", "kind", "files"} and
            manifest["revision"] == plan["revision"] and
            manifest["kind"] == plan["profile"]["kind"] and
            manifest["files"] == observed,
            "V8 material and model manifest identity changed")
    require(model_root.is_dir() and not model_root.is_symlink(),
            "model root missing or linked")
    found = {path.relative_to(model_root).as_posix() for path in model_root.rglob("*")
             if path.is_file() or path.is_symlink()}
    require(found == set(expected), "material directory contains undeclared or missing files")
    for name, size in expected.items():
        require(_file_digest(model_root / name, size) == observed[name],
                "material file digest changed after V8 physical run")

    require(type(physical) is dict and physical.get("schema") == RECEIPT and
            physical.get("candidate") == plan["candidate"] and
            physical.get("repo_id") == plan["repo_id"] and
            physical.get("revision") == plan["revision"] and
            physical.get("plan_sha256") == sha(canonical(plan)) and
            physical.get("snapshot_digest") == sha(canonical(manifest)) and
            physical.get("pooling") == plan["profile"]["pooling"] and
            physical.get("normalization") == plan["profile"]["normalization"] and
            physical.get("feature_width") == plan["profile"]["width"],
            "V8 physical receipt does not match pinned material or profile")
    require(physical.get("probe_input_sha256") == probe_input_digest(PROBE_TEXTS)
            and type(physical.get("probe_count")) is int
            and physical["probe_count"] == len(PROBE_TEXTS),
            "V8 physical input census is absent or changed")
    require(physical.get("forward_calls") == 2 and
            type(physical.get("feature_sha256")) is str and
            HEX64.fullmatch(physical["feature_sha256"]) and
            all(type(physical.get(k)) is int and physical[k] > 0 for k in
                ("wall_ns", "cpu_ns", "process_lifetime_peak_rss_bytes")),
            "physical forward identity or resource coverage missing")
    require(physical.get("pretrained_source_independently_attested") is False and
            physical.get("matched_pair_completed") is False and
            physical.get("heldout_efficacy_evaluated") is False and
            physical.get("production_accepted") is False and
            physical.get("authority") == "DENY_ALL",
            "V8 research-only authority posture changed")

    profile = {"schema": PROFILE, "candidate": plan["candidate"],
               "snapshot": manifest, "expected_width": plan["profile"]["width"],
               "maximum_tokens": plan["profile"]["max_tokens"],
               "batch_size": plan["profile"]["batch_size"],
               "pooling": plan["profile"]["pooling"],
               "normalization": plan["profile"]["normalization"]}
    linkage = {"schema": SCHEMA, "candidate": plan["candidate"],
               "repo_id": plan["repo_id"], "revision": plan["revision"],
               "plan_sha256": sha(canonical(plan)),
               "material_sha256": sha(canonical(material)),
               "physical_receipt_sha256": sha(canonical(physical)),
               "probe_input_sha256": probe_input_digest(PROBE_TEXTS),
               "profile_sha256": sha(canonical(profile)),
               "snapshot_sha256": sha(canonical(manifest)),
               "file_digests_rehashed": True,
               "independently_attested_physical_execution": False,
               "publisher_identity_verified": False,
               "future_learning_benefit_evaluated": False,
               "v5_train_predict_completed": False,
               "production_accepted": False,
               "authority": "DENY_ALL"}
    return profile, linkage


def _write_dir(path: Path, files: dict[str, bytes]) -> None:
    require(not path.exists() and not path.is_symlink() and path.parent.is_dir() and
            not path.parent.is_symlink(), "new output directory required")
    with tempfile.TemporaryDirectory(prefix=".hepta-v9-handoff-", dir=path.parent) as tmp:
        stage = Path(tmp)
        for name, raw in files.items():
            with (stage / name).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        os.rename(stage, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--material", type=Path, required=True)
    parser.add_argument("--physical", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = strict_json(args.plan)
        profile, receipt = handoff(plan, _json(args.material),
                                   _json(args.physical), args.model_root)
        _write_dir(args.output, {"profile.json": canonical(profile),
                                 "handoff.json": canonical(receipt)})
    except (AdmissionError, OSError, ValueError, KeyError, TypeError) as error:
        print("V9 research handoff refused: " + str(error)[:256], file=sys.stderr)
        return 2
    print("V9_PROFILE_REHASHED_NO_TRAINING_OR_PRODUCTION_AUTHORITY " + str(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

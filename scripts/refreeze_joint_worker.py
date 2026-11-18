#!/usr/bin/env python3
"""Refreeze exact transferred Cell artifacts for an explicit runtime and device.

This creates a new candidate identity. It never promotes the original candidate's
observations into a new runtime/device qualification.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from package_hia_cell_candidate import read_file, relative, strict_json


def verify_transferred_identity(root, sources, original_raw, *, allow_dirty=False):
    """Verify original source bytes without inventing a target checkout identity."""
    origin = hashlib.sha256(original_raw).hexdigest()
    if origin != sources.get("origin_candidate_sha256"):
        raise ValueError("portable source map names a different original candidate")
    old = strict_json(original_raw)
    identities = old.get("source_identity")
    observation = {
        "schema": "hepta.joint-source-materialization.v1",
        "origin_candidate_sha256": origin,
        "origin_identity_recorded": identities is not None,
        "origin_exact_head_source": False,
        "target_git_checkout_verified": False,
        "scope": "copied execution sources; HEAD/tree/ref describe the original checkout only",
    }
    if identities is None:
        return old, observation
    if set(identities) != {"cells", "hia"}:
        raise ValueError("original source identity lacks its Cell or HIA closure")
    mapped = {item["path"]: item for item in sources["files"]}
    if len(mapped) != len(sources["files"]):
        raise ValueError("duplicate portable source record")
    for group, identity in identities.items():
        if (
            identity.get("schema") != "hepta.joint-source-identity.v1"
            or identity.get("object_format") not in {"sha1", "sha256"}
            or type(identity.get("exact_head_source")) is not bool
            or type(identity.get("allow_dirty")) is not bool
            or type(identity.get("git_status_porcelain")) is not str
        ):
            raise ValueError("unknown original source identity")
        width = 40 if identity["object_format"] == "sha1" else 64
        if any(
            not re.fullmatch("[0-9a-f]{" + str(width) + "}", identity.get(key, ""))
            for key in ("head", "tree")
        ):
            raise ValueError("invalid original Git HEAD/tree identity")
        listed = {item["path"]: item for item in old["files"] if item["root"] == group}
        rows = identity["files"]
        if len({row["path"] for row in rows}) != len(rows) or {
            row["path"] for row in rows
        } != set(listed):
            raise ValueError(
                "source identity does not cover exactly the listed execution files"
            )
        for row in rows:
            name = group + "/" + str(relative(row["path"]))
            raw, mode = read_file(root, name)
            checksum = hashlib.sha256(raw).hexdigest()
            blob = hashlib.new(
                identity["object_format"],
                b"blob " + str(len(raw)).encode() + b"\0" + raw,
            ).hexdigest()
            if (
                name not in mapped
                or checksum != mapped[name]["sha256"]
                or checksum != listed[row["path"]]["sha256"]
                or checksum != row["sha256"]
                or len(raw) != row["bytes"]
                or blob != row["git_blob"]
                or format(mode | 0o100000, "o") != row["mode"]
            ):
                raise ValueError(
                    "transferred source differs from its original source identity"
                )
            if identity["exact_head_source"] and (
                row["git_blob"] != row["head_blob"] or row["mode"] != row["head_mode"]
            ):
                raise ValueError("source bytes do not match the claimed original HEAD")
        if identity["exact_head_source"] and identity["git_status_porcelain"]:
            raise ValueError("dirty original checkout cannot claim exact HEAD source")
        if not identity["exact_head_source"] and not allow_dirty:
            raise ValueError("dirty exploratory source requires explicit --allow-dirty")
    cells = identities["cells"]
    if old["source_bases"]["cells"] != (
        cells["head"] if cells["exact_head_source"] else None
    ):
        raise ValueError("Cell source base differs from original execution identity")
    observation["origin_exact_head_source"] = all(
        item["exact_head_source"] for item in identities.values()
    )
    return old, observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--runtime-pins", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    root = args.bundle.resolve(strict=True)
    sources = strict_json((root / "SOURCE_MAP.json").read_bytes())
    for item in sources["files"]:
        path = (root / item["path"]).resolve(strict=True)
        if (
            not path.is_relative_to(root)
            or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
        ):
            raise ValueError("transferred source or artifact mismatch")
    sys.path.insert(0, str(root / "cells/scripts"))
    from hepta_cell_joint_worker import device

    old, source_materialization = verify_transferred_identity(
        root,
        sources,
        (root / "candidate/original_candidate.json").read_bytes(),
        allow_dirty=args.allow_dirty,
    )
    pins = strict_json(args.runtime_pins.read_bytes())
    required = {"source_commit", "source_tree", "binary_sha256", "config_sha256"}
    if (
        not required <= pins.keys()
        or pins["source_commit"] != old["source_bases"]["runtime"]
    ):
        raise ValueError("runtime identity does not match the frozen source choice")
    for key in ("binary_sha256", "config_sha256"):
        if (
            type(pins[key]) is not str
            or len(pins[key]) != 64
            or bytes.fromhex(pins[key]) == bytes(32)
        ):
            raise ValueError("invalid runtime digest")
    measured = device()
    if measured["numpy"] != old["device"]["numpy"]:
        raise ValueError(
            "install the frozen NumPy version in an isolated environment first"
        )
    value = {
        **old,
        "device": measured,
        "hia_root": str(root / "hia"),
        "runtime_identity": pins,
        "origin_candidate_sha256": sources["origin_candidate_sha256"],
        "source_materialization": source_materialization,
        "runtime_execution": "new exact-source runtime/device candidate; actual execution still required",
    }
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    target = root / "candidate/candidate.json"
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        __import__("os").fsync(stream.fileno())
    print(
        json.dumps(
            {
                "candidate": str(target),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "device": measured,
                "transferred_files": len(sources["files"]),
            }
        )
    )


if __name__ == "__main__":
    main()

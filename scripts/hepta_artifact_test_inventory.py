#!/usr/bin/env python3
"""Generate a fail-closed, machine-derived Cargo target inventory.

The qualification workflow must never duplicate integration-test target names by
hand. Cargo metadata is the source of truth; nextest remains the source of truth
for individual test identities and execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

DEFAULT_PACKAGE = "codex-hepta-learning-artifacts"
DEFAULT_MANIFEST = Path("codex-rs/Cargo.toml")
MAX_METADATA = 16 * 1024 * 1024


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def strict_json(data: bytes | str) -> object:
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"nonfinite JSON value: {value}")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"invalid Cargo target {field}")
    return sorted(value)


def inventory_from_metadata(
    metadata: object,
    package_name: str,
    required_targets: tuple[str, ...] = (),
) -> dict:
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise ValueError("unsupported Cargo metadata format")
    packages = metadata.get("packages")
    if not isinstance(packages, list):
        raise ValueError("Cargo metadata packages are missing")
    matches = [row for row in packages if isinstance(row, dict) and row.get("name") == package_name]
    if len(matches) != 1:
        raise ValueError("expected exactly one learning.artifacts package")
    package = matches[0]
    package_id = package.get("id")
    manifest_path = package.get("manifest_path")
    targets = package.get("targets")
    if not isinstance(package_id, str) or not package_id:
        raise ValueError("Cargo package id is missing")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ValueError("Cargo package manifest path is missing")
    if not isinstance(targets, list) or not targets:
        raise ValueError("Cargo package targets are missing")

    rows = []
    identities = set()
    names = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("malformed Cargo target")
        name = target.get("name")
        src_path = target.get("src_path")
        edition = target.get("edition")
        if not isinstance(name, str) or not name:
            raise ValueError("Cargo target name is missing")
        if not isinstance(src_path, str) or not src_path:
            raise ValueError("Cargo target source path is missing")
        if not isinstance(edition, str) or not edition:
            raise ValueError("Cargo target edition is missing")
        kind = _strings(target.get("kind"), "kind")
        crate_types = _strings(target.get("crate_types"), "crate_types")
        required_features = _strings(target.get("required-features", []), "required-features")
        test = target.get("test")
        doctest = target.get("doctest")
        doc = target.get("doc")
        if type(test) is not bool or type(doctest) is not bool or type(doc) is not bool:
            raise ValueError("Cargo target boolean capability is missing")
        identity = (name, tuple(kind), src_path)
        if identity in identities:
            raise ValueError("duplicate Cargo target identity")
        identities.add(identity)
        names.add(name)
        rows.append(
            {
                "name": name,
                "kind": kind,
                "crateTypes": crate_types,
                "requiredFeatures": required_features,
                "srcPath": src_path,
                "edition": edition,
                "test": test,
                "doctest": doctest,
                "doc": doc,
            }
        )

    libraries = [row for row in rows if "lib" in row["kind"] or "proc-macro" in row["kind"]]
    if len(libraries) != 1:
        raise ValueError("expected exactly one library target")
    testable = [row for row in rows if row["test"]]
    if not testable:
        raise ValueError("Cargo exposes no test-capable target")
    missing = sorted(set(required_targets) - names)
    if missing:
        raise ValueError("required Cargo targets are missing: " + ",".join(missing))

    rows.sort(key=lambda row: (row["name"], row["kind"], row["srcPath"]))
    return {
        "schema": "hepta.learning-artifacts.cargo-target-inventory.v1",
        "metadataFormatVersion": 1,
        "packageName": package_name,
        "packageId": package_id,
        "manifestPath": manifest_path,
        "targetCount": len(rows),
        "testCapableTargetCount": len(testable),
        "requiredTargets": sorted(set(required_targets)),
        "targets": rows,
    }


def cargo_metadata(manifest: Path) -> object:
    command = [
        "cargo",
        "metadata",
        "--locked",
        "--format-version",
        "1",
        "--no-deps",
        "--manifest-path",
        str(manifest),
    ]
    data = subprocess.check_output(command)
    if len(data) > MAX_METADATA:
        raise ValueError("Cargo metadata exceeds bounded input profile")
    return strict_json(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--require-target", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        inventory = inventory_from_metadata(
            cargo_metadata(args.manifest), args.package, tuple(args.require_target)
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("xb") as stream:
            stream.write(canonical(inventory))
        print(json.dumps({"cargoTargetInventory": "valid", "targets": inventory["targetCount"]}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(json.dumps({"cargoTargetInventory": "refused", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

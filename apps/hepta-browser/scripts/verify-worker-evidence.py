#!/usr/bin/env python3
"""Validate current-pin feature admission and exact worker build evidence."""

import argparse
import hashlib
import json
import tomllib
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_metadata(metadata, topology):
    pin = topology["source"]["commit"]
    source = (
        f"git+https://github.com/{topology['source']['repository']}.git?rev={pin}#{pin}"
    )
    packages = metadata["packages"]
    require(
        not any(p["name"] == "webdriver_server" for p in packages),
        "webdriver_server entered the worker dependency graph",
    )
    servo = [p for p in packages if p["name"] == "servo"]
    require(len(servo) == 1, "expected exactly one Servo package")
    require(servo[0].get("source") == source, "Servo repository or source pin mismatch")
    nodes = [n for n in metadata["resolve"]["nodes"] if n["id"] == servo[0]["id"]]
    require(len(nodes) == 1, "resolved Servo feature node missing")
    features = set(nodes[0]["features"])
    decision = topology["decision"]
    forbidden = set(decision["initiallyForbiddenServoFeatures"]) | {"webdriver_server"}
    require(
        not features & forbidden,
        "forbidden Servo features: " + str(sorted(features & forbidden)),
    )
    require(
        set(decision["requiredServoFeatures"]) <= features,
        "required Servo features missing",
    )


def verify_receipt(root, topology, source_sha, source_tree, worker_sha, source_lock):
    receipt = json.loads((root / "build-receipt.json").read_text())
    require(
        receipt["schema"] == "hepta.browser.servo-worker-build-receipt.v1",
        "receipt schema mismatch",
    )
    require(receipt["sourceSha"] == source_sha, "receipt source mismatch")
    require(receipt["sourceTree"] == source_tree, "receipt source tree mismatch")
    require(
        receipt["servoPin"] == topology["source"]["commit"],
        "receipt Servo pin mismatch",
    )
    require(
        (root / "cargo-lock-source.txt").read_text().strip() == "committed",
        "target qualification requires a reviewed committed Cargo.lock",
    )
    require(
        digest(root / "Cargo.lock") == digest(source_lock),
        "lock differs from checked-out source",
    )
    for field, name in [
        ("workerSha256", "hepta-servo-worker"),
        ("cargoLockSha256", "Cargo.lock"),
        ("sbomSha256", "hepta-servo-worker.spdx.json"),
    ]:
        require(receipt[field] == digest(root / name), field + " mismatch")
    require(receipt["workerSha256"] == worker_sha, "reviewed worker digest mismatch")
    require(
        receipt["reproducibleIndependentBuilds"] is True,
        "reproducible build evidence missing",
    )
    probe = receipt["linuxSandboxProbe"]
    for field in [
        "externalNetworkDenied",
        "hostSecretHidden",
        "generalHostBinariesHidden",
        "privateProfileWritable",
    ]:
        require(probe[field] is True, "sandbox evidence missing: " + field)
    smoke = receipt["realWorkerSmoke"]
    require(smoke["workerSha256"] == worker_sha, "smoke worker digest mismatch")
    for field in [
        "currentPinWorkerBooted",
        "privateProtocolRoundTrip",
        "sandboxedStartStop",
    ]:
        require(smoke[field] is True, "worker smoke evidence missing: " + field)
    verify_metadata(json.loads((root / "cargo-metadata.json").read_text()), topology)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", required=True, type=Path)
    parser.add_argument("--pin-manifest", required=True, type=Path)
    parser.add_argument("--worker-manifest", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--metadata", type=Path)
    mode.add_argument("--receipt-root", type=Path)
    parser.add_argument("--source-sha")
    parser.add_argument("--source-tree")
    parser.add_argument("--worker-sha")
    args = parser.parse_args()
    topology = json.loads(args.topology.read_text())
    pin_manifest = json.loads(args.pin_manifest.read_text())
    worker = tomllib.loads(args.worker_manifest.read_text())["dependencies"]["servo"]
    require(
        topology["source"]["commit"]
        == pin_manifest["upstream_commit"]
        == worker["rev"],
        "canonical pin, topology and worker dependency disagree",
    )
    repository = pin_manifest["upstream_repository"]
    require(
        topology["source"]["repository"] == repository
        and worker["git"] == f"https://github.com/{repository}.git",
        "canonical Servo repository mismatch",
    )
    require(
        worker["default-features"] is False, "Servo default features must be disabled"
    )
    if args.metadata:
        verify_metadata(json.loads(args.metadata.read_text()), topology)
    else:
        require(
            all([args.source_sha, args.source_tree, args.worker_sha]),
            "exact receipt identities required",
        )
        verify_receipt(
            args.receipt_root,
            topology,
            args.source_sha,
            args.source_tree,
            args.worker_sha,
            args.worker_manifest.parent / "Cargo.lock",
        )
    print("Worker evidence bindings verified.")


if __name__ == "__main__":
    main()

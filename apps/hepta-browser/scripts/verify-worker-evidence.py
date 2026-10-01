#!/usr/bin/env python3
"""Validate current-pin feature admission and exact worker build evidence."""

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from pathlib import PurePosixPath

SERVICE_BUNDLE = "hepta-browser-service.mjs"
SERVICE_RECEIPT = SERVICE_BUNDLE + ".receipt.json"
SERVICE_EXTERNAL_MODULES = {
    "node:child_process",
    "node:crypto",
    "node:fs",
    "node:fs/promises",
    "node:path",
}


@contextmanager
def regular_input(path, maximum):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum,
            "evidence input must be a bounded regular file: " + str(path),
        )
        yield stream


def digest(path, maximum=512 * 1024 * 1024):
    hasher = hashlib.sha256()
    total = 0
    with regular_input(path, maximum) as stream:
        while chunk := stream.read(min(65536, maximum - total + 1)):
            total += len(chunk)
            require(total <= maximum, "evidence input grew beyond its bound")
            hasher.update(chunk)
    return hasher.hexdigest()


def read_json(path, maximum=1024 * 1024):
    with regular_input(path, maximum) as stream:
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, "evidence JSON exceeds its bound")
    return json.loads(data.decode("utf-8"))


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


def verify_service(root, source_root):
    receipt = read_json(root / SERVICE_RECEIPT)
    require(
        receipt["schema"] == "hepta.browser.service-build-receipt.v1",
        "service receipt schema mismatch",
    )
    require(
        receipt["builder"]
        == {"name": "esbuild", "version": "0.28.1", "parserVersion": "8.15.0"},
        "service builder identity mismatch",
    )
    require(receipt["nodeTarget"] == "node24", "service Node target mismatch")
    require(
        receipt["bundleSha256"] == digest(root / SERVICE_BUNDLE, 8 * 1024 * 1024),
        "service bundle digest mismatch",
    )
    for field, name in [
        ("buildRecipeSha256", "scripts/build-service.mjs"),
        ("packageLockSha256", "package-lock.json"),
    ]:
        require(
            receipt[field] == digest(source_root / name, 1024 * 1024),
            field + " mismatch",
        )
    inputs = receipt["inputs"]
    require(isinstance(inputs, list) and 1 <= len(inputs) <= 64, "invalid service inputs")
    paths = [item["path"] for item in inputs]
    require(paths == sorted(set(paths)), "service input paths must be unique and sorted")
    require("src/agentd-service-main.js" in paths, "service entrypoint input missing")
    for item in inputs:
        path = item["path"]
        parts = PurePosixPath(path).parts
        require(
            path.startswith("src/")
            and path.endswith(".js")
            and "\\" not in path
            and "\0" not in path
            and ".." not in parts
            and str(PurePosixPath(path)) == path,
            "invalid service input path",
        )
        source = source_root / path
        require(
            not source.is_symlink()
            and source.resolve(strict=True).is_relative_to(
                source_root.resolve(strict=True)
            ),
            "service input escapes checked-out source",
        )
        require(
            item["sha256"] == digest(source, 1024 * 1024),
            "service source input digest mismatch: " + path,
        )
    external = receipt["externalModules"]
    require(
        isinstance(external, list)
        and external == sorted(set(external))
        and set(external) <= SERVICE_EXTERNAL_MODULES,
        "unreviewed service external module",
    )
    # Hashes in a receipt alone do not prove that its listed files are the
    # complete import closure, or that its bundle was built from those files.
    # Rebuild with the checked-out pinned recipe and compare both products.
    with tempfile.TemporaryDirectory(prefix="hepta-service-rebuild-") as temporary:
        output = Path(temporary) / SERVICE_BUNDLE
        recipe = Path(__file__).with_name("build-service.mjs").resolve()
        script = (
            "import { buildService } from " + json.dumps(recipe.as_uri()) + ";"
            "await buildService({ outputPath: process.argv[1], sourceRoot: process.argv[2] });"
        )
        result = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                script,
                str(output),
                str(source_root / "src"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        require(result.returncode == 0, "service rebuild failed: " + result.stderr[:4096])
        require(
            digest(output, 8 * 1024 * 1024) == receipt["bundleSha256"],
            "service bundle differs from source rebuild",
        )
        rebuilt = read_json(Path(str(output) + ".receipt.json"))
        require(rebuilt == receipt, "service receipt differs from complete source rebuild")


def verify_receipt(
    root, topology, source_sha, source_tree, worker_sha, source_lock, service_source_root
):
    receipt = read_json(root / "build-receipt.json")
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
    for field, name, maximum in [
        ("workerSha256", "hepta-servo-worker", 512 * 1024 * 1024),
        ("cargoLockSha256", "Cargo.lock", 16 * 1024 * 1024),
        ("sbomSha256", "hepta-servo-worker.spdx.json", 64 * 1024 * 1024),
        ("serviceSha256", SERVICE_BUNDLE, 8 * 1024 * 1024),
        ("serviceReceiptSha256", SERVICE_RECEIPT, 1024 * 1024),
    ]:
        require(receipt[field] == digest(root / name, maximum), field + " mismatch")
    require(receipt["workerSha256"] == worker_sha, "reviewed worker digest mismatch")
    require(
        receipt["reproducibleIndependentBuilds"] is True,
        "reproducible build evidence missing",
    )
    require(
        receipt["reproducibleServiceBuilds"] is True,
        "reproducible service build evidence missing",
    )
    verify_service(root, service_source_root)
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
    verify_metadata(
        read_json(root / "cargo-metadata.json", 64 * 1024 * 1024), topology
    )


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
    parser.add_argument("--service-source-root", type=Path)
    args = parser.parse_args()
    topology = read_json(args.topology)
    pin_manifest = read_json(args.pin_manifest)
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
        verify_metadata(read_json(args.metadata, 64 * 1024 * 1024), topology)
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
            args.service_source_root or args.worker_manifest.parent.parent,
        )
    print("Worker evidence bindings verified.")


if __name__ == "__main__":
    main()

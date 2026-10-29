"""Published source/binary and selection identities, checked before phase work."""

from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

import numpy as np
import scipy

from .common import PACKAGE, REPOSITORY, REMOTE, protocol, read_json, save_json, sha


def verify_publication(commit, relative, expected):
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise ValueError("A complete published commit identity is required")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, REMOTE],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
    )
    raw = subprocess.check_output(
        ["git", "show", f"{commit}:{relative}"], cwd=REPOSITORY
    )
    if raw != expected:
        raise ValueError("Published artifact bytes differ from current sealed bytes")


def freeze(binary, build_receipt, native_manifest):
    value = protocol()
    if value["status"] != "FROZEN_BEFORE_TRAINING":
        raise ValueError("Finalize the declared protocol before creating a source seal")
    old_path = PACKAGE.parent / "continuous_boundary_policy/SOURCE_SEAL.json"
    inherited = read_json(old_path)
    files = dict(inherited["source_files"])
    for name, expected in files.items():
        if sha((REPOSITORY / name).read_bytes()) != expected:
            raise ValueError(f"Prior scientific source changed: {name}")
    receipt, manifest = read_json(build_receipt), read_json(native_manifest)
    if (
        receipt["source_sha256"] != manifest
        or receipt["binary_sha256"] != sha(Path(binary).read_bytes())
        or receipt["base_commit"] != "5898cd8b0f724c3152b6cc52856721f72e5e08be"
        or not receipt["native_rust_sources_unmodified"]
        or not receipt["external_dependencies_match_original_lock"]
    ):
        raise ValueError("Native build is not the declared original-source executable")
    for name, expected in manifest.items():
        if (
            name.startswith("experiments/")
            and sha((REPOSITORY / name).read_bytes()) != expected
        ):
            raise ValueError("Native research wrapper differs from build")
    native = PACKAGE / "native"
    native.mkdir(exist_ok=True)
    for source, name in [
        (build_receipt, "BUILD_RECEIPT.json"),
        (native_manifest, "SOURCE_MANIFEST.json"),
    ]:
        target = native / name
        raw = Path(source).read_bytes()
        if target.exists() and target.read_bytes() != raw:
            raise ValueError(
                "Preserve existing native build records; use a new study version"
            )
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(raw)
        files[str(target.relative_to(REPOSITORY))] = sha(raw)
    for path in PACKAGE.rglob("*.py"):
        files[str(path.relative_to(REPOSITORY))] = sha(path.read_bytes())
    files[str((PACKAGE / "PROTOCOL.json").relative_to(REPOSITORY))] = sha(
        (PACKAGE / "PROTOCOL.json").read_bytes()
    )
    seal = {
        "schema": "hepta.native-readout-objective.source-seal.v1",
        "source_files": files,
        "native_binary_sha256": receipt["binary_sha256"],
        "native_source_manifest_sha256": sha(Path(native_manifest).read_bytes()),
        "native_build_receipt_sha256": sha(Path(build_receipt).read_bytes()),
        "parent_source_seal_sha256": sha(old_path.read_bytes()),
        "scope": "new native build identity and independent objective study; prior experiments unchanged",
    }
    identity = save_json(PACKAGE / "SOURCE_SEAL.json", seal)
    return {
        "source_seal_sha256": identity,
        "source_files": len(files),
        "native_binary_sha256": seal["native_binary_sha256"],
    }


def verify_source(source, binary):
    if sha(Path(binary).read_bytes()) != source["native_binary_sha256"]:
        raise ValueError("Executable differs from source-bound native build")
    for relative, expected in source["source_files"].items():
        path = REPOSITORY / relative
        if (
            not path.resolve().is_relative_to(REPOSITORY.resolve())
            or sha(path.read_bytes()) != expected
        ):
            raise ValueError(f"Frozen source identity changed: {relative}")


def initialize(output, binary, commit):
    value = protocol()
    if value["status"] != "FROZEN_BEFORE_TRAINING":
        raise ValueError("Draft protocols cannot start scientific training")
    for name in ["PROTOCOL.json", "SOURCE_SEAL.json"]:
        verify_publication(
            commit,
            str((PACKAGE / name).relative_to(REPOSITORY)),
            (PACKAGE / name).read_bytes(),
        )
    source = read_json(PACKAGE / "SOURCE_SEAL.json")
    verify_source(source, binary)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name in ["PROTOCOL.json", "SOURCE_SEAL.json"]:
        shutil.copyfile(PACKAGE / name, output / name)
    (output / "costs.jsonl").touch()
    save_json(
        output / "ENVIRONMENT.json",
        {
            "schema": "hepta.native-readout-objective.environment.v1",
            "python": sys.version,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "platform": platform.platform(),
            "publication_commit": commit,
            "publication_remote_ref": REMOTE,
            "native_binary_sha256": source["native_binary_sha256"],
            "native_source_manifest_sha256": source["native_source_manifest_sha256"],
            "protocol_sha256": sha((output / "PROTOCOL.json").read_bytes()),
            "source_seal_sha256": sha((output / "SOURCE_SEAL.json").read_bytes()),
        },
    )


def verify_frozen(output, binary):
    output = Path(output)
    env = read_json(output / "ENVIRONMENT.json")
    for name, key in [
        ("PROTOCOL.json", "protocol_sha256"),
        ("SOURCE_SEAL.json", "source_seal_sha256"),
    ]:
        if sha((output / name).read_bytes()) != env[key]:
            raise ValueError("Study's frozen identity changed")
        verify_publication(
            env["publication_commit"],
            str((PACKAGE / name).relative_to(REPOSITORY)),
            (output / name).read_bytes(),
        )
    if read_json(output / "PROTOCOL.json") != protocol():
        raise ValueError("Stored and current protocols differ")
    source = read_json(output / "SOURCE_SEAL.json")
    if source["native_binary_sha256"] != env["native_binary_sha256"]:
        raise ValueError("Environment and source seal bind different executables")
    verify_source(source, binary)
    return source

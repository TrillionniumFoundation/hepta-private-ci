"""Create fresh pinned build inputs without a previous session's /tmp tree.

This prepares source and lock files only. Cargo performs authentic locked
dependency downloads and builds afterwards; no vendor checksums are invented.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIDGE = HERE.parents[1] / "native_task_bridge_20261031"


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def main(args):
    pinned = {"build.py": "eefceca764de4c5caa550a09f646400045dd75f1"}
    for name, identity in pinned.items():
        if blob((BRIDGE / name).read_bytes()) != identity:
            raise ValueError("Frozen bridge bootstrap input changed: " + name)
    spec = importlib.util.spec_from_file_location("frozen_native_bridge_build", BRIDGE / "build.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    target = args.existing_build.resolve()
    target.mkdir(parents=True, exist_ok=False)
    files = {}
    identity = json.loads((HERE / "SOURCE_IDENTITY.json").read_text())
    for item in identity["files"]:
        data = (args.source_root / item["path"]).read_bytes()
        if blob(data) != item["git_blob_sha"]:
            raise ValueError("Pinned native source mismatch: " + item["path"])
        path = target / "upstream" / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files[item["path"]] = hashlib.sha256(data).hexdigest()
    (target / "upstream/codex-rs/Cargo.toml").write_text(bridge.WORKSPACE)
    (target / "Cargo.toml").write_text(bridge.manifest(target).replace("codex-task-native-v2", "codex-native-event-owner-r8"))
    lock = (HERE / "native-Cargo.lock").read_bytes()
    if hashlib.sha256(lock).hexdigest() != "6bbac28b4ea02636d97d28db3ede87a2fe096e764f5434395b755180505e15bf":
        raise ValueError("Frozen owner Cargo lock changed")
    (target / "Cargo.lock").write_bytes(lock)
    (target / "nextest.toml").write_text(bridge.NEXTEST)
    cache = args.cargo_cache.resolve() / "registry"
    registry = target / "cargo-home/registry"
    registry.mkdir(parents=True)
    for name in ("index", "cache", "src"):
        (cache / name).mkdir(parents=True, exist_ok=True)
        (registry / name).symlink_to(cache / name, target_is_directory=True)
    result = dict(schema="hcsn.native-owner-fresh-inputs.v1", source_files=files,
        source_identity_sha256=hashlib.sha256((HERE / "SOURCE_IDENTITY.json").read_bytes()).hexdigest(),
        bridge_inputs=pinned, lock_source="native_owner/native-Cargo.lock recovered byte-for-byte from successful BUILD_ATTEMPT_05 derived_lock",
        copied_lock_sha256=hashlib.sha256((target / "Cargo.lock").read_bytes()).hexdigest(),
        dependency_resolution_performed=False, cargo_build_performed=False,
        next="Use cargo fetch --locked on this manifest, then native_owner/build.py; keep reports and target directories distinct")
    (target / "BOOTSTRAP.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(dict(source_files=len(files), existing_build=str(target), prepared=True)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("source-root", "existing-build", "cargo-cache"):
        parser.add_argument("--"+key, type=Path, required=True)
    main(parser.parse_args())

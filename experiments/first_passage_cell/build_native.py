"""Build the unchanged NDU owner crates with a bounded research transport.

Usage: python build_native.py --source-root REPO --output BUILD --toolchain BIN
       --nextest-bin DIR --just-bin DIR [--download-dependencies]
The source SHA manifest and locked registry package checksums are mandatory.
No owner source, original Cargo manifest, or workspace lockfile is modified.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request

BASE_COMMIT = "ed6f8c6645c927249cec0d3395f6bae21f278739"
HERE = Path(__file__).resolve().parent


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_source(source):
    manifest_bytes = (HERE / "NATIVE_SOURCE_MANIFEST.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest["source_commit"] != BASE_COMMIT:
        raise ValueError("unregistered native source commit")
    for entry in manifest["files"]:
        payload = (source / entry["path"]).read_bytes()
        git_hash = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        if digest(payload) != entry["sha256"] or git_hash != entry["git_blob"]:
            raise ValueError("native source mismatch: " + entry["path"])
    return digest(manifest_bytes)


def vendor_dependencies(lock, destination, allow_download):
    """Use exact lock checksums; no package index or version resolution."""
    packages = [p for p in tomllib.loads(lock.read_text())["package"] if "checksum" in p]
    destination.mkdir(parents=True, exist_ok=True)

    def obtain(package):
        name, version, checksum = package["name"], package["version"], package["checksum"]
        location = destination / (name + "-" + version)
        receipt = location / ".cargo-checksum.json"
        if receipt.exists():
            previous = json.loads(receipt.read_text())
            if previous["package"] != checksum:
                raise ValueError("cached crate checksum mismatch")
            for path, expected in previous["files"].items():
                if digest((location / path).read_bytes()) != expected:
                    raise ValueError("cached crate file changed")
            return
        if not allow_download:
            raise ValueError("missing locked dependency; pass --download-dependencies: " + name)
        url = "https://static.crates.io/crates/" + name + "/" + name + "-" + version + ".crate"
        payload = urllib.request.urlopen(url, timeout=45).read()
        if digest(payload) != checksum:
            raise ValueError("registry lock checksum mismatch: " + name)
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for member in archive.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                    raise ValueError("unsafe crate archive path")
            archive.extractall(destination, filter="data")
        hashes = {str(path.relative_to(location)): digest(path.read_bytes())
                  for path in sorted(location.rglob("*")) if path.is_file()}
        receipt.write_bytes(encoded({"files": hashes, "package": checksum}))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(obtain, packages))
    return packages


def build(args):
    source, output = args.source_root.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_digest = checked_source(source)
    owner = source / "codex-rs"
    cargo = '''[package]\nname = "hepta-first-passage-ndu-bridge"\nversion = "0.1.0"\nedition = "2024"\nlicense = "Apache-2.0"\npublish = false\n[workspace]\n[[bin]]\nname = "hepta-first-passage-ndu-bridge"\npath = "native_bridge.rs"\n[dependencies]\n'''
    cargo += "codex-hepta-ndu = { path = " + json.dumps(str(owner / "hepta-ndu")) + " }\n"
    cargo += "codex-hepta-types = { path = " + json.dumps(str(owner / "hepta-types")) + " }\n"
    cargo += 'serde = { version = "1", features = ["derive"] }\nserde_json = "1"\n[profile.dev]\ndebug = 0\nincremental = false\n[profile.test]\ndebug = 0\nincremental = false\n'
    (output / "Cargo.toml").write_text(cargo)
    for name in ("native_bridge.rs", "native_bridge_tests.rs"):
        shutil.copyfile(HERE / name, output / name)
    shutil.copyfile(HERE / "native-Cargo.lock", output / "Cargo.lock")
    packages = vendor_dependencies(output / "Cargo.lock", output / "vendor", args.download_dependencies)
    cargo_home = output / "cargo-home"
    cargo_home.mkdir(exist_ok=True)
    (cargo_home / "config.toml").write_text(
        '[source.crates-io]\nreplace-with = "locked-vendor"\n[source.locked-vendor]\ndirectory = '
        + json.dumps(str(output / "vendor")) + '\n[net]\noffline = true\n')
    temporary = output / "tmp"
    temporary.mkdir(exist_ok=True)
    target = args.target_dir.resolve() if args.target_dir else output / "target"
    environment = dict(os.environ)
    environment.update({"CARGO_HOME": str(cargo_home), "CARGO_TARGET_DIR": str(target), "CARGO_BUILD_JOBS": "1", "CARGO_INCREMENTAL": "0",
                        "TMPDIR": str(temporary), "RUSTUP_TOOLCHAIN": "1.95.0",
                        "PATH": os.pathsep.join([str(args.toolchain), str(args.nextest_bin),
                                                  str(args.just_bin), os.environ["PATH"]]),
                        "HEPTA_NDU_SOURCE_COMMIT": BASE_COMMIT,
                        "HEPTA_NDU_SOURCE_DIGEST": source_digest,
                        "HEPTA_NDU_BRIDGE_DIGEST": digest((HERE / "native_bridge.rs").read_bytes())})
    rustc = subprocess.check_output([str(args.toolchain / "rustc"), "--version"], env=environment, text=True).strip()
    environment["HEPTA_NDU_RUSTC"] = rustc
    subprocess.run([str(args.toolchain / "cargo"), "build", "--manifest-path", str(output / "Cargo.toml"),
                    "--locked", "--offline"], env=environment, check=True, cwd=output)
    # Use the repository's actual unmodified just test / nextest runner.
    subprocess.run([str(args.just_bin / "just"), "--justfile", str(source / "justfile"), "test",
                    "-p", "hepta-first-passage-ndu-bridge", "--manifest-path", str(output / "Cargo.toml"),
                    "--locked", "--offline", "--profile", "default"], env=environment, check=True, cwd=source)
    binary = output / "hepta-first-passage-ndu-bridge"
    shutil.copyfile(target / "debug/hepta-first-passage-ndu-bridge", binary)
    binary.chmod(0o755)
    identity = json.loads(subprocess.check_output([str(binary), "--identity"], env=environment))
    manifest = {"schema": "hepta.first-passage.native-build.v1", "identity": identity,
                "binary": str(binary), "binary_sha256": digest(binary.read_bytes()),
                "source_manifest_sha256": source_digest,
                "lock_sha256": digest((HERE / "native-Cargo.lock").read_bytes()),
                "adapter_sha256": digest((HERE / "native_bridge.rs").read_bytes()),
                "test_adapter_sha256": digest((HERE / "native_bridge_tests.rs").read_bytes()),
                "registry_packages": len(packages), "source_owner_unchanged": True,
                "test_command": "original just test -p hepta-first-passage-ndu-bridge --profile default",
                "test_status": "passed"}
    (output / "NATIVE_BUILD.json").write_bytes(encoded(manifest) + b"\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("source-root", "output", "toolchain", "nextest-bin", "just-bin"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--download-dependencies", action="store_true")
    parser.add_argument("--target-dir", type=Path)
    build(parser.parse_args())

"""Launch the existing read-only product gateway with its owned Rust UI build.

The manifest digest is derived from the actual build, not supplied as a receipt
or treated as signing authority. This does not create runtime state or keys.
"""

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


def bundle_arguments(root):
    manifest_path = root / "dist/build-manifest.json"
    if os.name != "posix":
        raise ValueError(
            "Product UI bundle launch needs a reviewed anchored reader on this platform"
        )
    # Walk from a pinned directory descriptor; reject symlink ancestors and a
    # FIFO/device final entry before reading. No canonicalize/open fallback.
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        if not manifest_path.is_absolute() or ".." in manifest_path.parts:
            raise ValueError("Manifest path must be normalized and absolute")
        for part in manifest_path.parts[1:-1]:
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            os.close(directory)
            directory = child
        descriptor = os.open(
            manifest_path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("UI manifest is not a regular file")
            if metadata.st_size > MAX_MANIFEST_BYTES:
                raise ValueError("UI manifest exceeds the supported bound")
            data = source.read(MAX_MANIFEST_BYTES + 1)
    finally:
        os.close(directory)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("UI manifest exceeds the supported bound")
    manifest = json.loads(data)
    if (
        manifest.get("schema") != "hepta.robrix-ui.build.v1"
        or manifest.get("browserRuntime") != "rust-makepad-wasm"
        or manifest.get("fixtures") is not False
    ):
        raise ValueError("Build the production Rust UI before launching the product")
    script = """
import {robrixSourceIdentity} from './tools/robrix-source-identity.mjs';
console.log((await robrixSourceIdentity(process.cwd())).sha256);
"""
    current = subprocess.check_output(
        ["node", "--input-type=module", "-e", script], cwd=root, text=True
    ).strip()
    if current != manifest.get("sourceIdentity", {}).get("sha256"):
        raise ValueError("UI build is stale; rebuild the current source")
    return [
        "--ui-bundle",
        str((root / "dist").resolve(strict=True)),
        "--ui-manifest-sha256",
        hashlib.sha256(data).hexdigest(),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hepta", type=Path, required=True, help="Built product hepta executable"
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        required=True,
        help="State directory; missing runtime contents are shown as unavailable",
    )
    parser.add_argument("--listen", default="127.0.0.1:7373")
    parser.add_argument(
        "--no-build", action="store_true", help="Verify and reuse a current build"
    )
    args = parser.parse_args()
    executable = args.hepta.resolve(strict=True)
    state = args.state_root.resolve(strict=True)
    if not executable.is_file() or not state.is_dir():
        parser.error("Supply a built executable and an existing state directory")
    if not args.no_build:
        subprocess.run(["node", "tools/build.mjs"], cwd=ROOT, check=True)
    bundle = bundle_arguments(ROOT)
    subprocess.run(
        [
            str(executable),
            "--serve-ui",
            "--listen",
            args.listen,
            "--state-root",
            str(state),
            *bundle,
        ],
        check=True,
    )


if __name__ == "__main__":
    main()

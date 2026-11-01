"""Build the standalone Rust research operator; no Cargo/network dependency."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

ROOT = Path(__file__).resolve().parent


def build(destination, rustc):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.glob("*.rs"))}
    identity = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    env = dict(os.environ, HCSN_NATIVE_SOURCE_SHA256=identity)
    version = subprocess.run([rustc, "--version", "--verbose"], check=True, capture_output=True, text=True).stdout
    suffix = {"Linux": ".so", "Darwin": ".dylib", "Windows": ".dll"}[platform.system()]
    library = destination / ("libhcsn_prepared" + suffix)
    commands = [[rustc, "--edition=2021", "-O", "--crate-type=cdylib", str(ROOT / "lib.rs"), "-o", str(library)]]
    if (ROOT / "main.rs").exists():
        commands.append([rustc, "--edition=2021", "-O", str(ROOT / "main.rs"), "-o", str(destination / "hcsn-native-r13")])
    if (ROOT / "events_main.rs").exists():
        commands.append([rustc, "--edition=2021", "-O", str(ROOT / "events_main.rs"), "-o", str(destination / "hcsn-events-r13")])
    receipts = []
    for command in commands:
        start = time.perf_counter()
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        receipts.append(dict(command=command, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                             wall_seconds=time.perf_counter() - start))
        if result.returncode:
            (destination / "BUILD_FAILED.json").write_text(json.dumps(receipts, indent=2) + "\n")
            raise RuntimeError(result.stderr)
    result = dict(schema="hcsn-r13-native-build-v1", source_sha256=sources, source_identity=identity,
                  compiler=version, commands=receipts,
                  binaries={Path(c[-1]).name: hashlib.sha256(Path(c[-1]).read_bytes()).hexdigest() for c in commands})
    (destination / "BUILD_RECEIPT.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "evidence" / "build"))
    parser.add_argument("--rustc", default="/tmp/hepta-digital-rust195/bin/rustc")
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output, arguments.rustc), indent=2))

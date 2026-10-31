"""Build the declared Linux research profile against unchanged native sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

BASE = "eb5a1cc503e1ea6592d68e73c95b94d24564352a"
PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parents[1]
CRATES = ("hepta-neuron", "hepta-infer-core", "hepta-types")
NEXTEST = """[profile.default]
slow-timeout = { period = "10s", terminate-after = 2 }
retries = 0
[profile.local]
inherits = "default"
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def provenance():
    paths = git("ls-files", "--", *("codex-rs/" + c for c in CRATES)).decode().splitlines()
    paths = [p for p in paths if p.endswith(".rs") or p.endswith("Cargo.toml")]
    paths += ["codex-rs/Cargo.toml", "codex-rs/rust-toolchain.toml"]
    upstream = {}
    for path in sorted(paths):
        committed = git("show", BASE + ":" + path)
        if (ROOT / path).read_bytes() != committed:
            raise RuntimeError("native baseline modified: " + path)
        upstream[path] = sha(committed)
    owned = {p.name: sha(p.read_bytes()) for p in sorted(PACKAGE.glob("*.rs"))}
    for name in ["fixture.json", "owner-Cargo.lock", "build.py", "verify.py", "rustfmt.toml"]:
        owned[name] = sha((PACKAGE / name).read_bytes())
    source = {"baseline_commit": BASE, "upstream_sha256": upstream, "owner_sha256": owned}
    source["source_digest"] = sha(json.dumps(source, sort_keys=True, separators=(",", ":")).encode())
    return source


def manifest():
    def path(crate):
        return json.dumps(str(ROOT / "codex-rs" / crate))

    return f"""[package]
name = "codex-fpt-owner-v2"
version = "0.1.0"
edition = "2024"
[workspace]
[[bin]]
name = "codex-fpt-owner-v2"
path = "main.rs"
[dependencies]
codex-hepta-neuron = {{ path = {path('hepta-neuron')} }}
codex-hepta-types = {{ path = {path('hepta-types')} }}
serde = {{ version = "1", features = ["derive"] }}
serde_json = "1"
libc = "=0.2.186"
[profile.dev]
debug = 0
incremental = false
"""


def run(command, directory, environment):
    started = time.monotonic()
    result = subprocess.run(command, cwd=directory, env=environment, capture_output=True, text=True)
    return {"command": command, "cwd": str(directory), "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr,
            "wall_seconds": time.monotonic() - started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--test", action="store_true", help="also run the contract tests through just test")
    args = parser.parse_args()
    if os.uname().sysname != "Linux":
        raise SystemExit("This profile is explicitly Linux-only.")
    if args.report.exists():
        raise SystemExit("Refusing to overwrite an existing build report.")
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    source = provenance()
    for path in PACKAGE.glob("*.rs"):
        shutil.copy2(path, build / path.name)
    shutil.copy2(PACKAGE / "fixture.json", build / "fixture.json")
    shutil.copy2(PACKAGE / "owner-Cargo.lock", build / "Cargo.lock")
    (build / "Cargo.toml").write_text(manifest())
    (build / "nextest.toml").write_text(NEXTEST)
    environment = os.environ.copy()
    environment.update(CARGO_TARGET_DIR=str(build / "target"), CARGO_BUILD_JOBS="2",
                       CARGO_INCREMENTAL="0", HEPTA_FPT_NATIVE_SOURCE_DIGEST=source["source_digest"])
    commands = [run(["rustc", "--version", "--verbose"], build, environment)]
    commands.append(run(["cargo", "build", "--offline", "--locked", "--manifest-path", str(build / "Cargo.toml")], build, environment))
    if args.test and all(c["returncode"] == 0 for c in commands):
        commands.append(run(["just", "test", "--offline", "--locked", "--manifest-path", str(build / "Cargo.toml"),
                             "--config-file", str(build / "nextest.toml"), "-p", "codex-fpt-owner-v2"], ROOT, environment))
    success = all(c["returncode"] == 0 for c in commands)
    binary = build / "target/debug/codex-fpt-owner-v2"
    report = {"schema": "hepta.fpt.owner-adoption.build.v2", **source,
              "derived_manifest": manifest(), "nextest_config": NEXTEST,
              "cargo_lock_sha256": sha((build / "Cargo.lock").read_bytes()),
              "commands": commands, "success": success,
              "binary": str(binary), "binary_sha256": sha(binary.read_bytes()) if success else None,
              "authority": "DENY_ALL", "production_activation": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"success": success, "binary": str(binary), "source_digest": source["source_digest"],
                      "report": str(args.report), "commands": [{"command": c["command"], "returncode": c["returncode"]} for c in commands]}))
    if not success:
        for command in commands:
            if command["returncode"]:
                print(command["stdout"] + command["stderr"])
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()

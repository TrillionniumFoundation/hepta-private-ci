#!/usr/bin/env python3
"""Verify parser/provider compatibility and a fresh private Secret Service session.

The old transport and YAML reader occur only in isolated comparison manifests.
All Rust tests run through the repository's original ``just test`` recipe.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[1]
SOURCES = [
    "codex-rs/keyring-store/src/lib.rs",
    "codex-rs/keyring-store/tests/provider_compatibility.rs",
    "codex-rs/skills/src/parser.rs",
    "codex-rs/skills/src/parser_tests.rs",
    "codex-rs/skills/tests/yaml_compatibility.rs",
    "scripts/fixtures/keyring_transport_roundtrip.rs",
    "scripts/fixtures/yaml_compatibility_differential.rs",
    "scripts/run_hepta_keyring_compatibility.py",
]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def archive_log(source, destination):
    with source.open("rb") as reader, gzip.open(destination, "wb") as writer:
        shutil.copyfileobj(reader, writer)


def run_logged(command, label, output, env, records):
    started = time.monotonic()
    log = output / f"{label}.log"
    with log.open("wb") as stream:
        result = subprocess.run(command, cwd=REPO, env=env, stdout=stream, stderr=stream)
    archive_log(log, output / f"{label}.log.gz")
    log.unlink()
    receipt = {
        "command": command,
        "exit_code": result.returncode,
        "wall_seconds": time.monotonic() - started,
        "log": f"{label}.log.gz",
    }
    records.append(receipt)
    write_json(output / f"{label}.json", receipt)
    result.check_returncode()


def dependency_versions():
    packages = tomllib.loads((REPO / "codex-rs/Cargo.lock").read_text())["package"]
    wanted = {"keyring", "serde", "thiserror", "pretty_assertions", "anyhow", "tracing"}
    versions = {package["name"]: package["version"] for package in packages if package["name"] in wanted}
    if versions.keys() != wanted or versions["keyring"] != "3.6.3":
        raise RuntimeError("comparison contract requires the reviewed keyring 3.6.3 graph")
    return versions


def make_manifest(directory, mode, versions):
    directory.mkdir(parents=True, exist_ok=True)
    common = [
        "[package]",
        f'name = "hepta-keyring-compat-{mode}"',
        'version = "0.1.0"',
        'edition = "2024"',
        "[workspace]",
        "[lib]",
    ]
    if mode == "offline":
        common += ['path = "loader.rs"']
    else:
        common += [
            'name = "codex_keyring_store"',
            f'path = {json.dumps(str(REPO / "codex-rs/keyring-store/src/lib.rs"))}',
            "test = false",
            "doctest = false",
            "[[test]]",
            'name = "transport_roundtrip"',
            f'path = {json.dumps(str(REPO / "scripts/fixtures/keyring_transport_roundtrip.rs"))}',
        ]
    features = ["crypto-rust"]
    features += ["linux-native-async-persistent"] if mode == "old" else ["linux-native-sync-persistent", "vendored"]
    common += [
        "[dependencies]",
        f'keyring = {{ version = "={versions["keyring"]}", default-features = false, features = {json.dumps(features)} }}',
        f'tracing = "={versions["tracing"]}"',
    ]
    if mode == "offline":
        common += [
            f'serde = {{ version = "={versions["serde"]}", features = ["derive"] }}',
            f'thiserror = "={versions["thiserror"]}"',
            'serde_yaml = { package = "serde_norway", version = "=0.9.42" }',
        ]
        loader = [
            "extern crate self as codex_skills;",
            f'#[path = {json.dumps(str(REPO / "codex-rs/skills/src/parser.rs"))}]',
            "mod parser;",
            "pub use parser::{ParsedSkillFrontmatter, parse_skill_frontmatter_metadata};",
        ]
        for module, source in [
            ("yaml_compatibility", "codex-rs/skills/tests/yaml_compatibility.rs"),
            ("provider_compatibility", "codex-rs/keyring-store/tests/provider_compatibility.rs"),
            ("yaml_differential", "scripts/fixtures/yaml_compatibility_differential.rs"),
        ]:
            loader += ["#[cfg(test)]", f'#[path = {json.dumps(str(REPO / source))}]', f"mod {module};"]
        (directory / "loader.rs").write_text("\n".join(loader) + "\n")
    common += [
        "[dev-dependencies]",
        f'anyhow = "={versions["anyhow"]}"',
        f'pretty_assertions = "={versions["pretty_assertions"]}"',
    ]
    if mode == "offline":
        common += ['serde_yaml_old = { package = "serde_yaml", version = "=0.9.34" }']
    common += ["[profile.dev]", "debug = 0"]
    (directory / "Cargo.toml").write_text("\n".join(common) + "\n")
    (directory / "nextest.toml").write_text('[profile.local]\nretries = 0\n[profile.local.junit]\npath = "junit.xml"\n')
    return directory / "Cargo.toml"


def run_tests(manifest, label, expected, output, env, records):
    command = [
        "just", "test", "--manifest-path", str(manifest),
        "--config-file", str(manifest.parent / "nextest.toml"), "--locked",
        "--success-output", "immediate",
    ]
    command += ["--lib"] if label == "offline" else ["--test", "transport_roundtrip"]
    junit = manifest.parent / "target/nextest/local/junit.xml"
    if junit.exists():
        junit.unlink()
    try:
        run_logged(command, label, output, env, records)
    finally:
        if junit.exists():
            shutil.copyfile(junit, output / f"{label}.junit.xml")
    tree = ET.parse(junit).getroot()
    cases = list(tree.iter("testcase"))
    if len(cases) != expected or any(case.find(tag) is not None for case in cases for tag in ["failure", "error", "skipped"]):
        raise RuntimeError(f"{label}: incomplete or unsuccessful JUnit result")


def stop_owned_process(process):
    if process is None:
        return None
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    return {"pid": process.pid, "exit_code": process.returncode, "terminated": process.poll() is not None}


def run_live(manifests, daemon, output, env, records):
    bus = keyring = None
    cleanup = {}
    private_name = None
    try:
        with tempfile.TemporaryDirectory(prefix="hepta-keyring-") as private:
            private_root = Path(private).resolve()
            private_name = str(private_root)
            local_env = env.copy()
            for name, relative in [
                ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime"),
                ("GNOME_KEYRING_CONTROL", "control"),
            ]:
                directory = private_root / relative
                directory.mkdir(mode=0o700)
                local_env[name] = str(directory)
            nonce = secrets.token_hex(16)
            (private_root / "nonce").write_text(nonce)
            local_env["HEPTA_KEYRING_COMPAT_NONCE"] = nonce
            local_env["HEPTA_KEYRING_COMPAT_ROOT"] = str(private_root)
            address = f"unix:path={private_root}/runtime/bus"
            local_env["DBUS_SESSION_BUS_ADDRESS"] = address
            with (output / "dbus.log").open("wb") as bus_log, (output / "daemon.log").open("wb") as daemon_log:
                try:
                    bus = subprocess.Popen(
                        ["dbus-daemon", "--session", "--nofork", f"--address={address}"],
                        env=local_env, stdout=bus_log, stderr=bus_log, start_new_session=True,
                    )
                    deadline = time.monotonic() + 10
                    while not (private_root / "runtime/bus").exists():
                        if bus.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("private D-Bus did not start")
                        time.sleep(0.05)
                    keyring = subprocess.Popen(
                        [daemon, "--foreground", "--components=secrets", f"--control-directory={private_root}/control", "--unlock"],
                        env=local_env, stdin=subprocess.PIPE, stdout=daemon_log,
                        stderr=daemon_log, start_new_session=True,
                    )
                    keyring.stdin.write(b"hepta-isolated-test-password\n")
                    keyring.stdin.close()
                    deadline = time.monotonic() + 10
                    while True:
                        owner = subprocess.run(
                            ["dbus-send", "--session", "--dest=org.freedesktop.DBus", "--type=method_call", "--print-reply", "/org/freedesktop/DBus", "org.freedesktop.DBus.NameHasOwner", "string:org.freedesktop.secrets"],
                            env=local_env, capture_output=True, text=True, timeout=2,
                        )
                        if owner.returncode == 0 and "boolean true" in owner.stdout:
                            break
                        if keyring.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError("private Secret Service did not acquire its bus name")
                        time.sleep(0.05)
                    for phase, mode in [
                        ("old-create", "old"), ("new-read-update", "new"),
                        ("old-read-update", "old"), ("new-read-delete", "new"),
                        ("old-missing", "old"),
                    ]:
                        local_env["HEPTA_KEYRING_COMPAT_PHASE"] = phase
                        run_tests(manifests[mode], phase, 1, output, local_env, records)
                finally:
                    cleanup["daemon"] = stop_owned_process(keyring)
                    cleanup["bus"] = stop_owned_process(bus)
    finally:
        cleanup["private_root"] = private_name
        cleanup["private_root_removed"] = private_name is not None and not Path(private_name).exists()
        write_json(output / "cleanup.json", cleanup)
        for label in ["dbus", "daemon"]:
            log = output / f"{label}.log"
            if log.exists():
                archive_log(log, output / f"{label}.log.gz")
                log.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--daemon", default="gnome-keyring-daemon")
    parser.add_argument("--mode", choices=["offline", "live", "all"], default="all")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("this Secret Service compatibility lane requires Linux")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "receipt.json").exists():
        parser.error("use a fresh output directory; previous evidence must not be overwritten")
    automatic_work = args.work_dir is None
    work = (args.work_dir or Path(tempfile.mkdtemp(prefix="hepta-keyring-build-"))).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(work).free < 300 * 1024 * 1024:
        parser.error("build volume has less than the 300 MiB free-space reserve")
    versions = dependency_versions()
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(work / "target")
    env["CARGO_BUILD_JOBS"] = env.get("CARGO_BUILD_JOBS", "2")
    env["CARGO_PROFILE_DEV_DEBUG"] = "0"
    records = []
    receipt = {
        "mode": args.mode, "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "source_sha256": {source: hashlib.sha256((REPO / source).read_bytes()).hexdigest() for source in SOURCES},
        "workspace_lock_sha256": hashlib.sha256((REPO / "codex-rs/Cargo.lock").read_bytes()).hexdigest(),
        "comparison_versions": versions, "commands": records, "passed": False,
        "scope": "isolated exact-source comparison; does not certify full workspace or native Windows",
    }
    try:
        modes = ["offline"] if args.mode == "offline" else ["old", "new"]
        if args.mode == "all":
            modes.insert(0, "offline")
        manifests = {mode: make_manifest(work / mode, mode, versions) for mode in modes}
        for mode, manifest in manifests.items():
            run_logged(["cargo", "generate-lockfile", "--manifest-path", str(manifest)], f"{mode}-resolve", output, env, records)
            for name in ["Cargo.toml", "Cargo.lock", "nextest.toml"]:
                shutil.copyfile(manifest.parent / name, output / f"{mode}-{name}")
            run_logged(["cargo", "tree", "--manifest-path", str(manifest), "--locked", "--edges", "normal", "--prefix", "none", "--format", "{p} {f}"], f"{mode}-activated-graph", output, env, records)
        if "offline" in manifests:
            run_tests(manifests["offline"], "offline", 13, output, env, records)
        if "new" in manifests:
            graph = gzip.decompress((output / "new-activated-graph.log.gz").read_bytes()).decode()
            if any(line.split(" ", 1)[0] in {"zbus", "zvariant", "zbus_names", "secret-service"} for line in graph.splitlines()):
                raise RuntimeError("new activated provider graph unexpectedly retains the old D-Bus transport")
            run_live(manifests, args.daemon, output, env, records)
        receipt["passed"] = True
    except Exception as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        receipt["free_bytes_at_finish"] = shutil.disk_usage(work).free
        write_json(output / "receipt.json", receipt)
        if automatic_work:
            shutil.rmtree(work)
    print(json.dumps({"passed": True, "mode": args.mode, "output": str(output)}))


if __name__ == "__main__":
    main()

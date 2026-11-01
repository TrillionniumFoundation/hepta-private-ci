"""Compile original/repaired v3 graphs and exercise a private real Secret Service."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

from . import prepare
from . import resolve
from . import semantic


def private_session(output):
    evidence = output / "evidence"
    fixture = output / "private-session"
    fixture.mkdir(mode=0o700)
    env = os.environ.copy()
    for variable, relative in (("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                               ("XDG_RUNTIME_DIR", "runtime"), ("GNOME_KEYRING_CONTROL", "control")):
        path = fixture / relative
        path.mkdir(mode=0o700)
        env[variable] = str(path)
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        raise ValueError("native fixture requires its private dbus-run-session bus")
    daemon = None
    daemon_log = (evidence / "private-keyring-daemon.log").open("xb")
    receipt = {"schema": "hepta.dependency-security-native-session.1", "status": "in_progress",
               "isolated_dbus": True, "synthetic_credentials_only": True, "cases": [],
               "keyutils_cache_tested": False,
               "backend": "unchanged upstream keyring v3 builder returns SsCredential"}

    def save():
        (evidence / "PRIVATE_NATIVE.json").write_text(json.dumps(receipt, indent=2) + "\n")

    def owner():
        result = subprocess.run(["dbus-send", "--session", "--print-reply", "--type=method_call",
                                 "--dest=org.freedesktop.DBus", "/org/freedesktop/DBus",
                                 "org.freedesktop.DBus.NameHasOwner", "string:org.freedesktop.secrets"],
                                env=env, capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise ValueError("private bus readiness query failed")
        return "boolean true" in result.stdout

    def start():
        nonlocal daemon
        if owner():
            raise ValueError("private bus unexpectedly has an existing Secret Service")
        daemon = subprocess.Popen(["gnome-keyring-daemon", "--foreground", "--components=secrets", "--unlock",
                                   "--control-directory=" + env["GNOME_KEYRING_CONTROL"]],
                                  env=env, stdin=subprocess.PIPE, stdout=daemon_log, stderr=daemon_log)
        daemon.stdin.write(b"synthetic-qualification-keyring-passphrase\n")
        daemon.stdin.close()
        for _ in range(100):
            if daemon.poll() is not None:
                raise ValueError("isolated native Secret Service exited")
            if owner():
                return
            time.sleep(0.05)
        raise ValueError("isolated native Secret Service readiness timed out")

    def stop():
        nonlocal daemon
        if daemon is not None:
            if daemon.poll() is None:
                daemon.terminate()
            try:
                daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=5)
            daemon = None
        for _ in range(100):
            if not owner():
                return
            time.sleep(0.05)
        raise ValueError("isolated native service did not release its bus name")

    def case(binary, mode, phase, service, unavailable=False):
        current = env.copy()
        if unavailable:
            current["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + str(fixture / "absent-bus")
        started = time.monotonic()
        result = subprocess.run([str(output / "binaries" / binary), mode, phase, service],
                                env=current, capture_output=True, text=True, timeout=45)
        record = {"binary": binary, "mode": mode, "phase": phase, "service": service,
                  "exit_code": result.returncode, "wall_seconds": time.monotonic() - started,
                  "stdout": result.stdout, "stderr": result.stderr}
        receipt["cases"].append(record)
        save()
        if result.returncode or "backend=keyring_v3_SsCredential" not in result.stdout:
            raise ValueError("actual native credential case failed: " + binary + "/" + phase + "/" + mode)

    save()
    try:
        start()
        service = "hepta-security-v3-cross-version"
        for binary, phase in (("baseline", "seed"), ("candidate", "update"),
                              ("baseline", "verify"), ("candidate", "verify")):
            case(binary, "sync", phase, service)
        case("candidate-tokio", "current-thread", "verify", service)
        case("candidate", "sync", "delete", service)
        case("baseline", "sync", "absent", service)
        stop()
        keyrings = list((fixture / "data/keyrings").glob("*.keyring"))
        if not keyrings:
            raise ValueError("native persistent keyring was not created")
        secrets = [b"synthetic-dependency-first-62a57266", "synthetic-dependency-updated-🔐-82f584bf".encode(),
                   b"synthetic-persistent-f73e6dfd"]
        for path in keyrings:
            if any(secret in path.read_bytes() for secret in secrets):
                raise ValueError("synthetic credential persisted in plaintext")
        receipt["persistent_keyrings"] = [{"name": path.name, **prepare.identity(path.read_bytes())} for path in keyrings]
        receipt["synthetic_plaintext_found"] = False
        start()
        for binary in ("candidate", "baseline"):
            case(binary, "sync", "persistent", service)
        case("candidate", "sync", "finish", service)
        for binary in ("candidate", "candidate-tokio"):
            for mode in ("sync", "current-thread", "multi-thread", "spawn-blocking"):
                case(binary, mode, "round-trip", "hepta-security-" + binary + "-" + mode)
            case(binary, "sync", "concurrent", "hepta-security-concurrent-" + binary)
            case(binary, "current-thread", "unavailable", "hepta-security-absent-" + binary, unavailable=True)
        case("baseline", "sync", "unavailable", "hepta-security-absent-baseline", unavailable=True)
        receipt["status"] = "complete"
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error)
        raise
    finally:
        try:
            stop()
        finally:
            daemon_log.close()
            save()
    return receipt


def run(root, resolved, output):
    root, resolved, output = root.resolve(), resolved.resolve(), output.resolve()
    if output.exists() or root == output or root in output.parents:
        raise ValueError("native qualification work directory must be new and external")
    evidence = output / "evidence"
    evidence.mkdir(parents=True)
    binaries = output / "binaries"
    binaries.mkdir()
    plan = json.loads((prepare.HERE / "INPUTS.json").read_text())
    capture = resolve.load_module(root, "scripts/capture_cargo_deny_diagnostic.py", "native_capture", plan["capture_git_blob"])
    receipt = {"schema": "hepta.dependency-security-native.1", "status": "in_progress", "qualification": False,
               "source_head": prepare.git(root, "rev-parse", "HEAD").decode().strip(), "commands": [], "binaries": {},
               "run_id": os.environ.get("GITHUB_RUN_ID"), "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
    started = time.monotonic()

    def save():
        receipt["wall_seconds"] = time.monotonic() - started
        (evidence / "NATIVE.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    def invoke(label, command, cwd, timeout=1800):
        save()
        result = capture.capture(command, cwd, evidence, label, timeout=timeout, limit=32 * 1024 * 1024)
        result["label"] = label
        receipt["commands"].append(result)
        save()
        if result["exit_code"] or result["timed_out"]:
            raise ValueError("actual native command failed: " + label)

    save()
    try:
        resolver = semantic.restore_candidate(root, resolved, plan)
        receipt["product_cargo_lock"] = resolver["cargo_lock"]
        product = root / "codex-rs/keyring-store/src/lib.rs"
        os.environ["HEPTA_PRODUCT_KEYRING_SOURCE"] = str(product)
        receipt["product_source"] = prepare.identity(product.read_bytes())
        product_graph = tomllib.loads((root / "codex-rs/Cargo.lock").read_text())["package"]
        versions = {}
        for name in ("tokio", "tracing"):
            rows = [row for row in product_graph if row["name"] == name]
            if len(rows) != 1:
                raise ValueError("ambiguous native fixture common dependency: " + name)
            versions[name] = rows[0]["version"]
        for variant in ("baseline", "candidate"):
            work = output / variant
            work.mkdir()
            (work / "src").mkdir()
            (work / "src/main.rs").write_bytes((prepare.HERE / "credential_probe.rs").read_bytes())
            manifest = ('[workspace]\nresolver = "3"\n\n[package]\nname = "hepta-native-keyring-probe"\n'
                        'version = "0.0.0"\nedition = "2021"\npublish = false\n\n'
                        '[features]\nprobe-native-tokio = ["keyring/tokio"]\n\n[dependencies]\n'
                        'keyring = { version = "=3.6.3", default-features = false, features = ["linux-native-async-persistent", "crypto-rust"] }\n'
                        'tokio = { version = "=' + versions["tokio"] + '", features = ["rt", "rt-multi-thread", "macros", "time", "net"] }\n'
                        'tracing = "=' + versions["tracing"] + '"\n')
            if variant == "candidate":
                manifest += ('\n[patch.crates-io]\nkeyring = { path = ' + json.dumps(str(root / "codex-rs/third_party/keyring-3.6.3"))
                             + ' }\nsecret-service = { path = ' + json.dumps(str(root / "codex-rs/third_party/secret-service-6.0.0")) + ' }\n')
            (work / "Cargo.toml").write_text(manifest)
            seed = root / "codex-rs/Cargo.lock" if variant == "candidate" else resolved / "Cargo.lock.before"
            (work / "Cargo.lock").write_bytes(seed.read_bytes())
            invoke(variant + "_metadata", ["cargo", "metadata", "--all-features", "--format-version", "1"], work, 1200)
            locked = (work / "Cargo.lock").read_bytes()
            graph = tomllib.loads(locked.decode())["package"]
            selected = {name: [row for row in graph if row["name"] == name] for name in ("keyring", "secret-service", "zbus")}
            if any(len(rows) != 1 for rows in selected.values()):
                raise ValueError("native fixture has an ambiguous backend graph")
            if selected["keyring"][0]["version"] != "3.6.3":
                raise ValueError("native fixture changed the original v3 public API")
            major = "6." if variant == "candidate" else "4."
            if not all(selected[name][0]["version"].startswith(major) for name in ("secret-service", "zbus")):
                raise ValueError("native fixture did not select its declared original/repaired backend")
            if variant == "candidate" and any(selected[name][0].get("source") for name in ("keyring", "secret-service")):
                raise ValueError("native repaired fixture substituted a registry backend")
            (evidence / (variant + ".Cargo.toml")).write_text(manifest)
            (evidence / (variant + ".Cargo.lock")).write_bytes(locked)
            receipt[variant + "_graph"] = selected
            invoke(variant + "_build", ["cargo", "build", "--locked", "--bin", "hepta-native-keyring-probe"], work)
            binary = work / "target/debug/hepta-native-keyring-probe"
            shutil.copyfile(binary, binaries / variant)
            (binaries / variant).chmod(0o755)
            receipt["binaries"][variant] = prepare.identity(binary.read_bytes())
            if variant == "candidate":
                invoke("candidate_tokio_build", ["cargo", "build", "--locked", "--bin", "hepta-native-keyring-probe", "--features", "probe-native-tokio"], work)
                shutil.copyfile(binary, binaries / "candidate-tokio")
                (binaries / "candidate-tokio").chmod(0o755)
                receipt["binaries"]["candidate-tokio"] = prepare.identity(binary.read_bytes())
            if (work / "Cargo.lock").read_bytes() != locked:
                raise ValueError("native locked build changed its graph")
        invoke("private_native_session", ["dbus-run-session", "--", sys.executable, "-B", "-m",
                                          "operational.parameter_field_security_closure_20261031.native",
                                          "--output", str(output), "--inside-session"], root, 900)
        native = json.loads((evidence / "PRIVATE_NATIVE.json").read_text())
        if native["status"] != "complete" or len(native["cases"]) != 23:
            raise ValueError("native interoperability evidence is incomplete")
        for path, expected in plan["candidate_files"].items():
            prepare.check((root / path).read_bytes(), expected, path)
        prepare.check(product.read_bytes(), plan["base_files"]["codex-rs/keyring-store/src/lib.rs"], "unchanged product keyring source")
        receipt["status"] = "complete"
        receipt["native_session"] = prepare.identity((evidence / "PRIVATE_NATIVE.json").read_bytes())
        receipt["product_source_preserved"] = True
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error)
        raise
    finally:
        save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--resolved", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inside-session", action="store_true")
    args = parser.parse_args()
    if args.inside_session:
        result = private_session(args.output.resolve())
    else:
        if args.repo is None or args.resolved is None:
            parser.error("--repo and --resolved are required outside the private bus")
        result = run(args.repo, args.resolved, args.output)
    print(json.dumps({"status": result["status"], "qualification": False}))


if __name__ == "__main__":
    main()

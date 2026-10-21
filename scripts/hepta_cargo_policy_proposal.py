#!/usr/bin/env python3
"""Produce auditable Cargo/Bazel postimages in the fixed project cloud branch."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import tomllib

from hepta_cargo_policy_checks import FEATURES, ROOT, VENDORS, source_hashes, write_json


EVIDENCE = Path(os.environ["CARGO_POLICY_EVIDENCE_DIR"]).resolve()
SCRIPT = ROOT / "scripts/hepta_cargo_policy_proposal.py"
CHECKS = ROOT / "scripts/hepta_cargo_policy_checks.py"
BASE = "f0fb978a70a8bff2756248abf9e676774bafe3a2"
TLS = {"rustls-webpki": ("0.103.15", "0.103.16"), "webpki-roots": ("1.0.9", "1.0.10"), "webpki-root-certs": ("1.0.9", "1.0.10")}
SERVICE_COMMANDS = {"vendor-tests", "vendor-doctests", "keyring-tests", "secrets-tests", "login-tests"}
ALLOWED_FILES = {"codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "MODULE.bazel.lock", ".github/workflows/hepta-cargo-policy-proposal.yml", "scripts/hepta_cargo_policy_proposal.py", "scripts/hepta_cargo_policy_checks.py", "scripts/hepta_cargo_policy_inventory.json"}
ALLOWED_ROOTS = tuple("codex-rs/third_party/" + vendor["directory"] + "/" for vendor in VENDORS.values()) + ("codex-rs/keyring-store/", "codex-rs/secrets/", "codex-rs/login/")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def state():
    names = set(ALLOWED_FILES)
    for prefix in ALLOWED_ROOTS:
        names.update(path.relative_to(ROOT).as_posix() for path in (ROOT / prefix).rglob("*") if path.is_file())
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(names) if (ROOT / name).is_file()}
    harness = EVIDENCE / "vendor-harness"
    if harness.is_dir():
        files.update({"evidence/vendor-harness/" + name: digest for name, digest in source_hashes(harness).items()})
    encoded = json.dumps(files, sort_keys=True).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": files}


def commands():
    return json.loads((EVIDENCE / "commands.json").read_text())


def save(records):
    write_json(EVIDENCE / "commands.json", records)


def initialize():
    EVIDENCE.mkdir()
    head = git("rev-parse", "HEAD").decode().strip()
    if head != os.environ["SOURCE_SHA"] or git("status", "--porcelain").strip():
        raise ValueError("Proposal source is not a clean checkout of the immutable event head")
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT, check=True)
    toolchain = tomllib.loads((ROOT / "codex-rs/rust-toolchain.toml").read_text())["toolchain"]
    write_json(EVIDENCE / "source.json", {"source_sha": head, "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(), "proposal_base_sha": BASE, "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "toolchain": toolchain, "input_head_qualified": False, "scope": "Generated candidate; original security and three-platform consumer gates remain mandatory", "input_files": state()})
    harness = EVIDENCE / "vendor-harness"
    manifest = str(harness / "Cargo.toml")
    plan = []

    def add(name, argv, cwd=ROOT, requires=(), stdout_artifact=None):
        plan.append({"name": name, "argv": list(map(str, argv)), "cwd": str(cwd), "requires": list(requires), "status": "not_started", "exit_code": None, "log": name + ".log", "stdout_artifact": stdout_artifact})

    add("v8", ["python3", "scripts/hepta_ci_v8.py"])
    packages = tomllib.loads((ROOT / "codex-rs/Cargo.lock").read_text())["package"]
    for name, (old, new) in TLS.items():
        versions = [package["version"] for package in packages if package["name"] == name and package["version"] in (old, new)]
        if len(versions) != 1:
            raise ValueError(f"Review the fixed precise-update plan for {name}: {versions}")
        add("update-" + name, ["cargo", "update", "--package", name + "@" + versions[0], "--precise", new], ROOT / "codex-rs")
    updates = ["update-" + name for name in TLS]
    add("metadata", ["cargo", "metadata", "--locked", "--format-version", "1"], ROOT / "codex-rs", updates, "metadata.json")
    add("lock-packages", ["python3", CHECKS, "lock-packages"], requires=["metadata"])
    add("prepare-harness", ["python3", CHECKS, "prepare-harness"], requires=["metadata"])
    add("harness-metadata", ["cargo", "metadata", "--format-version", "1", "--features", FEATURES], harness, ["prepare-harness"], "harness-metadata.json")
    add("normal-graph", ["python3", CHECKS, "normal-graph"], requires=["metadata", "harness-metadata"])
    add("vendor-test-list", ["cargo", "nextest", "list", "--manifest-path", manifest, "--workspace", "--features", FEATURES, "--locked", "--message-format", "json"], ROOT / "codex-rs", ["normal-graph"], "vendor-test-list.json")
    add("vendor-test-inventory", ["python3", CHECKS, "test-list"], requires=["vendor-test-list"])
    add("private-service", ["dbus-run-session", "--", "python3", SCRIPT, "service"], requires=["metadata"])
    add("vendor-tests", ["just", "test", "--manifest-path", manifest, "--workspace", "--features", FEATURES, "--locked", "--test-threads", "1", "--config-file", harness / ".config/nextest.toml"], ROOT / "codex-rs", ["vendor-test-inventory", "normal-graph"])
    add("vendor-doctests", ["just", "--justfile", harness / "justfile", "test-doc"], harness, ["normal-graph"])
    for name in ("keyring", "secrets", "login"):
        package = "codex-keyring-store" if name == "keyring" else "codex-" + name
        add(name + "-tests", ["just", "test", "--locked", "-p", package], ROOT / "codex-rs", ["metadata"] + (["v8"] if name == "login" else []))
    add("vendor-test-results", ["python3", CHECKS, "test-results"], requires=["vendor-tests"])
    add("vendor-fix", ["just", "--justfile", harness / "justfile", "fix"], harness, ["vendor-test-results", "vendor-doctests"])
    add("copy-vendor-fix", ["python3", CHECKS, "copy-fixed-sources"], requires=["vendor-fix"])
    add("consumer-fix", ["just", "fix", "-p", "codex-keyring-store", "-p", "codex-secrets", "-p", "codex-login"], ROOT / "codex-rs", ["keyring-tests", "secrets-tests", "login-tests"])
    add("format", ["just", "fmt", "--base", BASE], ROOT / "codex-rs")
    add("cargo-deny", ["cargo", "deny", "--log-level", "warn", "--manifest-path", "./codex-rs/Cargo.toml", "--all-features", "check"], requires=["metadata"])
    add("lock-update", ["just", "bazel-lock-update"], requires=["metadata"])
    add("lock-check", ["just", "bazel-lock-check"], requires=["lock-update"])
    add("lock-repeat", ["just", "bazel-lock-update"], requires=["lock-update"])
    add("lock-repeat-equal", ["cmp", EVIDENCE / "MODULE.bazel.lock.first-generation", ROOT / "MODULE.bazel.lock"], requires=["lock-update", "lock-repeat"])
    query = "labels(actual, set(" + " ".join("@crates//:" + vendor["directory"] for vendor in VENDORS.values()) + "))"
    add("bazel-vendor-query", ["bazel", "query", "--output=xml", query], requires=["lock-check", "lock-repeat-equal"], stdout_artifact="bazel-vendor-libraries.xml")
    add("bazel-generated-check", ["python3", CHECKS, "bazel-generated"], requires=["bazel-vendor-query", "metadata"])
    add("bazel-vendor-build", ["bazel", "build", "--keep_going", *["@crates//:" + vendor["directory"] for vendor in VENDORS.values()]], requires=["bazel-generated-check"])
    save(plan)
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        print(f'toolchain={toolchain["channel"]}', file=output)
        print(f'components={",".join(toolchain["components"])}', file=output)


def execute(name, extra_env=None):
    records = commands()
    record = next(item for item in records if item["name"] == name)
    by_name = {item["name"]: item for item in records}
    blocked = [dependency for dependency in record["requires"] if by_name[dependency]["status"] != "passed"]
    if blocked:
        record.update(status="blocked", blocked_by=blocked)
        save(records)
        return False
    record.update(status="running", started_unix_ns=time.time_ns(), input_state=state())
    save(records)
    print("Running " + shlex.join(record["argv"]), flush=True)
    result_code = None
    error_message = None
    with (EVIDENCE / record["log"]).open("wb") as log:
        output_path = EVIDENCE / record["stdout_artifact"] if record["stdout_artifact"] else None
        stdout = output_path.open("wb") if output_path else log
        try:
            result_code = subprocess.run(record["argv"], cwd=record["cwd"], env={**os.environ, **(extra_env or {})}, stdout=stdout, stderr=log if output_path else subprocess.STDOUT, check=False).returncode
        except OSError as error:
            error_message = str(error)
            log.write((error_message + "\n").encode())
        finally:
            if output_path:
                stdout.close()
    records = commands()  # The private service executes child commands into the same ledger.
    record = next(item for item in records if item["name"] == name)
    record.update(status="passed" if result_code == 0 else "failed", exit_code=result_code, finished_unix_ns=time.time_ns(), output_state=state())
    if name in SERVICE_COMMANDS and name != "vendor-doctests":
        junit = Path(os.environ["CARGO_TARGET_DIR"]) / "nextest/local/junit.xml"
        if junit.is_file() and junit.stat().st_mtime_ns >= record["started_unix_ns"]:
            shutil.copyfile(junit, EVIDENCE / (name + ".junit.xml"))
            record["junit"] = name + ".junit.xml"
        elif name == "vendor-tests" and result_code == 0:
            # A green test command without attributable per-test evidence is not green.
            record["status"] = "failed"
            record["error"] = f"Expected fresh vendor Nextest JUnit was not produced: {junit}"
    if error_message:
        record["error"] = error_message
    if name == "lock-update" and result_code == 0:
        shutil.copyfile(ROOT / "MODULE.bazel.lock", EVIDENCE / "MODULE.bazel.lock.first-generation")
    save(records)
    print(f'{name}: {record["status"]}, exit {result_code}', flush=True)
    if record["status"] != "passed":
        if record.get("error"):
            print(record["error"], flush=True)
        print("\n".join((EVIDENCE / record["log"]).read_text(errors="replace").splitlines()[-50:]), flush=True)
    return record["status"] == "passed"


def private_service():
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("The original environment guards and private dbus-run-session are required")
    private = EVIDENCE / "private-keyring"
    private.mkdir(mode=0o700)
    environment = {}
    for name in ("XDG_RUNTIME_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "GNOME_KEYRING_CONTROL"):
        directory = private / name.lower()
        directory.mkdir(mode=0o700)
        environment[name] = str(directory)
    daemon_argv = ["gnome-keyring-daemon", "--foreground", "--components=secrets", "--control-directory=" + environment["GNOME_KEYRING_CONTROL"], "--unlock"]
    service_steps = []
    daemon = None
    try:
        with (EVIDENCE / "gnome-keyring-daemon.log").open("wb") as log:
            daemon = subprocess.Popen(daemon_argv, env={**os.environ, **environment}, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
            service_steps.append({"argv": daemon_argv, "pid": daemon.pid, "status": "started", "log": "gnome-keyring-daemon.log"})
            daemon.stdin.write(b"hepta-ci-ephemeral-keyring\n")
            daemon.stdin.close()
            probes = [
                ["gdbus", "wait", "--session", "--timeout", "30", "org.freedesktop.secrets"],
                ["gdbus", "call", "--session", "--dest", "org.freedesktop.secrets", "--object-path", "/org/freedesktop/secrets", "--method", "org.freedesktop.Secret.Service.ReadAlias", "default"],
            ]
            for index, argv in enumerate(probes):
                result = subprocess.run(argv, env={**os.environ, **environment}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=40, check=False)
                path = EVIDENCE / f"private-service-probe-{index}.log"
                path.write_bytes(result.stdout)
                service_steps.append({"argv": argv, "exit_code": result.returncode, "log": path.name})
                write_json(EVIDENCE / "private-service-commands.json", service_steps)
                if result.returncode or (index == 1 and b"objectpath '/org/freedesktop/secrets/collection/" not in result.stdout):
                    raise ValueError("Private real Secret Service did not expose an unlocked default collection; see complete probe logs")
            collection = re.search(rb"objectpath '([^']+)'", result.stdout).group(1).decode()
            argv = ["gdbus", "call", "--session", "--dest", "org.freedesktop.secrets", "--object-path", collection, "--method", "org.freedesktop.DBus.Properties.Get", "org.freedesktop.Secret.Collection", "Locked"]
            result = subprocess.run(argv, env={**os.environ, **environment}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=40, check=False)
            (EVIDENCE / "private-service-unlocked.log").write_bytes(result.stdout)
            service_steps.append({"argv": argv, "exit_code": result.returncode, "log": "private-service-unlocked.log"})
            write_json(EVIDENCE / "private-service-commands.json", service_steps)
            if result.returncode or b"<false>" not in result.stdout or daemon.poll() is not None:
                raise ValueError("The private Secret Service default collection is not unlocked")
            for record in commands():
                if record["name"] in SERVICE_COMMANDS:
                    execute(record["name"], environment)
            if daemon.poll() is not None:
                raise ValueError("The private Secret Service daemon exited before all suites completed")
    finally:
        if daemon is not None:
            daemon.terminate()
            try:
                daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=10)
            service_steps[0]["cleanup_exit_code"] = daemon.returncode
        write_json(EVIDENCE / "private-service-commands.json", service_steps)
    return all(record["status"] == "passed" for record in commands() if record["name"] in SERVICE_COMMANDS)


def collect():
    source = json.loads((EVIDENCE / "source.json").read_text())
    head = git("rev-parse", "HEAD").decode().strip()
    tree = git("rev-parse", "HEAD^{tree}").decode().strip()
    inputs = git("diff", "--name-only", "--no-renames", "-z", BASE, "HEAD").decode().split("\0")
    changed = git("diff", "--name-only", "--no-renames", "-z", "HEAD").decode().split("\0")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    selected = sorted(set(inputs + changed + untracked + ["codex-rs/Cargo.lock", "MODULE.bazel.lock"]) - {""})
    unexpected = [name for name in selected if name not in ALLOWED_FILES and not name.startswith(ALLOWED_ROOTS)]
    files = []
    for name in selected:
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or ROOT not in path.resolve().parents:
            unexpected.append(name)
            continue
        destination = EVIDENCE / "postimage" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        data = path.read_bytes()
        files.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})
    (EVIDENCE / "candidate.patch").write_bytes(git("diff", "--binary", BASE))
    (EVIDENCE / "generated-changes.patch").write_bytes(git("diff", "--binary", "HEAD"))
    (EVIDENCE / "git-status.txt").write_bytes(git("status", "--short"))
    result = subprocess.run(["git", "diff", "--check", BASE], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    (EVIDENCE / "diff-check.log").write_bytes(result.stdout)
    records = commands()
    for record in records:
        if record["status"] in ("not_started", "running"):
            record.update(status="not_completed", reason="Setup, private service or proposal execution did not complete; this is not a pass")
    save(records)
    write_json(EVIDENCE / "setup-outcomes.json", json.loads(os.environ.get("SETUP_OUTCOMES", "{}")))
    write_json(EVIDENCE / "proposal.json", {"source": source, "actual_head": head, "actual_tree": tree, "input_identity_unchanged": head == source["source_sha"] and tree == source["source_tree"], "input_head_qualified": False, "unexpected_paths": sorted(set(unexpected)), "diff_check_exit_code": result.returncode, "files": files, "all_commands_passed": all(record["status"] == "passed" for record in records), "required_followup": "Review and commit generated Cargo/Bazel locks and formatting; rerun all original gates on that exact successor head"})
    artifact = {}
    for path in EVIDENCE.rglob("*"):
        relative = path.relative_to(EVIDENCE)
        if "target" in relative.parts or "private-keyring" in relative.parts or relative.as_posix() == "artifact-sha256.json":
            continue
        if path.is_symlink():
            raise ValueError(f"Refusing to export evidence symlink: {path}")
        if path.is_file():
            artifact[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(EVIDENCE / "artifact-sha256.json", artifact)


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != "TrillionniumFoundation/hepta-private-ci":
        raise SystemExit("This proposal runs only in the project GitHub Actions environment")
    operation = sys.argv[1]
    if operation == "initialize":
        initialize()
    elif operation == "v8":
        raise SystemExit(0 if execute("v8") else 1)
    elif operation == "run":
        for record in commands():
            if record["name"] != "v8" and record["name"] not in SERVICE_COMMANDS:
                execute(record["name"])
        raise SystemExit(0 if all(record["status"] == "passed" for record in commands()) else 1)
    elif operation == "service":
        raise SystemExit(0 if private_service() else 1)
    elif operation == "collect":
        collect()
    elif operation == "verdict":
        result = json.loads((EVIDENCE / "proposal.json").read_text())
        passed = result["input_identity_unchanged"] and result["all_commands_passed"] and not result["unexpected_paths"] and result["diff_check_exit_code"] == 0
        print("Candidate evidence complete; exact input head is not qualified" if passed else "Candidate remains blocked; inspect complete command ledger and postimages")
        raise SystemExit(0 if passed else 1)
    else:
        raise ValueError(f"Unknown fixed proposal operation: {operation}")


if __name__ == "__main__":
    main()

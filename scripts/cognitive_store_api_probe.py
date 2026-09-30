#!/usr/bin/env python3
"""Compile external consumers against the exact Cargo-emitted cognitive API.

This checks visibility, not runtime authorization or OS isolation. Failed builds,
missing artifacts and unexpected Rust diagnostics never count as denied access.
No manifests, lockfiles or source files in the checkout are rewritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "default": [],
    "host-unified": ["--features", "agentd-production-host"],
    "qualification": ["--features", "qualification-cognitive-write"],
}
PROBES = {
    "reader": (
        "pub fn reader(v: store::DurableCognitiveReadCapability) -> store::DurableCognitiveReadCapability { v }",
        None,
        "",
    ),
    "reader-compat": (
        "pub fn reader(v: store::DurableCognitiveReadStore) -> store::DurableCognitiveReadStore { v }",
        None,
        "",
    ),
    "federation-policy": (
        "use store::FederationPolicyCapability; pub fn policy(v: FederationPolicyCapability) -> FederationPolicyCapability { v }",
        "E0432",
        "FederationPolicyCapability",
    ),
    "raw-owner": (
        "use store::DurableCognitiveStore; pub fn owner(_: Option<DurableCognitiveStore>) {}",
        "E0432",
        "DurableCognitiveStore",
    ),
    "private-backend": (
        "pub fn owner(v: &store::DurableCognitiveReadCapability) { let _ = &v.backend; }",
        "E0616",
        "backend",
    ),
    "read-cannot-write": (
        "pub fn write(v: &store::DurableCognitiveReadCapability) { let _ = v.remember_with_kg(); }",
        "E0599",
        "remember_with_kg",
    ),
    "read-cannot-grant": (
        "pub fn grant(v: &store::DurableCognitiveReadCapability) { let _ = v.grant_federated_recall(); }",
        "E0599",
        "grant_federated_recall",
    ),
    "read-cannot-revoke": (
        "pub fn revoke(v: &store::DurableCognitiveReadCapability) { let _ = v.revoke_federated_recall_by_id(); }",
        "E0599",
        "revoke_federated_recall_by_id",
    ),
}


def check_diagnostics(returncode: int, stderr: str, code: str | None, symbol: str) -> None:
    messages = [json.loads(line) for line in stderr.splitlines() if line.strip()]
    errors = []
    for message in messages:
        if message.get("level") != "error":
            continue
        text = message.get("message", "")
        if not message.get("spans") and text.startswith("aborting due to "):
            continue
        errors.append(message)
    if code is None:
        if returncode != 0 or errors:
            raise ValueError("positive API control did not compile")
    elif returncode == 0 or not errors or any(
        (message.get("code") or {}).get("code") != code
        or symbol not in message.get("message", "")
        for message in errors
    ):
        raise ValueError("negative probe was not rejected for the expected API boundary")


def metadata_artifact(stdout: str) -> Path:
    paths = set()
    for line in stdout.splitlines():
        if not line.strip():
            continue
        message = json.loads(line)
        if message.get("reason") != "compiler-artifact":
            continue
        if message.get("target", {}).get("name") != "codex_hepta_cognitive_store":
            continue
        paths.update(Path(value) for value in message.get("filenames", []) if value.endswith(".rmeta"))
    if len(paths) != 1:
        raise ValueError("expected exactly one cognitive-store metadata artifact")
    path = paths.pop()
    if not path.is_file():
        raise ValueError("Cargo metadata artifact is absent")
    return path.resolve()


def run(profile: str, directory: Path) -> dict:
    command = ["cargo", "check", "--locked", "-p", "codex-hepta-cognitive-store",
               "--lib", "--no-default-features", "--message-format=json", *PROFILES[profile]]
    build = subprocess.run(command, cwd=ROOT / "codex-rs", text=True,
                           capture_output=True, timeout=1800, check=False)
    (directory / f"{profile}.cargo.log").write_text(build.stdout + build.stderr, encoding="utf-8")
    if build.returncode:
        raise ValueError(f"{profile}: Cargo build failed, not an API denial")
    artifact = metadata_artifact(build.stdout)
    results = []
    for name, (source, code, symbol) in PROBES.items():
        if name == "raw-owner" and profile == "qualification":
            code = None
        if name == "federation-policy" and profile != "default":
            code = None
        path = directory / f"{profile.replace('-', '_')}_{name.replace('-', '_')}.rs"
        path.write_text(source + "\n", encoding="utf-8")
        argv = ["rustc", "--edition=2024", "--crate-type=lib", "--emit=metadata",
                "--error-format=json", "--extern", f"store={artifact}",
                "-L", f"dependency={artifact.parent}", "--out-dir", str(directory), str(path)]
        probe = subprocess.run(argv, cwd=ROOT / "codex-rs", text=True,
                               capture_output=True, timeout=120, check=False)
        (directory / f"{path.stem}.rustc.log").write_text(probe.stderr, encoding="utf-8")
        check_diagnostics(probe.returncode, probe.stderr, code, symbol)
        results.append({"probe": name, "command": argv, "exitCode": probe.returncode,
                        "expectedError": code, "inputSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "diagnosticSha256": hashlib.sha256(probe.stderr.encode()).hexdigest()})
    return {"profile": profile, "buildCommand": command,
            "metadataSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "probes": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        raise SystemExit("API evidence must be outside the source checkout")
    output.parent.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    if os.environ.get("TESTED_SHA", head) != head or os.environ.get("TESTED_TREE", tree) != tree:
        raise SystemExit("API probe candidate identity mismatch")
    receipt = {"schema": "hepta.cognitive-store-api-probe.v1", "commit": head, "tree": tree,
               "runtimeAuthorizationProved": False, "profiles": [], "result": "failed"}
    try:
        receipt["rustc"] = subprocess.check_output(["rustc", "-Vv"], cwd=ROOT / "codex-rs", text=True)
        logs = output.with_name(output.stem + "-logs")
        logs.mkdir(exist_ok=False)
        receipt["logDirectory"] = str(logs)
        for profile in PROFILES:
            receipt["profiles"].append(run(profile, logs))
        receipt["result"] = "passed"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
    finally:
        output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if receipt["result"] != "passed":
        raise SystemExit(receipt.get("error", "API probes failed"))
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Read-only exact-candidate qualification with durable per-check diagnostics.

Never patches source, updates Cargo.lock, regenerates a map, formats in place,
self-accepts, or treats an empty test filter as a pass. Outputs must be outside
the checkout. A core-only pass is explicitly not a product qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CARGO = ROOT / "codex-rs"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def profile_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        opening = line.find('{"')
        if opening < 0:
            continue
        try:
            value = json.loads(line[opening:])
        except ValueError:
            continue
        if isinstance(value, dict) and str(value.get("schema", "")).startswith("hepta.prompt-registry."):
            rows.append(value)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["core", "product"], required=True)
    parser.add_argument("--lane", choices=["exact-head", "base-merge"], required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out == ROOT or ROOT in out.parents:
        raise SystemExit("qualification output must be outside the checkout")
    out.mkdir(parents=True, exist_ok=True)
    tested = git("rev-parse", "HEAD")
    source = git("rev-parse", args.source_sha + "^{commit}")
    base = git("rev-parse", args.base_sha + "^{commit}")
    if args.lane == "exact-head" and tested != source:
        raise SystemExit("exact-head identity mismatch")
    if args.lane == "base-merge":
        for ancestor in [base, source]:
            subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, tested], cwd=ROOT, check=True)
    receipt = {
        "schema": "hepta.prompt-registry.qualification-receipt.v2",
        "profile": args.profile, "lane": args.lane,
        "sourceSha": source, "baseSha": base, "testedSha": tested,
        "testedTree": git("rev-parse", "HEAD^{tree}"),
        "runId": os.environ.get("GITHUB_RUN_ID"), "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner": {"system": platform.platform(), "machine": platform.machine()},
        "checks": [], "allRequiredChecksPassed": False, "qualified": False,
        "productionReady": False, "productActivated": False, "accepted": False, "released": False,
        "sourceFiles": {},
    }
    for path in git("ls-files", "--", "codex-rs/hepta-prompt-registry", "codex-rs/hepta-prompt-optimizer",
                    "codex-rs/hepta-agentd/src/prompt*", "codex-rs/ext/hepta-prompt",
                    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
                    "docs/modules/prompt.registry", "scripts/hepta-prompt-registry-*").splitlines():
        receipt["sourceFiles"][path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()

    def save() -> None:
        temporary = out / "receipt.next"
        temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        temporary.replace(out / "receipt.json")

    commands: list[tuple[str, list[str], Path, int, list[str], int]] = [
        ("clean-before", ["git", "diff", "--exit-code", "HEAD"], ROOT, 30, [], 0),
        ("map", ["python3", "scripts/hepta-prompt-registry-map.py", "--check"], ROOT, 60, [], 0),
        ("toolchain", ["rustc", "--version", "--verbose"], ROOT, 30, [], 0),
        ("source-graph", ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"], CARGO, 90, [], 0),
    ]
    if args.profile == "core":
        commands.extend([
            ("format", ["cargo", "fmt", "--package", "codex-hepta-prompt-registry", "--", "--check"], CARGO, 120, [], 0),
            ("registry-inventory", ["cargo", "test", "--locked", "-p", "codex-hepta-prompt-registry", "--", "--list"], CARGO, 300,
             ["operational_restore_does_not_create_missing_paths_or_accept_unpinned_identity", "operational_compaction_retry_is_idempotent_and_conflicting_destination_is_untouched", "operational_poisoned_owner_exposes_diagnostics_but_not_authority"], 0),
            ("registry", ["cargo", "test", "--locked", "-p", "codex-hepta-prompt-registry", "--", "--test-threads=1"], CARGO, 180, [], 1),
            ("all-targets", ["cargo", "check", "--locked", "-p", "codex-hepta-prompt-registry", "--all-targets"], CARGO, 180, [], 0),
            ("lint", ["cargo", "clippy", "--locked", "-p", "codex-hepta-prompt-registry", "--all-targets", "--no-deps", "--", "-D", "warnings"], CARGO, 180, [], 0),
            ("operational-profiles", ["cargo", "test", "--locked", "-p", "codex-hepta-prompt-registry", "operational_", "--", "--ignored", "--nocapture", "--test-threads=1"], CARGO, 240, [], 2),
        ])
    else:
        packages = ["codex-hepta-prompt-optimizer", "codex-hepta-agentd", "codex-hepta-intelligence", "codex-hepta-prompt-extension"]
        flags = [part for package in packages for part in ["-p", package]]
        commands.extend([
            ("format", ["cargo", "fmt", *flags, "--", "--check"], CARGO, 120, [], 0),
            ("agentd-inventory", ["cargo", "test", "--locked", "-p", "codex-hepta-agentd", "prompt_", "--", "--list"], CARGO, 1200,
             ["final_use_revocation_precedes_snapshot_error_and_survives_restart", "named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host"], 0),
            ("extension-inventory", ["cargo", "test", "--locked", "-p", "codex-hepta-prompt-extension", "--", "--list"], CARGO, 600,
             ["cached_prompt_revalidates_owner_withdrawal_before_provider_begin", "cached_prompt_never_silently_switches_injected_payload"], 0),
            ("optimizer", ["cargo", "test", "--locked", "-p", "codex-hepta-prompt-optimizer", "--", "--test-threads=1"], CARGO, 300, [], 1),
            ("extension", ["cargo", "test", "--locked", "-p", "codex-hepta-prompt-extension", "--", "--test-threads=1"], CARGO, 300, [], 1),
            ("agentd", ["cargo", "test", "--locked", "-p", "codex-hepta-agentd", "prompt_", "--", "--nocapture", "--test-threads=1"], CARGO, 300, [], 1),
            ("all-targets", ["cargo", "check", "--locked", *flags, "--all-targets"], CARGO, 900, [], 0),
            ("lint", ["cargo", "clippy", "--locked", *flags, "--all-targets", "--no-deps", "--", "-D", "warnings"], CARGO, 900, [], 0),
            ("pipeline-profile", ["cargo", "test", "--locked", "-p", "codex-hepta-agentd", "operational_pipeline_compile_stage_final_use_profile", "--", "--ignored", "--nocapture", "--test-threads=1"], CARGO, 300, [], 1),
        ])
    commands.append(("clean-after", ["git", "diff", "--exit-code", "HEAD"], ROOT, 30, [], 0))
    receipt["checks"] = [{"name": name, "command": command, "state": "not_run", "exitCode": None} for name, command, *_ in commands]
    save()
    for index, (name, command, cwd, limit, required, minimum_passed) in enumerate(commands):
        entry = receipt["checks"][index]
        entry["state"] = "running"
        save()
        log = out / (name + ".log")
        start = time.monotonic()
        with log.open("w") as stream:
            try:
                child = subprocess.Popen(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = child.wait(timeout=limit)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                    code = 124
            except OSError as error:
                stream.write(f"{type(error).__name__}: command unavailable\n")
                code = 127
        text = log.read_text(errors="replace")
        checks = []
        if code == 0 and any(token not in text for token in required):
            checks.append("required compiled test is missing")
        counts = re.findall(r"test result: ok\. (\d+) passed", text)
        passed = sum(map(int, counts))
        if code == 0 and minimum_passed and passed < minimum_passed:
            checks.append("test filter did not execute the required nonzero tests")
        rows = profile_rows(text)
        if code == 0 and name == "operational-profiles":
            sizes = {row.get("logicalRecords") for row in rows if row.get("schema") == "hepta.prompt-registry.operational-scale.v2"}
            fsync = {row.get("bytes") for row in rows if row.get("schema") == "hepta.prompt-registry.fsync-profile.v2"}
            if sizes != {1000, 8000, 16384} or fsync != {4096, 65536, 1048576}:
                checks.append("missing operational measurement rows")
        if code == 0 and name == "pipeline-profile" and len([r for r in rows if r.get("schema") == "hepta.prompt-registry.pipeline-profile.v1"]) != 31:
            checks.append("expected 31 pipeline measurement rows")
        if name == "source-graph" and code == 0:
            graph = json.loads(text)
            names = {package["name"] for package in graph["packages"]}
            if not {"codex-hepta-prompt-registry", "codex-hepta-prompt-extension", "codex-hepta-agentd"}.issubset(names):
                checks.append("missing required workspace package")
        if name == "clean-after" and (git("status", "--porcelain", "--untracked-files=no") or git("rev-parse", "HEAD") != tested):
            checks.append("tested source changed during qualification")
        entry.update({"exitCode": code, "state": "passed" if code == 0 and not checks else "failed",
            "postconditionFailures": checks, "durationSeconds": time.monotonic() - start,
            "logSha256": hashlib.sha256(log.read_bytes()).hexdigest(), "passedTests": passed})
        if rows:
            (out / (name + ".json")).write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n")
        save()
        print(name, entry["state"], code, text[-3000:], flush=True)
    receipt["allRequiredChecksPassed"] = all(row["state"] == "passed" for row in receipt["checks"])
    # A single job cannot accept another lane, claim a deployed caller, or release.
    save()
    raise SystemExit(0 if receipt["allRequiredChecksPassed"] else 1)


if __name__ == "__main__":
    main()

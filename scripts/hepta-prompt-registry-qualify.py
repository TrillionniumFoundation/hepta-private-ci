#!/usr/bin/env python3
"""Read-only exact-candidate qualification with retry-audited dependency priming.

Network access is allowed only for a bounded dependency-prime check. A retry is
allowed only after a recognized transport failure, and every attempt is retained.
All compiler, test, lint, profile and map checks then run with Cargo offline.
Outputs are outside the checkout and every receipt remains fail-closed: a lane
cannot self-accept, activate, merge, release, or claim external infrastructure.
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CARGO = ROOT / "codex-rs"
DOC_ROOT = ROOT / "docs/modules/prompt.registry"
MAP = DOC_ROOT / "IMPLEMENTATION_MAP.json"
WORKFLOW = ROOT / ".github/workflows/hepta-prompt-registry-qualification.yml"
NETWORK_MARKERS = (
    "spurious network error", "failed to download", "failed to get `",
    "timeout was reached", "timed out", "connection reset", "connection refused",
    "could not resolve host", "temporary failure in name resolution",
    "failed to get successful http response", "operation too slow", "http2 framing layer",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(value: Path) -> str:
    return sha256_bytes(value.read_bytes())


def canonical_sha(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def tracked_manifest(*pathspecs: str) -> dict[str, str]:
    paths = git("ls-files", "--", *pathspecs).splitlines()
    return {path: sha256_bytes((ROOT / path).read_bytes()) for path in sorted(path for path in paths if path)}


def rust_target_triple() -> str:
    output = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
    for line in output.splitlines():
        if line.startswith("host: "):
            target = line.removeprefix("host: ").strip()
            if target:
                return target
    raise ValueError("rustc did not report a host target triple")


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


def completed_tests(text: str) -> set[str]:
    """A compiled inventory or zero-test harness is not execution evidence."""
    return set(re.findall(r"^test ([A-Za-z0-9_:]+) \.\.\. ok$", text, flags=re.MULTILINE))


def check_measurements(name: str, rows: list[dict]) -> list[str]:
    if name == "operational-profiles":
        scale = [r for r in rows if r.get("schema") == "hepta.prompt-registry.operational-scale.v2"]
        fsync = [r for r in rows if r.get("schema") == "hepta.prompt-registry.fsync-profile.v2"]
        if len(scale) != 3 or {r.get("logicalRecords") for r in scale} != {1000, 8000, 16384}:
            return ["missing or duplicate operational scale measurement rows"]
        if len(fsync) != 3 or {r.get("bytes") for r in fsync} != {4096, 65536, 1048576}:
            return ["missing or duplicate fsync measurement rows"]
        writers = [r for r in rows if r.get("schema") == "hepta.prompt-registry.writer-profile.v1"]
        if len(writers) != 3 or {r.get("finalLogicalRecords") for r in writers} != {1000, 8000, 16384}:
            return ["missing or duplicate actual writer profiles"]
        for writer in writers:
            if writer.get("registration", {}).get("samples") != 31 or writer.get("retirement", {}).get("samples") != 31:
                return ["missing actual writer latency samples"]
        for row in scale:
            gc = row.get("inPlaceGc", {})
            if gc.get("collectedPayloadRecords") != 1 or gc.get("cleanupPending") is not False:
                return ["in-place collection was not measured or did not complete"]
            for key in ["snapshot", "dereference"]:
                if row.get(key, {}).get("samples") != 31:
                    return ["missing read latency samples"]
        for row in fsync:
            if row.get("total", {}).get("samples") != 31:
                return ["missing fsync latency samples"]
    if name == "pipeline-profile":
        pipeline = [r for r in rows if r.get("schema") == "hepta.prompt-registry.pipeline-profile.v1"]
        if len(pipeline) != 31:
            return ["expected 31 pipeline measurement rows"]
    return []


def input_snapshot() -> dict[str, str]:
    """Detect tracked byte drift, not just a clean index or unchanged HEAD."""
    return tracked_manifest(
        "codex-rs/hepta-prompt-registry", "codex-rs/hepta-prompt-optimizer",
        "codex-rs/hepta-agentd/src/prompt*", "codex-rs/hepta-intelligence/src/prompt_delivery.rs",
        "codex-rs/ext/hepta-prompt", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
        "codex-rs/rust-toolchain.toml", "docs/modules/prompt.registry",
        "scripts/hepta-prompt-registry-*", ".github/workflows/hepta-prompt-registry-qualification.yml",
    )


def transient_network_failure(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in NETWORK_MARKERS)


def runner_identity(target: str) -> dict[str, str]:
    return {
        "system": platform.platform(),
        "machine": platform.machine(),
        "name": os.environ.get("RUNNER_NAME", "local"),
        "os": os.environ.get("RUNNER_OS", platform.system()),
        "arch": os.environ.get("RUNNER_ARCH", platform.machine()),
        "environment": os.environ.get("RUNNER_ENVIRONMENT", "local"),
        "imageOs": os.environ.get("ImageOS", os.environ.get("RUNNER_OS", platform.system())),
        "imageVersion": os.environ.get("ImageVersion", "unavailable"),
        "targetTriple": target,
    }


def artifact_hashes(out: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(entry for entry in out.rglob("*") if entry.is_file()):
        relative = path.relative_to(out).as_posix()
        if relative in {"receipt.json", "receipt.next"}:
            continue
        if path.is_symlink():
            raise ValueError("qualification artifact contains a symlink")
        values[relative] = file_sha256(path)
    return values


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
    workflow_sha = os.environ.get("PROMPT_REGISTRY_WORKFLOW_SHA", source)
    workflow_ref = os.environ.get("PROMPT_REGISTRY_WORKFLOW_REF", "local/source-bound")
    if not re.fullmatch(r"[a-f0-9]{40}", workflow_sha):
        raise SystemExit("invalid qualification workflow SHA")
    target_triple = rust_target_triple()
    runner = runner_identity(target_triple)
    source_files = input_snapshot()
    docs_manifest = tracked_manifest("docs/modules/prompt.registry")
    feature_profile = {
        "profile": args.profile, "lane": args.lane, "workspaceDefaultFeatures": True,
        "cargoOfflineAfterDependencyPrime": True,
        "packages": (["codex-hepta-prompt-registry"] if args.profile == "core" else [
            "codex-hepta-prompt-optimizer", "codex-hepta-agentd",
            "codex-hepta-intelligence", "codex-hepta-prompt-extension",
        ]),
    }
    receipt: dict[str, Any] = {
        "schema": "hepta.prompt-registry.qualification-receipt.v3",
        "profile": args.profile, "lane": args.lane,
        "candidateSha": source, "sourceSha": source, "baseSha": base,
        "testedSha": tested, "deterministicMergeSha": tested if args.lane == "base-merge" else None,
        "testedTree": git("rev-parse", "HEAD^{tree}"), "sourceTreeHash": git("rev-parse", "HEAD^{tree}"),
        "runId": os.environ.get("GITHUB_RUN_ID", "local"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "workflowRunId": os.environ.get("GITHUB_RUN_ID", "local"),
        "workflowRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "workflowSha": workflow_sha, "workflowRef": workflow_ref,
        "workflowFileSha256": file_sha256(WORKFLOW),
        "dependencyLockSha256": file_sha256(CARGO / "Cargo.lock"),
        "cargoLockSha256": file_sha256(CARGO / "Cargo.lock"),
        "implementationMapSha256": file_sha256(MAP),
        "documentationManifest": docs_manifest,
        "documentationHash": canonical_sha(docs_manifest),
        "sourceFiles": source_files,
        "sourceManifestSha256": canonical_sha(source_files),
        "featureProfile": feature_profile,
        "featureProfileSha256": canonical_sha(feature_profile),
        "targetTriple": target_triple,
        "runner": runner,
        "runnerImageIdentitySha256": canonical_sha(runner),
        "runnerImageDigest": None,
        "runnerImageDigestKind": "github-hosted-vm-identity-not-oci-content-digest",
        "checks": [], "artifactHashes": {}, "testSetSha256": None,
        "retryOccurred": False, "firstFailure": None,
        "allRequiredChecksPassed": False, "qualified": False,
        "mergeReady": False, "productionReady": False, "productActivated": False,
        "accepted": False, "released": False,
        "kmsHsmQualified": False, "wormRetentionQualified": False, "multiNodeQualified": False,
    }

    active_child: subprocess.Popen | None = None

    def save() -> None:
        receipt["artifactHashes"] = artifact_hashes(out)
        temporary = out / "receipt.next"
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(out / "receipt.json")

    def interrupt(signum: int, _frame: object) -> None:
        nonlocal active_child
        if active_child is not None and active_child.poll() is None:
            try:
                os.killpg(active_child.pid, signal.SIGKILL)
                active_child.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
        for entry in receipt["checks"]:
            if entry["state"] == "running":
                entry.update({"state": "interrupted", "exitCode": 128 + signum})
        receipt["interruptedBySignal"] = signum
        receipt["allRequiredChecksPassed"] = False
        save()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)

    commands: list[dict[str, Any]] = []

    def add(name: str, command: list[str], cwd: Path, limit: int, required: list[str] | None = None,
            minimum_passed: int = 0, network_prime: bool = False) -> None:
        commands.append({"name": name, "command": command, "cwd": cwd, "limit": limit,
                         "required": required or [], "minimumPassed": minimum_passed,
                         "networkPrime": network_prime})

    add("clean-before", ["git", "diff", "--exit-code", "HEAD"], ROOT, 30)
    add("harness-tests", ["python3", "scripts/hepta-prompt-registry-harness-tests.py"], ROOT, 120)
    add("public-api-map", ["python3", "scripts/hepta-prompt-registry-live-map.py", "--output", str(out / "live-public-api-map.json")], ROOT, 120)
    add("toolchain", ["rustc", "--version", "--verbose"], ROOT, 30)
    if args.profile == "core":
        add("format", ["cargo", "fmt", "--package", "codex-hepta-prompt-registry", "--", "--check"], CARGO, 120)
        add("dependency-prime", ["cargo", "test", "--locked", "-p", "codex-hepta-prompt-registry", "--no-run"], CARGO, 1200, network_prime=True)
    else:
        packages = ["codex-hepta-prompt-optimizer", "codex-hepta-agentd", "codex-hepta-intelligence", "codex-hepta-prompt-extension"]
        flags = [part for package in packages for part in ["-p", package]]
        add("format", ["cargo", "fmt", *flags, "--", "--check"], CARGO, 120)
        add("dependency-prime", ["cargo", "test", "--locked", *flags, "--no-run"], CARGO, 1800, network_prime=True)
    add("source-graph", ["cargo", "metadata", "--locked", "--offline", "--no-deps", "--format-version", "1"], CARGO, 90)
    if args.profile == "core":
        add("registry-inventory", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-registry", "--", "--list"], CARGO, 1200,
            ["gc_reclaims_inactive_raw_bytes_but_preserves_audit_and_revocation_after_restart", "gc_indeterminate_publication_poison_preserves_both_slots_until_reopen", "operational_restore_does_not_create_missing_paths_or_accept_unpinned_identity", "operational_compaction_retry_is_idempotent_and_conflicting_destination_is_untouched", "operational_poisoned_owner_exposes_diagnostics_but_not_authority"])
        add("registry", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-registry", "--", "--test-threads=1"], CARGO, 300, minimum_passed=1)
        add("all-targets", ["cargo", "check", "--locked", "--offline", "-p", "codex-hepta-prompt-registry", "--all-targets"], CARGO, 300)
        add("lint", ["cargo", "clippy", "--locked", "--offline", "-p", "codex-hepta-prompt-registry", "--all-targets", "--no-deps", "--", "-D", "warnings"], CARGO, 300)
        add("operational-profiles", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-registry", "operational_", "--", "--ignored", "--nocapture", "--test-threads=1"], CARGO, 900, minimum_passed=3)
    else:
        packages = ["codex-hepta-prompt-optimizer", "codex-hepta-agentd", "codex-hepta-intelligence", "codex-hepta-prompt-extension"]
        flags = [part for package in packages for part in ["-p", package]]
        add("agentd-inventory", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-agentd", "prompt_", "--", "--list"], CARGO, 1200,
            ["final_use_revocation_precedes_snapshot_error_and_survives_restart", "named_agentd_pipeline_stages_exact_registry_bytes_for_app_server_host"])
        add("extension-inventory", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-extension", "--", "--list"], CARGO, 600,
            ["cached_prompt_revalidates_owner_withdrawal_before_provider_begin", "cached_prompt_never_silently_switches_injected_payload"])
        add("optimizer", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-optimizer", "--", "--test-threads=1"], CARGO, 600, minimum_passed=1)
        add("extension", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-prompt-extension", "--", "--test-threads=1"], CARGO, 600, minimum_passed=1)
        add("agentd", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-agentd", "prompt_", "--", "--nocapture", "--test-threads=1"], CARGO, 600, minimum_passed=1)
        add("all-targets", ["cargo", "check", "--locked", "--offline", *flags, "--all-targets"], CARGO, 1200)
        add("lint", ["cargo", "clippy", "--locked", "--offline", *flags, "--all-targets", "--no-deps", "--", "-D", "warnings"], CARGO, 1200)
        add("pipeline-profile", ["cargo", "test", "--locked", "--offline", "-p", "codex-hepta-agentd", "operational_pipeline_compile_stage_final_use_profile", "--", "--ignored", "--nocapture", "--test-threads=1"], CARGO, 600, minimum_passed=1)
    add("clean-after", ["git", "diff", "--exit-code", "HEAD"], ROOT, 30)

    receipt["testSetSha256"] = canonical_sha([
        {"name": row["name"], "command": row["command"], "required": row["required"],
         "minimumPassed": row["minimumPassed"], "networkPrime": row["networkPrime"]}
        for row in commands
    ])
    receipt["checks"] = [{
        "name": row["name"], "command": row["command"],
        "required": row["required"], "minimumPassed": row["minimumPassed"],
        "networkPrime": row["networkPrime"], "state": "not_run",
        "exitCode": None, "attempts": [], "postconditionFailures": [],
    } for row in commands]
    save()

    for index, spec in enumerate(commands):
        name = spec["name"]
        entry = receipt["checks"][index]
        entry["state"] = "running"
        save()
        max_attempts = 3 if spec["networkPrime"] else 1
        combined: list[str] = []
        code = 127
        started = time.monotonic()
        for attempt in range(1, max_attempts + 1):
            attempt_log = out / f"{name}.attempt-{attempt}.log"
            attempt_started = time.monotonic()
            environment = os.environ.copy()
            if spec["networkPrime"]:
                environment.pop("CARGO_NET_OFFLINE", None)
                environment.setdefault("CARGO_NET_RETRY", "10")
                environment.setdefault("CARGO_HTTP_TIMEOUT", "600")
                environment.setdefault("CARGO_HTTP_LOW_SPEED_LIMIT", "1")
                environment.setdefault("CARGO_REGISTRIES_CRATES_IO_PROTOCOL", "sparse")
            elif spec["command"] and spec["command"][0] == "cargo":
                environment["CARGO_NET_OFFLINE"] = "true"
            with attempt_log.open("w", encoding="utf-8") as stream:
                try:
                    child = subprocess.Popen(spec["command"], cwd=spec["cwd"], env=environment,
                                             stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                    active_child = child
                    try:
                        code = child.wait(timeout=spec["limit"])
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                        code = 124
                except OSError as error:
                    stream.write(f"{type(error).__name__}: command unavailable\n")
                    code = 127
            active_child = None
            text = attempt_log.read_text(encoding="utf-8", errors="replace")
            transient = code != 0 and transient_network_failure(text)
            attempt_row = {
                "attempt": attempt, "exitCode": code,
                "durationSeconds": time.monotonic() - attempt_started,
                "log": attempt_log.name, "logSha256": file_sha256(attempt_log),
                "transientNetworkFailure": transient,
            }
            entry["attempts"].append(attempt_row)
            combined.append(f"===== attempt {attempt} exit={code} transientNetworkFailure={str(transient).lower()} =====\n{text}")
            if code == 0:
                break
            if not spec["networkPrime"] or not transient or attempt == max_attempts:
                break
            receipt["retryOccurred"] = True
            time.sleep(min(5 * (3 ** (attempt - 1)), 45))
        log = out / (name + ".log")
        log.write_text("\n".join(combined), encoding="utf-8")
        text = "\n".join(combined)
        failures: list[str] = []
        if code == 0 and any(token not in text for token in spec["required"]):
            failures.append("required compiled test is missing")
        counts = re.findall(r"test result: ok\. (\d+) passed", text)
        passed = sum(map(int, counts))
        if code == 0 and spec["minimumPassed"] and passed < spec["minimumPassed"]:
            failures.append("test filter did not execute the required nonzero tests")
        rows = profile_rows(text)
        if code == 0:
            failures.extend(check_measurements(name, rows))
            required_execution = {
                "registry": ["gc_reclaims_inactive_raw_bytes_but_preserves_audit_and_revocation_after_restart", "gc_indeterminate_publication_poison_preserves_both_slots_until_reopen", "gc_process_exit_after_unknown_commit_reconciles", "read_integrity_failures_never_become_recompile_or_availability_retries"],
                "agentd": ["final_use_integrity_error_is_not_a_recompilation_hint", "final_use_revocation_precedes_snapshot_error_and_survives_restart"],
                "extension": ["cached_prompt_revalidates_owner_withdrawal_before_provider_begin", "cached_prompt_never_silently_switches_injected_payload"],
            }.get(name, [])
            executed = {test.rsplit("::", 1)[-1] for test in completed_tests(text)}
            if any(test not in executed for test in required_execution):
                failures.append("required regression did not actually pass")
        if name == "source-graph" and code == 0:
            try:
                opening = text.find("{")
                graph = json.loads(text[opening:])
                names = {package["name"] for package in graph["packages"]}
            except (ValueError, KeyError, TypeError):
                failures.append("invalid Cargo source graph output")
                names = set()
            if not {"codex-hepta-prompt-registry", "codex-hepta-prompt-extension", "codex-hepta-agentd"}.issubset(names):
                failures.append("missing required workspace package")
        if name == "public-api-map" and code == 0:
            try:
                live_map = json.loads((out / "live-public-api-map.json").read_text(encoding="utf-8"))
                if live_map.get("candidateSha") != tested or live_map.get("sourceTreeHash") != receipt["testedTree"]:
                    failures.append("live public API map identity mismatch")
                if live_map.get("closedWorldPublicFunctions") is not True or live_map.get("dangerousLegacyPurgeSymbols") != []:
                    failures.append("public API inventory or legacy purge guard failed")
                receipt["livePublicApiMapSha256"] = file_sha256(out / "live-public-api-map.json")
                receipt["closedWorldPublicFunctions"] = live_map.get("closedWorldPublicFunctions") is True
                receipt["productExecutionProved"] = live_map.get("productExecutionProved") is True
            except (OSError, ValueError, TypeError):
                failures.append("invalid live public API map")
        if name == "clean-after":
            if git("status", "--porcelain", "--untracked-files=no") or git("rev-parse", "HEAD") != tested or input_snapshot() != receipt["sourceFiles"]:
                failures.append("tested source changed during qualification")
            untracked = git("ls-files", "--others", "--exclude-standard", "--", "codex-rs/hepta-prompt-registry", "codex-rs/hepta-agentd/src", "codex-rs/hepta-prompt-optimizer", "codex-rs/ext/hepta-prompt")
            if untracked:
                failures.append("untracked owned source appeared during qualification")
        entry.update({
            "exitCode": code, "state": "passed" if code == 0 and not failures else "failed",
            "postconditionFailures": failures, "durationSeconds": time.monotonic() - started,
            "logSha256": file_sha256(log), "passedTests": passed,
            "retried": len(entry["attempts"]) > 1,
            "firstAttemptExitCode": entry["attempts"][0]["exitCode"],
            "finalAttemptExitCode": entry["attempts"][-1]["exitCode"],
        })
        if rows:
            (out / (name + ".json")).write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        if entry["state"] != "passed" and receipt["firstFailure"] is None:
            receipt["firstFailure"] = {
                "check": name, "command": spec["command"], "exitCode": code,
                "postconditionFailures": failures,
                "firstAttemptExitCode": entry["firstAttemptExitCode"],
                "finalAttemptExitCode": entry["finalAttemptExitCode"],
                "retried": entry["retried"],
            }
        save()
        print(name, entry["state"], code, text[-3000:], flush=True)
        if name == "dependency-prime" and entry["state"] != "passed":
            for blocked in receipt["checks"][index + 1:]:
                if blocked["state"] == "not_run":
                    blocked["state"] = "blocked_by_dependency_prime"
            save()
            break

    receipt["allRequiredChecksPassed"] = all(row["state"] == "passed" for row in receipt["checks"])
    receipt["qualified"] = False
    receipt["mergeReady"] = False
    receipt["productionReady"] = False
    save()
    raise SystemExit(0 if receipt["allRequiredChecksPassed"] else 1)


if __name__ == "__main__":
    main()

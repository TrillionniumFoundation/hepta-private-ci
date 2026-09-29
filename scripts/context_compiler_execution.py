#!/usr/bin/env python3
"""Read-only dual-lane execution over a previously bound Git candidate.

The receipt binds source/base/tested commit and tree identities, the workflow and
runner identity, the complete command/log record, the pinned toolchain, and a
canonical digest of every evidence payload file produced before the signed
receipt. The source checkout is revalidated before and after every command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
from typing import Any

import context_compiler_candidate as candidate
import context_compiler_named_evidence as named_evidence

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def observed_tests(log: str) -> int:
    total = 0
    for line in ANSI.sub("", log).splitlines():
        if "test result:" not in line and "Summary" not in line:
            continue
        matched = re.search(r"\b(\d+) passed\b", line)
        if matched is None:
            matched = re.search(r"\b(\d+) tests run\b", line)
        if matched:
            total += int(matched.group(1))
    return total


def specs(legacy):
    commands = []
    for original in legacy.command_specs():
        spec = dict(original)
        spec["argv"] = list(original["argv"])
        if spec["argv"][:2] == ["cargo", "test"]:
            spec["argv"][:2] = ["just", "test"]
            spec["minimumTests"] = 1
        commands.append(spec)

    # These selectors exercise the actual provider-body slots, not only the
    # context compiler crate in isolation.
    commands[2:2] = [
        {
            "name": "typed-slot-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just", "test", "--locked", "-p", "codex-api", "--lib", "context_slot"
            ],
            "minimumTests": 11,
        },
        {
            "name": "exact-body-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just", "test", "--locked", "-p", "codex-hepta-prompt-extension",
                "--lib", "exact_body"
            ],
            "minimumTests": 8,
        },
        {
            "name": "v3-product-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just", "test", "--locked", "-p", "codex-hepta-intelligence",
                "prompt_product_v3",
            ],
            "minimumTests": 4,
        },
        {
            "name": "crash-recovery-regressions",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just", "test", "--locked", "-p", "codex-hepta-agentd",
                "registry_race_tests",
            ],
            "minimumTests": 5,
        },
        {
            "name": "v3-default-product-profile",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just", "test", "--locked",
                "-p", "codex-hepta-prompt-registry",
                "-p", "codex-hepta-context-compiler",
                "-p", "codex-hepta-intelligence",
                "-p", "codex-hepta-agentd",
            ],
            "minimumTests": 1,
        },
        {
            "name": "legacy-intelligence-profile",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just", "test", "--locked", "-p", "codex-hepta-intelligence",
                "--features", "legacy-prompt-context-v1",
            ],
            "minimumTests": 1,
        },
        {
            "name": "legacy-agentd-profile",
            "cwd": legacy.CODEX_RS,
            "argv": [
                "just", "test", "--locked", "-p", "codex-hepta-agentd",
                "--features", "legacy-prompt-context-v1",
            ],
            "minimumTests": 1,
        },
    ]

    commands[2:2] = [
        {
            "name": 'owner-lifecycle-regressions',
            "cwd": legacy.CODEX_RS,
            "argv": ["just", "test", "--locked", "-p", "codex-hepta-agentd",
                     'lifecycle_tests', "--status-level", "pass", "--success-output", "immediate"],
            "minimumTests": 10,
            "requiredNativeTests": [
                'exact_context_delivery::registry_race_tests::lifecycle_tests::sequential_completed_turns_release_more_than_256_stages',
                'exact_context_delivery::registry_race_tests::lifecycle_tests::runtime_stage_failure_does_not_publish_an_exact_stage',
                'exact_context_delivery::registry_race_tests::lifecycle_tests::runtime_capacity_failure_does_not_consume_exact_capacity',
                'exact_context_delivery::registry_race_tests::lifecycle_tests::uncertain_runtime_publication_leaves_no_exact_authorization',
                'exact_context_delivery::registry_race_tests::lifecycle_tests::preparation_reservation_blocks_clear_without_calling_runtime',
                'exact_context_delivery::registry_race_tests::lifecycle_tests::tool_continuation_and_unknown_terminal_keep_the_stage',
                'prompt_runtime::lifecycle_tests::explicit_retirement_survives_reopen_without_raw_context',
                'prompt_runtime::lifecycle_tests::unresolved_attempt_cannot_be_retired',
                'prompt_runtime::lifecycle_tests::schema_one_cannot_smuggle_retirement_and_schema_two_rejects_orphans',
                'prompt_runtime::lifecycle_tests::new_staging_cannot_spend_an_admitted_attempts_completion_reserve',
            ],
            "requireFixtureProfile": True,
        },
        {
            "name": 'owner-metrics-regressions',
            "cwd": legacy.CODEX_RS,
            "argv": ["just", "test", "--locked", "-p", "codex-hepta-agentd",
                     'exact_context_delivery::metrics::tests', "--status-level", "pass", "--success-output", "immediate"],
            "minimumTests": 4,
            "requiredNativeTests": [
                'exact_context_delivery::metrics::tests::window_is_bounded_and_percentiles_are_nearest_rank',
                'exact_context_delivery::metrics::tests::an_unobserved_phase_is_not_a_zero_latency_claim',
                'exact_context_delivery::metrics::tests::leaving_a_failed_phase_still_records_attempted_time',
                'exact_context_delivery::metrics::tests::diagnostics_do_not_hold_a_lock_across_measured_work',
            ],
        },
        {
            "name": 'owner-capacity-regressions',
            "cwd": legacy.CODEX_RS,
            "argv": ["just", "test", "--locked", "-p", "codex-hepta-agentd",
                     'exact_context_delivery::capacity_tests', "--status-level", "pass", "--success-output", "immediate"],
            "minimumTests": 3,
            "requiredNativeTests": [
                'exact_context_delivery::capacity_tests::unknown_observations_cannot_release_the_final_reservation',
                'exact_context_delivery::capacity_tests::reserve_exhaustion_rejects_before_writing_and_does_not_poison',
                'exact_context_delivery::capacity_tests::oversized_terminal_cannot_exceed_its_reserved_record_bound',
            ],
        },
        {"name": "named-evidence-parser-regressions", "cwd": legacy.ROOT,
         "argv": ["python3", "-B", "-m", "unittest", "discover", "-s", "scripts",
                  "-p", "test_context_compiler_named_evidence.py", "-v"]},
    ]
    return commands


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence_payload(output: Path, receipt_path: Path) -> dict[str, Any]:
    """Return a canonical manifest/digest without creating a self-reference."""
    files: list[dict[str, Any]] = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path == receipt_path or path.name.endswith(".tmp"):
            continue
        relative = path.relative_to(output).as_posix()
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema": "hepta.context-compiler-evidence-payload.v1",
        "files": files,
        "canonicalSha256": hashlib.sha256(canonical).hexdigest(),
    }


def environment_identity() -> dict[str, Any]:
    keys = (
        "GITHUB_REPOSITORY",
        "GITHUB_WORKFLOW",
        "GITHUB_WORKFLOW_REF",
        "GITHUB_WORKFLOW_SHA",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_JOB",
        "GITHUB_EVENT_NAME",
        "GITHUB_REF",
        "GITHUB_SHA",
        "GITHUB_ACTOR_ID",
        "RUNNER_NAME",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "RUNNER_ENVIRONMENT",
        "QUALIFICATION_WORKFLOW_REF",
        "QUALIFICATION_WORKFLOW_SHA",
        "QUALIFICATION_RUN_ID",
        "QUALIFICATION_RUN_ATTEMPT",
        "QUALIFICATION_RUNNER_IMAGE",
        "QUALIFICATION_RUNNER_OS",
        "QUALIFICATION_RUNNER_ARCH",
    )
    return {
        "environment": {key: os.environ.get(key) for key in keys},
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def main() -> int:
    import context_compiler_qualification as legacy

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-record", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    root = legacy.ROOT.resolve()
    output = args.output_dir.resolve()
    if output == root or root in output.parents:
        parser.error("execution evidence must be outside the checkout")
    output.mkdir(parents=True, exist_ok=True)

    record_document = json.loads(args.candidate_record.read_text(encoding="utf-8"))
    digest = record_document.pop("recordSha256", None)
    expected = hashlib.sha256(
        json.dumps(record_document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != expected:
        parser.error("candidate record digest mismatch")

    source_tree = candidate.git(root, "rev-parse", f"{record_document['sourceHeadSha']}^{{tree}}")
    base_tree = candidate.git(root, "rev-parse", f"{record_document['baseSha']}^{{tree}}")
    immutable_identity = {
        "sourceCommit": record_document["sourceHeadSha"],
        "sourceTree": source_tree,
        "baseCommit": record_document["baseSha"],
        "baseTree": base_tree,
        "testedCommit": record_document["testedHeadSha"],
        "testedTree": record_document["testedTreeSha"],
        "orderedParents": record_document["parents"],
        "lane": record_document["lane"],
    }

    receipt = {
        "schema": "hepta.context-compiler-dual-lane-execution.v2",
        "candidate": record_document,
        "immutableIdentity": immutable_identity,
        "executionEnvironment": environment_identity(),
        "status": "running",
        "commands": [],
        "independentAcceptance": False,
        "activation": False,
        "release": False,
    }
    receipt_path = output / "context-compiler-qualification-receipt.json"
    failure = None
    command_specs = specs(legacy)
    try:
        candidate.verify(root, record_document)
        legacy.write_receipt(receipt_path, receipt)
        for index, spec in enumerate(command_specs, start=1):
            candidate.verify(root, record_document)
            log = output / "logs" / f"{index:02d}-{spec['name']}.log"
            result = legacy.run_command(spec, log)
            minimum = spec.get("minimumTests")
            if minimum is not None:
                # Native summaries are at the tail; do not load an unbounded log.
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 1024 * 1024))
                    count = observed_tests(stream.read().decode("utf-8", errors="replace"))
                result.update({"minimumTests": minimum, "testsObserved": count})
                result["succeeded"] = result["succeeded"] and count >= minimum
            if spec.get("requiredNativeTests"):
                try:
                    named = named_evidence.bind_named_tests(log, spec["requiredNativeTests"])
                    result.update(named)
                    result["succeeded"] = result["succeeded"] and named["namedNativeTestsPassed"]
                    if spec.get("requireFixtureProfile"):
                        profile = named_evidence.fixture_profile(log)
                        result["ownerFixtureProfile"] = profile
                        result["succeeded"] = result["succeeded"] and profile is not None
                except (OSError, ValueError, TypeError, UnicodeError) as error:
                    result["namedEvidenceFailure"] = type(error).__name__
                    result["succeeded"] = False
            receipt["commands"].append(result)
            candidate.verify(root, record_document)
            receipt.pop("receiptSha256", None)
            legacy.write_receipt(receipt_path, receipt)
        candidate.verify(root, record_document)
    except (Exception, KeyboardInterrupt) as error:
        failure = type(error).__name__

    receipt.pop("receiptSha256", None)
    receipt["failureClass"] = failure
    receipt["status"] = "passed" if (
        failure is None
        and len(receipt["commands"]) == len(command_specs)
        and all(item["succeeded"] or not item["required"] for item in receipt["commands"])
    ) else "failed"
    state = json.loads(legacy.MANIFEST.read_text(encoding="utf-8"))
    receipt["consumerExecution"] = named_evidence.consumer_projection(
        state.get("consumerExecution", []), receipt["commands"], immutable_identity
    )
    receipt["toolchain"] = {
        name: legacy.tool_version(argv)
        for name, argv in {
            "git": ["git", "--version"],
            "python": [sys.executable, "--version"],
            "rustc": ["rustc", "-Vv"],
            "cargo": ["cargo", "--version"],
            "just": ["just", "--version"],
            "nextest": ["cargo", "nextest", "--version"],
            "cargoDeny": ["cargo", "deny", "--version"],
            "bazel": ["bazel", "--version"],
        }.items()
    }
    receipt["createdAt"] = legacy.utc_now()
    receipt["manifestCanonicalSha256"] = legacy.canonical_manifest_sha256()
    # Hash every command log, the candidate record, and any partial evidence
    # before serializing the final signed receipt. The outer Actions artifact
    # additionally retains a full-file manifest including this receipt.
    receipt["evidencePayload"] = evidence_payload(output, receipt_path)
    legacy.write_receipt(receipt_path, receipt)
    print(f"qualification {receipt['status']}: {receipt_path}")
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

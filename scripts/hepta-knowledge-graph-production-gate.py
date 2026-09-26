#!/usr/bin/env python3
"""Fail-closed production admission gate for knowledge.graph target-host evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

POLICY_SCHEMA = "hepta.knowledge-graph-production-qualification-policy.v1"
EVIDENCE_SCHEMA = "hepta.knowledge-graph-target-host-evidence.v1"
ADMISSION_SCHEMA = "hepta.knowledge-graph-target-host-admission.v1"
ACCEPTANCE_SCHEMA = "hepta.knowledge-graph-production-acceptance.v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class GateError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise GateError(message)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail(f"cannot read JSON {path}: {error}")
    if not isinstance(value, dict):
        fail(f"JSON root must be an object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_schema(value: dict[str, Any], expected: str, label: str) -> None:
    if value.get("schema") != expected:
        fail(f"{label} schema must be {expected}")


def require_hex(value: Any, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        fail(f"{label} is not a canonical hexadecimal digest")
    return value


def require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail(f"{label} must be an integer >= {minimum}")
    return value


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    return value


def require_list_of_strings(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        fail(f"{label} must be a non-empty string array")
    if len(value) != len(set(value)):
        fail(f"{label} must not contain duplicates")
    return value


def percentile(
    container: dict[str, Any], field: str, percentile_name: str, label: str
) -> int:
    distribution = require_dict(container.get(field), f"{label}.{field}")
    return require_int(
        distribution.get(percentile_name),
        f"{label}.{field}.{percentile_name}",
        minimum=1,
    )


def check_policy(policy: dict[str, Any]) -> None:
    require_schema(policy, POLICY_SCHEMA, "policy")
    profile_id = policy.get("profileId")
    if not isinstance(profile_id, str) or not profile_id:
        fail("policy.profileId is required")

    target = require_dict(policy.get("targetHost"), "policy.targetHost")
    for key in ("runnerName", "runnerOs", "runnerArch", "sourceRef"):
        if not isinstance(target.get(key), str) or not target[key]:
            fail(f"policy.targetHost.{key} is required")
    labels = require_list_of_strings(
        target.get("requiredLabels"), "policy.targetHost.requiredLabels"
    )
    if "self-hosted" not in labels:
        fail("target host labels must include self-hosted")
    if target.get("exclusiveRunRequired") is not True:
        fail("target host must require an exclusive run")
    if target.get("sharedGithubHostedRunnerForbidden") is not True:
        fail("shared GitHub-hosted runners must be forbidden")

    workload = require_dict(policy.get("workload"), "policy.workload")
    for key in (
        "writes",
        "querySamples",
        "reopenSamples",
        "contentionReaders",
        "contentionRounds",
        "logicalNodes",
        "logicalEdges",
    ):
        require_int(workload.get(key), f"policy.workload.{key}", minimum=1)

    budgets = require_dict(policy.get("budgets"), "policy.budgets")
    for key in (
        "mutationP95Ns",
        "mutationP99Ns",
        "queryP95Ns",
        "queryP99Ns",
        "reopenP95Ns",
        "reopenP99Ns",
        "peakRssKiB",
        "databaseAndWalBytes",
        "databaseGrowthPerMutationBytes",
        "contentionWriterP95Ns",
        "contentionWriterP99Ns",
        "contentionReaderP95Ns",
        "contentionReaderP99Ns",
    ):
        require_int(budgets.get(key), f"policy.budgets.{key}", minimum=1)
    for prefix in (
        "mutation",
        "query",
        "reopen",
        "contentionWriter",
        "contentionReader",
    ):
        if budgets[f"{prefix}P95Ns"] > budgets[f"{prefix}P99Ns"]:
            fail(f"policy {prefix} p95 budget exceeds p99 budget")

    writer = require_dict(policy.get("writer"), "policy.writer")
    if not isinstance(writer.get("selectedRuntimeWriter"), str):
        fail("policy.writer.selectedRuntimeWriter is required")
    require_int(
        writer.get("fullRebuildOracleInterval"),
        "policy.writer.fullRebuildOracleInterval",
        minimum=1,
    )

    retention = require_dict(policy.get("retention"), "policy.retention")
    for key in (
        "targetHostArtifactsDays",
        "releaseEvidenceDays",
        "hotGenerationReceiptsDays",
    ):
        require_int(retention.get(key), f"policy.retention.{key}", minimum=1)
    for key in ("rawLogsRequired", "structuredJsonRequired", "sha256ManifestRequired"):
        if retention.get(key) is not True:
            fail(f"policy.retention.{key} must be true")

    checkpoint = require_dict(policy.get("checkpoint"), "policy.checkpoint")
    require_int(
        checkpoint.get("onlineWalCheckpointGenerationInterval"),
        "policy.checkpoint.onlineWalCheckpointGenerationInterval",
        minimum=1,
    )
    require_int(
        checkpoint.get("onlineWalCheckpointBytes"),
        "policy.checkpoint.onlineWalCheckpointBytes",
        minimum=1,
    )
    if checkpoint.get("maintenanceRequiresExclusiveOwnerFence") is not True:
        fail("maintenance checkpoint requires an exclusive owner fence")

    archive = require_dict(policy.get("archive"), "policy.archive")
    require_int(
        archive.get("generationInterval"),
        "policy.archive.generationInterval",
        minimum=1,
    )
    require_int(
        archive.get("maximumWallClockHours"),
        "policy.archive.maximumWallClockHours",
        minimum=1,
    )
    if archive.get("appendOnly") is not True or archive.get("digest") != "sha256":
        fail("archive policy must be append-only and SHA-256 bound")

    external = require_dict(policy.get("externalGates"), "policy.externalGates")
    for key in (
        "independentSemanticReviewRequired",
        "operatorAcceptanceRequired",
        "canaryRequired",
        "rollbackRehearsalRequired",
        "activationRequiresAll",
        "releaseRequiresActivation",
    ):
        if external.get(key) is not True:
            fail(f"policy.externalGates.{key} must be true")


def check_runner(
    policy: dict[str, Any],
    runner: dict[str, Any],
    expected_sha: str,
) -> list[str]:
    errors: list[str] = []
    target = policy["targetHost"]
    expected_labels = set(target["requiredLabels"])
    labels = runner.get("labels")
    if not isinstance(labels, list) or any(not isinstance(item, str) for item in labels):
        errors.append("runner labels are missing or malformed")
    elif not expected_labels.issubset(set(labels)):
        errors.append(
            "runner labels do not satisfy target profile: "
            f"required={sorted(expected_labels)} observed={sorted(set(labels))}"
        )
    for key, expected in (
        ("runnerName", target["runnerName"]),
        ("runnerOs", target["runnerOs"]),
        ("runnerArch", target["runnerArch"]),
        ("githubRef", target["sourceRef"]),
        ("githubSha", expected_sha),
    ):
        if runner.get(key) != expected:
            errors.append(f"runner {key} mismatch: expected={expected!r}")
    if runner.get("eventName") not in ("push", "workflow_dispatch"):
        errors.append("runner event is not a controlled target-host trigger")
    if runner.get("exclusiveOwnerFence") is not True:
        errors.append("runner did not attest the exclusive owner fence")
    return errors


def evaluate_data(
    policy: dict[str, Any],
    evidence: dict[str, Any],
    raw_log: bytes,
    runner: dict[str, Any],
    expected_sha: str,
    expected_tree: str,
    *,
    policy_digest: str,
    evidence_digest: str,
    runner_digest: str,
) -> tuple[dict[str, Any], list[str]]:
    check_policy(policy)
    require_schema(evidence, EVIDENCE_SCHEMA, "evidence")
    require_hex(expected_sha, HEX40, "expected SHA")
    require_hex(expected_tree, HEX40, "expected tree")

    errors = check_runner(policy, runner, expected_sha)
    if evidence.get("sourceCommit") != expected_sha:
        errors.append("evidence sourceCommit is not the exact candidate SHA")
    if evidence.get("sourceTree") != expected_tree:
        errors.append("evidence sourceTree is not the exact candidate tree")
    if evidence.get("hostProfileId") != policy["profileId"]:
        errors.append("evidence hostProfileId does not match policy")
    if evidence.get("buildProfile") != "release":
        errors.append("target-host benchmark did not use the release profile")
    if evidence.get("nextestProfile") != "knowledge-graph-measurement":
        errors.append("target-host benchmark used the wrong nextest profile")
    if evidence.get("selectedRuntimeWriter") != policy["writer"][
        "selectedRuntimeWriter"
    ]:
        errors.append("target-host receipt used the wrong runtime writer")
    if evidence.get("incrementalPromoted") is not True:
        errors.append("target-host receipt did not exercise the incremental writer")
    if evidence.get("fullRebuildOracleInterval") != policy["writer"][
        "fullRebuildOracleInterval"
    ]:
        errors.append("full-rebuild oracle interval does not match policy")

    raw_digest = sha256_bytes(raw_log)
    if evidence.get("rawLogSha256") != raw_digest:
        errors.append("raw benchmark log SHA-256 does not match the evidence")

    parameters = evidence.get("parameters")
    if not isinstance(parameters, dict):
        errors.append("evidence parameters are missing")
        parameters = {}
    for evidence_key, policy_key in (
        ("writes", "writes"),
        ("querySamples", "querySamples"),
        ("reopenSamples", "reopenSamples"),
        ("contentionReaders", "contentionReaders"),
        ("contentionRounds", "contentionRounds"),
    ):
        if parameters.get(evidence_key) != policy["workload"][policy_key]:
            errors.append(f"workload parameter mismatch: {evidence_key}")

    benchmark = evidence.get("benchmark")
    if not isinstance(benchmark, dict):
        errors.append("benchmark receipt is missing")
        benchmark = {}
    for key in ("writes", "querySamples", "reopenSamples"):
        if benchmark.get(key) != policy["workload"][key]:
            errors.append(f"benchmark workload mismatch: {key}")
    for key in ("logicalNodes", "logicalEdges"):
        if benchmark.get(key) != policy["workload"][key]:
            errors.append(f"benchmark canonical cardinality mismatch: {key}")

    observed: dict[str, int] = {}
    try:
        observed["mutationP95Ns"] = percentile(
            benchmark, "mutationNs", "p95", "benchmark"
        )
        observed["mutationP99Ns"] = percentile(
            benchmark, "mutationNs", "p99", "benchmark"
        )
        observed["queryP95Ns"] = percentile(
            benchmark, "queryNs", "p95", "benchmark"
        )
        observed["queryP99Ns"] = percentile(
            benchmark, "queryNs", "p99", "benchmark"
        )
        observed["reopenP95Ns"] = percentile(
            benchmark, "reopenNs", "p95", "benchmark"
        )
        observed["reopenP99Ns"] = percentile(
            benchmark, "reopenNs", "p99", "benchmark"
        )
        contention = require_dict(benchmark.get("contention"), "benchmark.contention")
        observed["contentionWriterP95Ns"] = percentile(
            contention, "writerNs", "p95", "benchmark.contention"
        )
        observed["contentionWriterP99Ns"] = percentile(
            contention, "writerNs", "p99", "benchmark.contention"
        )
        observed["contentionReaderP95Ns"] = percentile(
            contention, "readerNs", "p95", "benchmark.contention"
        )
        observed["contentionReaderP99Ns"] = percentile(
            contention, "readerNs", "p99", "benchmark.contention"
        )
        process = require_dict(benchmark.get("process"), "benchmark.process")
        observed["peakRssKiB"] = require_int(
            process.get("peakRssKiB"), "benchmark.process.peakRssKiB", minimum=1
        )
        storage = require_dict(benchmark.get("storage"), "benchmark.storage")
        database_bytes = require_int(
            storage.get("databaseBytes"),
            "benchmark.storage.databaseBytes",
            minimum=1,
        )
        wal_bytes = require_int(
            storage.get("walBytes"),
            "benchmark.storage.walBytes",
            minimum=0,
        )
        observed["databaseAndWalBytes"] = database_bytes + wal_bytes
        writes = require_int(
            benchmark.get("writes"), "benchmark.writes", minimum=1
        )
        observed["databaseGrowthPerMutationBytes"] = math.ceil(
            observed["databaseAndWalBytes"] / writes
        )
    except GateError as error:
        errors.append(str(error))

    budgets = policy["budgets"]
    for key, observed_value in observed.items():
        limit = budgets[key]
        if observed_value > limit:
            errors.append(
                f"budget exceeded: {key} observed={observed_value} limit={limit}"
            )

    interpretation = evidence.get("interpretation")
    if not isinstance(interpretation, dict):
        errors.append("evidence interpretation is missing")
    else:
        for key in (
            "exactSourceBound",
            "namedTargetHostProfileMeasured",
            "sharedGithubHostedRunnerIsNotTargetHostEvidence",
            "measurementDoesNotGrantActivation",
            "measurementDoesNotGrantAcceptance",
            "measurementDoesNotGrantRelease",
        ):
            if interpretation.get(key) is not True:
                errors.append(f"evidence interpretation.{key} must be true")

    admission = {
        "schema": ADMISSION_SCHEMA,
        "profileId": policy["profileId"],
        "candidate": {"commit": expected_sha, "tree": expected_tree},
        "admitted": not errors,
        "policySha256": policy_digest,
        "evidenceSha256": evidence_digest,
        "runnerMetadataSha256": runner_digest,
        "rawLogSha256": raw_digest,
        "writer": {
            "selectedRuntimeWriter": evidence.get("selectedRuntimeWriter"),
            "fullRebuildOracleInterval": evidence.get(
                "fullRebuildOracleInterval"
            ),
            "remainingScaleBoundary": evidence.get(
                "remainingWriterScaleBoundary"
            ),
        },
        "observed": observed,
        "budgets": budgets,
        "errors": errors,
        "claimBoundary": {
            "targetHostReceiptAccepted": not errors,
            "independentSemanticReviewAccepted": False,
            "operatorAcceptanceAccepted": False,
            "canaryAccepted": False,
            "rollbackRehearsalAccepted": False,
            "activation": False,
            "release": False,
        },
    }
    return admission, errors


def evaluate(args: argparse.Namespace) -> int:
    policy_path = Path(args.policy)
    evidence_path = Path(args.evidence)
    raw_path = Path(args.raw_log)
    runner_path = Path(args.runner_metadata)
    output_path = Path(args.output)
    policy_bytes = policy_path.read_bytes()
    evidence_bytes = evidence_path.read_bytes()
    runner_bytes = runner_path.read_bytes()
    raw_bytes = raw_path.read_bytes()
    policy = read_json(policy_path)
    evidence = read_json(evidence_path)
    runner = read_json(runner_path)
    admission, errors = evaluate_data(
        policy,
        evidence,
        raw_bytes,
        runner,
        args.expected_sha,
        args.expected_tree,
        policy_digest=sha256_bytes(policy_bytes),
        evidence_digest=sha256_bytes(evidence_bytes),
        runner_digest=sha256_bytes(runner_bytes),
    )
    write_json(output_path, admission)
    if errors:
        for error in errors:
            print(f"ERROR_HEPTA_KG_PRODUCTION_GATE {error}", file=sys.stderr)
        return 1
    print(
        "PASS_HEPTA_KG_PRODUCTION_GATE "
        f"profile={policy['profileId']} sha={args.expected_sha}"
    )
    return 0


def verify_acceptance_state(
    policy: dict[str, Any],
    state: dict[str, Any],
    candidate_sha: str | None,
    *,
    require_inactive: bool,
) -> None:
    check_policy(policy)
    require_schema(state, ACCEPTANCE_SCHEMA, "acceptance state")
    activation = state.get("activation")
    release = state.get("release")
    if not isinstance(activation, bool) or not isinstance(release, bool):
        fail("acceptance activation/release must be booleans")
    if release and not activation:
        fail("release cannot be true before activation")

    gates = (
        "targetHostAdmission",
        "independentSemanticReview",
        "operatorAcceptance",
        "canary",
        "rollbackRehearsal",
    )
    gate_values: dict[str, dict[str, Any]] = {}
    for name in gates:
        value = require_dict(state.get(name), f"acceptance.{name}")
        status = value.get("status")
        if status not in ("pending", "accepted", "rejected"):
            fail(f"acceptance.{name}.status is invalid")
        gate_values[name] = value

    if require_inactive:
        if activation or release:
            fail("repository acceptance state must remain inactive before external gates")
        if any(value.get("status") == "accepted" for value in gate_values.values()):
            fail("inactive acceptance template must not pre-accept an external gate")
        return

    if candidate_sha is None:
        fail("--candidate-sha is required when verifying acceptance")
    require_hex(candidate_sha, HEX40, "candidate SHA")
    if activation:
        for name, value in gate_values.items():
            if value.get("status") != "accepted":
                fail(f"activation requires accepted gate: {name}")
            if value.get("candidateCommit") != candidate_sha:
                fail(f"acceptance gate {name} is not bound to the candidate")
            require_hex(value.get("receiptSha256"), HEX64, f"{name}.receiptSha256")
            actor = value.get("actor")
            if not isinstance(actor, str) or not actor:
                fail(f"acceptance gate {name} requires an actor")
        source_actor = state.get("sourceAuthor")
        semantic_actor = gate_values["independentSemanticReview"].get("actor")
        if source_actor and semantic_actor == source_actor:
            fail("independent semantic reviewer cannot be the source author")
    if release and gate_values["canary"].get("status") != "accepted":
        fail("release requires an accepted canary")


def verify_state(args: argparse.Namespace) -> int:
    policy = read_json(Path(args.policy))
    state = read_json(Path(args.state))
    verify_acceptance_state(
        policy,
        state,
        args.candidate_sha,
        require_inactive=args.require_inactive,
    )
    print(
        "PASS_HEPTA_KG_ACCEPTANCE_STATE "
        f"inactive={str(args.require_inactive).lower()}"
    )
    return 0


def fake_fixture(policy: dict[str, Any]) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    raw = b"knowledge.graph target-host self-test\n"
    workload = policy["workload"]
    evidence = {
        "schema": EVIDENCE_SCHEMA,
        "sourceCommit": "1" * 40,
        "sourceTree": "2" * 40,
        "hostProfileId": policy["profileId"],
        "buildProfile": "release",
        "nextestProfile": "knowledge-graph-measurement",
        "rawLogSha256": sha256_bytes(raw),
        "selectedRuntimeWriter": policy["writer"]["selectedRuntimeWriter"],
        "incrementalPromoted": True,
        "fullRebuildOracleInterval": policy["writer"][
            "fullRebuildOracleInterval"
        ],
        "remainingWriterScaleBoundary": policy["writer"][
            "remainingScaleBoundary"
        ],
        "parameters": {
            "writes": workload["writes"],
            "querySamples": workload["querySamples"],
            "reopenSamples": workload["reopenSamples"],
            "contentionReaders": workload["contentionReaders"],
            "contentionRounds": workload["contentionRounds"],
        },
        "benchmark": {
            "writes": workload["writes"],
            "querySamples": workload["querySamples"],
            "reopenSamples": workload["reopenSamples"],
            "logicalNodes": workload["logicalNodes"],
            "logicalEdges": workload["logicalEdges"],
            "mutationNs": {"p50": 1, "p95": 2, "p99": 3},
            "queryNs": {"p50": 1, "p95": 2, "p99": 3},
            "reopenNs": {"p50": 1, "p95": 2, "p99": 3},
            "contention": {
                "writerNs": {"p50": 1, "p95": 2, "p99": 3},
                "readerNs": {"p50": 1, "p95": 2, "p99": 3},
            },
            "storage": {"databaseBytes": 4096, "walBytes": 0},
            "process": {"peakRssKiB": 1},
        },
        "interpretation": {
            "exactSourceBound": True,
            "namedTargetHostProfileMeasured": True,
            "sharedGithubHostedRunnerIsNotTargetHostEvidence": True,
            "measurementDoesNotGrantActivation": True,
            "measurementDoesNotGrantAcceptance": True,
            "measurementDoesNotGrantRelease": True,
        },
    }
    runner = {
        "runnerName": policy["targetHost"]["runnerName"],
        "runnerOs": policy["targetHost"]["runnerOs"],
        "runnerArch": policy["targetHost"]["runnerArch"],
        "labels": policy["targetHost"]["requiredLabels"],
        "githubRef": policy["targetHost"]["sourceRef"],
        "githubSha": "1" * 40,
        "eventName": "push",
        "exclusiveOwnerFence": True,
    }
    return evidence, raw, runner


def self_test() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        policy = {
            "schema": POLICY_SCHEMA,
            "profileId": "self-test",
            "targetHost": {
                "runnerName": "rog",
                "requiredLabels": ["self-hosted", "linux", "x64", "rog"],
                "runnerOs": "Linux",
                "runnerArch": "X64",
                "exclusiveRunRequired": True,
                "sharedGithubHostedRunnerForbidden": True,
                "sourceRef": "refs/heads/main",
            },
            "workload": {
                "writes": 256,
                "querySamples": 100,
                "reopenSamples": 20,
                "contentionReaders": 8,
                "contentionRounds": 20,
                "logicalNodes": 4096,
                "logicalEdges": 32768,
            },
            "budgets": {
                "mutationP95Ns": 10,
                "mutationP99Ns": 10,
                "queryP95Ns": 10,
                "queryP99Ns": 10,
                "reopenP95Ns": 10,
                "reopenP99Ns": 10,
                "peakRssKiB": 10,
                "databaseAndWalBytes": 8192,
                "databaseGrowthPerMutationBytes": 64,
                "contentionWriterP95Ns": 10,
                "contentionWriterP99Ns": 10,
                "contentionReaderP95Ns": 10,
                "contentionReaderP99Ns": 10,
            },
            "writer": {
                "selectedRuntimeWriter": "incremental-delta-with-complete-cut-and-periodic-oracle",
                "fullRebuildOracleInterval": 64,
                "remainingScaleBoundary": "complete physical source-cut assembly and reopen digest scan",
            },
            "retention": {
                "targetHostArtifactsDays": 365,
                "releaseEvidenceDays": 2555,
                "hotGenerationReceiptsDays": 90,
                "rawLogsRequired": True,
                "structuredJsonRequired": True,
                "sha256ManifestRequired": True,
            },
            "checkpoint": {
                "onlineWalCheckpointGenerationInterval": 64,
                "onlineWalCheckpointBytes": 67108864,
                "mode": "PASSIVE",
                "maintenanceMode": "TRUNCATE",
                "maintenanceRequiresExclusiveOwnerFence": True,
            },
            "archive": {
                "generationInterval": 1024,
                "maximumWallClockHours": 24,
                "format": "content-addressed-immutable-bundle-v1",
                "requiredObjects": ["receipt"],
                "digest": "sha256",
                "appendOnly": True,
            },
            "externalGates": {
                "independentSemanticReviewRequired": True,
                "operatorAcceptanceRequired": True,
                "canaryRequired": True,
                "rollbackRehearsalRequired": True,
                "activationRequiresAll": True,
                "releaseRequiresActivation": True,
            },
        }
        evidence, raw, runner = fake_fixture(policy)
        admission, errors = evaluate_data(
            policy,
            evidence,
            raw,
            runner,
            "1" * 40,
            "2" * 40,
            policy_digest="3" * 64,
            evidence_digest="4" * 64,
            runner_digest="5" * 64,
        )
        if errors or admission["admitted"] is not True:
            fail(f"passing fixture was rejected: {errors}")
        evidence["benchmark"]["queryNs"]["p99"] = 11
        rejected, errors = evaluate_data(
            policy,
            evidence,
            raw,
            runner,
            "1" * 40,
            "2" * 40,
            policy_digest="3" * 64,
            evidence_digest="4" * 64,
            runner_digest="5" * 64,
        )
        if rejected["admitted"] is not False or not any(
            "queryP99Ns" in error for error in errors
        ):
            fail("over-budget fixture was not rejected")
        inactive_state = {
            "schema": ACCEPTANCE_SCHEMA,
            "sourceAuthor": "source-author",
            "targetHostAdmission": {"status": "pending"},
            "independentSemanticReview": {"status": "pending"},
            "operatorAcceptance": {"status": "pending"},
            "canary": {"status": "pending"},
            "rollbackRehearsal": {"status": "pending"},
            "activation": False,
            "release": False,
        }
        verify_acceptance_state(
            policy, inactive_state, None, require_inactive=True
        )
        inactive_state["activation"] = True
        try:
            verify_acceptance_state(
                policy, inactive_state, None, require_inactive=True
            )
        except GateError:
            pass
        else:
            fail("premature activation was not rejected")
    print("PASS_HEPTA_KG_PRODUCTION_GATE_SELF_TEST")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--policy", required=True)
    evaluate_parser.add_argument("--evidence", required=True)
    evaluate_parser.add_argument("--raw-log", required=True)
    evaluate_parser.add_argument("--runner-metadata", required=True)
    evaluate_parser.add_argument("--expected-sha", required=True)
    evaluate_parser.add_argument("--expected-tree", required=True)
    evaluate_parser.add_argument("--output", required=True)

    state_parser = subparsers.add_parser("verify-state")
    state_parser.add_argument("--policy", required=True)
    state_parser.add_argument("--state", required=True)
    state_parser.add_argument("--candidate-sha")
    state_parser.add_argument("--require-inactive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.command == "evaluate":
        return evaluate(args)
    if args.command == "verify-state":
        return verify_state(args)
    fail("a command is required")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as error:
        print(f"ERROR_HEPTA_KG_PRODUCTION_GATE {error}", file=sys.stderr)
        raise SystemExit(1)

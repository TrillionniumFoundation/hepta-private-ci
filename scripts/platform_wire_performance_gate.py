#!/usr/bin/env python3
"""Validate five frozen, paired performance paths; never issue deployment acceptance.

The benchmark/transport owner supplies the plan and raw measurements. A separate
registry freezes the only producer workflow, artifact name, plan digest and host
profile that may enter the protected intake. Digests bind inputs but do not prove
that an external benchmark was honestly executed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from typing import Any

from platform_wire_receipt_subject import unique_object

HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
WORKFLOW = re.compile(r"\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml")
ARTIFACT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
REGISTRY_SCHEMA = "hepta.platform-wire.performance-producers.v1"


def integer(value: Any, name: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def text(value: Any, name: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid {name}")
    return value.strip()


def digest(value: Any, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def p99(samples: list[int]) -> int:
    # Nearest-rank percentile, recomputed from retained observations.
    return sorted(samples)[(99 * len(samples) + 99) // 100 - 1]


def validate_registry(
    registry: Any,
    workflow_path: str,
    artifact_name: str,
    plan_digest: str,
    report: Any,
) -> dict[str, Any]:
    if not isinstance(registry, dict) or registry.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("invalid performance producer registry")
    if WORKFLOW.fullmatch(workflow_path) is None:
        raise ValueError("invalid selected producer workflow path")
    if ARTIFACT.fullmatch(artifact_name) is None:
        raise ValueError("invalid selected producer artifact name")
    digest(plan_digest, HEX64, "selected plan digest")
    producers = registry.get("producers")
    if not isinstance(producers, list) or len(producers) > 32:
        raise ValueError("performance producer registry must contain at most 32 entries")
    seen: set[tuple[str, str, str]] = set()
    matches: list[dict[str, Any]] = []
    for entry in producers:
        if not isinstance(entry, dict):
            raise ValueError("performance producer entry must be an object")
        path = entry.get("workflow_path")
        artifact = entry.get("artifact_name")
        plan = entry.get("plan_sha256")
        if not isinstance(path, str) or WORKFLOW.fullmatch(path) is None:
            raise ValueError("registered producer workflow path is invalid")
        if not isinstance(artifact, str) or ARTIFACT.fullmatch(artifact) is None:
            raise ValueError("registered producer artifact name is invalid")
        digest(plan, HEX64, "registered producer plan digest")
        key = (path, artifact, plan)
        if key in seen:
            raise ValueError("duplicate performance producer registration")
        seen.add(key)
        if type(entry.get("enabled")) is not bool:
            raise ValueError("performance producer enabled flag must be boolean")
        if entry.get("reference_transport") != "grpc":
            raise ValueError("registered reference transport must be gRPC")
        text(entry.get("host_profile"), "registered host profile", 128)
        text(entry.get("owner"), "registered producer owner", 128)
        if key == (workflow_path, artifact_name, plan_digest):
            matches.append(entry)
    if len(matches) != 1:
        raise ValueError("selected workflow/artifact/plan is not uniquely registered")
    selected = matches[0]
    if selected["enabled"] is not True:
        raise ValueError("selected performance producer is disabled")
    if not isinstance(report, dict):
        raise ValueError("paired report is not an object")
    if report.get("host_profile") != selected["host_profile"]:
        raise ValueError("paired report host profile differs from the registration")
    if report.get("reference_transport") != selected["reference_transport"]:
        raise ValueError("paired report reference transport differs from the registration")
    return {
        "workflow_path": selected["workflow_path"],
        "artifact_name": selected["artifact_name"],
        "plan_sha256": selected["plan_sha256"],
        "host_profile": selected["host_profile"],
        "reference_transport": selected["reference_transport"],
        "owner": selected["owner"],
    }


def validate(
    plan: Any,
    report: Any,
    source: str,
    plan_digest: str,
    expected_run_identity: str | None = None,
) -> list[dict[str, Any]]:
    digest(source, HEX40, "source SHA")
    digest(plan_digest, HEX64, "plan digest")
    if not isinstance(plan, dict) or plan.get("schema") != "hepta.platform-wire.performance-plan.v1":
        raise ValueError("invalid performance plan")
    paths = plan.get("paths")
    if not isinstance(paths, list) or len(paths) != 5:
        raise ValueError("exactly five frozen path definitions are required")
    minimum = integer(plan.get("minimum_samples"), "minimum_samples", 100)
    if minimum > 100000:
        raise ValueError("minimum_samples exceeds the bounded profile")
    definitions = {}
    for path in paths:
        if not isinstance(path, dict):
            raise ValueError("invalid path definition")
        name = path.get("path_id")
        if not isinstance(name, str) or not name or len(name) > 128 or name in definitions:
            raise ValueError("missing or duplicate path identity")
        definitions[name] = digest(path.get("workload_sha256"), HEX64, "workload digest")
    if not isinstance(report, dict) or report.get("schema") != "hepta.platform-wire.paired-measurements.v1":
        raise ValueError("invalid paired measurements")
    if report.get("source_sha") != source or report.get("plan_sha256") != plan_digest:
        raise ValueError("measurements do not bind the selected source and plan")
    if report.get("profile") != "release" or report.get("reference_transport") != "grpc":
        raise ValueError("release measurements against the reference gRPC transport required")
    for key in ("host_profile", "runner_identity", "toolchain", "run_identity"):
        text(report.get(key), f"paired measurement context: {key}", 1024)
    if expected_run_identity is not None and report.get("run_identity") != expected_run_identity:
        raise ValueError("paired report run identity differs from the selected producer run")
    rows = report.get("paths")
    if not isinstance(rows, list) or len(rows) != 5:
        raise ValueError("all five measured paths are required")
    seen = set()
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid measured path")
        name = row.get("path_id")
        if not isinstance(name, str) or name not in definitions or name in seen:
            raise ValueError("unexpected or duplicate measured path")
        seen.add(name)
        if row.get("workload_sha256") != definitions[name]:
            raise ValueError("candidate/reference workload drift")
        samples = {}
        sizes = {}
        artifacts = {}
        for side in ("candidate", "reference"):
            entry = row.get(side)
            if not isinstance(entry, dict):
                raise ValueError("missing benchmark side")
            artifacts[side] = digest(
                entry.get("artifact_sha256"), HEX64, "measured artifact digest"
            )
            sizes[side] = integer(entry.get("package_bytes"), "package_bytes")
            values = entry.get("latency_ns")
            if not isinstance(values, list) or not minimum <= len(values) <= 100000:
                raise ValueError("insufficient or excessive raw latency samples")
            for value in values:
                integer(value, "latency_ns")
            if integer(entry.get("completed_operations"), "completed_operations") != len(values):
                raise ValueError("missing or duplicated completed operation samples")
            if integer(entry.get("failed_operations"), "failed_operations", 0) != 0:
                raise ValueError("failed benchmark operations cannot qualify")
            samples[side] = values
        if artifacts["candidate"] == artifacts["reference"]:
            raise ValueError("candidate and gRPC reference must be distinct measured artifacts")
        if len(samples["candidate"]) != len(samples["reference"]):
            raise ValueError("candidate and reference sample counts differ")
        candidate_p99, reference_p99 = p99(samples["candidate"]), p99(samples["reference"])
        # Exact integer comparisons preserve the specified gates without rounding.
        if sizes["candidate"] * 100 > sizes["reference"] * 70:
            raise ValueError(f"{name}: package-size ratio exceeds 0.70")
        if candidate_p99 * 100 > reference_p99 * 80:
            raise ValueError(f"{name}: p99 ratio exceeds 0.80")
        result.append({
            "path_id": name,
            "sample_count": len(samples["candidate"]),
            "candidate_package_bytes": sizes["candidate"],
            "reference_package_bytes": sizes["reference"],
            "candidate_p99_ns": candidate_p99,
            "reference_p99_ns": reference_p99,
        })
    return result


def read_json(path: Path, limit: int) -> tuple[Any, str]:
    if path.is_symlink():
        raise ValueError("symlinked performance input rejected")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("performance input exceeds its byte limit")
    return json.loads(raw, object_pairs_hook=unique_object), hashlib.sha256(raw).hexdigest()


def fixture() -> tuple[dict, dict]:
    """Synthetic validator-only fixture; these are not registered product paths."""
    paths = [{"path_id": f"fixture-{i}", "workload_sha256": str(i) * 64} for i in range(5)]
    plan = {
        "schema": "hepta.platform-wire.performance-plan.v1",
        "minimum_samples": 100,
        "paths": paths,
    }
    report = {
        "schema": "hepta.platform-wire.paired-measurements.v1",
        "source_sha": "a" * 40,
        "plan_sha256": "b" * 64,
        "profile": "release",
        "reference_transport": "grpc",
        "host_profile": "fixture-host",
        "runner_identity": "fixture-runner",
        "toolchain": "fixture-toolchain",
        "run_identity": "github-actions:example/repo:7:1",
        "paths": [],
    }
    for path in paths:
        row = dict(path)
        for side, artifact, size, latency in (
            ("candidate", "c" * 64, 70, 80),
            ("reference", "d" * 64, 100, 100),
        ):
            row[side] = {
                "artifact_sha256": artifact,
                "package_bytes": size,
                "latency_ns": [latency] * 100,
                "completed_operations": 100,
                "failed_operations": 0,
            }
        report["paths"].append(row)
    return plan, report


def registry_fixture(enabled: bool = True) -> dict[str, Any]:
    return {
        "schema": REGISTRY_SCHEMA,
        "producers": [{
            "workflow_path": ".github/workflows/registered-five-path.yml",
            "artifact_name": "platform-wire-five-path",
            "plan_sha256": "b" * 64,
            "host_profile": "fixture-host",
            "reference_transport": "grpc",
            "owner": "performance-owner",
            "enabled": enabled,
        }],
    }


class PerformanceGateTests(unittest.TestCase):
    def test_exact_thresholds_pass(self):
        plan, report = fixture()
        self.assertEqual(
            len(validate(plan, report, "a" * 40, "b" * 64, report["run_identity"])),
            5,
        )

    def test_registered_producer_is_required(self):
        _, report = fixture()
        selected = validate_registry(
            registry_fixture(),
            ".github/workflows/registered-five-path.yml",
            "platform-wire-five-path",
            "b" * 64,
            report,
        )
        self.assertEqual(selected["owner"], "performance-owner")
        for registry in (
            {"schema": REGISTRY_SCHEMA, "producers": []},
            registry_fixture(enabled=False),
        ):
            with self.assertRaises(ValueError):
                validate_registry(
                    registry,
                    ".github/workflows/registered-five-path.yml",
                    "platform-wire-five-path",
                    "b" * 64,
                    report,
                )

    def test_registry_rejects_duplicate_or_context_drift(self):
        _, report = fixture()
        duplicate = registry_fixture()
        duplicate["producers"].append(copy.deepcopy(duplicate["producers"][0]))
        with self.assertRaises(ValueError):
            validate_registry(
                duplicate,
                ".github/workflows/registered-five-path.yml",
                "platform-wire-five-path",
                "b" * 64,
                report,
            )
        report["host_profile"] = "other-host"
        with self.assertRaises(ValueError):
            validate_registry(
                registry_fixture(),
                ".github/workflows/registered-five-path.yml",
                "platform-wire-five-path",
                "b" * 64,
                report,
            )

    def test_one_path_cannot_be_hidden_by_an_average(self):
        for field, value in (("package_bytes", 71), ("latency_ns", [81] * 100)):
            plan, report = fixture()
            report["paths"][4]["candidate"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(plan, report, "a" * 40, "b" * 64)

    def test_missing_duplicate_or_foreign_paths_reject(self):
        for mode in ("missing", "duplicate", "foreign"):
            plan, report = fixture()
            if mode == "missing":
                report["paths"].pop()
            elif mode == "duplicate":
                report["paths"][4] = copy.deepcopy(report["paths"][0])
            else:
                report["paths"][4]["path_id"] = "not-frozen"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate(plan, report, "a" * 40, "b" * 64)

    def test_source_plan_workload_or_run_drift_rejects(self):
        for field in ("source_sha", "plan_sha256", "workload_sha256", "run_identity"):
            plan, report = fixture()
            if field == "workload_sha256":
                report["paths"][0][field] = "f" * 64
            elif field == "run_identity":
                report[field] = "other-run"
            else:
                report[field] = "f" * 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(
                    plan,
                    report,
                    "a" * 40,
                    "b" * 64,
                    "github-actions:example/repo:7:1",
                )

    def test_candidate_and_reference_artifacts_must_differ(self):
        plan, report = fixture()
        report["paths"][0]["reference"]["artifact_sha256"] = (
            report["paths"][0]["candidate"]["artifact_sha256"]
        )
        with self.assertRaises(ValueError):
            validate(plan, report, "a" * 40, "b" * 64)

    def test_invalid_samples_reject(self):
        for value in (0, -1, True, 1.0, None):
            plan, report = fixture()
            report["paths"][0]["candidate"]["latency_ns"][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(plan, report, "a" * 40, "b" * 64)

    def test_missing_failed_or_mismatched_operations_reject(self):
        for field, value in (
            ("completed_operations", 99),
            ("failed_operations", 1),
            ("latency_ns", [80] * 99),
        ):
            plan, report = fixture()
            report["paths"][0]["candidate"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(plan, report, "a" * 40, "b" * 64)

    def test_cloud_microbenchmark_cannot_substitute_for_paired_context(self):
        for field in (
            "host_profile",
            "runner_identity",
            "toolchain",
            "run_identity",
            "reference_transport",
            "profile",
        ):
            plan, report = fixture()
            report.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(plan, report, "a" * 40, "b" * 64)

    def test_p99_is_recomputed_from_raw_samples(self):
        self.assertEqual(p99([1] * 98 + [80, 9999]), 80)
        self.assertEqual(p99([1] * 99 + [80, 9999]), 80)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--producer-workflow-path")
    parser.add_argument("--artifact-name")
    parser.add_argument("--producer-run-identity")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-sha")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(PerformanceGateTests)
        )
        return 0 if result.wasSuccessful() else 1
    required = (
        args.registry,
        args.producer_workflow_path,
        args.artifact_name,
        args.producer_run_identity,
        args.plan,
        args.plan_sha256,
        args.report,
        args.source_sha,
    )
    if not all(required):
        parser.error(
            "a registered producer, exact run identity, frozen plan, paired report "
            "and source SHA are required"
        )
    try:
        registry, registry_digest = read_json(args.registry, 256 * 1024)
        plan, plan_digest = read_json(args.plan, 256 * 1024)
        if plan_digest != args.plan_sha256:
            raise ValueError("frozen plan bytes do not match the selected digest")
        report, report_digest = read_json(args.report, 16 * 1024 * 1024)
        registration = validate_registry(
            registry,
            args.producer_workflow_path,
            args.artifact_name,
            plan_digest,
            report,
        )
        result = validate(
            plan,
            report,
            args.source_sha,
            plan_digest,
            args.producer_run_identity,
        )
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"five-path measurements rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "schema": "hepta.platform-wire.performance-check.v1",
        "source_sha": args.source_sha,
        "registry_sha256": registry_digest,
        "registration": registration,
        "producer_run_identity": args.producer_run_identity,
        "plan_sha256": plan_digest,
        "report_sha256": report_digest,
        "paths": result,
        "scope": (
            "registered paired-measurement validation, not independent benchmark "
            "provenance authentication or deployment acceptance"
        ),
        "independent_acceptance": False,
        "activation": False,
        "release": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

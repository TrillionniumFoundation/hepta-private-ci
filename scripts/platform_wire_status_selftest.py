"""Self-test fixtures for the platform.wire lifecycle renderer."""
from __future__ import annotations

import argparse
import copy
import json
import tempfile
from pathlib import Path

from platform_wire_status_receipts import (
    ACCEPT,
    ASSERTS,
    DESIGN,
    IMPL,
    PERF,
    PROD,
    PROD_METRICS,
    SCHEMA,
)


def fixtures(source: str) -> tuple[dict, dict]:
    paths = [
        {
            "path_id": f"p{index}",
            "sample_count": 100,
            "candidate_package_bytes": 70,
            "reference_package_bytes": 100,
            "candidate_p99_ns": 80,
            "reference_p99_ns": 100,
        }
        for index in range(5)
    ]
    performance = workflow_receipt(
        PERF,
        source,
        source,
        event="workflow_dispatch",
        environment="platform-wire-performance",
        measurement_run_id=7,
        measurement_workflow_path=".github/workflows/performance-producer.yml",
        measurement_artifact="performance-observations",
        measurement_artifact_digest="1" * 64,
        plan_sha256="2" * 64,
        report_sha256="3" * 64,
        host_profile="target-host-v1",
        runner_identity="runner-1",
        toolchain="rustc-1",
        measurement_run_identity="github-actions:o/r:7:1",
        reference_transport="grpc",
        path_count=5,
        size_ratio_numerator=70,
        size_ratio_denominator=100,
        p99_ratio_numerator=80,
        p99_ratio_denominator=100,
        paths=paths,
    )
    metrics = {
        "authenticated-ingress": {
            "authenticated_sessions": 2,
            "rejected_untrusted_peers": 2,
        },
        "gateway-provider-e2e": {
            "completed_operations": 2,
            "terminal_receipts": 2,
        },
        "bounded-pressure": {
            "max_connections_observed": 64,
            "connection_limit": 64,
            "max_transport_queue_bytes": 1024,
            "transport_queue_limit_bytes": 2048,
            "max_consumer_retained_bytes": 1024,
            "consumer_retained_limit_bytes": 2048,
            "max_active_fragment_bytes": 1024,
            "active_fragment_limit_bytes": 2048,
            "pressure_samples": 100,
            "max_rss_bytes": 4096,
        },
        "deadline-cancellation": {
            "deadline_cases": 2,
            "cancellation_cases": 2,
            "reconciled_indeterminate_cases": 1,
            "blind_retries": 0,
        },
        "reconnect-restart": {
            "reconnects": 2,
            "process_restarts": 1,
            "stale_session_rejections": 2,
        },
        "key-rotation-retirement": {
            "rotations": 2,
            "retired_session_rejections": 2,
        },
        "mixed-version-rolling": {
            "rolling_steps": 2,
            "downgrade_rejections": 2,
            "mixed_version_sessions": 2,
        },
        "canary-rollback": {
            "canary_windows": 2,
            "rollback_rehearsals": 1,
            "failed_rollbacks": 0,
        },
    }
    scenarios = [
        {
            "scenario_id": scenario,
            "attempts": 2,
            "completed_operations": 2,
            "unexpected_failures": 0,
            "assertion_count": ASSERTS[scenario],
            "artifact_sha256": f"{index:064x}",
            "log_sha256": f"{index + 8:064x}",
            "metrics": metrics[scenario],
        }
        for index, scenario in enumerate(PROD_METRICS, 1)
    ]
    production = workflow_receipt(
        PROD,
        source,
        source,
        event="workflow_dispatch",
        environment="platform-wire-production",
        observation_run_id=8,
        observation_workflow_path=".github/workflows/production-producer.yml",
        observation_artifact="production-observations",
        observation_artifact_digest="4" * 64,
        plan_sha256="5" * 64,
        report_sha256="6" * 64,
        candidate_artifact_sha256="7" * 64,
        gateway_artifact_sha256="8" * 64,
        provider_artifact_sha256="9" * 64,
        configuration_sha256="a" * 64,
        host_profile="target-host-v1",
        deployment_profile="production-v1",
        runner_identity="runner-1",
        toolchain="rustc-1",
        observation_run_identity="github-actions:o/r:8:1",
        deployment_id="deployment-1",
        scenario_count=8,
        transport={
            "network_scope": "cross-host",
            "peer_identity_scheme": "spiffe",
            "channel_binding": "tls-exporter",
            "key_provenance": "hsm-domain-1",
        },
        scenarios=scenarios,
    )
    return performance, production


def workflow_receipt(kind: str, source: str, tested: str, **extra: object) -> dict:
    payload = {
        "schema": SCHEMA,
        "kind": kind,
        "source_sha": source,
        "tested_sha": tested,
        "status": "passed",
        "workflow": "fixture",
        "workflow_ref": "fixture@main",
        "run_id": 1,
        "run_attempt": 1,
        "event": "pull_request",
        "generated_at": "2026-09-29T00:00:00Z",
    }
    payload.update(extra)
    return payload


def acceptance_receipt(kind: str, source: str, approver: str) -> dict:
    return {
        "schema": SCHEMA,
        "kind": kind,
        "source_sha": source,
        "tested_sha": source,
        "status": "accepted",
        "approver": approver,
        "approver_role": ACCEPT[kind],
        "implementation_author": "implementation-author",
        "approved_at": "2026-09-29T00:00:00Z",
        "evidence_url": "https://github.com/o/r/pull/1",
    }


def run(evaluate) -> None:
    source = "a" * 40
    base = "c" * 40
    merge = "b" * 40
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name in DESIGN + IMPL:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")

        performance, production = fixtures(source)
        data = {
            "exact": workflow_receipt(
                "platform-wire-exact-head",
                source,
                source,
                base_sha=base,
                lane="source-head",
            ),
            "merge": workflow_receipt(
                "platform-wire-synthetic-merge",
                source,
                merge,
                base_sha=base,
                lane="synthetic-merge",
            ),
            "target": workflow_receipt(
                "platform-wire-target-host",
                source,
                source,
                event="workflow_dispatch",
                environment="platform-wire-target-host",
                host_profile="target-host-v1",
                runner_name="runner-1",
                runner_os="Linux",
                runner_arch="X64",
            ),
            "performance": performance,
            "production": production,
            "reviewer": acceptance_receipt(
                "platform-wire-reviewer-acceptance", source, "reviewer"
            ),
            "operations": acceptance_receipt(
                "platform-wire-operations-acceptance", source, "operator"
            ),
            "release": {
                "schema": SCHEMA,
                "kind": "platform-wire-release",
                "source_sha": source,
                "tested_sha": source,
                "status": "released",
                "release_id": "release-v1",
                "artifact_digest": "d" * 64,
                "approved_by": "release-operator",
                "evidence_url": "https://github.com/o/r/releases/tag/release-v1",
            },
        }

        paths: dict[str, str] = {}

        def write(name: str) -> None:
            path = root / f"{name}.json"
            path.write_text(json.dumps(data[name]), encoding="utf-8")
            paths[name] = str(path)

        for name in data:
            write(name)

        args = argparse.Namespace(
            root=str(root),
            expected_source_sha=source,
            exact_head=paths["exact"],
            synthetic_merge=paths["merge"],
            target_host=paths["target"],
            performance=paths["performance"],
            production=paths["production"],
            reviewer_acceptance=paths["reviewer"],
            operations_acceptance=paths["operations"],
            release=paths["release"],
        )

        if not all(evaluate(args)["states"].values()):
            raise AssertionError("complete current-source evidence must release")

        args.performance = None
        if evaluate(args)["states"]["accepted"]:
            raise AssertionError("performance evidence must gate acceptance")
        args.performance = paths["performance"]

        args.production = None
        if evaluate(args)["states"]["accepted"]:
            raise AssertionError("production evidence must gate acceptance")
        args.production = paths["production"]

        original_approver = data["operations"]["approver"]
        data["operations"]["approver"] = data["reviewer"]["approver"]
        write("operations")
        if evaluate(args)["states"]["accepted"]:
            raise AssertionError("reviewer and operations identities must be distinct")
        data["operations"]["approver"] = original_approver
        write("operations")

        original_size = data["performance"]["paths"][0]["candidate_package_bytes"]
        data["performance"]["paths"][0]["candidate_package_bytes"] = 71
        write("performance")
        try:
            evaluate(args)
        except ValueError:
            pass
        else:
            raise AssertionError("over-threshold performance must fail closed")
        data["performance"]["paths"][0]["candidate_package_bytes"] = original_size
        write("performance")

        data["production"]["scenarios"][0]["unexpected_failures"] = 1
        write("production")
        try:
            evaluate(args)
        except ValueError:
            pass
        else:
            raise AssertionError("failed production scenario must fail closed")
        data["production"]["scenarios"][0]["unexpected_failures"] = 0
        write("production")

        mismatched = copy.deepcopy(data["production"])
        mismatched["source_sha"] = "f" * 40
        data["production"] = mismatched
        write("production")
        try:
            evaluate(args)
        except ValueError:
            pass
        else:
            raise AssertionError("cross-source evidence must fail closed")

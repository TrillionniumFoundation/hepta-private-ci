#!/usr/bin/env python3
"""Render fail-closed platform.wire lifecycle state from source-bound receipts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_wire_receipt_subject import require_selected_source
from platform_wire_status_receipts import (
    ACCEPT,
    DESIGN,
    FUZZ,
    IMPL,
    PERF,
    PROD,
    SCHEMA,
    WORK,
    load,
)


def evaluate(args):
    root = Path(args.root).resolve()
    missing_design = [path for path in DESIGN if not (root / path).is_file()]
    missing_implementation = [path for path in IMPL if not (root / path).is_file()]

    exact = load(args.exact_head, "platform-wire-exact-head")
    merge = load(args.synthetic_merge, "platform-wire-synthetic-merge")
    target = load(args.target_host, "platform-wire-target-host")
    fuzz = load(args.fuzz, FUZZ)
    performance = load(args.performance, PERF)
    production = load(args.production, PROD)
    reviewer = load(
        args.reviewer_acceptance, "platform-wire-reviewer-acceptance"
    )
    operations = load(
        args.operations_acceptance, "platform-wire-operations-acceptance"
    )
    release = load(args.release, "platform-wire-release")

    receipts = [
        receipt
        for receipt in (
            exact,
            merge,
            target,
            fuzz,
            performance,
            production,
            reviewer,
            operations,
            release,
        )
        if receipt
    ]
    sources = {receipt["source_sha"] for receipt in receipts}
    if len(sources) > 1:
        raise ValueError("receipt source disagreement")
    source = next(iter(sources), None)
    if source:
        require_selected_source(
            root,
            source,
            getattr(args, "expected_source_sha", None),
        )

    designed = not missing_design
    implemented = designed and not missing_implementation
    qualified = implemented and all(
        receipt and receipt["passed"]
        for receipt in (exact, merge, target, fuzz)
    )
    distinct_approvers = (
        reviewer
        and operations
        and reviewer["approver"]
        and operations["approver"]
        and reviewer["approver"].casefold()
        != operations["approver"].casefold()
    )
    accepted = bool(
        qualified
        and performance
        and performance["passed"]
        and production
        and production["passed"]
        and reviewer
        and reviewer["passed"]
        and operations
        and operations["passed"]
        and distinct_approvers
    )
    released = bool(accepted and release and release["passed"])

    def evidence_state(receipt):
        if not receipt:
            return None
        output = {
            key: receipt[key]
            for key in (
                "kind",
                "source_sha",
                "tested_sha",
                "status",
                "passed",
                "path",
            )
        }
        payload = receipt["payload"]
        for name in (
            "run_id",
            "run_attempt",
            "workflow",
            "workflow_ref",
            "lane",
            "base_sha",
            "environment",
            "host_profile",
            "deployment_profile",
            "runner_name",
            "runner_os",
            "runner_arch",
            "measurement_run_id",
            "measurement_workflow_path",
            "measurement_artifact",
            "measurement_artifact_digest",
            "observation_run_id",
            "observation_workflow_path",
            "observation_artifact",
            "observation_artifact_digest",
            "plan_sha256",
            "report_sha256",
            "path_count",
            "scenario_count",
            "deployment_id",
            "approver",
            "approver_role",
            "approved_at",
            "release_id",
            "artifact_digest",
            "evidence_url",
            "duration_seconds",
            "engine",
            "sanitizer",
            "toolchain",
            "cargo_fuzz_version",
        ):
            if name in payload:
                output[name] = payload[name]
        if receipt["kind"] == FUZZ:
            output["targets"] = sorted(payload["targets"])
        output["schema"] = payload.get("schema", SCHEMA)
        return output

    return {
        "schema": "hepta.platform-wire.status.v2",
        "source_sha": source,
        "states": {
            "designed": designed,
            "implemented": implemented,
            "qualified": qualified,
            "accepted": accepted,
            "released": released,
        },
        "missing": {
            "design": missing_design,
            "implementation": missing_implementation,
        },
        "evidence": {
            "exact_head": evidence_state(exact),
            "synthetic_merge": evidence_state(merge),
            "target_host": evidence_state(target),
            "fuzz_campaign": evidence_state(fuzz),
            "performance": evidence_state(performance),
            "production": evidence_state(production),
            "reviewer_acceptance": evidence_state(reviewer),
            "operations_acceptance": evidence_state(operations),
            "release": evidence_state(release),
        },
    }


def markdown(status):
    states = status["states"]
    lines = [
        "# platform.wire evidence-derived lifecycle status",
        "",
        "This file is generated by `scripts/platform_wire_status.py`; do not edit lifecycle booleans by hand.",
        "",
        "| State | Value | Derivation |",
        "|---|---:|---|",
        f"| Designed | `{'true' if states['designed'] else 'false'}` | repository design/document closure |",
        f"| Implemented | `{'true' if states['implemented'] else 'false'}` | required native source closure |",
        f"| Qualified | `{'true' if states['qualified'] else 'false'}` | exact-head + synthetic-merge + protected target-host + exact-source three-target libFuzzer campaign receipts |",
        f"| Accepted | `{'true' if states['accepted'] else 'false'}` | qualified state + passed five-path performance and production-composition receipts + distinct independent reviewer and operations receipts |",
        f"| Released | `{'true' if states['released'] else 'false'}` | accepted state + release receipt |",
        "",
        "## Evidence inputs",
        "",
    ]
    for name, receipt in status["evidence"].items():
        if receipt is None:
            lines.append(f"- `{name}`: absent")
        else:
            lines.append(
                f"- `{name}`: `{receipt['status']}`; "
                f"source `{receipt['source_sha']}`; tested `{receipt['tested_sha']}`"
            )
    lines += [
        "",
        "The protected fuzz, performance and production-composition contracts are documented in "
        "[SECURITY_AND_QUALIFICATION.md](SECURITY_AND_QUALIFICATION.md), "
        "[PERFORMANCE_INTAKE_20260929.md](PERFORMANCE_INTAKE_20260929.md) and "
        "[PRODUCTION_INTAKE_20260929.md](PRODUCTION_INTAKE_20260929.md).",
        "",
        "Absent, malformed, failing or source-inconsistent receipts fail closed. "
        "Qualified requires all three bounded libFuzzer targets to execute and pass on the exact source SHA. "
        "Accepted/Released additionally require both the five-path paired performance receipt and the "
        "eight-scenario production-composition receipt. Reviewer and operations acceptance must be issued "
        "by distinct identities independent of the implementation author; source code and ordinary CI "
        "cannot self-attest either receipt.",
        "",
    ]
    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="cmd", required=True)

    render = commands.add_parser("render")
    render.add_argument("--root", default=".")
    render.add_argument("--expected-source-sha")
    for name in (
        "exact-head",
        "synthetic-merge",
        "target-host",
        "fuzz",
        "performance",
        "production",
        "reviewer-acceptance",
        "operations-acceptance",
        "release",
    ):
        render.add_argument("--" + name)
    render.add_argument("--format", choices=("json", "markdown"), required=True)
    render.add_argument("--output", required=True)

    check = commands.add_parser("check-doc")
    check.add_argument("--root", default=".")
    check.add_argument(
        "--document",
        default="docs/modules/platform.wire/STATUS.md",
    )

    validate = commands.add_parser("validate-receipt")
    validate.add_argument("--path", required=True)
    validate.add_argument(
        "--kind",
        required=True,
        choices=sorted(WORK | set(ACCEPT) | {FUZZ, "platform-wire-release"}),
    )

    commands.add_parser("self-test")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.cmd == "self-test":
        from platform_wire_status_selftest import run

        run(evaluate)
        return 0
    if args.cmd == "validate-receipt":
        load(args.path, args.kind)
        return 0
    if args.cmd == "render":
        status = evaluate(args)
        output = (
            json.dumps(status, indent=2, sort_keys=True) + "\n"
            if args.format == "json"
            else markdown(status)
        )
        Path(args.output).write_text(output)
        return 0

    empty = argparse.Namespace(
        root=args.root,
        expected_source_sha=None,
        exact_head=None,
        synthetic_merge=None,
        target_host=None,
        fuzz=None,
        performance=None,
        production=None,
        reviewer_acceptance=None,
        operations_acceptance=None,
        release=None,
    )
    expected = markdown(evaluate(empty))
    actual = (Path(args.root) / args.document).read_text()
    if actual != expected:
        raise SystemExit(
            f"{args.document} is stale; regenerate it with platform_wire_status.py"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

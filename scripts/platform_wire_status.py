#!/usr/bin/env python3
"""Render platform.wire lifecycle status from source and evidence receipts."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA = "hepta.platform-wire.receipt.v2"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
PASS_VALUES = {"pass", "passed", "success", "qualified", "accepted", "released"}

DESIGN_FILES = (
    "docs/modules/platform.wire/TECHNICAL.md",
    "docs/lane-a-foundation/platform.wire/WIRE_V1.md",
    "docs/lane-a-foundation/platform.wire/WIRE_V2.md",
    "docs/lane-a-foundation/platform.wire/NEGOTIATION_V1.md",
    "docs/modules/platform.wire/SECURITY_AND_QUALIFICATION.md",
)
IMPLEMENTATION_FILES = (
    "codex-rs/hepta-wire/src/envelope.rs",
    "codex-rs/hepta-wire/src/envelope_v2.rs",
    "codex-rs/hepta-wire/src/frame.rs",
    "codex-rs/hepta-wire/src/frame_header.rs",
    "codex-rs/hepta-wire/src/version.rs",
    "codex-rs/hepta-wire/src/session.rs",
    "codex-rs/hepta-wire/src/stream.rs",
    "codex-rs/hepta-wire/src/schema.rs",
    "codex-rs/hepta-wire/src/registry.rs",
    "codex-rs/hepta-wire/src/secure_session.rs",
    "codex-rs/hepta-wire/src/directional_session.rs",
)
WORKFLOW_RECEIPT_KINDS = {
    "platform-wire-exact-head",
    "platform-wire-synthetic-merge",
    "platform-wire-target-host",
}
ACCEPTANCE_KINDS = {
    "platform-wire-reviewer-acceptance": "independent-reviewer",
    "platform-wire-operations-acceptance": "operations",
}


@dataclass(frozen=True)
class Receipt:
    kind: str
    source_sha: str
    tested_sha: str
    status: str
    path: str
    payload: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status.lower() in PASS_VALUES

    @property
    def approver(self) -> str | None:
        value = self.payload.get("approver")
        return value if isinstance(value, str) and value else None


def require_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"receipt field {field!r} must be a non-empty string")
    return value.strip()


def require_sha(payload: dict[str, Any], field: str) -> str:
    value = require_string(payload, field)
    if SHA_RE.fullmatch(value) is None:
        raise ValueError(f"receipt field {field!r} is not a lowercase 40-hex SHA")
    return value


def require_positive_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"receipt field {field!r} must be a positive integer")
    return value


def validate_workflow_receipt(payload: dict[str, Any], kind: str) -> None:
    require_string(payload, "workflow")
    require_string(payload, "workflow_ref")
    require_positive_int(payload, "run_id")
    require_positive_int(payload, "run_attempt")
    require_string(payload, "event")
    require_string(payload, "generated_at")

    source_sha = require_sha(payload, "source_sha")
    tested_sha = require_sha(payload, "tested_sha")
    if kind == "platform-wire-exact-head":
        require_sha(payload, "base_sha")
        if require_string(payload, "lane") != "source-head":
            raise ValueError("exact-head receipt lane must be 'source-head'")
        if tested_sha != source_sha:
            raise ValueError("exact-head receipt must test its exact source SHA")
    elif kind == "platform-wire-synthetic-merge":
        require_sha(payload, "base_sha")
        if require_string(payload, "lane") != "synthetic-merge":
            raise ValueError("synthetic-merge receipt lane must be 'synthetic-merge'")
        if tested_sha == source_sha:
            raise ValueError("synthetic-merge receipt must identify a distinct merge commit")
    elif kind == "platform-wire-target-host":
        if tested_sha != source_sha:
            raise ValueError("target-host receipt must test its exact source SHA")
        if require_string(payload, "event") != "workflow_dispatch":
            raise ValueError("target-host receipt must come from workflow_dispatch")
        if require_string(payload, "environment") != "platform-wire-target-host":
            raise ValueError(
                "target-host receipt must name the protected platform-wire-target-host environment"
            )
        require_string(payload, "host_profile")
        require_string(payload, "runner_name")
        require_string(payload, "runner_os")
        require_string(payload, "runner_arch")


def validate_acceptance_receipt(payload: dict[str, Any], kind: str) -> None:
    source_sha = require_sha(payload, "source_sha")
    tested_sha = require_sha(payload, "tested_sha")
    if source_sha != tested_sha:
        raise ValueError("acceptance receipt must bind the exact reviewed source SHA")
    approver = require_string(payload, "approver")
    implementation_author = require_string(payload, "implementation_author")
    expected_role = ACCEPTANCE_KINDS[kind]
    if require_string(payload, "approver_role") != expected_role:
        raise ValueError(f"{kind} approver_role must be {expected_role!r}")
    if approver.casefold() == implementation_author.casefold():
        raise ValueError("acceptance approver must be independent of implementation author")
    require_string(payload, "approved_at")
    evidence_url = require_string(payload, "evidence_url")
    if not evidence_url.startswith("https://github.com/"):
        raise ValueError("acceptance evidence_url must be an HTTPS GitHub URL")


def validate_release_receipt(payload: dict[str, Any]) -> None:
    source_sha = require_sha(payload, "source_sha")
    tested_sha = require_sha(payload, "tested_sha")
    if source_sha != tested_sha:
        raise ValueError("release receipt must bind the exact released source SHA")
    require_string(payload, "release_id")
    artifact_digest = require_string(payload, "artifact_digest")
    if DIGEST_RE.fullmatch(artifact_digest) is None:
        raise ValueError("release artifact_digest must be lowercase 64-hex")
    require_string(payload, "approved_by")
    evidence_url = require_string(payload, "evidence_url")
    if not evidence_url.startswith("https://github.com/"):
        raise ValueError("release evidence_url must be an HTTPS GitHub URL")


def load_receipt(path: str | None, expected_kind: str) -> Receipt | None:
    if not path:
        return None
    receipt_path = Path(path)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"receipt {receipt_path} must be a JSON object")
    if payload.get("schema") != RECEIPT_SCHEMA:
        raise ValueError(
            f"receipt {receipt_path} schema {payload.get('schema')!r} does not match {RECEIPT_SCHEMA!r}"
        )
    kind = require_string(payload, "kind")
    if kind != expected_kind:
        raise ValueError(
            f"receipt {receipt_path} kind {kind!r} does not match {expected_kind!r}"
        )
    source_sha = require_sha(payload, "source_sha")
    tested_sha = require_sha(payload, "tested_sha")
    status = require_string(payload, "status")

    if kind in WORKFLOW_RECEIPT_KINDS:
        validate_workflow_receipt(payload, kind)
    elif kind in ACCEPTANCE_KINDS:
        validate_acceptance_receipt(payload, kind)
    elif kind == "platform-wire-release":
        validate_release_receipt(payload)
    else:
        raise ValueError(f"unsupported receipt kind {kind!r}")

    return Receipt(kind, source_sha, tested_sha, status, str(receipt_path), payload)


def common_source_sha(receipts: list[Receipt | None]) -> str | None:
    present = [receipt for receipt in receipts if receipt is not None]
    if not present:
        return None
    source_shas = {receipt.source_sha for receipt in present}
    if len(source_shas) != 1:
        raise ValueError(f"evidence receipts disagree on source_sha: {sorted(source_shas)}")
    return present[0].source_sha


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    missing_design = [path for path in DESIGN_FILES if not (root / path).is_file()]
    missing_implementation = [
        path for path in IMPLEMENTATION_FILES if not (root / path).is_file()
    ]
    exact = load_receipt(args.exact_head, "platform-wire-exact-head")
    merge = load_receipt(args.synthetic_merge, "platform-wire-synthetic-merge")
    target = load_receipt(args.target_host, "platform-wire-target-host")
    reviewer = load_receipt(
        args.reviewer_acceptance, "platform-wire-reviewer-acceptance"
    )
    operations = load_receipt(
        args.operations_acceptance, "platform-wire-operations-acceptance"
    )
    release = load_receipt(args.release, "platform-wire-release")
    all_receipts = [exact, merge, target, reviewer, operations, release]
    source_sha = common_source_sha(all_receipts)

    designed = not missing_design
    implemented = designed and not missing_implementation
    qualification_receipts = [exact, merge, target]
    qualified = implemented and all(
        receipt is not None and receipt.passed for receipt in qualification_receipts
    )
    distinct_acceptors = (
        reviewer is not None
        and operations is not None
        and reviewer.approver is not None
        and operations.approver is not None
        and reviewer.approver.casefold() != operations.approver.casefold()
    )
    accepted = (
        qualified
        and reviewer is not None
        and reviewer.passed
        and operations is not None
        and operations.passed
        and distinct_acceptors
    )
    released = accepted and release is not None and release.passed

    def receipt_state(receipt: Receipt | None) -> dict[str, Any] | None:
        if receipt is None:
            return None
        state: dict[str, Any] = {
            "kind": receipt.kind,
            "schema": RECEIPT_SCHEMA,
            "source_sha": receipt.source_sha,
            "tested_sha": receipt.tested_sha,
            "status": receipt.status,
            "passed": receipt.passed,
            "path": receipt.path,
        }
        for field in (
            "run_id",
            "run_attempt",
            "workflow",
            "workflow_ref",
            "lane",
            "base_sha",
            "host_profile",
            "runner_name",
            "runner_os",
            "runner_arch",
            "approver",
            "approver_role",
            "approved_at",
            "release_id",
            "artifact_digest",
            "evidence_url",
        ):
            if field in receipt.payload:
                state[field] = receipt.payload[field]
        return state

    return {
        "schema": "hepta.platform-wire.status.v2",
        "source_sha": source_sha,
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
            "exact_head": receipt_state(exact),
            "synthetic_merge": receipt_state(merge),
            "target_host": receipt_state(target),
            "reviewer_acceptance": receipt_state(reviewer),
            "operations_acceptance": receipt_state(operations),
            "release": receipt_state(release),
        },
    }


def render_markdown(status: dict[str, Any]) -> str:
    states = status["states"]
    evidence = status["evidence"]
    rows = [
        ("Designed", states["designed"], "repository design/document closure"),
        ("Implemented", states["implemented"], "required native source closure"),
        (
            "Qualified",
            states["qualified"],
            "exact-head + synthetic-merge + protected target-host receipts",
        ),
        (
            "Accepted",
            states["accepted"],
            "qualified state + distinct independent reviewer and operations receipts",
        ),
        ("Released", states["released"], "accepted state + release receipt"),
    ]
    lines = [
        "# platform.wire evidence-derived lifecycle status",
        "",
        "This file is generated by `scripts/platform_wire_status.py`; do not edit lifecycle booleans by hand.",
        "",
        "| State | Value | Derivation |",
        "|---|---:|---|",
    ]
    lines.extend(
        f"| {name} | `{'true' if value else 'false'}` | {derivation} |"
        for name, value, derivation in rows
    )
    lines.extend(["", "## Evidence inputs", ""])
    for name in (
        "exact_head",
        "synthetic_merge",
        "target_host",
        "reviewer_acceptance",
        "operations_acceptance",
        "release",
    ):
        receipt = evidence[name]
        if receipt is None:
            lines.append(f"- `{name}`: absent")
        else:
            lines.append(
                f"- `{name}`: `{receipt['status']}`; source `{receipt['source_sha']}`; tested `{receipt['tested_sha']}`"
            )
    lines.extend(
        [
            "",
            "Absent, malformed, failing or source-inconsistent receipts fail closed. Reviewer and operations acceptance must be issued by distinct identities independent of the implementation author; source code and ordinary CI cannot self-attest either receipt.",
            "",
        ]
    )
    return "\n".join(lines)


def write_output(path: str, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def workflow_receipt(kind: str, source: str, tested: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "kind": kind,
        "source_sha": source,
        "tested_sha": tested,
        "status": "passed",
        "workflow": "fixture",
        "workflow_ref": "fixture@refs/heads/main",
        "run_id": 1,
        "run_attempt": 1,
        "event": "pull_request",
        "generated_at": "2026-09-27T00:00:00Z",
    }
    payload.update(extra)
    return payload


def self_test() -> None:
    source = "a" * 40
    merge_sha = "b" * 40
    base_sha = "c" * 40
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for path in DESIGN_FILES + IMPLEMENTATION_FILES:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture\n", encoding="utf-8")

        payloads = {
            "platform-wire-exact-head": workflow_receipt(
                "platform-wire-exact-head",
                source,
                source,
                base_sha=base_sha,
                lane="source-head",
            ),
            "platform-wire-synthetic-merge": workflow_receipt(
                "platform-wire-synthetic-merge",
                source,
                merge_sha,
                base_sha=base_sha,
                lane="synthetic-merge",
            ),
            "platform-wire-target-host": workflow_receipt(
                "platform-wire-target-host",
                source,
                source,
                event="workflow_dispatch",
                environment="platform-wire-target-host",
                host_profile="hepta-target-host",
                runner_name="fixture-runner",
                runner_os="Linux",
                runner_arch="X64",
            ),
            "platform-wire-reviewer-acceptance": {
                "schema": RECEIPT_SCHEMA,
                "kind": "platform-wire-reviewer-acceptance",
                "source_sha": source,
                "tested_sha": source,
                "status": "accepted",
                "approver": "reviewer",
                "approver_role": "independent-reviewer",
                "implementation_author": "implementer",
                "approved_at": "2026-09-27T00:00:00Z",
                "evidence_url": "https://github.com/example/repo/pull/1",
            },
            "platform-wire-operations-acceptance": {
                "schema": RECEIPT_SCHEMA,
                "kind": "platform-wire-operations-acceptance",
                "source_sha": source,
                "tested_sha": source,
                "status": "accepted",
                "approver": "operator",
                "approver_role": "operations",
                "implementation_author": "implementer",
                "approved_at": "2026-09-27T00:00:00Z",
                "evidence_url": "https://github.com/example/repo/pull/1",
            },
            "platform-wire-release": {
                "schema": RECEIPT_SCHEMA,
                "kind": "platform-wire-release",
                "source_sha": source,
                "tested_sha": source,
                "status": "released",
                "release_id": "release-fixture",
                "artifact_digest": "d" * 64,
                "approved_by": "release-operator",
                "evidence_url": "https://github.com/example/repo/releases/tag/v1",
            },
        }
        receipt_paths: dict[str, str] = {}
        for kind, payload in payloads.items():
            path = root / f"{kind}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            receipt_paths[kind] = str(path)

        args = argparse.Namespace(
            root=str(root),
            exact_head=receipt_paths["platform-wire-exact-head"],
            synthetic_merge=receipt_paths["platform-wire-synthetic-merge"],
            target_host=receipt_paths["platform-wire-target-host"],
            reviewer_acceptance=receipt_paths[
                "platform-wire-reviewer-acceptance"
            ],
            operations_acceptance=receipt_paths[
                "platform-wire-operations-acceptance"
            ],
            release=receipt_paths["platform-wire-release"],
        )
        status = evaluate(args)
        if not all(status["states"].values()):
            raise AssertionError(status)

        payloads["platform-wire-operations-acceptance"]["approver"] = "reviewer"
        Path(receipt_paths["platform-wire-operations-acceptance"]).write_text(
            json.dumps(payloads["platform-wire-operations-acceptance"]),
            encoding="utf-8",
        )
        status = evaluate(args)
        if status["states"]["accepted"] or status["states"]["released"]:
            raise AssertionError("duplicate acceptance identities must fail closed")


def add_evidence_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".")
    parser.add_argument("--exact-head")
    parser.add_argument("--synthetic-merge")
    parser.add_argument("--target-host")
    parser.add_argument("--reviewer-acceptance")
    parser.add_argument("--operations-acceptance")
    parser.add_argument("--release")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render")
    add_evidence_arguments(render)
    render.add_argument("--format", choices=("json", "markdown"), required=True)
    render.add_argument("--output", required=True)
    check = subparsers.add_parser("check-doc")
    check.add_argument("--root", default=".")
    check.add_argument("--document", default="docs/modules/platform.wire/STATUS.md")
    validate = subparsers.add_parser("validate-receipt")
    validate.add_argument("--path", required=True)
    validate.add_argument(
        "--kind",
        required=True,
        choices=sorted(
            WORKFLOW_RECEIPT_KINDS
            | set(ACCEPTANCE_KINDS)
            | {"platform-wire-release"}
        ),
    )
    subparsers.add_parser("self-test")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "validate-receipt":
        load_receipt(args.path, args.kind)
        return 0
    if args.command == "render":
        status = evaluate(args)
        content = (
            json.dumps(status, indent=2, sort_keys=True) + "\n"
            if args.format == "json"
            else render_markdown(status)
        )
        write_output(args.output, content)
        return 0
    status_args = argparse.Namespace(
        root=args.root,
        exact_head=None,
        synthetic_merge=None,
        target_host=None,
        reviewer_acceptance=None,
        operations_acceptance=None,
        release=None,
    )
    expected = render_markdown(evaluate(status_args))
    actual = (Path(args.root) / args.document).read_text(encoding="utf-8")
    if actual != expected:
        raise SystemExit(
            f"{args.document} is stale; regenerate it with platform_wire_status.py"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

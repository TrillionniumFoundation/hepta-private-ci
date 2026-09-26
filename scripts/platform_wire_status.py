#!/usr/bin/env python3
"""Render platform.wire lifecycle status from source and evidence receipts."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    "codex-rs/hepta-wire/src/version.rs",
    "codex-rs/hepta-wire/src/session.rs",
    "codex-rs/hepta-wire/src/stream.rs",
    "codex-rs/hepta-wire/src/schema.rs",
    "codex-rs/hepta-wire/src/registry.rs",
    "codex-rs/hepta-wire/src/secure_session.rs",
)
PASS_VALUES = {"pass", "passed", "success", "qualified", "released"}


@dataclass(frozen=True)
class Receipt:
    kind: str
    source_sha: str
    tested_sha: str
    status: str
    path: str

    @property
    def passed(self) -> bool:
        return self.status.lower() in PASS_VALUES


def load_receipt(path: str | None, expected_kind: str) -> Receipt | None:
    if not path:
        return None
    receipt_path = Path(path)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    kind = str(payload.get("kind", ""))
    if kind != expected_kind:
        raise ValueError(
            f"receipt {receipt_path} kind {kind!r} does not match {expected_kind!r}"
        )
    source_sha = str(payload.get("source_sha", ""))
    tested_sha = str(payload.get("tested_sha", ""))
    status = str(payload.get("status", payload.get("conclusion", "")))
    if not source_sha or not tested_sha or not status:
        raise ValueError(f"receipt {receipt_path} lacks source_sha/tested_sha/status")
    return Receipt(kind, source_sha, tested_sha, status, str(receipt_path))


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
    release = load_receipt(args.release, "platform-wire-release")
    source_sha = common_source_sha([exact, merge, target, release])

    designed = not missing_design
    implemented = designed and not missing_implementation
    qualification_receipts = [exact, merge, target]
    qualified = implemented and all(
        receipt is not None and receipt.passed for receipt in qualification_receipts
    )
    released = qualified and release is not None and release.passed

    def receipt_state(receipt: Receipt | None) -> dict[str, Any] | None:
        if receipt is None:
            return None
        return {
            "kind": receipt.kind,
            "source_sha": receipt.source_sha,
            "tested_sha": receipt.tested_sha,
            "status": receipt.status,
            "passed": receipt.passed,
            "path": receipt.path,
        }

    return {
        "schema": "hepta.platform-wire.status.v1",
        "source_sha": source_sha,
        "states": {
            "designed": designed,
            "implemented": implemented,
            "qualified": qualified,
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
            "exact-head + synthetic-merge + target-host receipts",
        ),
        ("Released", states["released"], "qualified state + release receipt"),
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
    for name in ("exact_head", "synthetic_merge", "target_host", "release"):
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
            "Absent, malformed, failing or source-inconsistent receipts fail closed. Independent reviewer/operator acceptance and target-host execution cannot be self-attested by source code.",
            "",
        ]
    )
    return "\n".join(lines)


def write_output(path: str, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for path in DESIGN_FILES + IMPLEMENTATION_FILES:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture\n", encoding="utf-8")
        receipts = {}
        for kind in (
            "platform-wire-exact-head",
            "platform-wire-synthetic-merge",
            "platform-wire-target-host",
            "platform-wire-release",
        ):
            path = root / f"{kind}.json"
            path.write_text(
                json.dumps(
                    {
                        "kind": kind,
                        "source_sha": "source",
                        "tested_sha": f"tested-{kind}",
                        "status": "passed",
                    }
                ),
                encoding="utf-8",
            )
            receipts[kind] = str(path)
        args = argparse.Namespace(
            root=str(root),
            exact_head=receipts["platform-wire-exact-head"],
            synthetic_merge=receipts["platform-wire-synthetic-merge"],
            target_host=receipts["platform-wire-target-host"],
            release=receipts["platform-wire-release"],
        )
        status = evaluate(args)
        if not all(status["states"].values()):
            raise AssertionError(status)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    render = subparsers.add_parser("render")
    render.add_argument("--root", default=".")
    render.add_argument("--exact-head")
    render.add_argument("--synthetic-merge")
    render.add_argument("--target-host")
    render.add_argument("--release")
    render.add_argument("--format", choices=("json", "markdown"), required=True)
    render.add_argument("--output", required=True)
    check = subparsers.add_parser("check-doc")
    check.add_argument("--root", default=".")
    check.add_argument(
        "--document", default="docs/modules/platform.wire/STATUS.md"
    )
    subparsers.add_parser("self-test")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "self-test":
        self_test()
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

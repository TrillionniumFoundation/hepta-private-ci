#!/usr/bin/env python3
"""Generate or verify the prompt.registry status block from the implementation map."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs/modules/prompt.registry/IMPLEMENTATION_MAP.json"
STATUS = ROOT / "docs/modules/prompt.registry/QUALIFICATION_STATUS.md"
BEGIN = "<!-- prompt.registry generated-status:begin -->"
END = "<!-- prompt.registry generated-status:end -->"


def truth(value: bool) -> str:
    return "true" if value else "false"


def render(row: dict) -> str:
    claim = row["claimBoundary"]
    lifecycle = row["lifecycleStates"]
    closed = bool(row["closedWorldPublicFunctions"])
    product_proved = bool(claim["productExecutionProved"])
    independently_accepted = bool(claim["independentAcceptance"])
    production_ready = bool(
        closed
        and claim["nativeSourceMappingComplete"]
        and product_proved
        and independently_accepted
        and claim["activation"]
    )
    schemas = ", ".join(str(value) for value in row["activePersistentSchemas"])
    values = [
        ("sourceImplemented", lifecycle["sourceImplemented"]),
        ("sourceComposed", lifecycle["sourceComposed"]),
        ("closedWorldPublicFunctions", closed),
        ("nativeSourceMappingComplete", claim["nativeSourceMappingComplete"]),
        ("productExecutionProved", product_proved),
        ("independentlyAccepted", independently_accepted),
        ("productActivated", lifecycle["productActivated"]),
        ("productionReady", production_ready),
        ("released", lifecycle["released"]),
    ]
    lines = [
        BEGIN,
        "",
        "| Generated field | Value |",
        "| --- | --- |",
        *[f"| `{name}` | `{truth(bool(value))}` |" for name, value in values],
        f"| `activePersistentSchemas` | `{schemas}` |",
        f"| `semanticSchema` | `{row['semanticSchema']}` |",
        f"| `payloadGenerationSchema` | `{row['payloadGenerationSchema']}` |",
        "",
        "This block is generated from `IMPLEMENTATION_MAP.json`. When either "
        "`productExecutionProved` or `closedWorldPublicFunctions` is false, this "
        "document cannot claim production completion.",
        "",
        END,
    ]
    return "\n".join(lines)


def replace_block(text: str, generated: str, *, create: bool) -> str:
    starts = text.count(BEGIN)
    ends = text.count(END)
    if starts == 0 and ends == 0 and create:
        return text.rstrip() + "\n\n## Machine-generated implementation status\n\n" + generated + "\n"
    if starts != 1 or ends != 1:
        raise ValueError("status document must contain exactly one generated block")
    before, remainder = text.split(BEGIN, 1)
    _, after = remainder.split(END, 1)
    return before + generated + after


def guard_human_claims(text: str, row: dict) -> None:
    scrubbed = re.sub(
        re.escape(BEGIN) + r".*?" + re.escape(END),
        "",
        text,
        flags=re.DOTALL,
    )
    claim = row["claimBoundary"]
    if not claim["productExecutionProved"] or not row["closedWorldPublicFunctions"]:
        forbidden = re.compile(
            r"\|\s*(?:productionReady|productExecutionProved|closedWorldPublicFunctions)\s*\|\s*(?:`?true`?)\s*\|",
            flags=re.IGNORECASE,
        )
        if forbidden.search(scrubbed):
            raise ValueError("human status contradicts the fail-closed implementation map")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    row = json.loads(MAP.read_text(encoding="utf-8"))
    text = STATUS.read_text(encoding="utf-8")
    guard_human_claims(text, row)
    expected = replace_block(text, render(row), create=args.write)
    if args.write:
        STATUS.write_text(expected.rstrip() + "\n", encoding="utf-8")
        print("generated prompt.registry qualification status")
    elif text != expected:
        raise SystemExit("prompt.registry qualification status is stale")
    else:
        print("prompt.registry qualification status verified")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise SystemExit(f"prompt.registry status rejected: {error}") from error

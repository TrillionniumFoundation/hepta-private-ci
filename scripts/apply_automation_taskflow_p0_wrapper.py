#!/usr/bin/env python3
"""Run the P0 applicator with narrow, reviewed prose-match fallbacks.

Source-code replacements remain exact. Only the two known dossier prose records
may fall back to anchored regular expressions, so documentation wrapping cannot
block the staged closure or weaken executable-boundary matching.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "automation_taskflow_p0", ROOT / "scripts/apply_automation_taskflow_p0.py"
)
if SPEC is None or SPEC.loader is None:
    raise SystemExit("cannot load P0 applicator")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ORIGINAL_REPLACE_ONCE = MODULE.replace_once


def reviewed_replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if label == "dossier status":
        changed, substitutions = re.subn(
            r"(?m)^Status:.*?(?= Common requirements:)",
            new,
            text,
            count=1,
        )
    elif label == "dossier rollback":
        changed, substitutions = re.subn(
            r"No second scheduler, TaskFlow engine, queue writer, authority issuer or "
            r"terminality oracle was introduced\..*?upgraded store\.",
            new,
            text,
            count=1,
            flags=re.DOTALL,
        )
    else:
        return ORIGINAL_REPLACE_ONCE(text, old, new, label)
    if substitutions != 1:
        raise MODULE.PatchError(
            f"{label}: reviewed prose fallback expected one occurrence, observed {substitutions}"
        )
    return changed


MODULE.replace_once = reviewed_replace_once


def bind_exact_source_base(source_sha: str) -> None:
    """Keep map-v3 identity structured and bind it to the tested source commit.

    The source commit intentionally precedes generated metadata, avoiding a
    self-reference while allowing the canonical path-only verifier to compare
    the tested implementation bytes with an exact commit/tree observation.
    """

    path = ROOT / "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    source_tree = MODULE.git("rev-parse", f"{source_sha}^{{tree}}")
    identity = {"commit": source_sha, "tree": source_tree}
    data["sourceBase"] = identity
    data["observedAtHead"] = identity
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("source")
    metadata = sub.add_parser("metadata")
    metadata.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    if args.command == "source":
        MODULE.apply_source()
    else:
        MODULE.apply_metadata(args.source_sha)
        bind_exact_source_base(args.source_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

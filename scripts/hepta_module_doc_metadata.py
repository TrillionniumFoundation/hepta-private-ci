#!/usr/bin/env python3
"""Regenerate only module-document metadata; never infer source completion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = "docs/modules/MODULE_DOCS.json"
README = "docs/modules/README.md"


def expected_metadata(root: Path) -> dict[Path, str]:
    modules = json.loads((root / "docs/modules/MODULES.json").read_text())["modules"]
    index = json.loads((root / INDEX).read_text())
    by_id = {module["id"]: module for module in modules}
    if (
        not modules
        or len(by_id) != len(modules)
        or len(index["modules"]) != len(modules)
        or {row["module"] for row in index["modules"]} != set(by_id)
    ):
        raise ValueError("module coverage mismatch")
    readme = (root / README).read_text()
    for row in index["modules"]:
        module = by_id[row["module"]]
        expected_path = f"docs/modules/{row['module']}/TECHNICAL.md"
        if row["path"] != expected_path or module["technicalDocument"] != expected_path:
            raise ValueError("technical document path mismatch")
        text = (root / expected_path).read_text(encoding="utf-8")
        row["sourceStatus"] = module["sourceStatus"]
        row["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row["bytes"] = len(text.encode("utf-8"))
        row["words"] = len(re.findall(r"\b[\w.-]+\b", text))
        pattern = (
            r"(" + re.escape(f"- [`{row['module']}`]") + r".*? — `)[^`]+(`, bootstrap)"
        )
        readme, count = re.subn(
            pattern, lambda match: match[1] + module["sourceStatus"] + match[2], readme
        )
        if count != 1:
            raise ValueError("README module coverage mismatch")
    return {
        root / INDEX: json.dumps(index, indent=2) + "\n",
        root / README: readme,
    }


def synchronize(root: Path, *, write: bool = False) -> list[Path]:
    """No authority, source-status, contract or work-package mutations."""
    expected = expected_metadata(root)
    changed = [path for path, text in expected.items() if path.read_text() != text]
    if write:
        for path in changed:
            path.write_text(expected[path], encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="explicit developer regeneration; CI must omit",
    )
    args = parser.parse_args()
    changed = synchronize(ROOT, write=args.write)
    print(
        json.dumps(
            {
                "stale_or_regenerated": [
                    str(path.relative_to(ROOT)) for path in changed
                ],
                "written": args.write,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return int(bool(changed) and not args.write)


if __name__ == "__main__":
    raise SystemExit(main())

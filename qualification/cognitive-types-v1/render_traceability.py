#!/usr/bin/env python3
"""Generate/check the obligation table, never implementation or pass state."""
import argparse
import json
from pathlib import Path
import sys


def render(manifest):
    rows = ["# cognitive.types invariant traceability", "",
            "Generated from `INVARIANTS.json`. Entries are obligations and source navigation, not execution receipts.",
            "The existing `IMPLEMENTATION_MAP.json` remains the status authority. Exact candidate execution lives in external artifacts.",
            "", "| ID | Obligation | Sources and tests | Required execution |", "| --- | --- | --- | --- |"]
    identities = set()
    for entry in manifest["invariants"]:
        if entry["id"] in identities:
            raise ValueError("duplicate invariant identity")
        identities.add(entry["id"])
        links = "<br>".join(f"`{path}`" for path in entry["source"] + entry["tests"])
        checks = entry["qualificationGroup"] + ": " + ", ".join(entry["checks"])
        rows.append(f"| {entry['id']} | {entry['obligation']} | {links} | {checks} |")
    rows += ["", "A green source test is not authenticated default-profile composition, compatibility retirement, independent acceptance, activation, or release.", ""]
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    directory = root / "docs/modules/cognitive.types"
    manifest = json.loads((directory / "INVARIANTS.json").read_text())
    if manifest.get("module") != "cognitive.types":
        raise ValueError("module identity mismatch")
    for entry in manifest["invariants"]:
        for reference in entry["source"] + entry["tests"]:
            path = (root / reference).resolve()
            if root not in path.parents or not path.is_file():
                raise ValueError("missing or escaping traceability reference: " + reference)
    result = render(manifest)
    if args.check:
        if (directory / "INVARIANTS.md").read_text() != result:
            raise SystemExit("traceability document drift; regenerate and commit normally, not inside qualification")
        print("Traceability projection matches; execution and product acceptance are not inferred.")
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()

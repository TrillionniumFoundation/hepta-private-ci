"""Extract real worker dispatch/reconcile code into a renderer-free Rust fixture.

This is a source-level regression harness, not a build of Servo. Compile the
output with reviewed serde_json/url/sha2 dependencies, then run its Rust tests
and scripts/worker-dispatch-owner.mjs with the resulting executable.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def extract(source, declaration, indent=""):
    match = re.search(rf"(?m)^{re.escape(indent + declaration)}", source)
    if match is None:
        raise ValueError(f"missing source declaration: {declaration}")
    end = re.search(rf"(?m)^{re.escape(indent)}}}$", source[match.end() :])
    if end is None:
        raise ValueError(f"missing source terminator: {declaration}")
    return source[match.start() : match.end() + end.end()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "servo-worker/src/main.rs")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.read_text()
    types = "#[derive(Clone)]\n" + extract(source, "struct StoredOperation {")
    types += "\n" + extract(source, "enum PreparedEffect {")
    methods = "\n".join(
        extract(source, f"fn {name}(", "    ")
        for name in ["dispatch", "reconcile", "outcome_digest"]
    )
    helpers = "\n".join(
        extract(source, f"fn {name}")
        for name in [
            "load_phase(",
            "remaining_deadline(",
            "origin(",
            "stored_receipt(",
            "succeeded(",
            "failed(",
            "fixed_click(",
            "fixed_focus(",
            "fixed_type(",
            "fixed_scroll(",
            "json_string(",
            "string_field<",
            "sha256_hex(",
            "stable_id(",
        ]
    )
    template = (ROOT / "servo-worker/tests/dispatch_source_harness.rs.in").read_text()
    replacements = {
        "// WORKER_TYPES": types,
        "// WORKER_CONSTANTS": "\n".join(
            re.findall(
                r"(?m)^const (?:MAX_SAFE_INTEGER|MAX_NAVIGATION_URL_BYTES|"
                r"MAX_STORED_OPERATIONS):[^\n]+",
                source,
            )
        ),
        "    // WORKER_METHODS": methods,
        "// WORKER_HELPERS": helpers,
        "// DOCUMENT_AUTHORITY": (
            "#[path = "
            + json.dumps(str(args.source.resolve().parent / "document_authority.rs"))
            + "]\nmod document_authority;"
        ),
    }
    for marker, replacement in replacements.items():
        if template.count(marker) != 1:
            raise ValueError(f"fixture must contain one {marker}")
        template = template.replace(marker, replacement)
    identity = hashlib.sha256(args.source.read_bytes()).hexdigest()
    args.output.write_text(f"// Exact worker source SHA-256: {identity}\n" + template)
    print(f"generated renderer-free source harness: {args.output} (source {identity})")


if __name__ == "__main__":
    main()

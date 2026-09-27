"""Read-only cognitive.types qualification; receipts are execution, not acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import hepta_ci_exec

PACKAGES = (
    "codex-hepta-cognitive-types", "codex-hepta-cognitive-store",
    "codex-hepta-cognitive-read", "codex-hepta-memory-retrieval",
    "codex-hepta-compact-engine", "codex-hepta-intelligence",
    "codex-hepta-memory", "codex-hepta-operations", "codex-state",
)


def commands(suite: str) -> list[tuple[str, list[str], int]]:
    if suite == "contracts":
        return [
            ("registry-self-test", ["python3", "scripts/hepta-hnmf.py", "self-test"], 0),
            ("registry", ["python3", "scripts/hepta-hnmf.py", "verify"], 0),
            ("v1-vectors", ["python3", "qualification/cognitive-types-v1/verify_vectors.py"], 0),
            ("bound-python", ["python3", "qualification/cognitive-types-v1/verify_bound_vector.py"], 0),
            ("bound-node", ["node", "qualification/cognitive-types-v1/verify_bound_vector.mjs"], 0),
            ("all-schema-python", ["python3", "qualification/cognitive-types-v1/verify_closure_vectors.py"], 0),
            ("all-schema-typescript", ["node", "--experimental-strip-types", "qualification/cognitive-types-v1/verify_closure_vectors.ts"], 0),
            ("mutation-classifier", ["python3", "scripts/tests/test_cognitive_types_mutation.py"], 0),
        ]
    packages = PACKAGES[:1] if suite == "types" else PACKAGES[1:]
    result = []
    for package in packages:
        args = ["--manifest-path", "codex-rs/Cargo.toml", "--locked", "-p", package]
        result.extend([
            (package + "-fmt", ["cargo", "fmt", "--manifest-path", "codex-rs/Cargo.toml", "-p", package, "--", "--check"], 0),
            (package + "-check", ["cargo", "check", *args, "--all-targets"], 0),
            (package + "-test", ["just", "test", "--locked", "-p", package], 1),
            (package + "-clippy", ["cargo", "clippy", *args, "--all-targets", "--", "-D", "warnings"], 0),
        ])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("types", "consumers", "contracts"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(hepta_ci_exec.git("rev-parse", "--show-toplevel")).resolve()
    output = args.output.resolve()
    if output.is_relative_to(root):
        raise ValueError("receipts must be outside the checkout")
    output.mkdir(parents=True, exist_ok=False)
    source = hepta_ci_exec.identity()
    records = []
    failed = False
    for name, argv, minimum in commands(args.suite):
        record = output / (name + ".json")
        code = hepta_ci_exec.run(record, argv, minimum_tests=minimum, timeout_seconds=1800)
        raw = record.read_bytes()
        value = json.loads(raw)
        records.append({
            "name": name, "receipt": record.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "status": value["status"], "exit_code": code,
        })
        failed |= code != 0
        # Do not dispatch another command after source mutation. Ordinary test
        # failures remain visible without hiding unrelated native diagnostics.
        if hepta_ci_exec.identity() != source:
            failed = True
            break
    summary = {
        "schema": "hepta.cognitive-types.command-suite.v1", "suite": args.suite,
        "lane": os.environ.get("HEPTA_CI_LANE"), "source": source,
        "base_sha": os.environ.get("BASE_SHA"), "source_sha": os.environ.get("SOURCE_SHA"),
        "status": "failed" if failed else "passed", "commands": records,
        "planned_commands": len(commands(args.suite)),
        "production_accepted": False, "activation": False, "release": False,
    }
    with (output / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

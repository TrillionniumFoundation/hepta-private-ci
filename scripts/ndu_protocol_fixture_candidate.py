#!/usr/bin/env python3
"""Regenerate protocol fixtures without changing their Rust source or assertions."""

import argparse
import json
from pathlib import Path
import shutil

from ndu_dependency_candidate_common import FILES
from ndu_dependency_candidate_common import Recorder
from ndu_dependency_candidate_common import checksum
from ndu_dependency_candidate_common import describe
from ndu_dependency_candidate_common import restore_candidate


SCHEMA_ROOT = "codex-rs/app-server-protocol/schema/"


def schema_path(name):
    path = Path(name)
    return (
        path.as_posix() == name
        and not path.is_absolute()
        and ".." not in path.parts
        and name.startswith(SCHEMA_ROOT)
        and path.suffix in (".json", ".ts", ".zst")
    )


def verify_scope(runner, candidate, schema_files=None):
    for key in ("policy_inputs", "vendor_inputs", "files"):
        if describe(runner.root, candidate[key]) != candidate[key]:
            raise ValueError(f"Protocol generation changed bound {key}")
    runner.record["original_dependency_policy_unchanged"] = True
    changed = set(
        runner.text(
            "changed-paths", ["git", "diff", "HEAD", "--name-only"]
        ).splitlines()
    )
    untracked = set(
        runner.text(
            "untracked-paths", ["git", "ls-files", "--others", "--exclude-standard"]
        ).splitlines()
    )
    outside_candidate = (changed | untracked) - set(FILES)
    if not outside_candidate or not all(map(schema_path, outside_candidate)):
        raise ValueError("Only generated schema files may change beyond the candidate")
    if not set(candidate["changed_paths"]) <= changed:
        raise ValueError("Protocol generation removed part of the dependency candidate")
    if schema_files is not None:
        if outside_candidate != set(schema_files):
            raise ValueError("The regression changed the schema file set")
        present = {p: v for p, v in schema_files.items() if v is not None}
        if describe(runner.root, present) != present:
            raise ValueError("The regression changed generated schema bytes")
        if any(
            (runner.root / p).exists() for p, v in schema_files.items() if v is None
        ):
            raise ValueError("The regression recreated a deleted schema file")
    return sorted(outside_candidate)


def generate(runner, artifact, expected_result, expected_source):
    candidate = restore_candidate(runner, artifact, expected_result, expected_source)
    source = [
        path
        for path in runner.text(
            "protocol-source-inputs",
            ["git", "ls-files", "codex-rs/app-server-protocol", "codex-rs/protocol"],
        ).splitlines()
        if not path.startswith(SCHEMA_ROOT)
    ]
    runner.record["protocol_source_inputs"] = describe(runner.root, source)
    runner.run("generate-stable", ["just", "write-app-server-schema"])
    runner.run(
        "generate-experimental", ["just", "write-app-server-schema", "--experimental"]
    )
    paths = verify_scope(runner, candidate)
    if describe(runner.root, source) != runner.record["protocol_source_inputs"]:
        raise ValueError("Protocol Rust source, generation code or tests changed")
    snapshots = {}
    for name in paths:
        path = runner.root / name
        snapshots[name] = (
            describe(runner.root, (name,))[name] if path.exists() else None
        )
        if path.exists():
            destination = runner.output / "files" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    runner.record["schema_files"] = snapshots
    runner.save()
    status = runner.run(
        "protocol-regressions",
        ["just", "test", "--locked", "-p", "codex-app-server-protocol"],
        required=False,
    )
    verify_scope(runner, candidate, snapshots)
    if describe(runner.root, source) != runner.record["protocol_source_inputs"]:
        raise ValueError("The regression changed protocol source or assertions")
    runner.run("stage-generated-paths", ["git", "add", "-N", "--", SCHEMA_ROOT])
    patch = runner.output / "schema-candidate.patch"
    runner.run(
        "export-schema-patch",
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            "--no-renames",
            f"--output={patch}",
            "HEAD",
            "--",
            SCHEMA_ROOT,
        ],
    )
    runner.record.update(
        status="schema_candidate_verified"
        if status == 0
        else "schema_regressions_failed",
        schema_patch_sha256=checksum(patch),
        regression_exit_code=status,
        qualification="Generated artifacts only; all protocol assertions remain unchanged.",
    )
    return status == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    args = parser.parse_args()
    runner = Recorder(args.repository, args.output, "protocol-fixture")
    success = False
    try:
        success = generate(
            runner, args.candidate, args.expected_result_sha256, args.expected_source
        )
    except Exception as error:
        runner.record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
    finally:
        runner.save()
    print(
        json.dumps(
            {
                "status": runner.record["status"],
                "result": str(runner.output / "RESULT.json"),
            }
        )
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

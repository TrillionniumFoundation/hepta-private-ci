#!/usr/bin/env python3
"""Generate and test reviewable dependency candidates on disposable CI checkouts.

The original cargo-deny policy and complete workspace remain in force. This
script never pushes, promotes, or substitutes extracted code for workspace tests.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tomllib

from ndu_dependency_candidate_common import FILES
from ndu_dependency_candidate_common import Recorder
from ndu_dependency_candidate_common import check_checkout
from ndu_dependency_candidate_common import checksum
from ndu_dependency_candidate_common import describe
from ndu_dependency_candidate_common import export_files
from ndu_dependency_candidate_common import restore_candidate
from ndu_dependency_candidate_common import verify_tree


INPUTS = "experiments/multimodal_output_portfolio/closure_v2_20261027/ci/dependency-remediation"
PATCHES = {
    "zip-source.patch": "8bc968c54ea49960a4c14896b48e861b68b30b653613f2b440e4ef2b32791c35",
    "zip-zstd-manifest.patch": "f5394874a7a1ed42890ea35dc3b4534ae518d54c34ab71d1c3a1d6357da29dd7",
    "i18n-config-manifest.patch": "74a2c048d91c795114226d676575a3b04f4766bd13fba4e83111ad953b75e4dc",
}
UPDATES = (
    ("zip", "9.1.2"),
    ("zstd", "0.14.3"),
    ("zstd-safe", "8.2.0"),
    ("zstd-sys", "2.1.2+zstd.1.5.7"),
    ("rustls-webpki", "0.103.16"),
    ("webpki-root-certs", "1.0.10"),
    ("webpki-roots", "1.0.10"),
    ("rustls", "0.23.46"),
)
TEST_GROUPS = {
    "plugins": (("codex-core-plugins",), ("i18n-config",), ("codex-secrets",)),
    "storage": (
        ("codex-http-client",),
        ("codex-rollout",),
        ("codex-app-server-protocol",),
        ("codex-thread-store",),
    ),
    "core": (("codex-core", "-E", "test(request_compression)"),),
}


def packages(root):
    return tomllib.loads((root / "codex-rs/Cargo.lock").read_text())["package"]


def validate_graph(root):
    resolved = packages(root)
    for name, version in UPDATES:
        found = [p["version"] for p in resolved if p["name"] == name]
        if found != [version]:
            raise ValueError(f"Expected only {name} {version}, resolved {found}")
    if any(p["name"] == "basic-toml" for p in resolved):
        raise ValueError("The abandoned basic-toml implementation remains in the graph")
    config = [p for p in resolved if p["name"] == "i18n-config"]
    if len(config) != 1 or "source" in config[0] or config[0]["version"] != "0.4.8":
        raise ValueError("The reviewed i18n-config path patch was not selected")
    if "toml" not in {d.split()[0] for d in config[0].get("dependencies", [])}:
        raise ValueError(
            "i18n-config did not select the maintained TOML implementation"
        )


def generate(runner, expected_source):
    check_checkout(runner, expected_source)
    for program in ("rustc", "cargo", "just", "bazel"):
        runner.run(f"version-{program}", [program, "--version"])
    runner.record["lock_inputs"] = describe(runner.root, FILES[:3])
    runner.record["input_patches"] = {}
    for name, expected in PATCHES.items():
        patch = runner.root / INPUTS / name
        if checksum(patch) != expected:
            raise ValueError(f"The reviewed patch bytes changed: {name}")
        runner.record["input_patches"][name] = expected
        runner.run(f"check-{name}", ["git", "apply", "--check", "--index", str(patch)])
        runner.run(f"apply-{name}", ["git", "apply", "--index", str(patch)])
    manifest = runner.root / "codex-rs/Cargo.toml"
    expected_manifest = checksum(manifest)
    runner.run("workspace-preflight", [sys.executable, "scripts/hepta_workspace.py"])
    runner.record["updates"] = []
    for name, version in UPDATES:
        current = [p["version"] for p in packages(runner.root) if p["name"] == name]
        runner.record["updates"].append(
            {"name": name, "before": current, "requested": version}
        )
        if current != [version]:
            runner.run(
                f"update-{name}",
                [
                    "cargo",
                    "update",
                    "--manifest-path",
                    str(manifest),
                    "--package",
                    name,
                    "--precise",
                    version,
                ],
            )
    # Same-version registry/path changes must be resolved explicitly as well.
    runner.run(
        "update-i18n-config",
        [
            "cargo",
            "update",
            "--manifest-path",
            str(manifest),
            "--package",
            "i18n-config",
        ],
    )
    validate_graph(runner.root)
    runner.run(
        "cargo-metadata",
        [
            "cargo",
            "metadata",
            "--manifest-path",
            str(manifest),
            "--locked",
            "--no-deps",
            "--format-version",
            "1",
        ],
    )
    runner.run("bazel-lock-update", ["just", "bazel-lock-update"])
    runner.run("bazel-lock-check", ["just", "bazel-lock-check"])
    runner.run("diff-check", ["git", "diff", "--check", "HEAD"])
    validate_graph(runner.root)
    if checksum(manifest) != expected_manifest:
        raise ValueError("A resolver changed the fixed candidate manifest")
    runner.record["files"] = export_files(runner)
    runner.record["changed_paths"] = runner.text(
        "candidate-paths", ["git", "diff", "HEAD", "--name-only"]
    ).splitlines()
    if set(runner.record["changed_paths"]) != set(FILES):
        raise ValueError(
            "Expected all manifest, lock and ZIP source changes in the candidate"
        )
    verify_tree(runner, runner.record)
    patch = runner.output / "candidate.patch"
    runner.run(
        "export-candidate-patch",
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            "--no-renames",
            f"--output={patch}",
            "HEAD",
            "--",
            *FILES,
        ],
    )
    runner.record.update(
        status="candidate_generated",
        candidate_patch_sha256=checksum(patch),
        validation="Generation and lock checks only. Bound full-workspace regressions run in separate jobs; unchanged cargo-deny and platform CI remain required.",
    )


def test_candidate(runner, candidate, expected_result, expected_source, group):
    record = restore_candidate(runner, candidate, expected_result, expected_source)
    validate_graph(runner.root)
    for command in (
        ["rustc", "--version"],
        ["cargo", "--version"],
        ["cargo", "nextest", "--version"],
        ["just", "--version"],
    ):
        runner.run(f"version-{command[0]}", command)
    runner.record.update(
        test_group=group, test_plan=TEST_GROUPS[group], test_results=[]
    )
    failures = []
    junit_root = (
        Path(os.environ.get("CARGO_TARGET_DIR", runner.root / "codex-rs/target"))
        / "nextest"
    )
    for package, *extra in TEST_GROUPS[group]:
        old_reports = {
            p: (p.stat().st_mtime_ns, checksum(p))
            for p in junit_root.glob("*/junit.xml")
        }
        command = [
            "just",
            "test",
            "--locked",
            "--cargo-profile",
            "ci-test",
            "-p",
            package,
            *extra,
        ]
        status = runner.run(f"test-{package}", command, required=False)
        outcome = {
            "package": package,
            "exit_code": status,
            "junit": [],
            "command_index": len(runner.record["commands"]) - 1,
            "log": runner.record["commands"][-1]["log"],
        }
        for junit in junit_root.glob("*/junit.xml"):
            if old_reports.get(junit) == (junit.stat().st_mtime_ns, checksum(junit)):
                continue
            destination = runner.output / f"{package}-{junit.parent.name}-junit.xml"
            destination.write_bytes(junit.read_bytes())
            outcome["junit"].append(
                {"file": destination.name, "sha256": checksum(destination)}
            )
        runner.record["test_results"].append(outcome)
        if status:
            failures.append({"package": package, "exit_code": status})
        verify_tree(runner, record)
    runner.record.update(
        status="tests_failed" if failures else "targeted_tests_passed",
        failed_tests=failures,
        test_scope="Actual complete repository checkout; no extracted-function substitute; selected packages and explicit core request-compression filter only.",
    )
    return not failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--mode", choices=("generate", "test"), default="generate")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--expected-result-sha256")
    parser.add_argument("--group", choices=TEST_GROUPS)
    args = parser.parse_args()
    runner = Recorder(args.repository, args.output, args.mode)
    success = False
    try:
        if args.mode == "generate":
            generate(runner, args.expected_source)
            success = True
        else:
            if not all((args.candidate, args.expected_result_sha256, args.group)):
                raise ValueError(
                    "Testing requires the producer artifact, result hash and test group"
                )
            success = test_candidate(
                runner,
                args.candidate.resolve(),
                args.expected_result_sha256,
                args.expected_source,
                args.group,
            )
    except Exception as error:
        runner.record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        if args.mode == "generate":
            try:
                runner.record["partial_files"] = export_files(runner, "partial-files")
            except Exception as snapshot_error:
                runner.record["partial_snapshot_error"] = str(snapshot_error)
    finally:
        runner.save()
    if success and args.mode == "generate" and os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write(f"source_commit={runner.record['source_commit']}\n")
            stream.write(f"result_sha256={checksum(runner.output / 'RESULT.json')}\n")
    print(
        json.dumps(
            {
                "status": runner.record["status"],
                "result": str(runner.output / "RESULT.json"),
            }
        ),
        flush=True,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

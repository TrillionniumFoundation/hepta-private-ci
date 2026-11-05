#!/usr/bin/env python3
"""Run the real V2 recovery regressions; never equate build failure with RED."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BASE = "3a8e50ddd79ec3e52ca58157323726c37069202c"
SOURCE = "29fcd2e88654d5bec2bf30134cc030b5bfa7831b"
SOURCE_TREE = "9653293a81dfda7f17c12a54fd7bd5f4170ea867"
OWNER_FILES = (
    "codex-rs/hepta-evidence/src/recovery_effect_frontier_tests.rs",
    "codex-rs/hepta-evidence/src/provider_effect_recovery_provenance_tests.rs",
)
OWNER_LIB = "codex-rs/hepta-evidence/src/lib.rs"
OWNER_FILTER = (
    "test(recovery_effect_frontier_tests::) | "
    "test(provider_effect_recovery_provenance_tests::)"
)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True
    ).strip()


def verify_sources(repo, manifest):
    for row in manifest["source_files"]:
        data = (repo / row["path"]).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        blob = hashlib.sha1(
            b"blob " + str(len(data)).encode("ascii") + b"\0" + data
        ).hexdigest()
        if (digest, blob, len(data)) != (
            row["sha256"], row["git_blob"], row["bytes"]
        ):
            raise RuntimeError("source identity mismatch: " + row["path"])


def observed_tests(log):
    found = {}
    for line in ANSI.sub("", log).splitlines():
        match = re.match(r"\s*(PASS|FAIL|TIMEOUT|XFAIL|XPASS|LEAK)\s+\[", line)
        if match:
            name = line.split()[-1]
            found.setdefault(name, set()).add(match.group(1))
    return {name: sorted(values) for name, values in found.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, help="Full checked-out commit SHA")
    parser.add_argument("--output", required=True, type=Path, help="New external receipt directory")
    parser.add_argument(
        "--phase", choices=("owner", "signed", "product", "full", "format", "all"),
        default="owner",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    manifest = json.loads(Path(__file__).with_name("manifest.json").read_text())
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", args.candidate):
        raise RuntimeError("--candidate requires a full lowercase commit SHA")
    if git(repo, "rev-parse", "HEAD") != args.candidate:
        raise RuntimeError("HEAD differs from the requested candidate")
    if git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("candidate checkout is not clean")
    subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", BASE, args.candidate],
        check=True,
    )
    if git(repo, "rev-parse", SOURCE + "^{tree}") != SOURCE_TREE:
        raise RuntimeError("qualified source tree does not match its pinned identity")
    subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", SOURCE, args.candidate],
        check=True,
    )
    later_paths = git(repo, "diff", "--name-only", SOURCE, args.candidate, "--").splitlines()
    if any(not path.startswith("evidence/recovery-v2-integration-20261105/")
           for path in later_paths):
        raise RuntimeError("candidate changes more than the pinned reproduction evidence")
    verify_sources(repo, manifest)
    output = args.output.resolve()
    if output == repo or repo in output.parents:
        raise RuntimeError("--output must be outside the candidate checkout")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {
        "candidate": args.candidate,
        "candidate_tree": git(repo, "rev-parse", "HEAD^{tree}"),
        "base": BASE,
        "source_commit": SOURCE,
        "source_tree": SOURCE_TREE,
        "phase": args.phase,
        "qualification": "HOLD_NO_GO",
        "commands": [],
        "environment": {
            key: os.environ.get(key)
            for key in (
                "CARGO_TARGET_DIR", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS",
                "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER",
            )
        },
    }
    env = dict(os.environ)
    env["CARGO_BUILD_JOBS"] = "1"

    def record(label, cwd, command, expected=None, red=False):
        path = output / (label + ".log")
        with path.open("w") as log_file:
            process = subprocess.run(
                command, cwd=cwd, env=env, stdout=log_file,
                stderr=subprocess.STDOUT, check=False,
            )
        log = path.read_text(errors="replace")
        observed = observed_tests(log)
        matched = None
        if expected is not None:
            matched = (
                observed == {name: [status] for name, status in expected.items()}
                and ((process.returncode != 0) if red else (process.returncode == 0))
            )
        elif label == "owner-full":
            matched = (
                process.returncode == 0 and bool(observed)
                and all(value == ["PASS"] for value in observed.values())
            )
        row = {
            "label": label, "cwd": str(cwd), "argv": command,
            "exit_code": process.returncode, "log": path.name,
            "observed_test_statuses": observed, "expected_statuses_match": matched,
        }
        receipt["commands"].append(row)
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if (expected is not None or label == "owner-full") and not matched:
            raise RuntimeError(label + ": assertions not verified; inspect the raw log")
        if expected is None and label != "owner-full" and process.returncode != 0:
            raise RuntimeError(label + ": command failed; inspect the raw log")

    try:
        if args.phase in ("format", "all"):
            record("format-check", repo / "codex-rs",
                   ["just", "fmt", "--base", BASE, "--check"])
            verify_sources(repo, manifest)
        if args.phase in ("owner", "all"):
            red_repo = output / "red-worktree"
            record("create-red-worktree", repo,
                   ["git", "worktree", "add", "--detach", str(red_repo), BASE])
            if git(red_repo, "rev-parse", "HEAD") != BASE:
                raise RuntimeError("RED checkout did not select the exact baseline")
            baseline_lib = (red_repo / OWNER_LIB).read_text()
            for path in OWNER_FILES:
                destination = red_repo / path
                if destination.exists():
                    raise RuntimeError("baseline unexpectedly contains " + path)
                destination.write_bytes((repo / path).read_bytes())
                module = Path(path).stem
                baseline_lib += (
                    '\n#[cfg(test)]\n#[path = "' + Path(path).name
                    + '"]\nmod ' + module + ';\n'
                )
            (red_repo / OWNER_LIB).write_text(baseline_lib)
            changed = set(git(red_repo, "diff", "--name-only", "HEAD", "--").splitlines())
            changed.update(git(red_repo, "ls-files", "--others", "--exclude-standard").splitlines())
            if changed != {OWNER_LIB, *OWNER_FILES}:
                raise RuntimeError("RED tree differs outside the three test-only paths")
            receipt["red_tree_modified_paths"] = sorted(changed)
            receipt["red_files"] = {
                path: hashlib.sha256((red_repo / path).read_bytes()).hexdigest()
                for path in sorted(changed)
            }
            owner_command = [
                "just", "test", "-p", "codex-hepta-evidence", "--locked",
                "--lib", "--retries", "0", "-E", OWNER_FILTER,
            ]
            record("owner-red", red_repo / "codex-rs", owner_command,
                   manifest["expected_owner_red"], red=True)
            record("owner-green", repo / "codex-rs", owner_command,
                   {name: "PASS" for name in manifest["expected_owner_red"]})
        if args.phase in ("full", "all"):
            record("owner-full", repo / "codex-rs",
                   ["just", "test", "-p", "codex-hepta-evidence", "--locked"])
        if args.phase in ("signed", "all"):
            record(
                "signed-frontier", repo / "codex-rs",
                ["just", "test", "-p", "codex-hepta-agentd", "--locked",
                 "--lib", "--retries", "0", "-E",
                 "test(evidence_frontier::tests::recovery_frontier_)"],
                {name: "PASS" for name in manifest["expected_signed_tests"]},
            )
        if args.phase in ("product", "all"):
            record(
                "agentd-product", repo / "codex-rs",
                ["just", "test", "-p", "codex-hepta-agentd", "--locked",
                 "--test", "kernel_evidence_product", "--retries", "0",
                 "-E", "test(signed_recovery_frontier_)"],
                {name: "PASS" for name in manifest["expected_product_tests"]},
            )
        verify_sources(repo, manifest)
        receipt["requested_phase_completed"] = True
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("Receipt:", output / "receipt.json")
        print("Qualification remains HOLD_NO_GO; this script covers scoped regressions only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Source-bound five-lib/four-integration qualification, not a whole-suite claim."""

from collections import Counter
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

import native_fixture_evidence as common

BASE = "852c44e62e828f41a3e91348c3186814cc8787e8"
BASE_TREE = "23e35c75c0cb558f58aa5ec0381c4e787bfc4883"
PINS = {
    "codex-rs/hepta-agentd/tests/support/cognitive_recovery_snapshot.rs": "eb184ba98cab5b30fe3614bc8fe2bc48757a27975ea36133dae4a35e834f1378",
    "codex-rs/hepta-memory/src/cognitive_store.rs": "78f4dfde7bde04d95e4d8e3d7a27ba8397c9c82680589bf531e4cdff8eb2f007",
    "codex-rs/hepta-memory/src/cognitive_store_lifecycle_tests.rs": "a8b942fec47a920006fbc2b06685d06acb73ded75023d5dd4dcfd94d0cecba62",
    "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs": "d89ea0a6290adbbc0decf468c37ef3447edda48dff69ae95d1b2fde598f7903c",
    "codex-rs/.config/nextest.toml": "2c13217e00ea45a022286aa217bcc04c2cf1ea6eedb56284a55dc3e48c99de07",
}
CHANGED_SOURCES = {
    "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs",
    "codex-rs/hepta-agentd/tests/support/cognitive_recovery_snapshot.rs",
    "codex-rs/.config/nextest.toml",
}
TOOL_VERSIONS = {
    "rustc": "rustc 1.95.0 (59807616e 2026-04-14)",
    "cargo": "cargo 1.95.0 (f2d3ce0bd 2026-03-21)",
    "just": "just 1.59.0",
    "cargo-nextest": (
        "cargo-nextest 0.9.149 (3fe4ef319 2026-10-20)\n"
        "release: 0.9.149\n"
        "commit-hash: 3fe4ef31972f24e0c94cfe291718eab0fe678260\n"
        "commit-date: 2026-10-20\n"
        "host: x86_64-unknown-linux-gnu"
    ),
}
CI_FILES = {
    ".github/workflows/hepta-native-recovery.yml",
    ".github/scripts/native_recovery_evidence.py",
    ".github/scripts/test_native_recovery_evidence.py",
}
SUPPORT = {
    ".github/workflows/hepta-native-preflight-reads.yml",
    "codex-rs/Cargo.lock",
    "codex-rs/Cargo.toml",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/rustfmt.toml",
    "codex-rs/hepta-memory/Cargo.toml",
    "codex-rs/hepta-agentd/Cargo.toml",
    "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs",
    "justfile",
    "scripts/run-nextest.py",
    "scripts/just-shell.py",
    ".github/scripts/native_fixture_evidence.py",
}
LIB_TESTS = (
    "close_marks_clone_pool_immediately_and_retains_recovery_guard_until_drop",
    "close_waits_for_checked_out_transaction_commit_and_preserves_all_source_fields",
    "close_cancelled_before_pool_drain_can_be_retried_and_is_idempotent",
    "close_does_not_close_independently_opened_pool_for_same_database",
    "close_preserves_unresolved_queued_lease_and_release_still_fails_closed",
)
EXPECTED = {
    "owning": {
        ("codex-hepta-memory", f"cognitive_store::lifecycle_tests::{name}")
        for name in LIB_TESTS
    },
    "integration": common.EXPECTED
    | {
        (
            "codex-hepta-agentd::cognitive_store_product_writer",
            "agentd_product_host_recovers_exact_cut_into_fenced_writer_generation",
        ),
        (
            "codex-hepta-agentd::cognitive_store_product_writer",
            "agentd_product_host_recovers_existing_active_lease_without_advancing_cut",
        ),
    },
}
require, run, digest, write = common.require, common.run, common.digest, common.write


def expression(phase):
    return " | ".join(f"test(={name})" for _, name in sorted(EXPECTED[phase]))


def command(phase):
    args = ["just", "test", "--locked", "-p"]
    args += (
        ["codex-hepta-memory", "--lib"]
        if phase == "owning"
        else [
            "codex-hepta-agentd",
            "--features",
            "codex-hepta-agentd/qualification-cognitive-write",
            "--test",
            "cognitive_product_e2e",
            "--test",
            "cognitive_store_product_writer",
        ]
    )
    return args + [
        "--profile",
        "native-recovery",
        "--no-tests",
        "fail",
        "-E",
        expression(phase),
    ]


def bind(out):
    head = run("git", "rev-parse", "HEAD")
    require(
        head == os.environ["CANDIDATE_SHA"] == os.environ["WORKFLOW_SHA"],
        "source/workflow SHA mismatch",
    )
    require(
        run("git", "rev-parse", "HEAD^") == BASE,
        "expected one commit directly on reviewed base",
    )
    require(run("git", "rev-parse", f"{BASE}^{{tree}}") == BASE_TREE, "wrong base tree")
    require(not run("git", "status", "--porcelain=v1"), "dirty source")
    changed = set(
        run("git", "diff", "--no-renames", "--name-only", BASE, head).splitlines()
    )
    require(changed == CHANGED_SOURCES | CI_FILES, "unexpected/missing candidate paths")
    require(
        run("git", "rev-parse", "HEAD:codex-rs/Cargo.lock") == common.LOCK,
        "lock changed",
    )
    for path, expected in PINS.items():
        require(digest(path) == expected, f"unreviewed source: {path}")
    files = {}
    for path in sorted(set(PINS) | CI_FILES | SUPPORT):
        require(
            Path(path).is_file() and not Path(path).is_symlink(),
            f"invalid source: {path}",
        )
        files[path] = {
            "blob": run("git", "rev-parse", f"HEAD:{path}"),
            "sha256": digest(path),
        }
    write(
        out,
        "source.json",
        {
            "head": head,
            "tree": run("git", "rev-parse", "HEAD^{tree}"),
            "base": BASE,
            "base_tree": BASE_TREE,
            "files": files,
        },
    )
    (out / "candidate.patch").write_bytes(
        subprocess.check_output(["git", "diff", "--binary", "--full-index", BASE, head])
    )


def validate_report(path, phase):
    root = ET.parse(path).getroot()
    require(
        root.tag == "testsuites" and root.get("name") == "native-recovery",
        "wrong report",
    )
    require(all(node.tag == "testsuite" for node in root), "unexpected report element")
    cases = root.findall("./testsuite/testcase")
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    require(
        len(identities) == len(EXPECTED[phase]) and set(identities) == EXPECTED[phase],
        "missing/duplicate/unexpected test identity",
    )
    groups = Counter(classname for classname, _ in identities)
    require(len(root) == len(groups), "unexpected/duplicate suite")
    require(
        Counter(suite.get("name") for suite in root)
        == Counter({name: 1 for name in groups}),
        "wrong suite identity",
    )
    for node in [root, *root]:
        count = len(cases) if node is root else groups[node.get("name")]
        require(int(node.get("tests", "-1")) == count, "wrong test count")
        for key in ("failures", "errors", "skipped", "disabled"):
            require(
                int(node.get(key, "-1" if key in {"failures", "errors"} else "0")) == 0,
                f"missing/nonzero {key}",
            )
    for suite in root:
        require(len(suite) == groups[suite.get("name")], "wrong suite case count")
        for case in suite:
            require(
                case.tag == "testcase" and case.get("classname") == suite.get("name"),
                "wrong case/suite",
            )
            require(bool(case.get("timestamp")), "missing execution timestamp")
            require(
                all(child.tag in {"system-out", "system-err"} for child in case),
                "failure/skip/retry/unknown result",
            )
    return sorted(identities)


def verify(out):
    source = json.loads((out / "source.json").read_text())
    tools = json.loads((out / "tools.json").read_text())
    require(
        tools["versions"] == TOOL_VERSIONS and tools["sha256"] == common.TOOL_HASHES,
        "unverified tool identity",
    )
    require(
        source["head"]
        == os.environ["CANDIDATE_SHA"]
        == os.environ["WORKFLOW_SHA"]
        == run("git", "rev-parse", "HEAD"),
        "source changed",
    )
    require(
        source["base"] == BASE and source["base_tree"] == BASE_TREE,
        "wrong source receipt",
    )
    require(
        set(source["files"]) == set(PINS) | CI_FILES | SUPPORT,
        "incomplete source receipt",
    )
    require(not run("git", "status", "--porcelain=v1"), "dirty source after run")
    for path, identity in source["files"].items():
        require(digest(path) == identity["sha256"], f"source changed: {path}")
    results = {}
    for phase in EXPECTED:
        directory = out / phase
        for name in ("test.exit", "tee.exit", "report-copy.exit"):
            require(
                (directory / name).read_text().strip() == "0",
                f"{phase}: {name} missing/failed",
            )
        require(
            shlex.split((directory / "command.txt").read_text()) == command(phase),
            "unexpected command",
        )
        require(
            (directory / "native-tests.log").stat().st_size > 0,
            "missing original output",
        )
        results[phase] = validate_report(directory / "junit.xml", phase)
    return results


def main():
    mode, destination, *extra = sys.argv[1:]
    if mode in {"command", "filter"}:
        print(
            shlex.join(command(destination))
            if mode == "command"
            else expression(destination)
        )
        return
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    try:
        require(not extra, "unexpected arguments")
        result = {"bind": bind, "tools": common.tools, "verify": verify}[mode](out)
        write(out, f"{mode}-status.json", {"status": "passed", "result": result})
    except Exception as error:
        write(out, f"{mode}-status.json", {"status": "failed", "error": str(error)})
        raise


if __name__ == "__main__":
    main()

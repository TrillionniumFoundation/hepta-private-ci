#!/usr/bin/env python3
"""Source-bound five-lib/four-integration/ten-bootstrap qualification, not a whole-suite claim."""

from collections import Counter
from datetime import datetime
import json
import re
import os
from pathlib import Path
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

import native_fixture_evidence as common

BASE = "ca2efe465139b1d93a282d74e311491d57ba8df1"
BASE_TREE = "8df7fe9bddae199f495433ea194806a065e7ae80"
PINS = {
    ".github/scripts/native_fixture_evidence.py": "59f906f12705ff3cc3cc9377873e99ec7d1bbc5211cc961e39d53b6df78d51fd",
    ".github/scripts/native_recovery_evidence.py": "db788c529e53989a7af5fc70a20490f79a6590dddb0783c588c2ac4c4410340a",
    ".github/scripts/test_native_recovery_evidence.py": "ae424de08714fe1dfb554f32ccabca44ae1148946ea6694072800df36cc91d41",
    ".github/workflows/hepta-native-preflight-reads.yml": "6c96542785180afe1071acfa7bc4ab053c222682fabbf02d85d948af3595f6c3",
    ".github/workflows/hepta-native-recovery.yml": "20ec8d722f7cb2261d1dbe762540017707fa7e8c2ecb143f310ccc32763764ae",
    "codex-rs/.config/nextest.toml": "e1ceb1d0d308dc4180dd66d89639d3cf4fda08c44da5afcef52eb17709ce5217",
    "codex-rs/Cargo.lock": "3b4e7f8b39d6fad51bcde7b15647882d30e6d80e25d7e81ca62cebfa95643a03",
    "codex-rs/Cargo.toml": "1e2e3d7e2b431704023689c0938e16cccf6dd5cdd6312c232c57e8e94e30d2a5",
    "codex-rs/hepta-agentd/Cargo.toml": "e7b95ad191e37587975961d64b00d7ae0a2e4de3dbf485bda458771a06a1af83",
    "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs": "6daedad42ace5196b041b42797b39beacb91a7211b70428e6583a8bfbd975950",
    "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs": "d89ea0a6290adbbc0decf468c37ef3447edda48dff69ae95d1b2fde598f7903c",
    "codex-rs/hepta-agentd/tests/support/cognitive_recovery_snapshot.rs": "24497b34a69d2b2227c7a2e015d1d7bf3853672ccb2a5e1e7cc20aafc236ec78",
    "codex-rs/hepta-memory/BUILD.bazel": "a6ba8b3463e2c2656143260ee46283628da718aef968fd214f0b9e548974be84",
    "codex-rs/hepta-memory/Cargo.toml": "5ec9e7bd2a5757cc6241351e65d93cb35812d960ba4516343b4cd66dbbeb016c",
    "codex-rs/hepta-memory/src/cognitive_database_crash_tests.rs": "616dd1905038210f327a9142e76c95f3c11ca874144f4707cd4df458d61c6f3b",
    "codex-rs/hepta-memory/src/cognitive_database_init_tests.rs": "0515aa0f52c18b84abebc2afddca3e886c91f12e2e776abce23faec9bbbc754d",
    "codex-rs/hepta-memory/src/cognitive_database_lock_tests.rs": "9b6a68941bb697ff9faafae8dff4ade0042f9da1fda5c1ba77ac29e0d0808faf",
    "codex-rs/hepta-memory/src/cognitive_store.rs": "f54d3b6f016d751540a5ec9fb7795b38378181598ac1b37538c3c58468eb5f59",
    "codex-rs/hepta-memory/src/cognitive_store_lifecycle_tests.rs": "a8b942fec47a920006fbc2b06685d06acb73ded75023d5dd4dcfd94d0cecba62",
    "codex-rs/hepta-memory/src/cognitive_store_recovery.rs": "0ce1dd6a1f73bd7c82c778fd85fc70e8f237d2c1309f1c5aa13cb8aa1fe83deb",
    "codex-rs/hepta-memory/src/cognitive_test_support.rs": "8547bec659250c636a9997cdf537dd3e155aeadf76dcfd4ed0ab4161b0c1a708",
    "codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs": "6c4c7ad0476b20a2c806a80b0a9b9dfb1c67209d609f4bfe485256125908c3c4",
    "codex-rs/hepta-memory/src/lib.rs": "20db65ce7c37c61cd914ede18e626cd986b9dffbd54ccccb87f80be16746ae6a",
    "codex-rs/rust-toolchain.toml": "570656042681cfd8795403a455baf9a33035331a07db0645e866bbcea89a3d64",
    "codex-rs/rustfmt.toml": "384d5d8a1366a86cd6fc01aecde2b0a5806a9e77073ff53abd97b4f6cad94d1c",
    "codex-rs/state/BUILD.bazel": "4bdf532e9243f6b91bf33beff3de0533887f2cbdb7e7ec14ad74ad42d44c4170",
    "codex-rs/state/Cargo.toml": "2da10f840265545592862302111b14b4e6ae83d3e0ed567e8fb1a1c4ecd12b3d",
    "codex-rs/state/src/sqlite.rs": "2de55524f4ac31174770d961883921183a17de8a6199b1105bf145026b4136c0",
    "codex-rs/state/src/sqlite_bootstrap.rs": "8fe58c99a0ecc0ee1d690ae6170d30c3797c57fa05364c18e32e14577af47beb",
    "codex-rs/state/src/sqlite_recovery.rs": "30e215e7e9ae63a314b94c0afff70e8bba9ebd6f272c0681a673d10a70666c03",
    "codex-rs/state/src/sqlite_recovery_image.rs": "60610912a99967c9055b2275a5d1c0e7b96cd4d769279b630b0d44cbe46d5dac",
    "justfile": "74f869224eba12fc4212b043428e7f5b35b551d26f5b06161c25d8aca525f124",
    "scripts/just-shell.py": "444d6b328d44abf6453b77b6acce2a0c881fc162ff30b20f352c85067797fbe9",
    "scripts/run-nextest.py": "45c4e35d1ff24840d9e1e05331af0b89475bfe1aec3231afc56fecb8cea66127",
}
CHANGED_SOURCES = {
    "codex-rs/hepta-memory/src/cognitive_database_init_tests.rs",
    "codex-rs/state/src/sqlite_bootstrap.rs",
    "codex-rs/hepta-memory/src/cognitive_database_lock_tests.rs",
    "codex-rs/hepta-memory/src/cognitive_database_crash_tests.rs",
    "codex-rs/state/src/sqlite_recovery.rs",
    "codex-rs/hepta-memory/src/cognitive_store.rs",
    "codex-rs/hepta-memory/src/lane_c_snapshot_tests.rs",
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
    "codex-rs/.config/nextest.toml",
    ".github/workflows/hepta-private-bootstrap.yml",
    ".github/scripts/test_native_bootstrap_evidence.py",
    ".github/scripts/native_bootstrap_evidence.py",
}
SUPPORT = {
    "codex-rs/rustfmt.toml",
    ".github/scripts/native_recovery_evidence.py",
    "scripts/run-nextest.py",
    "codex-rs/hepta-agentd/Cargo.toml",
    ".github/scripts/native_fixture_evidence.py",
    "codex-rs/state/BUILD.bazel",
    "codex-rs/hepta-memory/Cargo.toml",
    "codex-rs/Cargo.toml",
    "codex-rs/hepta-memory/src/lib.rs",
    "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs",
    "codex-rs/Cargo.lock",
    "codex-rs/state/Cargo.toml",
    "codex-rs/state/src/sqlite_recovery_image.rs",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/hepta-agentd/tests/support/cognitive_recovery_snapshot.rs",
    "codex-rs/hepta-memory/src/cognitive_test_support.rs",
    ".github/workflows/hepta-native-preflight-reads.yml",
    "codex-rs/state/src/sqlite.rs",
    "justfile",
    "scripts/just-shell.py",
    "codex-rs/hepta-memory/src/cognitive_store_lifecycle_tests.rs",
    "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs",
    "codex-rs/hepta-memory/src/cognitive_store_recovery.rs",
    ".github/workflows/hepta-native-recovery.yml",
    ".github/scripts/test_native_recovery_evidence.py",
    "codex-rs/hepta-memory/BUILD.bazel",
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
EXPECTED["bootstrap"] = {
    ("codex-hepta-memory", name)
    for name in [
        "cognitive_store::database_init_tests::abrupt_child_keeps_private_sidecars_and_public_exact_cut_recovery",
        "cognitive_store::database_init_tests::recovery_does_not_repair_an_unsafe_existing_sidecar",
        "cognitive_store::database_init_tests::existing_private_bytes_are_neither_truncated_nor_rewritten",
        "cognitive_store::database_init_tests::existing_links_and_restrictive_permissions_are_rejected_without_repair",
        "cognitive_store::database_init_tests::existing_fifo_is_rejected_without_waiting_for_a_peer",
        "cognitive_store::database_init_tests::open_rejects_existing_nonprivate_main_without_repair",
        "cognitive_store::database_init_tests::crash_tests::abrupt_bootstrap_fresh_process_recovery_new_write_survives_third_process",
        "cognitive_store::database_init_tests::lock_tests::existing_main_validation_preserves_live_sqlite_posix_locks",
        "cognitive_store::database_init_tests::lock_tests::competing_first_opens_keep_private_consistent_state_or_fail_closed",
        "lane_c_snapshot_tests::retained_cut_detects_old_valid_backup_after_ordinary_reopen",
    ]
}

require, run, digest, write = common.require, common.run, common.digest, common.write


def expression(phase):
    return " | ".join(f"test(={name})" for _, name in sorted(EXPECTED[phase]))


def command(phase):
    args = ["just", "test", "--locked", "-p"]
    args += (
        ["codex-hepta-memory", "--lib"]
        if phase in {"owning", "bootstrap"}
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
        f"native-bootstrap-{phase}",
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


def validate_report(path, phase, started=None):
    root = ET.parse(path).getroot()
    require(
        root.tag == "testsuites" and root.get("name") == "native-bootstrap",
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
            if started is not None:
                executed = datetime.fromisoformat(
                    case.get("timestamp").replace("Z", "+00:00")
                )
                require(
                    executed.tzinfo is not None and executed.timestamp() >= started,
                    "stale report",
                )
            require(
                all(child.tag in {"system-out", "system-err"} for child in case),
                "failure/skip/retry/unknown result",
            )
    return sorted(identities)


def validate_log(path, phase):
    text = re.sub(r"\x1b\[[0-9;]*m", "", path.read_text())
    records = re.findall(
        r"(?m)^\s*(PASS|FAIL|TIMEOUT|LEAK|SKIP|RETRY)\s+\[[^\n]*?\]\s+(?:\([^)]+\)\s+)?(\S+)\s+(\S+)\s*$",
        text,
    )
    require(len(records) == len(EXPECTED[phase]), "missing/extra native log records")
    require(
        all(status == "PASS" for status, _, _ in records),
        "native log failure/skip/retry",
    )
    require(
        {(owner, name) for _, owner, name in records} == EXPECTED[phase],
        "native log identities differ",
    )


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
    require(
        source["tree"] == run("git", "rev-parse", "HEAD^{tree}"), "wrong candidate tree"
    )
    for path, identity in source["files"].items():
        require(
            identity["blob"] == run("git", "rev-parse", f"HEAD:{path}"),
            "wrong source blob",
        )
    require((out / "rustfmt.exit").read_text().strip() == "0", "formatter failed")
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
        started = float((directory / "started-unix.txt").read_text())
        require(started > 0, "invalid phase start")
        validate_log(directory / "native-tests.log", phase)
        results[phase] = validate_report(directory / "junit.xml", phase, started)
    return results


def seal(out):
    # Separate always step: verification's tee has already closed its log.
    # Never seal while a producer is still appending an inventoried file.
    destination = out / "artifact-seal.json"
    require(not destination.exists(), "refuse to replace an existing artifact seal")
    files = {}
    for path in sorted(out.rglob("*")):
        require(not path.is_symlink(), "artifact contains symlink")
        if path.is_file():
            files[str(path.relative_to(out))] = {
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
    require(bool(files), "cannot seal empty evidence")
    write(
        out,
        "artifact-seal.json",
        {"schema": "hepta.bootstrap.artifact-seal.v1", "files": files},
    )


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
        if mode == "seal":
            seal(out)
            return
        result = {"bind": bind, "tools": common.tools, "verify": verify}[mode](out)
        write(out, f"{mode}-status.json", {"status": "passed", "result": result})
    except Exception as error:
        write(out, f"{mode}-status.json", {"status": "failed", "error": str(error)})
        raise


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Bind the two-fixture source and fail closed on incomplete nextest evidence."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

BASE = "f2144a2451e0ca03f8c91e0c30755970cc1e4867"
BASE_TREE = "a28c0127586067aaca9318cbe7c5b008d04e2941"
LOCK = "a34342416c6b3cefb31d5ca7043f29deea6ce990"
FIXTURES = {
    "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs": "6daedad42ace5196b041b42797b39beacb91a7211b70428e6583a8bfbd975950",
    "codex-rs/hepta-agentd/tests/cognitive_store_product_writer.rs": "04b2aa858a58a2525826c4c8a76d10310a410baddb9ba65be6fe3413bed17b73",
}
CI_FILES = {
    ".github/workflows/hepta-native-memory-fixtures.yml",
    ".github/scripts/native_fixture_evidence.py",
    ".github/scripts/test_native_fixture_evidence.py",
    "codex-rs/.config/nextest.toml",
}
EXPECTED = {
    (
        "codex-hepta-agentd::cognitive_product_e2e",
        "real_agentd_remember_recall_correct_and_forget_revalidate_physical_sends",
    ),
    (
        "codex-hepta-agentd::cognitive_store_product_writer",
        "agentd_product_host_commits_through_canonical_cognitive_store",
    ),
}
TOOL_HASHES = {
    "just": "50cd9b4a47c26a2570a0cca1bf86a106290b1cd35b131630696f63b9fbd1400d",
    "cargo-nextest": "7f557542ea0d9d7218c2d564987a2cebf367de1d0f9eca45f93f270932a3d9ff",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(out, name, value):
    (out / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def bind(out):
    head = run("git", "rev-parse", "HEAD")
    require(head == os.environ["CANDIDATE_SHA"], "checkout/event SHA mismatch")
    require(
        run("git", "rev-parse", f"{BASE}^{{tree}}") == BASE_TREE, "wrong baseline tree"
    )
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, head], check=True)
    require(not run("git", "status", "--porcelain=v1"), "dirty source")
    changed = set(
        run("git", "diff", "--no-renames", "--name-only", BASE, head).splitlines()
    )
    require(changed == set(FIXTURES) | CI_FILES, "unexpected/missing candidate paths")
    require(run("git", "rev-parse", "HEAD:codex-rs/Cargo.lock") == LOCK, "lock changed")
    for path, expected in FIXTURES.items():
        require(digest(path) == expected, f"unreviewed fixture: {path}")
    require(
        digest("codex-rs/.config/nextest.toml")
        == "0aeb77fbd48d31636e73c2759b13b45cd6259c48a08dc955f164361e585cc6b7",
        "unreviewed nextest configuration",
    )
    files = {}
    for path in sorted(
        changed
        | {
            "codex-rs/Cargo.lock",
            "justfile",
            "scripts/run-nextest.py",
            "scripts/just-shell.py",
            "codex-rs/rust-toolchain.toml",
        }
    ):
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


def tools(out):
    versions = {
        name: run(name, "--version")
        for name in ("rustc", "cargo", "just", "cargo-nextest")
    }
    require(
        versions["rustc"].splitlines()[0] == "rustc 1.95.0 (59807616e 2026-04-14)",
        "wrong Rust",
    )
    require(
        versions["cargo"].splitlines()[0] == "cargo 1.95.0 (f2d3ce0bd 2026-03-21)",
        "wrong Cargo",
    )
    require(versions["just"] == "just 1.59.0", "wrong just")
    require(
        versions["cargo-nextest"].splitlines()[0]
        == "cargo-nextest 0.9.149 (3fe4ef319 2026-10-20)",
        "wrong nextest",
    )
    hashes = {name: digest(shutil.which(name)) for name in TOOL_HASHES}
    require(hashes == TOOL_HASHES, "tool archive/binary identity mismatch")
    write(
        out,
        "tools.json",
        {
            "versions": versions,
            "sha256": hashes,
            "rustc_verbose": run("rustc", "-Vv"),
            "runner": {
                key: os.environ.get(key)
                for key in (
                    "ImageOS",
                    "ImageVersion",
                    "RUNNER_ARCH",
                    "GITHUB_RUN_ID",
                    "GITHUB_RUN_ATTEMPT",
                )
            },
        },
    )


def validate_report(path):
    root = ET.parse(path).getroot()
    require(
        root.tag == "testsuites" and root.get("name") == "native-fixtures",
        "wrong report",
    )
    require(
        all(child.tag == "testsuite" for child in root), "unexpected report element"
    )
    cases = root.findall("./testsuite/testcase")
    require(len(cases) == 2, "expected exactly two test cases")
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    require(
        len(set(identities)) == 2 and set(identities) == EXPECTED,
        "missing/duplicate/unexpected test",
    )
    require(len(root.findall("testsuite")) == 2, "unexpected test suite")
    for node in [root, *root.findall("testsuite")]:
        expected_count = 2 if node is root else len(node.findall("testcase"))
        require(int(node.get("tests", "-1")) == expected_count, "test count mismatch")
        for key in ("failures", "errors", "skipped", "disabled"):
            require(
                int(node.get(key, "-1" if key in {"failures", "errors"} else "0")) == 0,
                f"missing/nonzero {key}",
            )
    for suite in root.findall("testsuite"):
        require(
            all(child.tag == "testcase" for child in suite), "unexpected suite element"
        )
        require(len(suite.findall("testcase")) == 1, "unexpected suite test count")
        require(
            suite.get("name") == suite.find("testcase").get("classname"),
            "suite identity mismatch",
        )
    for case in cases:
        require(case.get("timestamp") is not None, "missing execution timestamp")
        require(
            all(child.tag in {"system-out", "system-err"} for child in case),
            "failure/skip/retry/unknown result",
        )
    return sorted(identities)


def verify(out):
    require(
        (out / "source.json").is_file() and (out / "tools.json").is_file(),
        "missing identity evidence",
    )
    source = json.loads((out / "source.json").read_text())
    require(
        source["head"]
        == os.environ["CANDIDATE_SHA"]
        == run("git", "rev-parse", "HEAD"),
        "source changed",
    )
    require(not run("git", "status", "--porcelain=v1"), "source changed during run")
    for path, identity in source["files"].items():
        require(digest(path) == identity["sha256"], f"source changed: {path}")
    require(
        (out / "test.exit").read_text().strip() == "0",
        "original wrapper failed or was not run",
    )
    require((out / "tee.exit").read_text().strip() == "0", "test log capture failed")
    return validate_report(out / "junit.xml")


def main():
    mode, destination = sys.argv[1:]
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    try:
        result = {"bind": bind, "tools": tools, "verify": verify}[mode](out)
        write(out, f"{mode}-status.json", {"status": "passed", "result": result})
    except Exception as error:
        write(out, f"{mode}-status.json", {"status": "failed", "error": str(error)})
        raise


if __name__ == "__main__":
    main()

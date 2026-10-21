#!/usr/bin/env python3
"""Run the fixed Windows acquisition cases and two production-only reversions."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = "codex-rs/utils/path-utils/src/private_state_windows_directory.rs"
FIXTURES = ROOT / ".github/fixtures/windows-private-state-acquisition"
PREFIX = "private_state_windows::directory::tests::"
CREATION = PREFIX + "rejects_junction_before_creating_private_leaf"
SUBSTITUTION = PREFIX + "rejects_ancestor_substitution_at_retained_open"
SOURCE_SHA256 = "8c7552e3a45f2bf67f2f6fbd66036e4d71306b1cc40a27a6c8d43d6aee0101fb"
PATCHES = {
    "unchecked-create": "93ed0742de0e4cfe226334fd2f71f1129ee42125f214ecf77297916d97696369",
    "path-check-open": "2afdd0034ac20e4a1d86e73063eea74eac1eccd09bf74b511d48dad3616efe73",
}
COMMAND = [
    "just",
    "test",
    "--locked",
    "-p",
    "codex-utils-path",
    "--lib",
    "-E",
    f"test({PREFIX})",
    "--test-threads",
    "1",
    "--no-tests",
    "fail",
    "--retries",
    "0",
    "--success-output",
    "immediate",
    "--failure-output",
    "immediate",
    "--status-level",
    "all",
    "--final-status-level",
    "all",
]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def check_result(lane, returncode, output):
    """A compiler error, timeout, wrong failure or incomplete fixture cannot qualify."""
    require(lane in ("positive", *PATCHES), "unrecognized qualification lane")
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output).replace("\r\n", "\n")
    statuses = {}
    for status, name in re.findall(
        r"^\s*(PASS|FAIL)\s+\[[^\]\r\n]+\]\s+codex-utils-path\s+(\S+)\s*$",
        clean,
        re.MULTILINE,
    ):
        require(
            name not in statuses or statuses[name] == status,
            "inconsistent test status",
        )
        statuses[name] = status
    expected = {CREATION: "PASS", SUBSTITUTION: "PASS"}
    if lane == "unchecked-create":
        expected[CREATION] = "FAIL"
    if lane == "path-check-open":
        expected[SUBSTITUTION] = "FAIL"
    require(statuses == expected, f"wrong exact test outcomes: {statuses}")
    require(returncode == (0 if lane == "positive" else 1), "wrong command exit code")
    summaries = re.findall(r"^\s*Summary\s+\[[^\]]+\]\s+(.*)$", clean, re.MULTILINE)
    require(len(summaries) == 1, "missing or duplicate nextest summary")
    counts = (
        "2 tests run: 2 passed"
        if lane == "positive"
        else "2 tests run: 1 passed, 1 failed"
    )
    require(
        re.fullmatch(re.escape(counts) + r", [0-9]+ skipped", summaries[0]),
        "wrong test counts",
    )
    expected_observations = {
        "creation": "denied=true created="
        + ("true" if lane == "unchecked-create" else "false"),
        "substitution": "swapped=true denied=false redirected=true"
        if lane == "path-check-open"
        else "swapped=true denied=true redirected=false",
    }
    observations = re.findall(
        r"^\s*PRIVATE_STATE_ACQUISITION (creation|substitution) (.*)$",
        clean,
        re.MULTILINE,
    )
    require(
        len(observations) == 2 and dict(observations) == expected_observations,
        "missing actual filesystem observations",
    )
    return {"statuses": statuses, "observations": dict(observations)}


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def main():
    require(sys.platform == "win32", "native Windows is required; no platform skip")
    require(
        len(sys.argv) == 2,
        "usage: check_windows_private_state_acquisition.py EVIDENCE_DIR",
    )
    evidence = Path(sys.argv[1]).resolve()
    require(not evidence.is_relative_to(ROOT), "evidence must be outside the checkout")
    evidence.mkdir(parents=True, exist_ok=False)
    source = ROOT / PRODUCTION
    original = source.read_bytes()
    head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    require(
        not git("status", "--porcelain", "--untracked-files=no"),
        "checkout must start clean",
    )
    require(
        sha256(original) == SOURCE_SHA256,
        "production source differs from frozen controls",
    )
    manifest = {
        "source_head": head,
        "source_tree": tree,
        "production_path": PRODUCTION,
        "production_sha256": SOURCE_SHA256,
        "command": COMMAND,
        "lanes": [],
        "rustc": subprocess.check_output(
            ["rustc", "--version", "--verbose"], cwd=ROOT / "codex-rs", text=True
        ),
        "qualified": False,
        "restored": False,
    }
    try:
        for lane in ("positive", *PATCHES):
            record = {"lane": lane}
            manifest["lanes"].append(record)
            try:
                if lane != "positive":
                    patch = FIXTURES / f"{lane}.patch"
                    record["patch_sha256"] = sha256(patch.read_bytes())
                    require(
                        record["patch_sha256"] == PATCHES[lane], "frozen patch changed"
                    )
                    # The full source SHA pins zero-context patch locations;
                    # context-only spaces would fail repository diff checks.
                    subprocess.run(
                        ["git", "apply", "--check", "--unidiff-zero", str(patch)],
                        cwd=ROOT,
                        check=True,
                    )
                    subprocess.run(
                        ["git", "apply", "--unidiff-zero", str(patch)],
                        cwd=ROOT,
                        check=True,
                    )
                    require(
                        git("diff", "--name-only") == PRODUCTION,
                        "negative control must change exactly the acquisition implementation",
                    )
                    (evidence / f"{lane}.patch").write_bytes(patch.read_bytes())
                require(
                    git("diff", "--cached") == "", "negative control changed the index"
                )
                record["production_sha256"] = sha256(source.read_bytes())
                (evidence / f"{lane}.rs").write_bytes(source.read_bytes())
                log = evidence / f"{lane}.log"
                with log.open("wb") as stream:
                    result = subprocess.run(
                        COMMAND,
                        cwd=ROOT / "codex-rs",
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        check=False,
                        timeout=600,
                    )
                record["exit_code"] = result.returncode
                raw = log.read_bytes()
                record["log_sha256"] = sha256(raw)
                record.update(
                    check_result(
                        lane, result.returncode, raw.decode("utf-8", "replace")
                    )
                )
                print(json.dumps(record, sort_keys=True), flush=True)
            finally:
                source.write_bytes(original)
                require(git("rev-parse", "HEAD") == head, "source HEAD changed")
                require(
                    not git("status", "--porcelain", "--untracked-files=no"),
                    "qualification failed to restore the original clean source",
                )
        manifest["qualified"] = True
    finally:
        manifest["restored"] = source.read_bytes() == original and not git(
            "status", "--porcelain", "--untracked-files=no"
        )
        (evidence / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()

"""Native Windows positive cases and two exact production-only reversions."""

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
PREFIX = "sqlite_recovery::windows_tests::"
PIN = PREFIX + "retained_sources_deny_same_size_write_and_byte_identical_replacement"
SNAPSHOT = PREFIX + "attributes_are_part_of_the_complete_retained_identity"
COMMAND = [
    "just", "test", "--locked", "-p", "codex-state", "--lib", "-E",
    f"test({PIN}) | test({SNAPSHOT})", "--test-threads", "1",
    "--no-tests", "fail", "--retries", "0", "--success-output", "immediate",
    "--failure-output", "immediate", "--status-level", "all", "--final-status-level", "all",
]


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_result(lane, returncode, output):
    require(lane in ("positive", "shared-source", "skip-snapshot"), "unexpected lane")
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output).replace("\r\n", "\n")
    statuses = {}
    for status, name in re.findall(
        r"^\s*(PASS|FAIL)\s+\[[^\]\r\n]+\]\s+codex-state\s+(\S+)\s*$", clean, re.MULTILINE
    ):
        require(name not in statuses or statuses[name] == status, "inconsistent status")
        statuses[name] = status
    expected = {PIN: "PASS", SNAPSHOT: "PASS"}
    if lane == "shared-source":
        expected[PIN] = "FAIL"
    if lane == "skip-snapshot":
        expected[SNAPSHOT] = "FAIL"
    require(statuses == expected, f"wrong exact test outcomes: {statuses}")
    require(returncode == (0 if lane == "positive" else 1), "wrong command exit")
    summaries = re.findall(r"^\s*Summary\s+\[[^\]]+\]\s+(.*)$", clean, re.MULTILINE)
    counts = "2 tests run: 2 passed" if lane == "positive" else "2 tests run: 1 passed, 1 failed"
    require(len(summaries) == 1 and re.fullmatch(re.escape(counts) + r", [0-9]+ skipped", summaries[0]), "incomplete test summary")
    observations = re.findall(r"^\s*WINDOWS_RECOVERY (source_pin|metadata) (.*)$", clean, re.MULTILINE)
    expected_observations = {
        "source_pin": "write_denied=false replace_denied=false" if lane == "shared-source" else "write_denied=true replace_denied=true",
        "metadata": "changed=true rejected=false" if lane == "skip-snapshot" else "changed=true rejected=true",
    }
    require(len(observations) == 2 and dict(observations) == expected_observations, "missing actual filesystem attack observations")
    if lane == "shared-source":
        require("assertion" in clean and "left" in clean and "right" in clean, "expected source sharing assertion missing")
    if lane == "skip-snapshot":
        require("a retained handle does not excuse metadata drift" in clean, "expected metadata assertion missing")
    return {"statuses": statuses, "observations": dict(observations)}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    require(sys.platform == "win32", "real native Windows required; no skip")
    require(len(sys.argv) == 2, "usage: run.py EVIDENCE_DIR")
    evidence = Path(sys.argv[1]).resolve()
    require(not evidence.is_relative_to(ROOT), "evidence must be outside checkout")
    evidence.mkdir(parents=True, exist_ok=False)
    controls = json.loads((HERE / "controls.json").read_text())
    require([item["lane"] for item in controls] == ["shared-source", "skip-snapshot"], "wrong controls")
    originals = {item["production_path"]: (ROOT / item["production_path"]).read_bytes() for item in controls}
    baseline_diff = git("diff", "--binary", "HEAD")
    baseline_status = git("status", "--porcelain", "--untracked-files=all")
    baseline_index = git("write-tree")
    (evidence / "baseline.patch").write_bytes(baseline_diff)
    manifest = {
        "source_sha": git("rev-parse", "HEAD").decode().strip(),
        "source_tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "baseline_diff_sha256": sha(baseline_diff), "baseline_status": baseline_status.decode(),
        "input_head_qualified": False, "command": COMMAND, "lanes": [], "restored": False,
        "qualified_native_controls": False,
    }
    try:
        for lane in ["positive", *[item["lane"] for item in controls]]:
            record = {"lane": lane, "status": "running"}
            manifest["lanes"].append(record)
            (evidence / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            for item in controls:
                require(sha((ROOT / item["production_path"]).read_bytes()) == item["source_sha256"], "source differs from frozen control")
            if lane != "positive":
                item = next(item for item in controls if item["lane"] == lane)
                patch = HERE / item["patch"]
                require(sha(patch.read_bytes()) == item["patch_sha256"], "control patch changed")
                subprocess.run(["git", "apply", "--check", "--unidiff-zero", str(patch)], cwd=ROOT, check=True)
                subprocess.run(["git", "apply", "--unidiff-zero", str(patch)], cwd=ROOT, check=True)
                require(sha((ROOT / item["production_path"]).read_bytes()) == item["mutated_sha256"], "mutation differs from exact frozen postimage")
            for path in originals:
                (evidence / f"{lane}-{Path(path).name}").write_bytes((ROOT / path).read_bytes())
            with (evidence / f"{lane}.log").open("wb") as log:
                try:
                    result = subprocess.run(COMMAND, cwd=ROOT / "codex-rs", stdout=log, stderr=subprocess.STDOUT, timeout=1200, check=False)
                    record["exit_code"] = result.returncode
                except (OSError, subprocess.TimeoutExpired) as error:
                    record["status"] = "failed_to_complete"
                    record["error"] = str(error)
                    raise
            output = (evidence / f"{lane}.log").read_text(errors="replace")
            try:
                record.update(check_result(lane, result.returncode, output))
            except RuntimeError as error:
                record.update(status="failed_validation", error=str(error))
                raise
            record["status"] = "passed"
            for path, data in originals.items():
                (ROOT / path).write_bytes(data)
            require(git("diff", "--binary", "HEAD") == baseline_diff, "control changed unrelated source")
            require(git("status", "--porcelain", "--untracked-files=all") == baseline_status, "control left extra source")
            require(git("write-tree") == baseline_index, "control changed index")
        manifest["qualified_native_controls"] = True
    finally:
        for path, data in originals.items():
            (ROOT / path).write_bytes(data)
        restored = (
            git("diff", "--binary", "HEAD") == baseline_diff
            and git("status", "--porcelain", "--untracked-files=all") == baseline_status
            and git("write-tree") == baseline_index
        )
        manifest["restored"] = restored
        (evidence / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        require(restored, "original source was not exactly restored")


if __name__ == "__main__":
    main()

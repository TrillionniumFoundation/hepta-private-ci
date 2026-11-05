"""Run one owned ACL counterfactual after the unchanged Windows unit target.

This script never converts the preceding target's failure into success. A valid
counterfactual is a physical replacement mutation followed by one exact failing
assertion, with the positive source restored in finally. It is not B11 closure.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET


TARGET = "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests"
CASE = "acl::tests::deny_repair_rejects_a_replaced_path_before_mutating_either_object"
SOURCE = "codex-rs/windows-sandbox-rs/src/acl_deny.rs"
TEST_SOURCE = "codex-rs/windows-sandbox-rs/src/acl_tests.rs"
POSITIVE = "da5346c220c41cf0c83f62b596132c74c02284d8"
NEGATIVE = "0baeb6ec2f3bfd0964be6d014fc5d80d890ea3d7"
TEST_BLOB = "ec0264a7615097bec1b554cb60918b4f4662eec2"
CHECK = b'''    ensure!(
        actual == expected,
        "deny repair path no longer identifies the retained object: {}",
        path.display()
    );'''
IGNORED_CHECK = b"    let _ = actual == expected;"
MARKER = "deny_repair_identity: directory=false returned_ok=true replacement_changed=true original_changed=false"
ASSERTION = "a replacement object must not receive the queried object's deny"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def save(directory, name, value):
    (directory / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_owned_source(path, body):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix="b11-identity-", suffix=".tmp", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    require(result.returncode == 0, f"read-only git command failed: {args!r}: {result.stderr!r}")
    return result.stdout


def canonical(body, expected, description):
    normalized = body.replace(b"\r\n", b"\n")
    require(b"\r" not in normalized, f"unexpected newline representation: {description}")
    require(body == normalized or body == normalized.replace(b"\n", b"\r\n"),
            f"mixed newline representation: {description}")
    require(digest(normalized)["git_blob"] == expected, f"source blob mismatch: {description}")
    return normalized


def source_guard(root, head, expected, dirty):
    require(git(root, "rev-parse", "HEAD").decode().strip() == head, "HEAD changed")
    require(not git(root, "diff", "--cached", "--name-only"), "ordinary index has staged changes")
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all").decode().splitlines()
    require(status == ([f" M {SOURCE}"] if dirty else []), f"unexpected worktree status: {status!r}")
    canonical((root / SOURCE).read_bytes(), expected, SOURCE)
    canonical((root / TEST_SOURCE).read_bytes(), TEST_BLOB, TEST_SOURCE)
    return {"head": head, "head_tree": git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
            "source": digest((root / SOURCE).read_bytes()), "source_canonical_git_blob": expected,
            "tests": digest((root / TEST_SOURCE).read_bytes()), "status": status,
            "index_entries": digest(git(root, "ls-files", "--stage")),
            "locks": {name: digest((root / name).read_bytes()) for name in ("codex-rs/Cargo.lock", "MODULE.bazel.lock")}}


def retained_log(root, head, tree, dirty):
    """Use only exact-target copies from this step's wrapper-owned archive."""
    records = []
    for kind in ("failed-test-logs", "selected-target-test-logs"):
        for path in (root / kind).glob("invocation-*/manifest.json"):
            require(not path.is_symlink(), "collector manifest is a symlink")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if TARGET not in manifest.get("selected_targets", []):
                continue
            require(manifest.get("complete_for_selected_targets") is True and not manifest.get("errors"),
                    "collector target copy is incomplete")
            source = manifest.get("source", {})
            require(source == {"commit": head, "tree": tree, "tracked_worktree_dirty": dirty},
                    "collector source does not match this exact phase")
            selected = {}
            for row in manifest.get("files", []):
                if row.get("target") != TARGET or row.get("testlogs_relative_path") not in {
                    "codex-rs/windows-sandbox-rs/windows-sandbox-rs-unit-tests/test.log",
                    "codex-rs/windows-sandbox-rs/windows-sandbox-rs-unit-tests/test.xml",
                }:
                    continue
                relative = Path(row["archive_relative_path"])
                require(not relative.is_absolute() and ".." not in relative.parts, "unsafe collector member path")
                file = path.parent / relative
                require(file.resolve().is_relative_to(path.parent.resolve()) and not file.is_symlink(),
                        "collector member escapes its invocation")
                body = file.read_bytes()
                require(len(body) == row["bytes"] and hashlib.sha256(body).hexdigest() == row["sha256"],
                        "collector member bytes do not match manifest")
                suffix = Path(row["testlogs_relative_path"]).suffix
                require(suffix not in selected, "duplicate target log or XML")
                selected[suffix] = (body, {"path": str(file), **digest(body)})
            require(set(selected) == {".log", ".xml"}, "missing exact target log/XML")
            records.append((selected, {"path": str(path), **digest(path.read_bytes())}))
    require(len(records) == 1, f"expected one exact current target copy, found {len(records)}")
    return records[0]


def target_terminal(console, expected):
    clean = ANSI.sub("", console.decode("utf-8", errors="strict")).replace("\r", "")
    lines = [line.strip() for line in clean.splitlines() if line.startswith(TARGET + " ")]
    require(len(lines) == 1, "missing or ambiguous exact target summary")
    require("cached" not in lines[0].lower() and "FLAKY" not in lines[0], "cached/retried target is not fresh evidence")
    require(re.fullmatch(re.escape(TARGET) + r"\s+" + expected + r" in [0-9.]+s", lines[0]) is not None,
            f"unexpected target terminal: {lines[0]}")
    return lines[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    original = args.evidence.resolve(strict=True)
    require(original.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)), "evidence must be owned runner temp")
    evidence = original / "acl-identity-counterfactual"
    evidence.mkdir(exist_ok=False)
    report = {"status": "NOT_STARTED", "physical_counterfactual_qualified": False,
              "physical_oracle_reached": False,
              "product_B11": "OPEN", "restored_exact_original_bytes": False}
    mutated = False
    mutation_attempted = False
    error = None
    restore_error = None
    source = root / SOURCE
    original_bytes = None
    negative_bytes = None
    entry = None
    head = git(root, "rev-parse", "HEAD").decode().strip()
    try:
        entry = source_guard(root, head, POSITIVE, False)
        save(evidence, "source-entry.json", entry)
        require(git(root, "show", f"HEAD:{SOURCE}") == canonical(source.read_bytes(), POSITIVE, SOURCE),
                "positive source is not the checked-out commit's blob")
        require(git(root, "show", "HEAD:.github/scripts/run_b11_acl_identity_counterfactual.py").replace(b"\r\n", b"\n")
                == Path(__file__).read_bytes().replace(b"\r\n", b"\n"), "counterfactual script differs from checkout")
        original_status = int((original / "original-bazel-exit-code.txt").read_text().strip())
        require(original_status in {0, 3}, "original target did not reach ordinary test completion")
        require(int((original / "console-copy-exit-code.txt").read_text().strip()) == 0,
                "original full console copy failed")
        require((original / "source-head-tree.txt").read_text().splitlines() == [head, entry["head_tree"]],
                "original target source identity differs from this checkout")
        require(not (original / "source-status-before.txt").read_text().strip()
                and not (original / "source-status-after.txt").read_text().strip(),
                "original target did not retain a clean tracked checkout")
        original_console = (original / "bazel-console.log").read_bytes()
        original_summary = target_terminal(original_console, "PASSED" if original_status == 0 else "FAILED")
        archive = Path(os.environ["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"]).resolve(strict=True)
        require(archive.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)), "original archive is outside runner temp")
        positive, positive_manifest = retained_log(archive, head, entry["head_tree"], False)
        positive_text = ANSI.sub("", positive[".log"][0].decode("utf-8", errors="strict")).replace("\r", "")
        for required in [CASE, "acl::tests::existing_native_deny_does_not_require_write_dac",
                         "acl::tests::native_file_and_directory_repairs_are_idempotent_for_read_and_write",
                         "token::tests::partial_delete_deny_is_repaired_before_native_workspace_writes"]:
            require(len(re.findall(r"^test " + re.escape(required) + r" \.\.\. ok$", positive_text, re.MULTILINE)) == 1,
                    f"original target lacks one exact positive result for {required}")
        require(f"---- {CASE} stdout ----" not in positive_text, "new case failed in original full target")
        save(evidence, "positive-prerequisites.json", {"original_exit_code": original_status,
             "original_summary": original_summary, "console": digest(original_console),
             "collector_manifest": positive_manifest, "files": {k: v[1] for k, v in positive.items()}})

        original_bytes = source.read_bytes()
        positive_body = canonical(original_bytes, POSITIVE, SOURCE)
        require(positive_body.count(CHECK) == 1, "identity enforcement is not unique")
        negative_body = positive_body.replace(CHECK, IGNORED_CHECK)
        require(digest(negative_body)["git_blob"] == NEGATIVE, "negative source is not the approved blob")
        negative_bytes = negative_body if original_bytes == positive_body else negative_body.replace(b"\n", b"\r\n")
        (evidence / "positive-source.original").write_bytes(original_bytes)
        (evidence / "negative-source.original").write_bytes(negative_bytes)
        mutation_attempted = True
        replace_owned_source(source, negative_bytes)
        mutated = True
        before = source_guard(root, head, NEGATIVE, True)
        require(before["index_entries"] == entry["index_entries"] and before["locks"] == entry["locks"], "index/locks changed")
        save(evidence, "source-negative-before.json", before)
        negative_archive = evidence / "bazel-execution-logs"
        negative_archive.mkdir()
        env = os.environ.copy()
        env["CODEX_BAZEL_EXECUTION_LOG_COMPACT_DIR"] = str(negative_archive)
        argv = ["bash", "./.github/scripts/run-bazel-ci.sh", "--print-failed-action-summary",
                "--print-failed-test-logs", "--windows-msvc-host-platform", "--remote-download-toplevel", "--", "test",
                "--platforms=//:windows_x86_64_msvc", "--skip_incompatible_explicit_targets",
                "--test_tag_filters=-argument-comment-lint", "--test_verbose_timeout_warnings", "--test_output=all",
                f"--build_metadata=COMMIT_SHA={os.environ['GITHUB_SHA']}",
                "--build_metadata=TAG_b11_observation_only=true", "--build_metadata=TAG_b11_identity_counterfactual=true",
                "--nocache_test_results", "--flaky_test_attempts=1", f"--test_arg={CASE}", "--test_arg=--exact", "--", TARGET]
        save(evidence, "negative-command.json", {"argv": argv, "cwd": str(root), "source": before,
             "scope": "One new physical case only; original full-target command and its exit remain unchanged."})
        started = time.monotonic()
        with (evidence / "negative-console.log").open("wb") as console_file:
            result = subprocess.run(argv, cwd=root, env=env, stdout=console_file, stderr=subprocess.STDOUT, check=False)
        save(evidence, "negative-command-terminal.json", {"exit_code": result.returncode, "elapsed_seconds": time.monotonic() - started})
        after = source_guard(root, head, NEGATIVE, True)
        save(evidence, "source-negative-after.json", after)
        require(after == before, "negative execution changed guarded source/index/locks")
        require(result.returncode == 3, "negative command must be an ordinary Bazel test failure")
        target_terminal((evidence / "negative-console.log").read_bytes(), "FAILED")
        negative, negative_manifest = retained_log(negative_archive, head, entry["head_tree"], True)
        log = ANSI.sub("", negative[".log"][0].decode("utf-8", errors="strict")).replace("\r", "")
        require(log.splitlines().count(MARKER) == 1, "missing unique physical replacement marker")
        headers = re.findall(r"^---- (.+) stdout ----$", log, re.MULTILINE)
        require(headers == [CASE], "wrong or additional failed test case")
        require(re.search(r"^thread '" + re.escape(CASE) + r"'(?: \([0-9]+\))? panicked at (?:codex-rs[\\/])?windows-sandbox-rs[\\/]src[\\/]acl_tests\.rs:597:9:$", log, re.MULTILINE) is not None,
                "wrong physical assertion location")
        require(ASSERTION in log, "wrong assertion message")
        summaries = re.findall(r"^test result: (.+)$", log, re.MULTILINE)
        require(len(summaries) == 1 and re.fullmatch(r"FAILED\. 0 passed; 1 failed; 0 ignored; 0 measured; 155 filtered out; finished in [0-9.]+s", summaries[0]) is not None,
                "negative must execute precisely one original new case without an ignored test or retry")
        xml = ET.fromstring(negative[".xml"][0])
        cases = xml.findall(".//testcase")
        require(len(cases) == 1 and cases[0].get("status") == "run", "unexpected outer test XML")
        failures = cases[0].findall("error")
        require(len(failures) == 1 and failures[0].get("message") == "exited with error code 101"
                and not cases[0].findall("failure") and not cases[0].findall("skipped"),
                "negative must end at ordinary libtest assertion exit 101, not timeout/unknown exit")
        report.update(status="PHYSICAL_ORACLE_REACHED_PENDING_RESTORE", physical_counterfactual_qualified=True,
                      physical_oracle_reached=True,
                      negative_collector_manifest=negative_manifest, negative_files={k: v[1] for k, v in negative.items()})
    except Exception as exc:
        error = repr(exc)
    finally:
        if mutation_attempted:
            try:
                require(source.read_bytes() in {negative_bytes, original_bytes}, "refusing to overwrite an unexpected source during restore")
                replace_owned_source(source, original_bytes)
                require(source.read_bytes() == original_bytes, "positive source did not restore byte-for-byte")
                final = source_guard(root, head, POSITIVE, False)
                save(evidence, "source-restored.json", final)
                require(final == entry, "final source/index/locks differ from entry")
                report["restored_exact_original_bytes"] = True
            except Exception as exc:
                restore_error = repr(exc)
        report.update(error=error, restore_error=restore_error, source_mutated=mutated,
                      source_mutation_attempted=mutation_attempted,
                      original_target_exit_code_unchanged=True, hard_cancellation_restore_guaranteed=False)
        if error is None and restore_error is None and report["physical_counterfactual_qualified"] and report["restored_exact_original_bytes"]:
            report["status"] = "VALID_NEGATIVE_AND_EXACT_RESTORE"
        else:
            report["status"] = "INVALID_OR_NOT_RUN"
            report["physical_counterfactual_qualified"] = False
        save(evidence, "counterfactual-terminal.json", report)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "VALID_NEGATIVE_AND_EXACT_RESTORE" else 1


if __name__ == "__main__":
    raise SystemExit(main())

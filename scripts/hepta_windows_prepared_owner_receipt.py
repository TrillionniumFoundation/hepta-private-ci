"""Additional native Windows owner evidence; never production sandbox admission."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from hepta_ci_exec import git, observed_test_counts
from hepta_windows_pe_identity import MACHINES, pe_identity, pe_machine


CASES = tuple(
    "process::prepared_context::tests::" + name
    for name in (
        "prepared_process_owner_retains_source_and_root_handles_after_original_base_closes",
        "prepared_process_owner_refuses_changed_acl_before_creating_launch_resources",
        "prepared_process_owner_refuses_acl_drift_at_the_one_use_handoff",
    )
)
SELECTOR = "test(/^process::prepared_context::tests::/)"
COMMAND = [
    "just",
    "test",
    "--locked",
    "-p",
    "codex-windows-sandbox",
    "--lib",
    "-E",
    SELECTOR,
    "--test-threads",
    "1",
    "--no-capture",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(directory, name, value):
    (directory / name).write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load(directory, name):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selected_suite(registry):
    suites = registry["rust-suites"]
    require(len(suites) == 1, "require exactly one Windows library test binary")
    suite_id, suite = next(iter(suites.items()))
    require(
        suite_id
        == suite["binary-id"]
        == suite["package-name"]
        == "codex-windows-sandbox"
        and suite["binary-name"] == "codex_windows_sandbox"
        and suite["kind"] == "lib"
        and suite["status"] == "listed",
        "unexpected native test suite",
    )
    matched = {
        name: row
        for name, row in suite["testcases"].items()
        if row["filter-match"]["status"] == "matches"
    }
    require(
        set(matched) == set(CASES)
        and all(row["ignored"] is False for row in matched.values()),
        "missing, extra or ignored owner case",
    )
    return {
        "suite_id": suite_id,
        "path": suite["binary-path"],
        "required_test_names": list(CASES),
    }


def source_snapshot(directory, phase, original):
    # Keep the original Windows policy: exact Git blobs and tree modes, allowing
    # native Windows symlink placeholders; POSIX executable bits do not apply.
    require(os.name == "nt", "this receipt requires native Windows execution")
    expected = load(original, "source-before.json")
    require(
        expected["native"]
        == {
            "runner": os.environ["HEPTA_CI_RUNNER"],
            "target": os.environ["HEPTA_CI_TARGET"],
            "runner_arch": os.environ["RUNNER_ARCH"],
        }
        and os.environ["RUNNER_OS"] == "Windows",
        "original native source identity differs",
    )
    require(
        expected["tested_sha"] == os.environ["TESTED_SHA"] == git("rev-parse", "HEAD"),
        "tested source changed",
    )
    require(expected["tree"] == git("rev-parse", "HEAD^{tree}"), "tested tree changed")
    require(
        not git(
            "diff", "--cached", "--raw", "--no-ext-diff", "--no-textconv", "HEAD", "--"
        ),
        "staged source changed",
    )
    require(
        not git("ls-files", "--others", "--exclude-standard", "-z"),
        "unexpected untracked source",
    )
    require(
        not any(
            row and (row[0] == "S" or row[0].islower())
            for row in git("ls-files", "-v", "-z").split("\0")
        ),
        "hidden worktree flags",
    )
    overrides = (
        "RUSTC",
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
        "CARGO_BUILD_TARGET",
    )
    require(
        not any(os.environ.get(key) for key in overrides),
        "unexpected compiler override",
    )
    require(
        not any(
            value
            for key, value in os.environ.items()
            if key.startswith("CARGO_TARGET_")
            and key.endswith(("_RUSTFLAGS", "_RUNNER"))
        ),
        "unexpected target override",
    )
    manifest, placeholders = [], 0
    for row in git("ls-tree", "--full-tree", "-r", "-z", "HEAD").split("\0"):
        if not row:
            continue
        metadata, relative = row.split("\t", 1)
        mode, kind, blob = metadata.split()
        require(
            kind == "blob" and mode in {"100644", "100755", "120000"},
            "unsupported source entry",
        )
        path = Path(relative)
        if path.is_symlink():
            require(mode == "120000", "unexpected source symlink")
            data = os.fsencode(os.readlink(path))
        else:
            require(path.is_file(), "source file is missing")
            data = path.read_bytes()
            placeholders += int(mode == "120000")
        actual = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False
        ).hexdigest()
        require(actual == blob, "tracked source bytes differ: " + relative)
        manifest.append([relative, mode, hashlib.sha256(data).hexdigest()])
    require(
        len(manifest) == expected["tracked_files"]
        and placeholders == expected["symlink_placeholders"],
        "tracked source shape changed",
    )
    require(
        hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest()
        == expected["tracked_bytes_sha256"],
        "tracked source inventory changed",
    )
    save(directory, "tracked-" + phase + ".json", manifest)
    save(directory, "source-" + phase + ".json", expected)
    return expected


def execution_receipt(raw, codes):
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw.decode("utf-8", errors="replace"))
    passed, failed = observed_test_counts(text)
    names = re.findall(r"^test (.+?) \.\.\. ok\s*$", text, re.MULTILINE)
    summaries = re.findall(
        r"^[ \t]*Summary\b[^\n]*?(\d+) tests? run:", text, re.MULTILINE
    )
    require(
        type(codes) is list
        and len(codes) == 2
        and all(type(code) is int and code == 0 for code in codes),
        "test or logger failed",
    )
    require(
        passed == 3
        and failed == 0
        and summaries == ["3"]
        and len(re.findall(r"^[ \t]*Summary\b", text, re.MULTILINE)) == 1,
        "incomplete or duplicate three-case summary",
    )
    require(
        len(names) == 3 and set(names) == set(CASES),
        "missing, duplicate or unexpected completed case",
    )
    require(
        not re.search(
            r"^[ \t]*(?:TRY\b|RETRY\b|FLAKY\b|FAIL\b|TIMEOUT\b|TMT\b|LEAK\b|ABORT\b|Summary\b[^\n]*\b[1-9]\d* flaky\b|test .+? \.\.\. (?:FAILED|ignored))",
            text,
            re.MULTILINE,
        ),
        "failed, retried or ignored case",
    )
    return {
        "command": COMMAND,
        "returncode": codes[0],
        "logging_returncode": codes[1],
        "observed_passed_tests": passed,
        "observed_failed_tests": failed,
        "observed_passed_test_names": names,
        "log_sha256": hashlib.sha256(raw).hexdigest(),
    }


def reconcile(
    before,
    after,
    original_after,
    prepared,
    registry_raw,
    before_pe,
    after_pe,
    raw,
    codes,
):
    require(after == before == original_after, "source snapshots disagree")
    require(
        prepared["registry_sha256"] == hashlib.sha256(registry_raw).hexdigest(),
        "registry changed after preparation",
    )
    selected = selected_suite(json.loads(registry_raw))
    require(selected == prepared["selected"], "selected native binary changed")
    require(
        after_pe == before_pe, "actual test PE changed between registry and execution"
    )
    return {
        **execution_receipt(raw, codes),
        "source": after,
        "registry_sha256": prepared["registry_sha256"],
        "actual_test_pe": after_pe,
        "selected": selected,
    }


def main():
    phase, directory = sys.argv[1], Path(sys.argv[2])
    directory.mkdir(parents=True, exist_ok=True)
    original = Path(os.environ["RUNNER_TEMP"]) / "windows-delete-boundary"
    report = {
        "schema": "hepta-windows-prepared-owner-receipt-v2",
        "python_version": sys.version,
        "python_executable": sys.executable,
        "phase": phase,
        "status": "failed",
        "required_test_names": list(CASES),
        "required_exact_cases": 3,
        "production_sandbox_admitted": False,
        "legacy_full_read_qualified": False,
        "child_lifetime_qualified": False,
    }
    try:
        if phase == "before":
            source_snapshot(directory, "before", original)
            for name in ("rustc.txt", "cargo.txt", "just.txt", "nextest.txt"):
                (directory / name).write_bytes((original / name).read_bytes())
            (directory / "original-source-before.json").write_bytes(
                (original / "source-before.json").read_bytes()
            )
        elif phase == "prepare":
            code = int(sys.argv[3])
            report["registry_exit_code"] = code
            save(directory, "registry-exit.json", {"returncode": code})
            require(code == 0, "native registry command failed")
            source_snapshot(directory, "prepared", original)
            selected = selected_suite(load(directory, "registry.json"))
            save(
                directory,
                "pe-before.json",
                pe_identity(selected["path"], os.environ["HEPTA_CI_TARGET"]),
            )
            save(
                directory,
                "prepared.json",
                {
                    "registry_sha256": sha(directory / "registry.json"),
                    "selected": selected,
                },
            )
        elif phase == "run":
            codes = [int(value) for value in sys.argv[3].split()]
            report["actual_test_exit_codes"] = codes
            save(directory, "run-codes.json", codes)
            execution_receipt((directory / "native.log").read_bytes(), codes)
        elif phase == "finish":
            if (directory / "run-codes.json").is_file():
                report["actual_test_exit_codes"] = load(directory, "run-codes.json")
            for step in ("before", "prepare", "run"):
                prior = load(directory, step + "-phase.json")
                require(
                    prior["phase"] == step and prior["status"] == "recorded",
                    "an earlier owner phase did not complete",
                )
            after = source_snapshot(directory, "after", original)
            prepared = load(directory, "prepared.json")
            selected = selected_suite(load(directory, "registry.json"))
            after_pe = pe_identity(selected["path"], os.environ["HEPTA_CI_TARGET"])
            save(directory, "pe-after.json", after_pe)
            report.update(
                reconcile(
                    load(directory, "source-before.json"),
                    after,
                    load(original, "source-after.json"),
                    prepared,
                    (directory / "registry.json").read_bytes(),
                    load(directory, "pe-before.json"),
                    after_pe,
                    (directory / "native.log").read_bytes(),
                    load(directory, "run-codes.json"),
                )
            )
            report.update(
                run_id=os.environ["GITHUB_RUN_ID"],
                run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
            )
            report["original_result_sha256"] = sha(original / "result.json")
            report["original_result_status"] = load(original, "result.json")["status"]
            for name in ("source-after.json", "result.json"):
                (directory / ("original-" + name)).write_bytes(
                    (original / name).read_bytes()
                )
            report["status"] = "passed"
        else:
            raise ValueError("unknown receipt phase")
        if phase != "finish":
            report["status"] = "recorded"
        code = 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        subprocess.SubprocessError,
    ) as error:
        report["error"] = str(error)
        code = 1
    save(
        directory,
        "receipt.json" if phase == "finish" else phase + "-phase.json",
        report,
    )
    print(
        json.dumps(
            {"phase": phase, "status": report["status"], "error": report.get("error")}
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the ignored collection after the original Windows shard, once per job."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from openssh_diagnostic_evidence import CASE, TARGET, check_exact_list, check_matrix
from openssh_diagnostic_evidence import digest, inspect_bep, preserve, require
from openssh_diagnostic_evidence import (
    require_fresh_single,
    retain_test_files,
    write_json,
)


SOURCE_PATHS = (
    ".github/workflows/bazel.yml",
    ".github/scripts/run-bazel-ci.sh",
    ".github/scripts/run_bazel_with_buildbuddy.py",
    ".github/actions/prepare-bazel-ci/action.yml",
    ".github/scripts/run_openssh_diagnostic_ci.py",
    ".github/scripts/openssh_diagnostic_evidence.py",
    ".bazelversion",
    ".bazelrc",
    ".gitattributes",
    "MODULE.bazel",
    "MODULE.bazel.lock",
    "defs.bzl",
    "codex-rs/Cargo.lock",
    "codex-rs/hepta-operator-acceptance/Cargo.toml",
    "codex-rs/hepta-operator-acceptance/BUILD.bazel",
    "codex-rs/hepta-operator-acceptance/src/trust_tests.rs",
    "codex-rs/hepta-operator-acceptance/src/trust_openssh_diagnostic_tests.rs",
    "codex-rs/hepta-operator-acceptance/src/trust.rs",
    "codex-rs/hepta-operator-acceptance/src/openssh_windows.rs",
    "codex-rs/hepta-operator-acceptance/src/test_support.rs",
    "codex-rs/utils/path-utils/src/private_state_windows.rs",
    "codex-rs/utils/path-utils/src/private_state_windows_directory.rs",
)
DIAGNOSTIC_BLOBS = {
    "codex-rs/hepta-operator-acceptance/src/trust_tests.rs": "6635fb65a4597f7d35d8a45e9df38b13170f1a87",
    "codex-rs/hepta-operator-acceptance/src/trust_openssh_diagnostic_tests.rs": "db4f6fe87ff68128a18a0406cb76362f39e12896",
}


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True
    ).stdout


def source_snapshot(repo, output):
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    result = {
        "head": head,
        "tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip(),
        "files": [],
        "checkout_config": {},
        "status": "INCOMPLETE",
    }
    name = None
    try:
        require(
            head == os.environ["GITHUB_SHA"], "checkout differs from workflow source"
        )
        # Read only these public checkout settings, never a general config dump.
        for key in ("core.autocrlf", "core.eol"):
            value = subprocess.run(
                ["git", "config", "--null", "--get-all", key],
                cwd=repo,
                capture_output=True,
                check=False,
            )
            record = {
                "exit": value.returncode,
                "stdout": preserve(value.stdout, output / "config" / (key + ".stdout")),
                "stderr": preserve(value.stderr, output / "config" / (key + ".stderr")),
            }
            result["checkout_config"][key] = record
            require(
                record["stdout"]["raw_equal_published"]
                and record["stderr"]["raw_equal_published"],
                "checkout config retention was redacted",
            )
            require(value.returncode in (0, 1), "checkout config query failed")
            require(
                (value.returncode == 1 and not value.stdout)
                or (value.returncode == 0 and value.stdout.endswith(b"\0")),
                "checkout config query is incomplete",
            )
            record["values"] = [
                item.decode() for item in value.stdout.split(b"\0")[:-1]
            ]
        for name in SOURCE_PATHS:
            raw = (repo / name).read_bytes()
            blob = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            record = {
                "path": name,
                "working_git_blob": blob,
                "working": preserve(raw, output / "source" / name),
            }
            result["files"].append(record)
            expected = git(repo, "rev-parse", f"HEAD:{name}").decode().strip()
            canonical = git(repo, "cat-file", "blob", expected)
            canonical_blob = hashlib.sha1(
                b"blob " + str(len(canonical)).encode() + b"\0" + canonical
            ).hexdigest()
            record.update(
                expected_git_blob=expected,
                canonical_git_blob=canonical_blob,
                pinned_git_blob=DIAGNOSTIC_BLOBS.get(name),
                canonical=preserve(canonical, output / "canonical" / name),
            )
            # Preserve both actual worktree and Git object bytes before any byte rejection.
            require(
                record["working"]["raw_equal_published"]
                and record["canonical"]["raw_equal_published"],
                "source retention was redacted",
            )
            require(
                canonical_blob == expected
                and expected == DIAGNOSTIC_BLOBS.get(name, expected),
                f"canonical source identity mismatch: {name}",
            )
            attrs = ("text", "eol", "filter", "ident", "working-tree-encoding")
            for label, options in (
                ("worktree_attributes", []),
                ("index_attributes", ["--cached"]),
            ):
                observation = git(
                    repo, "check-attr", *options, "-z", *attrs, "--", name
                )
                record[label] = {"raw": preserve(observation, output / label / name)}
                require(
                    record[label]["raw"]["raw_equal_published"],
                    "checkout attributes retention was redacted",
                )
                fields = observation.split(b"\0")
                require(
                    fields[-1] == b"" and len(fields) == 3 * len(attrs) + 1,
                    "incomplete checkout attributes",
                )
                triples = [fields[i : i + 3] for i in range(0, len(fields) - 1, 3)]
                require(
                    all(path.decode() == name for path, _, _ in triples)
                    and [key.decode() for _, key, _ in triples] == list(attrs),
                    "checkout attributes name mismatch",
                )
                record[label]["values"] = {
                    key.decode(): value.decode() for _, key, value in triples
                }
            actual = record["worktree_attributes"]["values"]
            require(
                actual == record["index_attributes"]["values"],
                "checkout attributes changed",
            )
            require(
                all(
                    actual[key] in ("unspecified", "unset")
                    for key in ("filter", "ident", "working-tree-encoding")
                ),
                "unsupported source content conversion",
            )
            if raw == canonical:
                record["conversion"] = "NONE"
                continue
            autocrlf = result["checkout_config"]["core.autocrlf"]["values"]
            eol = result["checkout_config"]["core.eol"]["values"]
            autocrlf = autocrlf[-1].lower() if autocrlf else "false"
            eol = eol[-1].lower() if eol else "unspecified"
            supported_text = actual["text"] in ("set", "auto", "unspecified")
            explicit_crlf = actual["eol"] == "crlf"
            configured_crlf = actual["eol"] == "unspecified" and (
                autocrlf == "true"
                or (
                    autocrlf == "false"
                    and eol == "crlf"
                    and actual["text"] in ("set", "auto")
                )
            )
            require(
                supported_text
                and (explicit_crlf or configured_crlf)
                and b"\0" not in canonical
                and b"\r" not in canonical
                and b"\n" in canonical
                and raw == canonical.replace(b"\n", b"\r\n"),
                f"source byte mismatch: {name}",
            )
            record["conversion"] = "EXACT_CANONICAL_LF_TO_CHECKOUT_CRLF"
        # Keep the original complete tracked-source cleanliness gate. It runs
        # after retention so a dirty source cannot erase its own failure evidence.
        name = None
        git(repo, "diff", "--quiet", "HEAD", "--")
        result["status"] = "SOURCE_OBSERVED"
    except Exception as error:
        result["error"] = {
            "path": name,
            "type": type(error).__name__,
            "message": str(error),
        }
        raise
    finally:
        write_json(output / "source.json", result)
    return result


def pe_identity(repo):
    path = (
        repo
        / "bazel-bin/codex-rs/hepta-operator-acceptance/hepta-operator-acceptance-tests.exe"
    ).resolve(strict=True)
    before = path.stat()
    value = hashlib.sha256()
    with path.open("rb") as handle:
        require(handle.read(2) == b"MZ", "test payload is not a PE")
        handle.seek(0)
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    after = path.stat()
    require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        "PE changed during hash",
    )
    return {
        "path": str(path),
        "device": before.st_dev,
        "inode": before.st_ino,
        "bytes": before.st_size,
        "sha256": value.hexdigest(),
        "mode": before.st_mode,
        "mtime_ns": before.st_mtime_ns,
        "payload_body_uploaded": False,
    }


def observe(path, tag, repo, output):
    output.mkdir(parents=True, exist_ok=False)
    raw = path.read_bytes()
    # Even invalid/incomplete BEP must remain available, after credential redaction.
    receipt = preserve(raw, output / "bep.public.jsonl", bep=True)
    write_json(output / "bep.bytes.json", receipt)
    _, events, observation = inspect_bep(path, os.environ["GITHUB_SHA"], tag)
    observation["retained_test_files"] = retain_test_files(observation, repo, output)
    write_json(output / "observation.json", observation)
    return events, observation


def run_phase(phase, bash, repo, scratch, output):
    bep = scratch / f"{phase}.jsonl"
    require(not bep.exists(), "diagnostic scope was already used")
    selected = (
        ["--list", "--ignored", "--exact", CASE]
        if phase == "list"
        else ["--ignored", "--exact", CASE, "--nocapture"]
    )
    args = [
        str(bash),
        "./.github/scripts/run-bazel-ci.sh",
        "--print-failed-action-summary",
        "--print-failed-test-logs",
        "--windows-msvc-host-platform",
        "--remote-download-toplevel",
        "--",
        "test",
        "--platforms=//:windows_x86_64_msvc",
        "--skip_incompatible_explicit_targets",
        "--test_tag_filters=-argument-comment-lint",
        "--test_verbose_timeout_warnings",
        f"--build_metadata=COMMIT_SHA={os.environ['GITHUB_SHA']}",
        f"--build_metadata=TAG_windows_test_shard=openssh-diagnostic-{phase}",
        "--nocache_test_results",
        "--test_output=all",
        f"--build_event_json_file={bep}",
        "--nobuild_event_json_file_path_conversion",
        *[f"--test_arg={arg}" for arg in selected],
        "--",
        TARGET,
    ]
    started = time.time_ns()
    write_json(
        output / f"{phase}.start.json",
        {
            "argv": args,
            "started_unix_ns": started,
            "test_timeout_retry_profile_changed": False,
            "caller_stdin": "inherited",
            "wrapper_internally_merges_bazel_stdout_stderr": True,
        },
    )
    stdout = scratch / f"{phase}.stdout"
    stderr = scratch / f"{phase}.stderr"
    with stdout.open("xb") as out, stderr.open("xb") as err:
        # Actions owns the original 120-minute job deadline and cancellation.
        # No replay, new per-child timeout, background child or signal is added.
        process = subprocess.run(args, cwd=repo, stdout=out, stderr=err, check=False)
    receipt = {
        "argv": args,
        "started_unix_ns": started,
        "ended_unix_ns": time.time_ns(),
        "actual_wrapper_exit": process.returncode,
        "stdout": preserve(stdout.read_bytes(), output / f"{phase}.wrapper.stdout"),
        "stderr": preserve(stderr.read_bytes(), output / f"{phase}.wrapper.stderr"),
    }
    write_json(output / f"{phase}.terminal.json", receipt)
    events, observation = observe(
        bep, f"openssh-diagnostic-{phase}", repo, output / phase
    )
    require_fresh_single(observation, events, process.returncode)
    log = (output / phase / "attempt-0/test.log").read_text(encoding="utf-8")
    if phase == "list":
        check_exact_list(log)
        result = {"official_list_exact_one": CASE, "native_case_executed": False}
    else:
        result = check_matrix(log, output / phase)
    write_json(output / f"{phase}.result.json", result)
    return {
        "uuid": observation["uuid"],
        "actual_exit": process.returncode,
        "result": result,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bash", type=Path, required=True)
    args = parser.parse_args()
    require(
        os.name == "nt" and os.environ.get("RUNNER_OS") == "Windows",
        "Windows CI required",
    )
    require(
        os.environ.get("BAZEL_TEST_SHARD") == "4", "diagnostic belongs only to shard 4"
    )
    outcome = os.environ.get("ORIGINAL_WINDOWS_SHARD_OUTCOME")
    require(outcome in ("success", "failure"), "original shard did not complete first")
    run_id, attempt = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"]
    require(run_id.isdigit() and attempt.isdigit(), "missing actual Actions identity")
    repo = Path.cwd().resolve(strict=True)
    temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    output = temp / f"openssh-diagnostic-{run_id}-{attempt}"
    scratch = temp / f"openssh-diagnostic-private-{run_id}-{attempt}"
    output.mkdir(exist_ok=False)
    scratch.mkdir(exist_ok=False)
    report = {
        "schema": "hepta.windows.openssh.diagnostic-ci.v1",
        "run_id": run_id,
        "run_attempt": attempt,
        "original_shard_outcome": outcome,
        "diagnostic_status": "INCOMPLETE",
        "original_33_result_overwritten": False,
        "product_qualification": False,
        "job_timeout_minutes_unchanged": 120,
        "phases": [],
        "process_custody": "foreground subprocess.run; Actions job cancellation remains authoritative; no descendant-quiescence claim",
    }
    exit_code = 1
    try:
        before = source_snapshot(repo, output / "before")
        report["source_before"] = before
        report["bash"] = {
            "path": str(args.bash.resolve(strict=True)),
            "sha256": digest(args.bash.read_bytes()),
        }
        original = temp / f"openssh-original-{run_id}-{attempt}-4.jsonl"
        _, original_observation = observe(original, "4", repo, output / "original")
        report["original_uuid"] = original_observation["uuid"]
        original_exit = original_observation["finished"]["exitCode"].get("code", 0)
        require(
            (original_exit == 0) == (outcome == "success"),
            "original step and BEP exit disagree",
        )
        report["pe_before"] = pe_identity(repo)
        uuids = {original_observation["uuid"]}
        for phase in ("list", "run"):
            value = run_phase(phase, args.bash, repo, scratch, output)
            require(value["uuid"] not in uuids, "BEP invocation was replayed")
            uuids.add(value["uuid"])
            report["phases"].append(value)
            actual_pe = pe_identity(repo)
            require(
                actual_pe == report["pe_before"],
                "test PE changed across original/list/run",
            )
            report[f"pe_after_{phase}"] = actual_pe
        report["diagnostic_status"] = "COLLECTION_COMPLETE"
        exit_code = 0
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            after = source_snapshot(repo, output / "after")
            report["source_after"] = after
            require(
                after == report.get("source_before"),
                "source changed during observation",
            )
        except Exception as error:
            exit_code = 1
            report["diagnostic_status"] = "INCOMPLETE"
            report["source_after_error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        report["collector_exit"] = exit_code
        write_json(output / "SUMMARY.json", report)
        inventory = [
            {
                "path": str(path.relative_to(output)),
                "bytes": path.stat().st_size,
                "sha256": digest(path.read_bytes()),
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        ]
        write_json(
            output / "INDEX.json",
            {"files": inventory, "summary_self_report_not_Actions_terminal": True},
        )
    print(
        json.dumps(
            {
                "diagnostic_status": report["diagnostic_status"],
                "collector_exit": exit_code,
                "original_shard_outcome": outcome,
                "product_qualification": False,
            }
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

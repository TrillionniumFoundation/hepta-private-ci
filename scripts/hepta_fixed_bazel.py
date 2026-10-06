"""Fixed, source-only Bazel diagnostic groups; ordinary CI is unaffected.

Windows execution is bounded by the caller's Actions step timeout. A runner
shutdown can leave a running receipt, which is never qualification evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import stat
import subprocess
import sys
import time
import tempfile

import hepta_ci_candidate
import hepta_ci_exec

GROUPS = {
    "windows-delete-diagnostic": (
        "//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests",
    ),
    "windows-queue-diagnostic": (
        "//codex-rs/ext/queue:queue-queue_service-test",
    ),
    "linux-supervisor": (
        "//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test",
    ),
}


def budget_minutes(started: float, now: float) -> int:
    if not math.isfinite(started) or not math.isfinite(now) or started > now:
        raise ValueError("invalid first-step budget anchor")
    remaining = math.floor((started + 45 * 60 - now) / 60)
    if remaining < 1:
        raise ValueError("native diagnostic budget exhausted")
    return remaining


def source_identity() -> dict:
    source = os.environ["SOURCE_SHA"]
    tested = os.environ["TESTED_SHA"]
    if os.environ.get("HEPTA_CI_LANE") != "source-head":
        raise ValueError("manual diagnostics require an explicit source-head lane")
    plan = hepta_ci_candidate.candidate_plan(source=source, tested=tested, lane="source-head")
    identity = hepta_ci_exec.identity()
    if identity["dirty"]:
        raise ValueError("diagnostic source must be clean")
    return {"plan": plan, "git": identity}


def verify_bep(path: Path, labels: tuple[str, ...]) -> dict:
    summaries = {}
    count = size = 0
    digest = hashlib.sha256()
    deadline = time.monotonic() + 10
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("BEP must be a regular file")
        while True:
            if time.monotonic() >= deadline:
                raise ValueError("BEP verification deadline exceeded")
            line = stream.readline(1024 * 1024 + 1)
            if not line:
                break
            count += 1
            size += len(line)
            if len(line) > 1024 * 1024 or size > 32 * 1024**2 or count > 100_000:
                raise ValueError("BEP evidence exceeds bounded reader limits")
            digest.update(line)
            event = json.loads(line)
            label = event.get("id", {}).get("testSummary", {}).get("label")
            if label in labels:
                if label in summaries:
                    raise ValueError("duplicate selected target summary")
                summaries[label] = event.get("testSummary", {})
    if set(summaries) != set(labels):
        raise ValueError("one or more selected target summaries are absent")
    for label, summary in summaries.items():
        if summary.get("overallStatus") not in ("PASSED", "FLAKY"):
            raise ValueError(f"selected target did not pass: {label}: {summary.get('overallStatus')}")
        if type(summary.get("totalRunCount")) is not int or summary["totalRunCount"] < 1:
            raise ValueError("selected target executed no test actions")
        if summary.get("totalNumCached", 0) != 0:
            raise ValueError("selected target reused cached test results")
    return {"bep_sha256": digest.hexdigest(), "bep_bytes": size, "targets": summaries,
            "flaky_targets": [label for label, item in summaries.items() if item["overallStatus"] == "FLAKY"],
            "scope": "target-level fresh test actions; not individual test counts"}


def retain_bep_tail(path: Path, output: Path, *, maximum_bytes: int = 2 * 1024**2) -> dict:
    """Keep bounded raw diagnostic bytes even when target verification fails."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError('BEP tail requires a regular file')
        start = max(0, metadata.st_size - maximum_bytes)
        stream.seek(start)
        data = stream.read(maximum_bytes)
    with output.open('xb') as stream:
        stream.write(data)
    return {'path': output.name, 'captured_bytes': len(data),
            'source_size_observed': metadata.st_size, 'tail_truncated': start > 0,
            'may_begin_mid_record': start > 0, 'sha256': hashlib.sha256(data).hexdigest()}


def replace_receipt(path: Path, record: dict) -> None:
    with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8', delete=False) as stream:
        pending = Path(stream.name)
        json.dump(record, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def windows_command(group: str, directory: Path) -> list[str]:
    if group not in ("windows-delete-diagnostic", "windows-queue-diagnostic"):
        raise ValueError("not a fixed Windows group")
    bash = os.environ.get("HEPTA_BAZEL_BASH", "")
    parsed = PureWindowsPath(bash)
    # MSYS may expose its running executable without the native .exe suffix.
    if parsed.name.lower() == "bash":
        parsed = parsed.with_name(parsed.name + ".exe")
    if not parsed.is_absolute() or parsed.name.lower() != "bash.exe":
        raise ValueError("an absolute Actions Git Bash executable is required")
    return [
        str(parsed), ".github/scripts/run-bazel-ci.sh",
        "--print-failed-action-summary", "--print-failed-test-logs",
        "--windows-msvc-host-platform", "--remote-download-toplevel", "--",
        "test", "--platforms=//:windows_x86_64_msvc", "--nocache_test_results",
        "--test_tag_filters=-argument-comment-lint", "--test_verbose_timeout_warnings",
        f"--build_metadata=COMMIT_SHA={os.environ.get('TESTED_SHA', '')}",
        f"--build_event_json_file={(directory / (group + '.bep.json')).as_posix()}",
        "--", *GROUPS[group],
    ]


def run_windows(group: str, directory: Path) -> int:
    if os.name != "nt":
        raise ValueError("Windows native group requires a Windows host")
    budget_minutes(float(os.environ["HEPTA_PILOT_JOB_STARTED"]), time.monotonic())
    before = source_identity()
    root = Path(hepta_ci_exec.git("rev-parse", "--show-toplevel")).resolve()
    if not directory.is_absolute() or directory.resolve().is_relative_to(root):
        raise ValueError("diagnostic records must be outside source")
    directory.mkdir(parents=True, exist_ok=True)
    record_path = directory / (group + '.json')
    command = windows_command(group, directory)
    if not Path(command[0]).is_file():
        raise ValueError("the Actions Git Bash executable is unavailable")
    record = {"scope": "source-only fixed native targets", "group": group,
              "source_before": before, "command": command, "status": "running",
              "command_exit_code": None, "run_id": os.environ.get("GITHUB_RUN_ID"),
              "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "timeout_owner": "Actions step, first-job-anchor remaining budget"}
    with record_path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, sort_keys=True)
    code = 2
    try:
        # Inherit native log streaming. Do not reuse the POSIX-only recorder or
        # claim local process-tree quiescence on Windows.
        log_path = directory / (group + '.log')
        kept = 0
        truncated = False
        log_hash = hashlib.sha256()
        with log_path.open('xb') as log, subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        ) as process:
            assert process.stdout is not None
            while True:
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                saved = chunk[:max(0, 64 * 1024**2 - kept)]
                log.write(saved)
                log.flush()
                kept += len(saved)
                log_hash.update(saved)
                truncated |= len(saved) != len(chunk)
                sys.stdout.write(chunk.decode('utf-8', errors='replace'))
                sys.stdout.flush()
            code = process.wait()
        record['log_bytes'] = kept
        record['log_sha256'] = log_hash.hexdigest()
        record['log_truncated'] = truncated
        record["command_exit_code"] = code
        after = source_identity()
        record["source_after"] = after
        if after != before:
            raise ValueError("source changed during native execution")
        record["test_evidence"] = verify_bep(directory / (group + '.bep.json'), GROUPS[group])
        record["status"] = "passed" if code == 0 else "failed"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        record["status"] = "failed"
        record["error"] = str(error)
        code = code or 2
    finally:
        # Abrupt runner termination may prevent this write; the original
        # exclusive running receipt must then be treated as incomplete.
        try:
            record['bep_tail'] = retain_bep_tail(
                directory / (group + '.bep.json'), directory / (group + '.bep-tail.jsonl'),
            )
        except (OSError, ValueError) as error:
            record['bep_tail_unavailable'] = str(error)
        replace_receipt(record_path, record)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('budget', 'windows', 'verify-linux'))
    parser.add_argument('--group', choices=tuple(GROUPS))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--github-output', type=Path)
    args = parser.parse_args()
    if args.phase == 'budget':
        source_identity()
        minutes = budget_minutes(float(os.environ['HEPTA_PILOT_JOB_STARTED']), time.monotonic())
        with args.github_output.open('a', encoding='utf-8') as stream:
            stream.write(f'minutes={minutes}\n')
        return 0
    if args.phase == 'windows':
        return run_windows(args.group, args.directory)
    before = source_identity()
    record = json.loads((args.directory / 'native.json').read_text())
    if record.get('status') != 'passed' or record.get('before') != before['git'] or record.get('after') != before['git']:
        raise ValueError('Linux native receipt is absent, failed or source-mismatched')
    evidence = verify_bep(args.directory / 'build-events.json', GROUPS['linux-supervisor'])
    with (args.directory / 'selected-targets.json').open('x', encoding='utf-8') as stream:
        json.dump({'source': before, 'test_evidence': evidence}, stream, sort_keys=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

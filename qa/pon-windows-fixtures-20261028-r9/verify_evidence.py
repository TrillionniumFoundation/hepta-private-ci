#!/usr/bin/env python3
"""Read-only byte/source checks; never executes Rust, Cargo, Bazel or hooks."""

from __future__ import annotations

import ast
import hashlib
import io
import json
import lzma
from pathlib import Path
import re

QA = Path(__file__).resolve().parent
ROOT = QA.parents[1]
FIXTURE = "codex-rs/hepta-agentd/src/cognitive_retrieval_learning_tests.rs"
QUEUE = "codex-rs/ext/queue/tests/queue_service.rs"
OBSERVER = "codex-rs/ext/queue/tests/common/queue_hook_diagnostics.rs"
GUARD = "\n    let _hook_diagnostics = HookDiagnostics::attach(test.codex_home_path());"
CASES = (
    "caller_abort_after_core_started_keeps_exact_authority_until_persistence",
    "core_error_after_started_never_releases_ambiguous_dispatch",
    "rejected_queue_messages_remain_durable_and_block_followups",
    "explicitly_started_rejected_queue_messages_remain_durable",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_archive(data: bytes, specification: dict) -> bytes:
    if len(data) > 512_000 or len(data) != specification["bytes"]:
        raise ValueError("archive size differs or exceeds the original cap")
    if sha(data) != specification["sha256"]:
        raise ValueError("archive SHA-256 differs")
    size = specification["decoded_bytes"]
    if not 0 < size <= 4 * 1024 * 1024:
        raise ValueError("decoded size is outside this evidence contract")
    with lzma.LZMAFile(io.BytesIO(data)) as stream:
        raw = stream.read(size + 1)
    if len(raw) != size or sha(raw) != specification["decoded_sha256"]:
        raise ValueError("decoded original bytes differ")
    return raw


def original_log_cases(raw: bytes) -> tuple[set[str], int]:
    lines = [re.sub(r"^\S+Z ", "", line) for line in raw.decode().splitlines()]
    tail = next(
        i for i, line in enumerate(lines) if "##[group]Bazel test log tail" in line
    )
    names = [
        match.group(1)
        for line in lines[:tail]
        if (match := re.fullmatch(r"test (.+) \.\.\. FAILED", line))
    ]
    return set(names), len(names)


def check_test_scope(originals: dict[str, str], fixture: str, queue: str) -> dict:
    start = fixture.index("fn directory_handle(")
    end = fixture.index("fn sink()", start)
    helper = fixture[start:end]
    for required in (
        "#[cfg(windows)]",
        ".read(true)",
        ".write(true)",
        ".custom_flags(/*flags*/ 0x0200_0000)",
        ".open(path)",
        "#[cfg(not(windows))]",
        "File::open(path)",
    ):
        if required not in helper:
            raise ValueError("directory fixture contract differs")
    restored = (fixture[:start] + fixture[end:]).replace(
        "directory_handle(temp.path())", "File::open(temp.path())"
    )
    if restored != originals[FIXTURE]:
        raise ValueError("directory fixture changed an original test or behavior")

    if queue.count(GUARD) != len(CASES):
        raise ValueError("unexpected hook diagnostic guards")
    for name in CASES:
        body = queue[queue.index("async fn " + name) :]
        next_test = body.find("\n#[tokio::test")
        if next_test != -1:
            body = body[:next_test]
        if body.count(GUARD) != 1:
            raise ValueError("diagnostic guard is not bound to an original case")
    restored = queue.replace(GUARD, "")
    restored = restored.replace("use queue_hook_diagnostics::HookDiagnostics;\n", "")
    restored = restored.replace(
        '\n#[path = "common/queue_hook_diagnostics.rs"]\nmod queue_hook_diagnostics;\n',
        "",
    )
    replacement = "    let command = queue_hook_diagnostics::write_hook(home, &script_path, &script);"
    for message in ("write queue hook script", "write blocking queue hook script"):
        restored = restored.replace(
            replacement,
            "    std::fs::write(&script_path, script)\n"
            f'        .unwrap_or_else(|error| panic!("{message}: {{error}}"));',
            1,
        )
    restored = restored.replace(
        '"command": command,',
        '"command": format!("python3 {}", script_path.display()),',
    )
    if restored != originals[QUEUE]:
        raise ValueError(
            "queue observer changed an original assertion, timeout or script"
        )
    return {
        "all_original_fixture_tests_retained": True,
        "all_original_queue_tests_and_timeouts_retained": True,
        "observed_queue_cases": list(CASES),
    }


def check_observer(source: str) -> dict:
    constants = dict(re.findall(r'const (\w+): &str = r#"(.*?)"#;', source, re.S))
    ast.parse(constants["PYTHON_IDENTITY"])
    unix = constants["UNIX_LAUNCHER"]
    windows = constants["WINDOWS_LAUNCHER"]
    for text, capture, replay, terminate in (
        (
            unix,
            "HEPTA_QUEUE_HOOK_EXIT=$?",
            'cat "$HEPTA_QUEUE_HOOK_RUN/stdout.bin"',
            'exit "$HEPTA_QUEUE_HOOK_EXIT"',
        ),
        (
            windows,
            'set "HEPTA_QUEUE_HOOK_EXIT=%ERRORLEVEL%"',
            'type "%HEPTA_QUEUE_HOOK_RUN%\\stdout.bin"',
            "exit /b %HEPTA_QUEUE_HOOK_EXIT%",
        ),
    ):
        command = text.index("@COMMAND@ >")
        recorded_exit = text.index("exit-code.txt", text.index(capture))
        if (
            not command
            < text.index(capture)
            < recorded_exit
            < text.index(replay)
            < text.index(terminate)
        ):
            raise ValueError("child output/exit retention order differs")
        if text.count("@COMMAND@") != 1:
            raise ValueError("original command must execute once per observation")
    if (
        'let original_command = format!("python3 {}", script_path.display());'
        not in source
    ):
        raise ValueError("the original interpreter command was replaced")
    if "running_or_interrupted_unknown" not in source:
        raise ValueError("missing exit may not become an invented outcome")
    return {"python_identity_syntax": "valid", "launcher_control_flow": "static_only"}


def verify() -> dict:
    manifest = json.loads((QA / "provenance.json").read_text())
    archives = {}
    for name, specification in manifest["archives"].items():
        path = QA / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("archive must be a regular retained file")
        archives[name] = decode_archive(path.read_bytes(), specification)
    frozen = json.loads(archives["evidence/actual-merge-source.json.xz"])
    originals = {}
    for item in frozen["files"]:
        raw = item["content"].encode()
        git_blob = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
        if (
            len(raw) != item["bytes"]
            or sha(raw) != item["sha256"]
            or git_blob != item["git_blob"]
        ):
            raise ValueError("actual-merge source identity differs")
        originals[item["path"]] = item["content"]
    if len(originals) != 15:
        raise ValueError("source denominator differs")

    observed = {}
    for shard, expected in ((1, 6), (3, 43)):
        raw = archives[f"evidence/windows-shard{shard}.raw.log.xz"]
        names, occurrences = original_log_cases(raw)
        matrix = json.loads((QA / f"windows-shard{shard}-matrix.json").read_text())
        cases = matrix["cases" if shard == 1 else "all_failed_cases"]
        if len(names) != expected or names != {case["name"] for case in cases}:
            raise ValueError("original failed-case denominator differs")
        if sha(raw) != matrix["raw_log"]["sha256"]:
            raise ValueError("matrix does not bind the original log")
        observed[str(shard)] = {
            "unique_failed_cases": len(names),
            "original_failed_observations": occurrences,
        }
    normalized = archives["evidence/windows-shard3.raw.log.xz"].replace(b"\r\n", b"\n")
    if sha(normalized) != manifest["normalized_shard3_correction"]["sha256"]:
        raise ValueError("earlier newline correction is not reproducible")
    for name, expected in manifest["protected_source_sha256"].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"production source, workflow or policy changed: {name}")
    scope = check_test_scope(
        originals, (ROOT / FIXTURE).read_text(), (ROOT / QUEUE).read_text()
    )
    observer = check_observer((ROOT / OBSERVER).read_text())
    return {
        "schema": "hepta-windows-fixtures-static-review-v1",
        "archive_count": len(archives),
        "actual_merge_source_files": len(originals),
        "original_failed_cases": observed,
        "protected_source_files": len(manifest["protected_source_sha256"]),
        **scope,
        **observer,
        "native_tests_executed": False,
        "windows_blockers_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))

"""Diagnose the original Matrix startup failure without changing its limits."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time


SQLITE_SOURCE_SHA256 = {
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/utils.rs": "e450cadd34ea04129b2da35076655bcddcf15a1b7ccd6be9b8077bcd31496616",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/connection.rs": "893957181ce82046d0375a934a2f1782c6485b447ffb281e25b964b6a0627de6",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/state_store.rs": "1ff989781d3c2c95d996ce186477b5b77f7bd120c88d3b4bf46de9fb33bb5871",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/crypto_store.rs": "33f4d434c17b8da20fde72f0add8edcb37076d413bf6e7b776c715f7e6330d24",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/event_cache_store.rs": "c563506ec52f1389a557d7b0fb49ab895c781f8b993e94073c6a1c0e9e2c8a1e",
    "codex-rs/third_party/matrix-sdk-sqlite-0.19.1/src/media_store.rs": "d27efeb8d30cede965533dbf66242da214f944cab887379feb251bf9a9b9ee00"
}

SDK_PATH = Path("codex-rs/hepta-matrix-sdk/src/sdk.rs")
SDK_SHA256 = "3061024c6e84abd962b3933f2e974d744aba6d7f1ea2a0020720dd632e9268e5"
DIAGNOSTIC_SHA256 = "4af146ae73d0d1e5fb442558672ec1eb034fe5d5a4c23bf25e156be86c2b3386"
TEST_PATH = Path("codex-rs/hepta-matrix-sdk/tests/storage_upgrade.rs")
TEST_SHA256 = "0c8afc74027288ca994f9ab06a4026a795bee625c99ab2d15f0f469bc3bff274"
TARGET = "//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-storage_upgrade-test"
CASES = (
    "legacy_encrypted_storage_migrates_and_reopens_with_the_same_identity",
    "wrong_passphrase_preserves_the_existing_encrypted_store",
)


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def diagnostic_source(original):
    """Reproduce the exact temporary source already exercised on native macOS."""
    if sha256(original) != SDK_SHA256:
        raise ValueError("Matrix SDK source differs from the diagnosed revision")
    source = original.decode()
    needle = "        let sidecar = tokio::time::timeout(\n"
    assert source.count(needle) == 3
    source = source.replace(
        needle, "        let phase_start = std::time::Instant::now();\n" + needle
    )
    needle = "        .map_err(|_| MatrixSdkError::Initialization)??;"
    assert source.count(needle) == 3
    source = source.replace(
        needle,
        """        .map_err(|_| {
            eprintln!("matrix-phase build_timeout elapsed_ms={}", phase_start.elapsed().as_millis());
            MatrixSdkError::Initialization
        })??;""",
    )
    needle = "        let paths = MatrixSdkPaths::prepare(layout, &config)?;"
    assert source.count(needle) == 1
    source = source.replace(
        needle,
        """        let phase_start = std::time::Instant::now();
        eprintln!("matrix-phase build_enter");
        let paths = MatrixSdkPaths::prepare(layout, &config)?;
        eprintln!("matrix-phase paths_ready elapsed_ms={}", phase_start.elapsed().as_millis());""",
    )
    start = source.index("    async fn build(")
    end = source.index("\n    pub fn client(", start)
    body = source[start:end]
    needle = "            .map_err(|_| MatrixSdkError::Initialization)?;"
    assert body.count(needle) == 3
    for error, success in (
        ("builder_error", "builder_complete"),
        ("sync_token_error", "sync_token_removed"),
        ("callback_error", "callbacks_registered"),
    ):
        body = body.replace(
            needle,
            """            .map_err(|_| {
                eprintln!("matrix-phase """
            + error
            + """ elapsed_ms={}", phase_start.elapsed().as_millis());
                MatrixSdkError::Initialization
            })?;
        eprintln!("matrix-phase """
            + success
            + """ elapsed_ms={}", phase_start.elapsed().as_millis());""",
            1,
        )
    result = (source[:start] + body + source[end:]).encode()
    assert sha256(result) == DIAGNOSTIC_SHA256
    return result


def successful_libtest_execution(log, expected_cases, exit_code):
    """Bind named execution and the exact zero-failure summary, even with nocapture."""
    log = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log)
    names = set(re.findall(r"(?m)^test ([^\s]+) \.\.\.", log))
    summaries = re.findall(
        r"(?m)^test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured;", log
    )
    expected = set(expected_cases)
    return {
        "observed_names": sorted(names),
        "successful_execution_verified": (
            exit_code == 0
            and names == expected
            and summaries == [str(len(expected_cases))]
        ),
    }


def sqlite_diagnostic_source(name, original):
    """Observe durations only; never log a path, key, password, SQL, or DB value."""
    source = original.decode()

    def replace_once(old, new):
        nonlocal source
        assert source.count(old) == 1, (name, old)
        source = source.replace(old, new)

    if name == "utils.rs":
        replace_once(
            '        const STORAGE_KEY: &str = "cipher";',
            '        const STORAGE_KEY: &str = "cipher";\n        static NEXT_OBSERVATION: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);\n        let observation = NEXT_OBSERVATION.fetch_add(1, std::sync::atomic::Ordering::Relaxed);\n        let cipher_start = std::time::Instant::now();\n        eprintln!("matrix-detail cipher id={observation} stage=load_begin thread={:?}", std::thread::current().id());',
        )
        replace_once(
            "        let cipher = if let Some(encrypted) = encrypted_cipher {",
            '        eprintln!("matrix-detail cipher id={observation} stage=load_end elapsed_us={}", cipher_start.elapsed().as_micros());\n        let cipher = if let Some(encrypted) = encrypted_cipher {',
        )
        replace_once(
            "                Secret::PassPhrase(passphrase) => StoreCipher::import(passphrase, &encrypted)?,",
            '                Secret::PassPhrase(passphrase) => {\n                    let started = std::time::Instant::now();\n                    eprintln!("matrix-detail cipher id={observation} stage=import_begin thread={:?}", std::thread::current().id());\n                    let result = StoreCipher::import(passphrase, &encrypted);\n                    eprintln!("matrix-detail cipher id={observation} stage=import_end elapsed_us={} ok={}", started.elapsed().as_micros(), result.is_ok());\n                    result?\n                },',
        )
        replace_once(
            "                        cipher.export(passphrase)",
            '                        let started = std::time::Instant::now();\n                        eprintln!("matrix-detail cipher id={observation} stage=export_begin thread={:?}", std::thread::current().id());\n                        let result = cipher.export(passphrase);\n                        eprintln!("matrix-detail cipher id={observation} stage=export_end elapsed_us={} ok={}", started.elapsed().as_micros(), result.is_ok());\n                        result',
        )
        replace_once(
            "\n        Ok(cipher)\n",
            '\n        eprintln!("matrix-detail cipher id={observation} stage=complete elapsed_us={}", cipher_start.elapsed().as_micros());\n        Ok(cipher)\n',
        )
        replace_once(
            "        self.interact(move |conn| conn.query_row(sql.as_ref(), params, f))",
            '        self.interact(move |conn| {\n            let started = std::time::Instant::now();\n            let result = conn.query_row(sql.as_ref(), params, f);\n            eprintln!("matrix-detail sqlite stage=query_row elapsed_us={} ok={}", started.elapsed().as_micros(), result.is_ok());\n            result\n        })',
        )
        replace_once(
            "        self.interact(move |conn| conn.execute_batch(sql.as_ref()))",
            '        self.interact(move |conn| {\n            let started = std::time::Instant::now();\n            let result = conn.execute_batch(sql.as_ref());\n            eprintln!("matrix-detail sqlite stage=execute_batch elapsed_us={} ok={}", started.elapsed().as_micros(), result.is_ok());\n            result\n        })',
        )
    elif name == "connection.rs":
        replace_once(
            "        SyncWrapper::new(RUNTIME, move || rusqlite::Connection::open(path)).await",
            '        SyncWrapper::new(RUNTIME, move || {\n            let started = std::time::Instant::now();\n            let result = rusqlite::Connection::open(path);\n            eprintln!("matrix-detail sqlite stage=open elapsed_us={} ok={}", started.elapsed().as_micros(), result.is_ok());\n            result\n        }).await',
        )
    else:
        kind = name.removesuffix("_store.rs")
        signature = "    pub async fn open_with_config(config: &SqliteStoreConfig) -> Result<Self, OpenStoreError> {"
        replace_once(signature, signature + f"\n        let detail_started = std::time::Instant::now();\n        eprintln!(\"matrix-detail store={kind} stage=begin\");")
        begin = source.index(signature)
        end = source.index("\n    }", begin)
        body = source[begin:end]
        needle = "        fs::create_dir_all(&config.path).await.map_err(OpenStoreError::CreateDir)?;"
        assert body.count(needle) == 1
        body = body.replace(needle, needle + f'\n        eprintln!("matrix-detail store={kind} stage=directory_ready elapsed_us={{}}", detail_started.elapsed().as_micros());')
        needle = "        Ok(this)"
        assert body.count(needle) == 1
        body = body.replace(needle, f'        eprintln!("matrix-detail store={kind} stage=complete elapsed_us={{}}", detail_started.elapsed().as_micros());\n' + needle)
        source = source[:begin] + body + source[end:]
    return source.encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--check-source", action="store_true")
    options = parser.parse_args()
    repo = options.repo.resolve()
    sdk = repo / SDK_PATH
    fixture = repo / TEST_PATH
    original = sdk.read_bytes()
    diagnostic = diagnostic_source(original)
    source_files = {sdk: original}
    diagnostic_files = {sdk: diagnostic}
    for relative, expected_sha in SQLITE_SOURCE_SHA256.items():
        path = repo / relative
        content = path.read_bytes()
        assert sha256(content) == expected_sha, relative
        source_files[path] = content
        diagnostic_files[path] = sqlite_diagnostic_source(path.name, content)
    assert sha256(fixture.read_bytes()) == TEST_SHA256
    if options.check_source:
        print(json.dumps({
            "sources": {str(path.relative_to(repo)): sha256(content) for path, content in source_files.items()},
            "diagnostics": {str(path.relative_to(repo)): sha256(content) for path, content in diagnostic_files.items()},
            "fixture": TEST_SHA256,
        }))
        return
    if options.report_dir is None:
        parser.error("--report-dir is required for execution")
    if platform.system() != "Darwin":
        raise RuntimeError("This diagnostic requires the original native macOS platform")
    out = options.report_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    commands = []

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + "\n")

    def run(name, arguments):
        log = out / f"{name}.log"
        started = time.monotonic()
        with log.open("wb") as stream:
            result = subprocess.run(arguments, cwd=repo, stdout=stream, stderr=subprocess.STDOUT)
        row = {
            "name": name,
            "argv": arguments,
            "exit": result.returncode,
            "seconds": round(time.monotonic() - started, 3),
            "sha256": sha256(log.read_bytes()),
            "bytes": log.stat().st_size,
            "sdk_sha256": sha256(sdk.read_bytes()),
        }
        commands.append(row)
        save("results.json", commands)
        print(json.dumps(row), flush=True)
        assert sha256(fixture.read_bytes()) == TEST_SHA256
        return result.returncode

    subprocess.run(["git", "diff", "--exit-code"], cwd=repo, check=True)
    save(
        "source.json",
        {
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
            "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, text=True).strip(),
            "original_failure_head": "57e489472a03515438df8ed7a0fabec882404f02",
            "original_failure_run": 43654720946,
            "original_arm_job": 132630631390,
            "sdk_sha256": SDK_SHA256,
            "diagnostic_sha256": DIAGNOSTIC_SHA256,
            "fixture_sha256": TEST_SHA256,
            "runner_os_version": platform.mac_ver()[0],
            "machine": platform.machine(),
            "tmpdir": os.environ.get("TMPDIR"),
            "runner_name": os.environ.get("RUNNER_NAME"),
            "diagnostic_only": True,
        },
    )
    (out / "source-before.rs").write_bytes(original)
    (out / "source-diagnostic.rs").write_bytes(diagnostic)
    save("diagnostic-sources.json", {
        str(path.relative_to(repo)): {"original": sha256(content), "diagnostic": sha256(diagnostic_files[path])}
        for path, content in source_files.items()
    })
    run("runner", ["/bin/sh", "-c", "uname -a; sw_vers; sysctl hw.logicalcpu hw.physicalcpu hw.memsize; uptime"])

    def bazel(name, test_arguments, expected_cases):
        result = run(
            name,
            [
                "./.github/scripts/run-bazel-ci.sh",
                "--print-failed-action-summary",
                "--print-failed-test-logs",
                "--",
                "test",
                "--nocache_test_results",
                "--flaky_test_attempts=1",
                "--test_output=all",
                "--test_arg=--nocapture",
                f"--build_event_json_file={out / (name + '.bep.json')}",
                *test_arguments,
                "--",
                TARGET,
            ],
        )
        log = (out / f"{name}.log").read_text(errors="replace")
        commands[-1]["expected_cases"] = list(expected_cases)
        commands[-1].update(successful_libtest_execution(log, expected_cases, result))
        save("results.json", commands)
        return result

    try:
        run(
            "compiler-actions",
            [
                "./.github/scripts/run-bazel-ci.sh",
                "--",
                "aquery",
                "--output=textproto",
                "--include_artifacts=false",
                "--include_param_files=true",
                f'mnemonic("Rustc", filter("matrix.sdk.store.encryption|matrix.sdk.sqlite|pbkdf2|hmac|sha2", deps({TARGET})))',
            ],
        )
        bazel("original-pair", [], CASES)
        assert sdk.read_bytes() == original
        for path, content in diagnostic_files.items():
            path.write_bytes(content)
        bazel("diagnostic-pair", [], CASES)
        for index, case in enumerate(CASES):
            assert sdk.read_bytes() == diagnostic
            bazel(
                f"diagnostic-single-{index + 1}",
                [f"--test_arg={case}", "--test_arg=--exact", "--test_arg=--test-threads=1"],
                [case],
            )
    finally:
        for path, content in source_files.items():
            if path.read_bytes() not in (content, diagnostic_files[path]):
                raise RuntimeError(f"Concurrent source mutation detected: {path.relative_to(repo)}")
        for path, content in source_files.items():
            path.write_bytes(content)
        save("source-restored.json", {
            str(path.relative_to(repo)): {"sha256": sha256(path.read_bytes()), "exact": path.read_bytes() == content}
            for path, content in source_files.items()
        })
    clean = run("source-clean", ["git", "diff", "--exit-code"])
    all_passed = all(
        row["exit"] == 0 and row.get("successful_execution_verified", True)
        for row in commands
    )
    save(
        "complete.json",
        {
            "complete": True,
            "all_commands_passed": all_passed,
            "sdk_source_restored": sha256(sdk.read_bytes()) == SDK_SHA256,
            "all_instrumented_sources_restored": all(
                path.read_bytes() == content for path, content in source_files.items()
            ),
            "original_fixture_unchanged": sha256(fixture.read_bytes()) == TEST_SHA256,
            "original_5_second_startup_and_pbkdf2_200000_unchanged": True,
            "tmpdir_not_overridden": True,
            "ci_failure_root_cause_confirmed": False,
            "full_workspace_qualified": False,
            "diagnostic_only": True,
        },
    )
    if not all_passed or clean:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

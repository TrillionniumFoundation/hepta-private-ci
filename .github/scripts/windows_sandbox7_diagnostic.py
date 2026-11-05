"""Run the original Windows sandbox seven-case diagnostic with actual helpers.

Only --success-output immediate is added to the original test argv. This is
not the original 131-case qualification, even when every selected test passes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time


BASE = "6fd18c0e077e2c94ff9968b42de53dcb499aebfa"
BASE_TREE = "3fde256c766150d154df64b5d1942445d60ee5f4"
BRANCH = "diagnostics/p1-windows-sandbox7-20261105-ba4b"
DRIVER = ".github/scripts/windows_sandbox7_diagnostic.py"
WORKFLOW = ".github/workflows/hepta-windows-sandbox7-diagnostic.yml"
ORIGINAL_DRIVER = ".github/scripts/windows_current_ci.py"
SCOPE = ".github/fixtures/windows-current-ci-scope.json"
GROUP_ID = "sandbox-original-failures"
GROUP_SHA256 = "16ef660ff6f45aa9d14886864a95791909a8f7e9b7a9c4b14e487345de6e0c0a"
EXPECTED_TESTS = (
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces",
    "unified_exec::tests::acl_setup_tests::legacy_capture_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::acl_setup_tests::legacy_session_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit",
    "unified_exec::tests::legacy_non_tty_cmd_emits_output",
    "unified_exec::tests::legacy_non_tty_cmd_rejects_deny_read_overrides",
    "unified_exec::tests::legacy_workspace_write_delete_is_limited_to_writable_roots",
)
INPUT_BLOBS = {
    ORIGINAL_DRIVER: "161ed1149c8ffb5f2bb2a8272f555f8b91d729fe",
    ".github/scripts/test_windows_current_ci.py": "37b431d0fa3aa41b8cd12fe99fe8dccf3db5f171",
    SCOPE: "27b62138734497459874131e198830b9e74bcd78",
    "justfile": "a215a76cf407ace9715bca39c20497014e7dd4dc",
    "scripts/just-shell.py": "bb2db6ebc4312a301ee39d2793fde16289d046d8",
    "scripts/run-nextest.py": "1ed63abe84267b320cbfb0123a70aac5507f4595",
    "codex-rs/Cargo.toml": "7e2ec509988e11cdf92130e385ffdf409bbcc15d",
    "codex-rs/rust-toolchain.toml": "917d2492264a35bc9c0feaef41878d8825870866",
    "codex-rs/windows-sandbox-rs/Cargo.toml": "aa41ed5f08608c0275785b2f5e27ec5db08f50dd",
    "codex-rs/windows-sandbox-rs/build.rs": "6ba79e6c75deb87067ced02e824eaf7faf79346d",
    "codex-rs/windows-sandbox-rs/src/elevated/runner_client.rs": "95a1a2891a0b8df23f7257783e63b0ed22b2e995",
    "codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs": "1c06624f04400b15221708fa7e39e5ae76480d18",
}
LOCK_SHA256 = {
    "MODULE.bazel.lock": "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb",
    "apps/hepta-control-ui/rust/.config/nextest.toml": "4a479affb48b1d3eadb431d8bdbaf249c5514754a8652db4693798b41dd7f25f",
    "apps/hepta-control-ui/rust/Cargo.lock": "99d22c4031512530e66b1e1cbec256d069e6e613e158f37d247d9307de265734",
    "apps/hepta-control-ui/rust/robrix-ui/patches/cargo-makepad.Cargo.lock": "a7a430f48541ea113a6d8a85153ec3de5c9570953602a212e8a71597e4cca647",
    "codex-rs/.config/nextest.toml": "a829e7ba9e72c44d3a8c5378a0ae595aee57cdb4265ed1f5ad1f7ef03a602a6a",
    "codex-rs/Cargo.lock": "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c",
    "codex-rs/third_party/accesskit-0.17.1/Cargo.lock": "113950acd22987215eee25cdd9a63e7b2fb2fea4dd97bb4c14118e5f14e03f4c",
    "codex-rs/third_party/aws-config-1.12.0/Cargo.lock": "3a37dfd25d255503591e98e804521872ada8ae33b4fd155604291621b48a9e4f",
    "codex-rs/third_party/matrix-sdk-crypto-0.18.0/Cargo.lock": "a5d7e872d3cbe3d1fdb5f2fb1aacf0647ad08774e939d19c4dd07103464686e9",
    "codex-rs/third_party/matrix-sdk-sqlite-0.18.0/Cargo.lock": "3d01214819e5129222113e3f3a07891821fd1e9d13db0a7bec6e4c9fab4e282d",
    "qualification/hnmf-adversarial-reference/Cargo.lock": "077b9eb1010dbe284566760a75373972c292164f21bc8efc78d8a13b3e4df5c5",
    "qualification/hnmf-contract-reference/Cargo.lock": "37e381293ce9281e203dad1bbb4ffcc7ace611a0ff789ea7a472814d5839c69d",
    "qualification/hnmf-reference/Cargo.lock": "8557470dd0e1e6c68b52ce54835b754beca16e00a2f0b20098e48c06530422ac",
    "scripts/codex_package/smoke_tests/uv.lock": "f91022575695bdbec3bf87a3fbd97f9f6aacd03bbbcea5e33b1056a98dfac6e7",
    "scripts/uv.lock": "6b8e7a82d1a4f4c5d59ce57cf8be472ea031c6fb0a905506258d434132b3c99c",
    "sdk/python-runtime/uv.lock": "77751399c5fb958a85607cdec8b2f7704c3b4a2fffd5f5ef66f907146590e791",
    "sdk/python/uv.lock": "c212c08818ad1a2b4016862d27e22e77b950296b3ed382594233535fdc5ba258",
    "tools/argument-comment-lint/Cargo.lock": "43deace1b5473447caf871bbf463c6f9b9c83e1382dc5f9db602394ac5d18421"
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def git(source, *args):
    forbidden = (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
    )
    require(not any(name in os.environ for name in forbidden), "Unexpected Git environment override")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(
        ["git", "--no-replace-objects", "-c", "core.fsmonitor=false", "-C", str(source), *args],
        env=env, capture_output=True, check=True, timeout=30,
    ).stdout


def snapshot(source, expected_head):
    head = git(source, "rev-parse", "HEAD").decode().strip()
    require(head == expected_head, "Checkout differs from the diagnostic event head")
    require(git(source, "show", "-s", "--format=%P", "HEAD").decode().strip() == BASE,
            "Diagnostic parent differs from the frozen source")
    require(git(source, "rev-parse", BASE + "^{tree}").decode().strip() == BASE_TREE,
            "Original base tree differs")
    require(not git(source, "status", "--porcelain=v1", "--untracked-files=all"),
            "Source is not clean")
    delta = git(source, "diff-tree", "--no-commit-id", "--name-status", "-r", BASE, head)
    require(sorted(delta.decode().splitlines()) == ["A\t" + p for p in sorted((DRIVER, WORKFLOW))],
            "Diagnostic commit changes original source, tests, or workflows")
    tracked = len(git(source, "ls-files", "-z").split(b"\0")) - 1
    require(tracked == 10776, "Complete tracked source inventory differs")
    config = {name: git(source, "config", "--get", name).decode().strip()
              for name in ("core.autocrlf", "core.eol")}
    require(config == {"core.autocrlf": "false", "core.eol": "lf"}, "LF checkout configuration differs")
    inputs = {}
    paths = sorted(set(INPUT_BLOBS) | set(LOCK_SHA256) | {DRIVER, WORKFLOW,
        "codex-rs/windows-sandbox-rs/codex-windows-sandbox-setup.manifest",
        "codex-rs/windows-sandbox-rs/src/bin/setup_main/main.rs",
        "codex-rs/windows-sandbox-rs/src/bin/command_runner/main.rs",
        "codex-rs/windows-sandbox-rs/src/token_tests.rs"})
    for name in paths:
        path = source / name
        require(path.is_file() and not path.is_symlink(), "Source input is not a regular file")
        working = path.read_bytes()
        canonical = git(source, "show", "HEAD:" + name)
        object_id = git_blob(canonical)
        require(working == canonical, "Working bytes differ from Git blob: " + name)
        if name in INPUT_BLOBS:
            require(object_id == INPUT_BLOBS[name], "Frozen original input blob differs: " + name)
        if name in LOCK_SHA256:
            require(digest(canonical) == LOCK_SHA256[name], "Original lock/configuration differs: " + name)
        inputs[name] = {
            "git_blob": object_id, "git_bytes": len(canonical),
            "git_sha256": digest(canonical), "working_blob": git_blob(working),
            "working_bytes": len(working), "working_sha256": digest(working),
        }
    return {"head": head, "tree": git(source, "rev-parse", "HEAD^{tree}").decode().strip(),
            "base": BASE, "base_tree": BASE_TREE, "clean": True, "tracked_files": tracked,
            "lock_count": len(LOCK_SHA256), "git_checkout_config": config, "inputs": inputs}


def file_record(path):
    data = path.read_bytes()
    return {"file": path.name, "bytes": len(data), "sha256": digest(data)}


def load_original(source):
    spec = importlib.util.spec_from_file_location("windows_current_ci", source / ORIGINAL_DRIVER)
    require(spec is not None and spec.loader is not None, "Original driver cannot be imported")
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    return original


def tool_versions(source):
    commands = {"rustc": ["rustc", "--version", "--verbose"],
                "cargo": ["cargo", "--version"], "just": ["just", "--version"],
                "nextest": ["cargo", "nextest", "--version"], "python": [sys.executable, "--version"]}
    values = {}
    for name, command in commands.items():
        completed = subprocess.run(command, cwd=source / "codex-rs", check=True,
                                   capture_output=True, text=True, timeout=30)
        values[name] = completed.stdout.strip()
    require(values["rustc"].startswith("rustc 1.96.0 ")
            and "host: x86_64-pc-windows-msvc" in values["rustc"], "Original native Rust differs")
    require(values["cargo"].startswith("cargo 1.96.0 "), "Original Cargo differs")
    require(values["just"] == "just 1.51.0", "Original just differs")
    require(re.match(r"^cargo-nextest 0\.9\.103(?:\s|$)", values["nextest"]) is not None,
            "Original nextest differs")
    return {"versions": values, "resolved_paths": {
        "rustc": shutil.which("rustc"), "cargo": shutil.which("cargo"),
        "just": shutil.which("just"), "cargo_nextest": shutil.which("cargo-nextest"),
        "pwsh": shutil.which("pwsh.exe") or shutil.which("pwsh"), "python": sys.executable}}


def save(output, report):
    (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def run_to_file(command, cwd, path):
    # File-backed outer output preserves nextest's own per-test PIPE capture
    # without introducing Python communicate() reader threads.
    with path.open("xb") as stream:
        process = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                 check=False)
    return process.returncode


def verify_helpers(helpers):
    records = []
    for item in helpers.get("artifacts", []):
        source, sibling = Path(item["source"]), Path(item["testSibling"])
        a, b = source.read_bytes(), sibling.read_bytes()
        require(a == b and len(a) == item["bytes"] and digest(a) == item["sha256"],
                "An actual sandbox helper changed after publication")
        records.append({"name": item["name"], "bytes": len(a), "sha256": digest(a),
                        "source": str(source), "test_sibling": str(sibling)})
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_OS") == "Windows", "Requires the Windows Actions runner")
    require(os.environ.get("GITHUB_REF") == "refs/heads/" + BRANCH,
            "Requires the isolated sandbox7 branch")
    source = Path(__file__).resolve().parents[2]
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    output = args.output.resolve()
    require(output.is_relative_to(runner_temp) and output != runner_temp
            and not output.is_relative_to(source), "Evidence must use its own runner-temporary directory")
    output.mkdir(exist_ok=False)
    report = {
        "schema": "hepta.windows-sandbox7-diagnostic.v1", "qualification": False,
        "original_131_executed": False, "diagnostic_passed": False, "execution_complete": False,
        "started_unix": time.time(), "stage": "admission", "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"), "platform": platform.platform(),
        "machine": platform.machine(), "python": sys.version, "groups": [],
        "runner_image": {"ImageOS": os.environ.get("ImageOS"),
                         "ImageVersion": os.environ.get("ImageVersion")},
        "test_retries": 0, "only_test_cli_addition": ["--success-output", "immediate"],
    }
    before = None
    save(output, report)
    try:
        require(re.fullmatch(r"[0-9a-f]{40}", args.expected_head) is not None
                and args.expected_head == os.environ.get("GITHUB_SHA"), "Expected event head differs")
        expected_env = {"RUSTUP_TOOLCHAIN": "1.96.0", "CARGO_BUILD_JOBS": "1",
            "CARGO_INCREMENTAL": "0", "CARGO_PROFILE_DEV_DEBUG": "0", "CARGO_PROFILE_TEST_DEBUG": "0",
            "CARGO_TERM_COLOR": "never", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
        require(all(os.environ.get(k) == v for k, v in expected_env.items()),
                "Original workflow environment differs")
        report["workflow_environment"] = expected_env
        report["stage"] = "source_before"
        save(output, report)
        before = snapshot(source, args.expected_head)
        report["source_before"] = before
        report["tools"] = tool_versions(source)
        (output / "compiler.txt").write_text(report["tools"]["versions"]["rustc"] + "\n", encoding="utf-8")
        target = Path(os.environ["CARGO_TARGET_DIR"]).resolve()
        require(target == runner_temp / "hepta-windows-sandbox7-target"
                and not target.is_relative_to(source), "Cargo target is not the isolated task target")
        target.mkdir(exist_ok=False)
        report["target"] = str(target)
        report["disk_free_before"] = shutil.disk_usage(target).free
        scope = json.loads((source / SCOPE).read_text(encoding="utf-8"))
        selected = [group for group in scope["groups"] if group["id"] == GROUP_ID]
        require(len(selected) == 1, "Original seven-case group is not unique")
        group = selected[0]
        require(digest(json.dumps(group, sort_keys=True, separators=(",", ":")).encode()) == GROUP_SHA256,
                "Original seven-case group changed")
        require(group["package"] == "codex-windows-sandbox" and group["expectedTestCount"] == 7
                and group["requiredTests"] == list(EXPECTED_TESTS)
                and group["filter"] == " | ".join("test(=" + name + ")" for name in EXPECTED_TESTS),
                "Original seven-case names or filter differ")
        report["selected_group"] = group
        (output / "selected-group.json").write_text(json.dumps(group, indent=2) + "\n", encoding="utf-8")
        original = load_original(source)

        report["stage"] = "original_scope_checker_tests"
        save(output, report)
        checker_command = [sys.executable, "-m", "unittest", "discover", "-s", ".github/scripts",
                           "-p", "test_windows_current_ci.py"]
        checker_log = output / "original-scope-checker.log"
        checker_code = run_to_file(checker_command, source, checker_log)
        report["original_scope_checker"] = {"command": checker_command, "exit_code": checker_code,
                                            "log": file_record(checker_log)}
        require(checker_code == 0, "Original scope checker tests failed")

        temporary = {"original_temp": os.environ.get("TEMP"), "original_tmp": os.environ.get("TMP"),
                     "runner_temp": str(runner_temp)}
        case_temp = runner_temp / "hepta-original-case-temp"
        case_temp.mkdir(exist_ok=False)
        native_temp = case_temp.resolve(strict=True)
        os.environ["TEMP"] = os.environ["TMP"] = str(native_temp)
        temporary["physical_case_temp"] = str(native_temp)
        report["temporary_environment"] = temporary
        report["stage"] = "original_sandbox_helper_build"
        save(output, report)
        helpers = original.prepare_sandbox_helpers(source, output)
        report["sandbox_helper_preparation"] = helpers
        # As in the original driver, retain test results even if a prerequisite
        # failed; helper failure always prevents a passing diagnostic.
        save(output, report)

        report["stage"] = "original_sandbox_seven_tests"
        # Nextest 0.9.103 resolves store.dir beneath the Cargo workspace,
        # independently of CARGO_TARGET_DIR.
        junit = source / "codex-rs" / "target" / "nextest" / "local" / "junit.xml"
        require(not junit.exists(), "Original-config JUnit already exists before this run")
        report["junit"] = {"original_config_path": str(junit), "preexisting": False}
        save(output, report)
        raw_log = output / "nextest-raw.log"

        def invoke(command):
            command.extend(["--success-output", "immediate"])
            report["actual_test_argv"] = list(command)
            save(output, report)
            started = time.monotonic()
            code = run_to_file(command, source / "codex-rs", raw_log)
            report["raw_nextest"] = {"exit_code": code, "duration_seconds": time.monotonic() - started,
                                    "log": file_record(raw_log)}
            save(output, report)
            # Match the original driver's universal-newline text read for its
            # assessor; the independent raw file above remains byte-exact.
            return code, raw_log.read_text(encoding="utf-8", errors="replace")

        report["groups"] = original.execute_groups(source, output, [group], invoke)
        report["sandbox_helpers_after"] = verify_helpers(helpers)
        report["junit"]["produced_by_original_config"] = junit.is_file()
        if junit.is_file():
            destination = output / "nextest.junit.xml"
            destination.write_bytes(junit.read_bytes())
            report["junit"].update(file_record(destination))
        report["stages_finished"] = True
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["error_errno"] = getattr(error, "errno", None)
        if isinstance(error, RuntimeError):
            report["error_message"] = str(error)  # Only fixed, task-local require messages.
    finally:
        report["stage_at_exit"] = report["stage"]
        if before is not None:
            try:
                report["source_after"] = snapshot(source, args.expected_head)
                report["source_unchanged"] = report["source_after"] == before
            except Exception as error:
                report["source_after_error_type"] = type(error).__name__
                if isinstance(error, RuntimeError):
                    report["source_after_error_message"] = str(error)
                report["source_unchanged"] = False
        intact = report.get("source_unchanged", False)
        groups = report["groups"]
        report["execution_complete"] = bool(report.get("stages_finished") and intact
            and len(groups) == 1 and groups[0]["selectionMatches"])
        report["diagnostic_passed"] = bool(report["execution_complete"]
            and report["sandbox_helper_preparation"]["passed"] and groups[0]["passed"])
        try:
            report["disk_free_after"] = shutil.disk_usage(runner_temp).free
        except OSError as error:
            report["resource_observation_error"] = type(error).__name__
        report["finished_unix"] = time.time()
        save(output, report)
        files = [file_record(path) for path in sorted(output.iterdir())
                 if path.is_file() and path.name != "artifact-manifest.json"]
        (output / "artifact-manifest.json").write_text(
            json.dumps({"files": files, "qualification": False}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"diagnostic_passed": report["diagnostic_passed"],
            "execution_complete": report["execution_complete"], "qualification": False,
            "stage": report["stage_at_exit"], "groups": report["groups"]}), flush=True)
    return 0 if report["diagnostic_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

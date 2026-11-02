#!/usr/bin/env python3
"""Execute workflow shell and the real wrapper with a synthetic tool boundary."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml


TARGET = "//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test"
WORKFLOW = ".github/workflows/hcsn-robrix-fixture-r16.yml"
WRAPPER = ".github/scripts/run-bazel-ci.sh"
SOURCE = "f52dc359344cd0eb9b5dba84d4af3d5815aeb629"
HEAD_EXPRESSION = "${{ github.event.pull_request.head.sha || github.sha }}"
STUB = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
if args[:1] == ["--wrapper-args-file"]:
    raw = pathlib.Path(args[1]).read_bytes()
    assert raw.endswith(b"\0")
    args = [item.decode() for item in raw[:-1].split(b"\0")]
with open(os.environ["SYNTHETIC_CAPTURE"], "a", encoding="utf-8") as out:
    out.write(json.dumps(args) + "\n")
if "test" in args:
    status = int(os.environ["SYNTHETIC_BAZEL_EXIT"])
    if status:
        print("ERROR: synthetic lower-executor failure")
    sys.exit(status)
assert "info" in args, args
print("/synthetic/no-test-logs")
'''


def identity(path):
    data = path.read_bytes()
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def run(command, cwd, env):
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
    return {"command": command, "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    doc = yaml.safe_load((root / WORKFLOW).read_text())
    assert doc["permissions"] == {"contents": "read"}
    assert set(doc["jobs"]) == {"robrix"}
    job = doc["jobs"]["robrix"]
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["include"] == [
        {"os": "ubuntu-24.04", "target": "x86_64-unknown-linux-gnu"},
        {"os": "windows-latest", "target": "x86_64-pc-windows-msvc"},
    ]
    assert job["env"]["SOURCE_COMMIT"] == HEAD_EXPRESSION
    steps = {step["name"]: step for step in job["steps"]}
    checkout = steps["Check out the exact source head"]
    assert checkout["with"] == {"ref": HEAD_EXPRESSION, "persist-credentials": False}
    assert checkout["uses"] == "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd"
    prepare = steps["Prepare Bazel CI"]
    assert prepare["uses"] == "./.github/actions/prepare-bazel-ci"
    assert prepare["with"] == {"target": "${{ matrix.target }}", "cache-scope": "bazel-test"}
    selected = steps["Run the complete Robrix fixture target"]
    assert "continue-on-error" not in selected and "if" not in selected
    assert selected["shell"] == "bash"
    assert selected["env"] == {"BUILDBUDDY_API_KEY": "${{ secrets.BUILDBUDDY_API_KEY }}"}
    clean = steps["Check for a clean worktree"]
    assert clean["uses"] == "./.github/actions/check-clean-worktree"
    assert clean["if"] == "always() && !cancelled()" and "continue-on-error" not in clean
    upload = steps["Upload Bazel execution logs"]
    assert upload["if"] == "always() && !cancelled()"
    assert upload["uses"] == "actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f"
    assert upload["with"]["path"] == "${{ runner.temp }}/bazel-execution-logs"
    runs = []
    preflight = []
    with tempfile.TemporaryDirectory(prefix="robrix-workflow-wiring-") as temp:
        base = Path(temp)
        script = base / WRAPPER
        script.parent.mkdir(parents=True)
        shutil.copyfile(root / WRAPPER, script)
        script.chmod(0o755)
        lower = script.with_name("run_bazel_with_buildbuddy.py")
        lower.write_text(STUB)
        lower.chmod(0o755)
        for platform in ["Linux", "Windows"]:
            for status in [0, 37]:
                capture = base / f"{platform}-{status}.jsonl"
                env = {"PATH": os.defpath, "RUNNER_OS": platform,
                       "SOURCE_COMMIT": SOURCE, "BUILDBUDDY_API_KEY": "",
                       "SYNTHETIC_CAPTURE": str(capture),
                       "SYNTHETIC_BAZEL_EXIT": str(status)}
                if platform == "Windows":
                    for name in ["INCLUDE", "LIB", "LIBPATH", "UniversalCRTSdkDir",
                                 "VCToolsInstallDir", "WindowsSdkDir"]:
                        env[name] = "synthetic-sdk-path"
                    env["CODEX_BAZEL_WINDOWS_PATH"] = "synthetic-windows-path"
                execution = run(["bash", "-c", selected["run"]], base, env)
                calls = [json.loads(row) for row in capture.read_text().splitlines()]
                tests = [call for call in calls if "test" in call]
                assert execution["exit_code"] == status, execution
                assert len(tests) == 1, calls
                command = tests[0]
                assert command[command.index("--") + 1:] == [TARGET], command
                assert command.count("--nocache_test_results") == 1
                assert command.count("--test_output=all") == 1
                assert "--build_metadata=COMMIT_SHA=" + SOURCE in command
                assert not any("filter" in arg or "skip" in arg or "shard" in arg
                               for arg in command)
                assert "--host_platform=//:local_windows_msvc" in command if platform == "Windows" else "--host_platform=//:local_windows_msvc" not in command
                assert "--platforms=//:windows_x86_64_msvc" in command if platform == "Windows" else "--platforms=//:windows_x86_64_msvc" not in command
                expected_config = "--config=ci-windows" if platform == "Windows" else "--config=ci-linux"
                assert expected_config in command
                runs.append({"runner_os": platform, "synthetic_lower_exit": status,
                             "execution": execution, "lower_executor_calls": calls})
        repo = base / "preflight"
        repo.mkdir()
        env = {"PATH": os.defpath}
        for command in [["git", "init", "-q"], ["git", "-c", "user.name=Workflow Audit",
                        "-c", "user.email=workflow-audit@local.invalid", "commit", "--allow-empty",
                        "-qm", "Synthetic source identity"]]:
            execution = run(command, repo, env)
            assert execution["exit_code"] == 0, execution
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        for requested, expected in [(head, 0), ("0" * 40, 1)]:
            execution = run(["bash", "-c", steps["Verify the source commit"]["run"]],
                            repo, {**env, "SOURCE_COMMIT": requested})
            assert execution["exit_code"] == expected, execution
            preflight.append({"actual_head": head, "requested_head": requested, "execution": execution})
    receipt = {"schema": "robrix-workflow-wiring-v1", "passed": True,
               "scope": "Actual extracted workflow Bash plus unchanged shell wrapper on Linux; Python executor is an explicit synthetic argument/exit double. No native Bazel, MSVC, Windows host, or test assertions executed.",
               "workflow": identity(root / WORKFLOW), "shell_wrapper": identity(root / WRAPPER),
               "workflow_matrix_runs": runs, "source_preflight_runs": preflight,
               "native_execution_count": 0}
    with args.output.open("x") as output:
        json.dump(receipt, output, indent=2)
        output.write("\n")
    print(json.dumps({"passed": True, "wrapper_cases": len(runs), "source_cases": len(preflight),
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()

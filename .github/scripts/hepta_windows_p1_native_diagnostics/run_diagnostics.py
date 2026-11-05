"""Run bounded native diagnostics without replacing original Windows tests."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


BASE = "6fd18c0e077e2c94ff9968b42de53dcb499aebfa"
BASE_TREE = "3fde256c766150d154df64b5d1942445d60ee5f4"
PREFIX = ".github/scripts/hepta_windows_p1_native_diagnostics"
MANIFEST = PREFIX + "/manifest.json"
WORKFLOW = ".github/workflows/hepta-windows-p1-native-diagnostics.yml"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(source, *args):
    forbidden = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")
    require(not any(name in os.environ for name in forbidden), "Unexpected Git environment override")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_OPTIONAL_LOCKS="0")
    return subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(source), *args],
                          env=env, capture_output=True, check=True, timeout=30).stdout


def snapshot(source, manifest, expected_head):
    head = git(source, "rev-parse", "HEAD").decode().strip()
    require(head == expected_head, "Checkout differs from actual workflow event head")
    require(git(source, "show", "-s", "--format=%P", "HEAD").decode().strip() == BASE,
            "Diagnostic commit has a different parent")
    require(git(source, "rev-parse", BASE + "^{tree}").decode().strip() == BASE_TREE,
            "Original provisional base tree differs")
    require(not git(source, "status", "--porcelain=v1", "--untracked-files=all"),
            "Source checkout is not clean")
    expected_paths = sorted([WORKFLOW, PREFIX + "/run_diagnostics.py", MANIFEST,
                             *[item["path"] for item in manifest["probes"]]])
    delta = git(source, "diff-tree", "--no-commit-id", "--name-status", "-r", BASE, head)
    require(sorted(delta.decode().splitlines()) == ["A\t" + path for path in expected_paths],
            "Diagnostic branch modifies original product/test/workflow inputs")
    input_records = {}
    for name in expected_paths:
        data = (source / name).read_bytes()
        mode = git(source, "ls-tree", "HEAD", "--", name).decode().split()[0]
        require(mode == "100644", "Unexpected diagnostic source file mode")
        input_records[name] = {"bytes": len(data), "sha256": sha256(data)}
    for item in manifest["probes"]:
        require(input_records[item["path"]]["sha256"] == item["sha256"],
                "Reviewed native probe changed")
    require(len(manifest["locks"]) == 18, "Original lock/nextest inventory changed")
    for name, digest in manifest["locks"].items():
        require(sha256((source / name).read_bytes()) == digest,
                "Original lock/nextest working bytes differ")
        require(sha256(git(source, "show", BASE + ":" + name)) == digest,
                "Original lock/nextest base bytes differ")
    tracked = len(git(source, "ls-files", "-z").split(b"\0")) - 1
    require(tracked == 10774 + len(expected_paths), "Complete tracked file inventory differs")
    return {"head": head, "tree": git(source, "rev-parse", "HEAD^{tree}").decode().strip(),
            "base": BASE, "base_tree": BASE_TREE, "tracked_files": tracked,
            "clean": True, "original_lock_count": len(manifest["locks"]),
            "diagnostic_inputs": input_records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_OS") == "Windows", "Requires an owned Windows Actions runner")
    source = Path(__file__).resolve().parents[3]
    output = args.output.resolve()
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    require(output.is_relative_to(runner_temp) and not output.is_relative_to(source),
            "Evidence must stay in runner temporary storage outside the checkout")
    output.mkdir(parents=False, exist_ok=False)
    report = {"kind": "standalone Windows native diagnosis", "qualification": False,
              "original_product_tests_executed": False, "started_unix": time.time(),
              "platform": platform.platform(), "python": sys.version,
              "run_id": os.environ.get("GITHUB_RUN_ID"),
              "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "probes": [], "complete": False}
    try:
        manifest = json.loads((source / MANIFEST).read_text(encoding="utf-8"))
        require(manifest["base"] == BASE and manifest["base_tree"] == BASE_TREE,
                "Diagnostic manifest base differs")
        expected_head = os.environ["GITHUB_SHA"]
        report["source_before"] = snapshot(source, manifest, expected_head)
        for item in manifest["probes"]:
            label = item["name"]
            require(label in {"programdata", "logon-stdio", "token-accesscheck"},
                    "Unexpected native probe")
            stdout_path, stderr_path = output / (label + ".stdout.log"), output / (label + ".stderr.log")
            record = {"name": label, "source_sha256": item["sha256"],
                      "started_unix": time.time(), "timed_out": False}
            try:
                with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                    completed = subprocess.run([sys.executable, "-B", str(source / item["path"])],
                                               cwd=source, stdout=stdout, stderr=stderr,
                                               timeout=600, check=False)
                record["exit_code"] = completed.returncode
            except subprocess.TimeoutExpired:
                record.update(timed_out=True, exit_code=None)
            record["finished_unix"] = time.time()
            for name, path in [("stdout", stdout_path), ("stderr", stderr_path)]:
                data = path.read_bytes()
                record[name] = {"file": path.name, "bytes": len(data), "sha256": sha256(data)}
            try:
                receipt = json.loads(stdout_path.read_text(encoding="utf-8"))
                require(isinstance(receipt, dict), "Native probe did not return one JSON object")
                record["receipt"] = receipt
                observed = receipt.get("observations_complete", receipt.get("passed", False))
                record["observations_complete"] = observed is True and record["exit_code"] == 0
            except (UnicodeError, ValueError, RuntimeError) as error:
                record["receipt_error_type"] = type(error).__name__
                record["observations_complete"] = False
            report["probes"].append(record)
            (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        report["source_after"] = snapshot(source, manifest, expected_head)
        require(report["source_before"] == report["source_after"], "Source changed during diagnostics")
        report["complete"] = len(report["probes"]) == len(manifest["probes"]) and all(
            item["observations_complete"] for item in report["probes"])
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["error_errno"] = getattr(error, "errno", None)
    finally:
        report["finished_unix"] = time.time()
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"complete": report["complete"], "qualification": False,
                          "probes": [{"name": item["name"], "exit_code": item.get("exit_code"),
                                      "observations_complete": item.get("observations_complete", False)}
                                     for item in report["probes"]]}), flush=True)
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""Run the registered experiment on the existing verified project runner."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


BRANCH = "refs/heads/research/ndu-latent-riccati-20261021"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
GROUP = "trillionnium-android-gpu"
PINNED = {"torch": "2.5.1+cpu", "numpy": "1.26.4", "scipy": "1.14.1"}


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_capture(command, cwd=None):
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def dependency_receipt(python):
    code = """
import importlib,json,os,platform,sys
out={'python':sys.version,'python_executable':sys.executable,
     'platform':platform.platform(),'cpu_count':os.cpu_count(),'libraries':{}}
for name in ['torch','numpy','scipy']:
    try:
        m=importlib.import_module(name)
        out['libraries'][name]={'version':m.__version__,'import_ok':True}
        if name=='torch':
            out['cuda']={'available':m.cuda.is_available(),
                         'device_count':m.cuda.device_count(),'build':m.version.cuda}
    except Exception as exc:
        out['libraries'][name]={'import_ok':False,'error':str(exc)}
print(json.dumps(out))
"""
    return json.loads(run_capture([python, "-c", code]))


def dependencies_match(receipt):
    return all(receipt["libraries"].get(name, {}).get("version", "")
               == version for name, version in PINNED.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "launcher-receipt.json").exists():
        print("Existing launcher receipt retained; use a new run output directory", file=sys.stderr)
        return 78
    source = Path(__file__).resolve().parents[1]
    repo = source.parents[1]
    receipt = {"schema": "ndu-latent-riccati-launcher-v1", "started_at": utc_now(),
               "requested_execution_tier": "dedicated-cloud",
               "dedicated_runner_verified": False, "source_verified": False,
               "stage": "runner_identity", "success": False,
               "scientific_success_inferred_from_process_exit": False}
    started = time.perf_counter()
    exit_code = 78
    try:
        expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
                    "GITHUB_REF": BRANCH, "RUNNER_NAME": "desktop",
                    "RUNNER_ENVIRONMENT": "self-hosted", "RUNNER_OS": "Linux",
                    "RUNNER_ARCH": "X64", "HEPTA_DEDICATED_RUNNER_GROUP": GROUP}
        receipt["assignment"] = {name: os.environ.get(name) for name in expected}
        receipt["run_id"] = os.environ.get("GITHUB_RUN_ID")
        receipt["run_attempt"] = os.environ.get("GITHUB_RUN_ATTEMPT")
        wrong = [name for name, value in expected.items() if os.environ.get(name) != value]
        if wrong:
            raise RuntimeError("Unverified project runner identity fields: " + ", ".join(wrong))
        if os.environ.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}:
            raise RuntimeError("Unexpected workflow event")
        runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
        if not runner_temp.is_dir() or not output.is_relative_to(runner_temp):
            raise RuntimeError("Evidence output must be inside the assigned RUNNER_TEMP")
        receipt["dedicated_runner_verified"] = True
        receipt["stage"] = "source_verification"
        expected_sha = os.environ.get("HEPTA_EXPERIMENT_EXPECTED_SHA", "")
        actual_sha = run_capture(["git", "rev-parse", "HEAD"], repo)
        receipt["source_sha"] = actual_sha
        receipt["expected_source_sha"] = expected_sha
        if not re.fullmatch(r"[0-9a-f]{40}", expected_sha) or actual_sha != expected_sha:
            raise RuntimeError("Checkout does not match the workflow source SHA")
        source_relative = source.relative_to(repo).as_posix()
        run_capture(["git", "diff", "--exit-code", "HEAD", "--", source_relative], repo)
        untracked = run_capture(["git", "ls-files", "--others", "--exclude-standard",
                                 "--", source_relative], repo)
        if untracked:
            raise RuntimeError("Untracked files exist inside experiment source")
        request = json.loads((source / "CLOUD_RUN_REQUEST.json").read_text())
        protocol_path = source / "protocol.json"
        protocol_bytes = protocol_path.read_bytes()
        protocol_hash = hashlib.sha256(protocol_bytes).hexdigest()
        receipt["protocol_sha256"] = protocol_hash
        if request.get("protocol_sha256") != protocol_hash:
            raise RuntimeError("Protocol hash differs from the registered cloud request")
        tracked = run_capture(["git", "ls-files", "--", source_relative], repo).splitlines()
        hashes = {path: hashlib.sha256((repo / path).read_bytes()).hexdigest()
                  for path in tracked if (repo / path).is_file()}
        (output / "source-manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
        (output / "protocol.json").write_bytes(protocol_bytes)
        (output / "CLOUD_RUN_REQUEST.json").write_text(json.dumps(request, indent=2) + "\n")
        receipt["source_verified"] = True
        receipt["stage"] = "dependencies"
        python = os.environ.get("HEPTA_EXPERIMENT_PYTHON", sys.executable)
        version = json.loads(run_capture([python, "-c", "import json,sys;print(json.dumps(list(sys.version_info[:2])))"]))
        if tuple(version) not in {(3, 10), (3, 11), (3, 12)}:
            raise RuntimeError("Pinned experiment dependencies require Python 3.10-3.12")
        initial = dependency_receipt(python)
        (output / "runtime-initial.json").write_text(json.dumps(initial, indent=2) + "\n")
        with (output / "dependency-install.log").open("w") as install_log:
            if not dependencies_match(initial):
                venv = Path(tempfile.mkdtemp(prefix="ndu-latent-venv-", dir=runner_temp))
                subprocess.run([python, "-m", "venv", str(venv)], check=True,
                               stdout=install_log, stderr=subprocess.STDOUT)
                python = str(venv / "bin" / "python")
                pip = [python, "-m", "pip", "--isolated", "install",
                       "--disable-pip-version-check", "--no-input", "--no-cache-dir"]
                subprocess.run(pip + ["--index-url", "https://pypi.org/simple",
                                      "numpy==1.26.4", "scipy==1.14.1"], check=True,
                               stdout=install_log, stderr=subprocess.STDOUT)
                subprocess.run(pip + ["--index-url", "https://download.pytorch.org/whl/cpu",
                                      "torch==2.5.1"], check=True,
                               stdout=install_log, stderr=subprocess.STDOUT)
                receipt["dependency_environment"] = "isolated_runner_temp_venv"
            else:
                receipt["dependency_environment"] = "existing_pinned_interpreter"
        final_runtime = dependency_receipt(python)
        (output / "runtime.json").write_text(json.dumps(final_runtime, indent=2) + "\n")
        if not dependencies_match(final_runtime):
            raise RuntimeError("Pinned runtime validation failed")
        run_capture([python, "-c", "import numpy as n,torch;assert torch.from_numpy(n.zeros(1)).numpy().shape==(1,)" ])
        receipt["python_executable"] = python
        receipt["stage"] = "experiment"
        run_output = output / "run"
        if run_output.exists():
            raise RuntimeError("Experiment output already exists; refusing to overwrite evidence")
        env = os.environ.copy()
        env.update({"PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1", "MPLCONFIGDIR": str(output / "matplotlib"),
                    "HEPTA_EXECUTION_TIER": "dedicated-cloud",
                    "HEPTA_DEDICATED_RUNNER_VERIFIED": "1",
                    "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"})
        command = [python, str(source / "run_experiment.py"), "--output", str(run_output),
                   "--execution-tier", "dedicated-cloud"]
        receipt["command"] = command
        with (output / "experiment.log").open("w") as log:
            with subprocess.Popen(command, cwd=repo, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1) as process:
                for line in process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                    log.flush()
                exit_code = process.wait()
        receipt["experiment_exit_code"] = exit_code
        if exit_code:
            raise RuntimeError(f"Experiment failed with exit code {exit_code}; partial evidence retained")
        receipt["stage"] = "complete"
        receipt["success"] = True
    except Exception as exc:
        receipt["error"] = str(exc)
        print(f"Launcher failed at {receipt['stage']}: {exc}", file=sys.stderr, flush=True)
        if exit_code == 0:
            exit_code = 78
    finally:
        receipt["finished_at"] = utc_now()
        receipt["elapsed_seconds"] = time.perf_counter() - started
        receipt["exit_code"] = exit_code
        (output / "launcher-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

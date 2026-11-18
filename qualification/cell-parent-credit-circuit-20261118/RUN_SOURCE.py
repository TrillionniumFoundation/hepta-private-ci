"""Own the fixed parent/credit E4 run and retain actual process and business exits."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time

ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
RUNTIME = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
TRAINING = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
CREDIT = Path(
    "/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b/source/qualification/cell-current-policy-credit-20261118"
)
PRIOR = Path(
    "/home/qian-qi/.local/state/hepta-runtime-mac-worker/jobs/1a1ef5fa542-ffbe-4a4"
)
PRIOR_HASHES = {
    "exit.json": "2ed0edc339a08c17ce9047467fa33a72470a5ead54078ab8376f9181d39224e6",
    "exit.witness.json": "134863fa0fa047c351424b3ab1e28a414386e7a44a0811f87f3c0cd8e20c38c8",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("xb") as stream:
        stream.write(
            json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    source, owned, output = root / "source", root / "owned-run-1", root / "run-1"
    owned.mkdir(exist_ok=False)
    started = time.monotonic()
    initial_self = resource.getrusage(resource.RUSAGE_SELF)
    initial_children = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        freeze = json.loads((root / "SOURCE_FREEZE.json").read_text())
        assert freeze["source_commit"] == args.source_commit
        assert (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip()
            == args.source_commit
        )
        assert (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True
            ).strip()
            == freeze["source_tree"]
        )
        assert not subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=source, text=True
        )
        for name, expected in freeze["files"].items():
            assert digest(source / name) == expected, name
        for name, expected in PRIOR_HASHES.items():
            assert digest(PRIOR / name) == expected, name
        prior = json.loads((PRIOR / "exit.json").read_text())
        assert (
            prior["exit_code"] == 0
            and not prior["timed_out"]
            and not prior["cancelled"]
        )
        assert prior["output_complete"] and prior["output_durable"]
        command = [
            str(RUNTIME / "venv/bin/python"),
            "-I",
            "-B",
            str(source / "scripts/cell_experiments/diagnostic_run_v4.py"),
            "--provider-python",
            str(RUNTIME / "venv/bin/python"),
            "--provider-script",
            str(source / "scripts/cell_experiments/diagnostic_provider_v4.py"),
            "--artifact-root",
            str(ARTIFACT),
            "--module-root",
            str(source / "scripts/cell_experiments"),
            "--output",
            str(output),
            "--study",
            "repair_retrieval",
            "--panel",
            "blind_b2",
            "--matched-training-source",
            str(TRAINING),
            "--current-credit-source",
            str(CREDIT),
        ]
        lock_path = ARTIFACT / "research-round03-20261118-392934-b/WORKER.lock"
        assert lock_path.is_file() and not lock_path.is_symlink()
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            gpu = subprocess.run(
                [
                    "/usr/bin/nvidia-smi",
                    "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            assert int(gpu.stdout.splitlines()[0]) >= 4096
            write(
                owned / "INTENT.json",
                {
                    "schema": "hepta.parent-credit-owned-run.v1",
                    "command": command,
                    "source_commit": args.source_commit,
                    "source_tree": freeze["source_tree"],
                    "wrapper_sha256": digest(Path(__file__)),
                    "source_freeze_sha256": digest(root / "SOURCE_FREEZE.json"),
                    "prior_receipts": {
                        name: {"path": str(PRIOR / name), "sha256": value}
                        for name, value in PRIOR_HASHES.items()
                    },
                    "lock": str(lock_path),
                    "gpu_free_mib_prefilter": int(gpu.stdout.splitlines()[0]),
                    "planned_primary_model_calls": 108,
                    "planned_A_setup_model_calls": 4,
                    "planned_primary_verifier_calls": 108,
                    "planned_A_setup_verifier_calls": 4,
                    "planned_A_reference_verifier_calls": 6,
                    "B2_already_exposed": True,
                    "automatic_retry": False,
                    "started_at_ns": time.time_ns(),
                },
            )
            env = dict(
                os.environ,
                HF_HUB_OFFLINE="1",
                TRANSFORMERS_OFFLINE="1",
                HF_DATASETS_OFFLINE="1",
                PYTHONDONTWRITEBYTECODE="1",
                TOKENIZERS_PARALLELISM="false",
                OMP_NUM_THREADS="1",
                OPENBLAS_NUM_THREADS="1",
            )
            timed_out = False
            with (
                (owned / "STDOUT.txt").open("xb") as stdout,
                (owned / "STDERR.txt").open("xb") as stderr,
            ):
                child = subprocess.Popen(
                    command,
                    cwd=source,
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                write(
                    owned / "STARTED.json",
                    {
                        "pid": child.pid,
                        "process_group_id": child.pid,
                        "started_at_ns": time.time_ns(),
                        "intent_sha256": digest(owned / "INTENT.json"),
                    },
                )
                try:
                    code = child.wait(timeout=1800)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        code = child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        code = child.wait(timeout=30)
            final_self = resource.getrusage(resource.RUSAGE_SELF)
            final_children = resource.getrusage(resource.RUSAGE_CHILDREN)
            receipt = {
                "pid": child.pid,
                "wait_returncode": code,
                "exit_source": "subprocess.Popen.wait",
                "timed_out": timed_out,
                "automatic_retry": False,
                "wall_seconds": time.monotonic() - started,
                "owner_user_cpu_seconds": final_self.ru_utime - initial_self.ru_utime,
                "owner_system_cpu_seconds": final_self.ru_stime - initial_self.ru_stime,
                "observed_child_user_cpu_seconds": final_children.ru_utime
                - initial_children.ru_utime,
                "observed_child_system_cpu_seconds": final_children.ru_stime
                - initial_children.ru_stime,
                "cost_scope": "owner plus owned child and waited descendants; nested model/verifier scopes are not additive",
                "full_system_cost_known": False,
                "monetary_cost": None,
                "energy_joules": None,
                "result_present": (output / "RESULT.json").is_file(),
                "failure_present": (output / "FAILED.json").is_file(),
                "stdout_sha256": digest(owned / "STDOUT.txt"),
                "stderr_sha256": digest(owned / "STDERR.txt"),
            }
            write(owned / "EXIT.json", receipt)
            print(json.dumps(receipt), flush=True)
            if code != 0 or timed_out:
                raise SystemExit(code if code > 0 else 1)
            result = json.loads((output / "RESULT.json").read_text())
            calibration = json.loads(
                (output / "A_SETUP_CALIBRATION/RESULT.json").read_text()
            )
            assert result["status"] == calibration["status"] == "COMPLETE"
            assert (
                result["cost"]["model_calls"] == result["cost"]["verifier_calls"] == 108
            )
            assert calibration["model_calls"] == calibration["verifier_calls"] == 4
            assert result["study_extension"]["additional_reference_verifier_calls"] == 6
            assert result["pool_initialization_cost"]["adapter_load_count"] == 2
            for name, expected in freeze["files"].items():
                assert digest(source / name) == expected, name
            write(
                owned / "COMPLETE.json",
                {
                    "status": "COMPLETE",
                    "model_calls": 112,
                    "verifier_calls": 118,
                    "actual_child_exit_sha256": digest(owned / "EXIT.json"),
                    "primary_result_sha256": digest(output / "RESULT.json"),
                    "setup_result_sha256": digest(
                        output / "A_SETUP_CALIBRATION/RESULT.json"
                    ),
                    "scientific_gain_claim": False,
                    "native_owner_adoption": False,
                    "GPU_released_after_owner_exit": True,
                },
            )
    except BaseException as error:
        if not isinstance(error, SystemExit):
            write(
                owned / "WRAPPER_FAILED.json",
                {
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "automatic_retry": False,
                    "cost_complete": False,
                },
            )
        raise


if __name__ == "__main__":
    main()

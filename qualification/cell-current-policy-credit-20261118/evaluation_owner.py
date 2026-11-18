"""Own fixed post-freeze evaluation without changing the training candidate."""

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


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def main(root):
    artifact = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
    output = artifact / "research-current-policy-credit-20261118-2e9b"
    source = root / "eval-source"
    deployment = json.loads((root / "EVAL_DEPLOYMENT.json").read_text())
    qualification = "qualification/cell-current-policy-credit-20261118"
    candidate = root / "source" / qualification
    old = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
    panels = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/retained/PANELS.json")
    python = "/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python"
    owned, retained = root / "owned-evaluation-1", root / "retained"
    owned.mkdir(exist_ok=False)
    training_exit = json.loads((root / "owned-train-1/COMPLETE.json").read_text())
    assert training_exit["status"] == "COMPLETE"
    assert sha(output / "WEIGHTS_FROZEN.json") == training_exit["weights_frozen_sha256"]
    for stage in ("freeze", "train-all_observed", "train-verified_credit", "audit"):
        exit_record = json.loads((root / "owned-train-1" / stage / "EXIT.json").read_text())
        assert exit_record["wait_returncode"] == 0 and exit_record["timed_out"] is False
    stages = ("freeze", "NoUpdate", "all_observed", "verified_credit")
    lock = artifact / "research-round03-20261118-392934-b/WORKER.lock"
    assert lock.is_file() and not lock.is_symlink()

    def checkpoint(stage):
        files = {}
        for path in sorted(output.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            name, expected = path.relative_to(output).as_posix(), sha(path)
            target = retained / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert sha(target) == expected, name
            else:
                with path.open("rb") as origin, target.open("xb") as stream:
                    for block in iter(lambda: origin.read(1048576), b""):
                        stream.write(block)
                    stream.flush()
                    os.fsync(stream.fileno())
                assert sha(target) == expected
            files[name] = {"sha256": expected, "bytes": path.stat().st_size}
        write(owned / ("CHECKPOINT-" + stage + ".json"), {"stage": stage, "files": files})

    try:
        with lock.open("a+b") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            gpu = subprocess.run(["/usr/bin/nvidia-smi", "--query-gpu=memory.free",
                "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True)
            assert int(gpu.stdout.splitlines()[0]) >= 4096
            write(owned / "INTENT.json", {"evaluation_source_commit": deployment["source_commit"],
                "evaluation_source_tree": deployment["source_tree"],
                "deployment_sha256": sha(root / "EVAL_DEPLOYMENT.json"),
                "training_complete_sha256": sha(root / "owned-train-1/COMPLETE.json"),
                "weights_frozen_sha256": sha(output / "WEIGHTS_FROZEN.json"),
                "lock": str(lock), "stages": stages, "planned_generation_calls": 108,
                "automatic_retry": False, "started_at_ns": time.time_ns()})
            env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                HF_DATASETS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1",
                TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="1")
            for stage in stages:
                for name, expected in deployment["files"].items():
                    assert sha(source / name) == expected, name
                command = [python, "-I", "-B", str(source / qualification / "evaluate.py"), stage,
                    "--artifact-root", str(artifact), "--old-code-root", str(old),
                    "--candidate-root", str(candidate), "--output", str(output),
                    "--original-panels", str(panels), "--b2-loader", str(source / deployment["b2_loader"]),
                    "--b2-directory", str(source / deployment["b2_directory"]),
                    "--code-commit", deployment["source_commit"]]
                directory = owned / stage
                directory.mkdir(exist_ok=False)
                started, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
                write(directory / "INTENT.json", {"stage": stage, "argv": command,
                    "started_at_ns": time.time_ns(), "automatic_retry": False})
                timed_out = False
                with (directory / "STDOUT.txt").open("xb") as out, (directory / "STDERR.txt").open("xb") as err:
                    child = subprocess.Popen(command, cwd=source, env=env, stdout=out, stderr=err,
                                             start_new_session=True)
                    write(directory / "STARTED.json", {"pid": child.pid, "process_group_id": child.pid,
                                                       "started_at_ns": time.time_ns()})
                    try:
                        code = child.wait(timeout=1800 if stage != "freeze" else 240)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            code = child.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            code = child.wait(timeout=30)
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                receipt = {"stage": stage, "wait_returncode": code, "exit_source": "subprocess.Popen.wait",
                    "timed_out": timed_out, "wall_seconds": time.perf_counter() - started,
                    "completed_child_user_cpu_seconds": after.ru_utime - usage.ru_utime,
                    "completed_child_system_cpu_seconds": after.ru_stime - usage.ru_stime,
                    "stdout_sha256": sha(directory / "STDOUT.txt"), "stderr_sha256": sha(directory / "STDERR.txt"),
                    "full_system_cost_known": False, "nested_costs_are_not_additive": True,
                    "automatic_retry": False}
                write(directory / "EXIT.json", receipt)
                checkpoint(stage)
                print(json.dumps(receipt), flush=True)
                if code:
                    write(owned / "FAILED.json", receipt)
                    return 1
            write(owned / "COMPLETE.json", {"status": "COMPLETE", "stages": stages,
                "retained": str(retained), "actual_model_calls": 108,
                "GPU_released_after_owner_exit": True})
        return 0
    except BaseException as error:
        write(owned / "WRAPPER_FAILED.json", {"error_type": type(error).__name__, "error": str(error),
                                             "automatic_retry": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    raise SystemExit(main(parser.parse_args().root.resolve(strict=True)))

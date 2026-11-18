"""Own only the three fixed-prefix diagnostic children under the existing GPU lock."""
import argparse, fcntl, hashlib, json, os, resource, signal, subprocess, time
from pathlib import Path

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())

def main(root):
    source = root / "source"
    here = source / "qualification/cell-e2-fixed-prefix-20261118"
    owned = root / "owned-run-1"
    owned.mkdir(exist_ok=False)
    deployment = json.loads((root / "FINAL_DEPLOYMENT.json").read_text())
    previous = Path("/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b")
    complete = json.loads((previous / "owned-evaluation-1/COMPLETE.json").read_text())
    assert complete["status"] == "COMPLETE" and complete["actual_model_calls"] == 108
    for mode in ("NoUpdate", "all_observed", "verified_credit"):
        exit_record = json.loads((previous / "owned-evaluation-1" / mode / "EXIT.json").read_text())
        assert exit_record["wait_returncode"] == 0 and exit_record["timed_out"] is False
    assert sha(previous / "export-complete-1/ARCHIVE_MANIFEST.json") == "a97062044b5252b98ea983f7e1107741ba49697aff2055c27d21c703e903c099"
    lock = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-round03-20261118-392934-b/WORKER.lock")
    assert lock.is_file() and not lock.is_symlink()
    try:
        with lock.open("a+b") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            gpu = subprocess.run(["/usr/bin/nvidia-smi", "--query-gpu=memory.free",
                "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True)
            assert int(gpu.stdout.splitlines()[0]) >= 4096
            write(owned / "INTENT.json", {"source_commit": deployment["source_commit"],
                "source_tree": deployment["source_tree"], "deployment_sha256": sha(root / "FINAL_DEPLOYMENT.json"),
                "protocol_sha256": sha(here / "prepared/PROTOCOL.json"),
                "lock": str(lock), "planned_model_calls": 33, "planned_verifier_calls": 33,
                "new_training_updates": 0, "automatic_retry": False, "started_at_ns": time.time_ns()})
            env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                PYTHONDONTWRITEBYTECODE="1", TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="1")
            for mode in ("NoUpdate", "all_observed", "verified_credit"):
                for name, expected in deployment["files"].items():
                    assert sha(source / name) == expected, name
                command = ["/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python",
                    "-I", "-B", str(here / "run_prefix.py"), mode, "--root", str(root),
                    "--code-commit", deployment["source_commit"]]
                folder = owned / mode
                folder.mkdir(exist_ok=False)
                started, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
                write(folder / "INTENT.json", {"mode": mode, "argv": command, "started_at_ns": time.time_ns()})
                timed_out = False
                with (folder / "STDOUT.txt").open("xb") as out, (folder / "STDERR.txt").open("xb") as err:
                    child = subprocess.Popen(command, cwd=source, env=env, stdout=out, stderr=err, start_new_session=True)
                    write(folder / "STARTED.json", {"pid": child.pid, "process_group_id": child.pid,
                                                  "started_at_ns": time.time_ns()})
                    try:
                        code = child.wait(timeout=900)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            code = child.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                            code = child.wait(timeout=30)
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                receipt = {"mode": mode, "wait_returncode": code, "exit_source": "subprocess.Popen.wait",
                    "timed_out": timed_out, "wall_seconds": time.perf_counter() - started,
                    "completed_child_user_cpu_seconds": after.ru_utime - usage.ru_utime,
                    "completed_child_system_cpu_seconds": after.ru_stime - usage.ru_stime,
                    "stdout_sha256": sha(folder / "STDOUT.txt"), "stderr_sha256": sha(folder / "STDERR.txt"),
                    "nested_windows_are_not_additive": True, "full_system_cost_known": False, "automatic_retry": False}
                write(folder / "EXIT.json", receipt)
                print(json.dumps(receipt), flush=True)
                if code:
                    write(owned / "FAILED.json", receipt)
                    return 1
                result = json.loads((root / "output" / mode / "RESULT.json").read_text())
                assert result["status"] == "COMPLETE" and result["cost"]["model_calls"] == 11
                assert result["cost"]["verifier_calls"] == 11
            write(owned / "COMPLETE.json", {"status": "COMPLETE", "actual_model_calls": 33,
                "actual_verifier_calls": 33, "new_training_updates": 0,
                "GPU_released_after_owner_exit": True, "research_NoUpdate_retained": True})
        return 0
    except BaseException as error:
        write(owned / "WRAPPER_FAILED.json", {"error_type": type(error).__name__, "error": str(error),
                                             "automatic_retry": False})
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    raise SystemExit(main(parser.parse_args().root.resolve(strict=True)))

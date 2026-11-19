import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

payload_path = Path("/home/qian-qi/c2-d706-source-5cb83d9.json")
payload = payload_path.read_bytes()
if hashlib.sha256(payload).hexdigest() != "7034a235fc088d99777734c378b92de6f11b1eb501f8f55bec46d26e8b3043d2":
    raise ValueError("source transfer identity differs")
bound = json.loads(payload)
if bound["source_commit"] != "5cb83d9c76beedf4c1c917e4bf561f5f26261ce7":
    raise ValueError("source commit differs")
root = Path("/home/qian-qi/hcsn-c2-real-replay-20261112-d706-attempt001")
root.mkdir(exist_ok=False)
source = root / "source"
identities = {}
for entry in bound["files"]:
    relative = Path(entry["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid source path")
    raw = entry["content"].encode()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != entry["git_blob"]:
        raise ValueError("Git source identity differs")
    path = source / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    identities[entry["path"]] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": blob}

def write(name, value):
    with (root / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())

interpreter = "/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python"
driver = source / "qualification/hcsn_differentiable/replay_v1/run_replay.py"
selection = driver.with_name("SELECTION.json")
command = ["/usr/bin/time", "-v", "-o", str(root / "orchestrator-time.txt"), interpreter, "-B", str(driver),
    "--original-root", "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/c2-native-execution-20261110-c385-v1",
    "--study-source", "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/run-source-v8",
    "--output", str(root / "execution"), "--selection", str(selection),
    "--selection-sha256", "6271b8dd1859b8a124f5ecd06ba307c0f9ebcdc5e6f86a9d164c4ac374cdbd55"]
env = os.environ.copy()
env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
    PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", CUDA_VISIBLE_DEVICES="")
os.nice(10)
write("LAUNCH.json", {"schema": "hcsn-c2-fixed-replay-native-launch-v1", "source_commit": bound["source_commit"],
    "source_identities": identities, "command": command, "source_transfer_sha256": hashlib.sha256(payload).hexdigest(),
    "maximum_outer_wall_seconds": 4500, "workers": 2, "threads_per_worker": 1,
    "per_worker_address_space_bytes": 8 * 1024**3, "started_unix_ns": time.time_ns(),
    "independent_complete_training_replays_added": 0, "original_c2_restarted": False,
    "scientific_admission": "HOLD_NO_GO"})
started = time.monotonic()
timed_out = False
with (root / "orchestrator.stdout").open("xb") as stdout, (root / "orchestrator.stderr").open("xb") as stderr:
    child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env, start_new_session=True)
    try:
        returncode = child.wait(timeout=4500)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(child.pid, signal.SIGTERM)
        try:
            returncode = child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            returncode = child.wait()
after = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in identities}
result = {"schema": "hcsn-c2-fixed-replay-native-exit-v1", "returncode": returncode,
    "timed_out": timed_out, "wall_seconds": time.monotonic() - started, "finished_unix_ns": time.time_ns(),
    "source_unchanged": all(after[name] == row["sha256"] for name, row in identities.items()),
    "summary_present": (root / "execution/SUMMARY.json").is_file(), "scientific_admission": "HOLD_NO_GO"}
write("EXIT.json", result)
print(json.dumps(result, sort_keys=True), flush=True)
raise SystemExit(returncode if returncode >= 0 else 128 - returncode)


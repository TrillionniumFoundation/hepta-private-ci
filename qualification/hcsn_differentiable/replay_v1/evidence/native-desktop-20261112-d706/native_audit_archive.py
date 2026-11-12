import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

root = Path("/home/qian-qi/hcsn-c2-real-replay-20261112-d706-attempt001")
auditor = root / "audit_replay_originals.py"
if hashlib.sha256(auditor.read_bytes()).hexdigest() != "fbdbea1302a4f97738b1788f3d58fb0124f0ac6a85f2de9e9bc85d38578a1c41":
    raise ValueError("auditor source differs")
def write(name, value):
    with (root / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
write("AUDIT_LAUNCH.json", {"schema": "hcsn-c2-independent-native-audit-launch-v1", "started_unix_ns": time.time_ns(),
    "auditor_sha256": "fbdbea1302a4f97738b1788f3d58fb0124f0ac6a85f2de9e9bc85d38578a1c41",
    "model_forwards": 0, "optimizer_calls": 0, "maximum_wait_seconds": 1800, "original_replay_restarted": False})
deadline = time.monotonic() + 1800
while not (root / "EXIT.json").is_file():
    if time.monotonic() >= deadline:
        write("AUDIT_EXIT.json", {"state": "waiting_budget_exhausted", "replay_outcome": "UNKNOWN", "model_forwards": 0})
        raise SystemExit(2)
    time.sleep(2)
env = os.environ.copy()
env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
    PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", CUDA_VISIBLE_DEVICES="")
os.nice(10)
command = ["/usr/bin/time", "-v", "-o", str(root / "audit-time.txt"),
    "/home/qian-qi/hepta-hcsn-trainer-20261108-s3-v1/dependency-recovery-v2/venv/bin/python", "-B", str(auditor),
    "--root", str(root), "--output", str(root / "INDEPENDENT_AUDIT.json")]
with (root / "audit.stdout").open("xb") as stdout, (root / "audit.stderr").open("xb") as stderr:
    process = subprocess.run(command, env=env, stdout=stdout, stderr=stderr, timeout=300)
write("AUDIT_EXIT.json", {"returncode": process.returncode, "command": command, "finished_unix_ns": time.time_ns(),
    "model_forwards": 0, "optimizer_calls": 0, "scientific_admission": "HOLD_NO_GO"})
files = sorted(path for path in root.rglob("*") if path.is_file())
if any(path.is_symlink() for path in files):
    raise ValueError("symlink in evidence")
manifest = {"schema": "hcsn-c2-native-evidence-members-v1", "source_commit": "5cb83d9c76beedf4c1c917e4bf561f5f26261ce7",
    "scope": "fixed original C2 checkpoint continuation diagnostic, not complete C2 training replay",
    "files": {str(path.relative_to(root)): {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files}}
write("MANIFEST.json", manifest)
archive = root / "NATIVE_ORIGINALS.zip"
with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
    for path in files + [root / "MANIFEST.json"]:
        bundle.write(path, "native_attempt001/" + str(path.relative_to(root)))
with zipfile.ZipFile(archive) as bundle:
    for name, expected in manifest["files"].items():
        raw = bundle.read("native_attempt001/" + name)
        if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError("archive member differs: " + name)
receipt = {"schema": "hcsn-c2-native-evidence-archive-v1", "archive": str(archive), "bytes": archive.stat().st_size,
    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "members": len(files) + 1,
    "manifest_sha256": hashlib.sha256((root / "MANIFEST.json").read_bytes()).hexdigest(),
    "replay_returncode": json.loads((root / "EXIT.json").read_bytes())["returncode"],
    "independent_audit_returncode": process.returncode, "scientific_admission": "HOLD_NO_GO"}
write("ZIP_RECEIPT.json", receipt)
print(json.dumps(receipt, sort_keys=True), flush=True)
raise SystemExit(process.returncode)


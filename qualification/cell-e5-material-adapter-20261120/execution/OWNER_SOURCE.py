"""One local owner for exact published-source material readback; zero native/model work."""
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
pub, output = root / "publication", root / "readback-final-1"
receipts = pub / "execution"
receipts.mkdir(exist_ok=False)
freeze_raw = (pub / "CHECK_EXECUTION_FREEZE.json").read_bytes()
freeze = json.loads(freeze_raw)
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
for path, expected in freeze["source_files"].items():
    assert sha(pub / path) == expected
for path, key in [("MATERIAL_INDEX.json", "material_index_sha256"), ("PAYLOAD_MANIFEST.json", "payload_manifest_sha256"),
                  ("SOURCE_PREFIX_FREEZE.json", "source_prefix_sha256"), ("BOUND_INPUT_ROOT.json", "complete_input_root_sha256"),
                  ("SOURCE_INPUTS.json", "source_inputs_sha256")]:
    assert sha(pub / path) == freeze[key]
(receipts / "OWNER_STARTED.json").write_text(json.dumps({"owner_id": freeze["owner_id"], "source_sha256": sha(Path(__file__)),
    "freeze_sha256": hashlib.sha256(freeze_raw).hexdigest(), "started_at_ns": time.time_ns()}, sort_keys=True) + "\n")
commands = [["unpack_materials.py", "--manifest", str(pub / "PAYLOAD_MANIFEST.json"), "--output", str(output)],
    ["lossless_admission.py", "--root", str(output), "--prefix", str(pub / "SOURCE_PREFIX_FREEZE.json"), "--output", str(receipts / "ADMISSION_READOUT.json")],
    ["test_lossless_admission.py", "--root", str(output), "--prefix", str(pub / "SOURCE_PREFIX_FREEZE.json"), "--output", str(receipts / "ADMISSION_CONTROLS.json")],
    ["check_existing_codec.py", "--root", str(output), "--provenance", str(pub / "provenance"), "--output", str(receipts / "CODEC_REFERENCE_READOUT.json")]]
began, rows = time.perf_counter(), []
for index, command in enumerate(commands):
    argv = [sys.executable, "-B", str(pub / command[0]), *command[1:]]
    start, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    (receipts / f"{index}.stdout").write_bytes(result.stdout)
    (receipts / f"{index}.stderr").write_bytes(result.stderr)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    rows.append({"argv": argv, "exit_code": result.returncode, "wall_seconds": time.perf_counter() - start,
        "child_cpu_seconds": after.ru_utime + after.ru_stime - usage.ru_utime - usage.ru_stime,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(), "stderr_sha256": hashlib.sha256(result.stderr).hexdigest()})
    assert result.returncode == 0, rows[-1]
manifest = json.loads((pub / "BOUND_INPUT_ROOT.json").read_bytes())
actual = [{"path": str(p.relative_to(output)), "bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(output.rglob("*")) if p.is_file()]
assert actual == manifest["files"]
assert all(sha(pub / path) == expected for path, expected in freeze["source_files"].items())
result = {"schema": "hepta.e5.material-check-owner-result.v1", "owner_id": freeze["owner_id"], "stages": rows,
    "wall_seconds": time.perf_counter() - began, "freeze_sha256": hashlib.sha256(freeze_raw).hexdigest(),
    "source_before_after_unchanged": True, "complete_input_root_sha256": freeze["complete_input_root_sha256"],
    "complete_input_members_read_back": len(actual), "material_index_sha256": freeze["material_index_sha256"],
    "source_prefix_sha256": freeze["source_prefix_sha256"], "new_native_children": 0, "model_calls": 0, "training_updates": 0,
    "administrative_integrity_checks_only": True, "full_physical_monetary_cost_known": False}
(receipts / "OWNER_RESULT.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
print(json.dumps({k: v for k, v in result.items() if k != "stages"}, sort_keys=True))

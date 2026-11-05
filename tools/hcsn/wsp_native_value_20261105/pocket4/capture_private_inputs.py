#!/usr/bin/env python3
"""Preserve the exact small private probe inputs; export only hashes and sizes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

started, cpu = time.perf_counter(), time.process_time()
os.umask(0o077)
root = Path.home() / ".local/state/hepta-wsp"
source = root / "20261105-head-probe-237419/probe_adapter_heads.py"
expected_source = "fe6b661c349443a6e6d647eed895313247b2941fcb2ba9f430fd6794a91ceaa0"
if hashlib.sha256(source.read_bytes()).hexdigest() != expected_source:
    raise RuntimeError("BOUND_PROBE_SOURCE_CHANGED")
spec = importlib.util.spec_from_file_location("bound_probe_source", source)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
config, job, binding = audit.bound_live()
candidate, parent = Path(job["output_directory"]), Path(job["parent_directory"])
base = Path(config["base_directory"])
runtime = Path(config["runtime_directory"]) / "learn/laya_cell"
locations = {
    "candidate_adapter.safetensors": candidate / "adapter.safetensors",
    "parent_adapter.safetensors": parent / "adapter.safetensors",
    "candidate_manifest.json": candidate / "candidate.json",
    "parent_manifest.json": parent / "candidate.json",
    "base_manifest.json": base / "base-manifest.json",
    "model.py": runtime / "model.py",
    "resident_model.py": runtime / "resident_model.py",
}
raw = {name: audit.read(path, 1048576) for name, path in locations.items()}
assert audit.digest(raw["candidate_adapter.safetensors"]) == audit.EXPECTED["adapter_sha256"]
assert audit.digest(raw["parent_adapter.safetensors"]) == audit.EXPECTED["parent_adapter_sha256"]
assert audit.digest(raw["parent_manifest.json"]) == job["parent_manifest_sha256"]
assert json.loads(raw["candidate_manifest.json"])["candidate_id"] == audit.EXPECTED["candidate_id"]
target = root / "20261105-head-private-snapshot-237419"
target.mkdir(mode=0o700, parents=True, exist_ok=False)
for name, content in raw.items():
    with (target / name).open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    assert (target / name).stat().st_mode & 0o077 == 0
    assert (target / name).read_bytes() == content
for name, path in locations.items():
    assert audit.read(path, 1048576) == raw[name]
assert audit.bound_live()[2] == binding
receipt = {
    "schema": "hepta.wsp.private_head_input_snapshot.v1",
    "status": "PASS_PRIVATE_SMALL_INPUTS_PRESERVED",
    "source_sha256": audit.digest(Path(__file__).read_bytes()),
    "bound_probe_source_sha256": expected_source,
    "files": {name: {"sha256": audit.digest(content), "bytes": len(content)}
              for name, content in raw.items()},
    "candidate_id": audit.EXPECTED["candidate_id"],
    "live_binding_stable": True,
    "atomic_cross_file_snapshot": False,
    "all_copies_exclusive_and_private": True,
    "public_raw_weights_or_private_rows": False,
    "base_model_copied": False,
    "base_model_reference_sha256": audit.EXPECTED["base_model_sha256"],
    "base_reproduction_requires_existing_or_upstream_hash_matched_checkpoint": True,
    "original_files_changed": False,
    "model_forward_or_training_executed": False,
    "observed_end_utc": audit.utc(),
    "cpu_seconds_through_receipt": time.process_time() - cpu,
    "wall_seconds_through_receipt": time.perf_counter() - started,
}
text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
(target / "PUBLIC_RECEIPT.json").write_text(text)
print(text)

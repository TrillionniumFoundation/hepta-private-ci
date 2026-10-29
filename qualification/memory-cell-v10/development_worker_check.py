"""Exercise the actual isolated JSONL worker with a development-only model."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from cells import Cell, fit
from export_native import canonical, sha
from inventory_worker import POLICY_FILES, wire_bytes
from routing import matching_entries, masked_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    qualification = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("development_worker_encoder", qualification / "memory-cell-adapters" / "encoder.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    encoder = module.PinnedMiniLMEncoder(args.encoder_dir)
    texts = ["policy ENTITY configuration", "reserve pack limit ENTITY", "WORKFLOW steps", "WORKFLOW instruction procedure",
             "execute WORKFLOW ENTITY", "run ENTITY WORKFLOW", "remove unknown things", "compose a poem"]
    features = encoder.encode(texts)
    targets = np.eye(4, dtype=np.float32)[[0, 0, 1, 1, 2, 2, 3, 3]]
    model = Cell(384, 4, 0, 90401)
    schedule = np.random.default_rng(90401).integers(8, size=(800, 32), dtype=np.int64)
    receipt = fit(model, features, targets, (("multiclass", 4),), schedule, lr=0.01,
                  source_ids=[sha(text.encode()) for text in texts], label="development-only-wire-test")
    checkpoint = model.save(args.output / "checkpoint", encoder_sha256=encoder.base_encoder_sha, outputs=(("multiclass", 4),))
    pins = {name: sha((qualification / name).read_bytes()) for name in POLICY_FILES}
    manifest = {"schema": "hepta.memory.v10.inventory-router.v1", "checkpoint_manifest_sha256": checkpoint["manifest_sha256"],
                "parameter_sha256": model.identity(), "encoder_sha256": encoder.base_encoder_sha,
                "policy_files": pins, "policy_digest": sha(canonical(pins)), "threshold": 0.2,
                "development_wire_test_only": True, "formal_calibration_reused": False}
    payload = canonical(manifest)
    (args.output / "manifest.json").write_bytes(payload)
    registry = {"schema": "hepta.memory.inventory-owner-registry.v1", "scope": "development:scope",
                "source_cut": sha(b"development-cut-not-real-owner-evidence"),
                "entities": [{"key": "development:semantic:0", "aliases": ["开发站"]}],
                "workflows": [{"key": "development:procedure:0", "aliases": ["开发流程"]}]}
    boundary_cases = {"policy 开发站 configuration": True, "policy：开发站，configuration": True,
                      "policy 开发站二 configuration": False, "policy 二开发站 configuration": False}
    for text, expected in boundary_cases.items():
        if bool(matching_entries(text, registry["entities"])) != expected:
            raise AssertionError("Unicode alias boundary changed the addressed entity")
        masked, entities, _ = masked_request(text, registry["entities"], registry["workflows"])
        if bool(entities) != expected or (not expected and masked != text):
            raise AssertionError("Unicode alias normalization must preserve unsupported names")
    frames = []
    for index, text in enumerate(("policy 开发站 configuration", "policy absent-location configuration",
                                 "policy 开发站二 configuration")):
        request = {"schema": "hepta.memory.inventory-request.v1", "query_id": f"development:query:{index}",
                   "scope": "development:scope", "entity_key": "development:semantic:0", "workflow_key": "development:procedure:0",
                   "text": text, "at": 20, "since": 10, "max_cells": 4, "max_hops": 3, "max_steps": 4}
        frames.append({"schema": "hepta.memory.inventory-address-worker-request.v1", "request": request, "registry": registry})
    completed = subprocess.run([sys.executable, "-I", "-u", "-B", str(Path(__file__).with_name("inventory_worker.py")),
                                "--model", str(args.output), "--model-digest", sha(payload), "--encoder", str(args.encoder_dir)],
                               input=b"".join(wire_bytes(frame) + b"\n" for frame in frames), capture_output=True, timeout=60, check=False)
    (args.output / "worker.stdout").write_bytes(completed.stdout)
    (args.output / "worker.stderr").write_bytes(completed.stderr)
    if completed.returncode:
        raise AssertionError("isolated worker failed; process evidence retained")
    ready = json.loads(completed.stderr)
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    if ready["model_digest"] != sha(payload) or [row["status"] for row in responses] != ["accepted", "rejected", "rejected"]:
        raise AssertionError("isolated worker did not preserve learned acceptance and missing-key rejection")
    for frame, response in zip(frames, responses, strict=True):
        if response["request_digest"] != sha(wire_bytes(frame["request"])) or response["registry_digest"] != sha(wire_bytes(registry)):
            raise AssertionError("UTF-8 wire binding mismatch")
    result = {"actual_isolated_worker_passed": True, "formal_inputs_read": False, "development_seed": 90401,
              "model_training": receipt, "responses": responses, "ready": ready, "exit_code": completed.returncode,
              "Unicode_alias_boundary_cases": boundary_cases}
    (args.output / "DEVELOPMENT.json").write_bytes(canonical(result))
    print(json.dumps({"actual_isolated_worker_passed": True, "statuses": [row["status"] for row in responses], "UTF8_bound": True}))


if __name__ == "__main__":
    main()

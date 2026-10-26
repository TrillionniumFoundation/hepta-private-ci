"""Actual Adam/controller roundtrip on explicitly synthetic qualification data.

This runs the frozen research implementations, the compiled native codec, and
the existing checkpoint loader. It never evaluates a scientific candidate gate.
"""

import argparse
import copy
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

from handoff_v7 import canonical, checkpoint, encode, require, restore_native_dump, sha


def serving(state, artifact, generation):
    def ident(value):
        raw = value.encode("ascii")
        return struct.pack(">H", len(raw))+raw

    projection = np.zeros((384, 8))
    projection[:8] = np.eye(8)
    cell = f"synthetic-{state.head.mode}-seed7"
    data = bytearray(b"HPTACV05"+ident(artifact)+struct.pack(">Q", generation)
        +bytes.fromhex(sha(b"synthetic encoder identity; no encoder executed")))
    data += projection.astype(">f8").tobytes()+struct.pack(">H", 1)+ident(cell)
    data += bytes.fromhex(state.digest())+bytes.fromhex(state.bindings["feature_identity"])
    data += bytes([int(state.head.mode == "gated")])
    for name in (("W", "b") if state.head.mode == "linear" else ("W", "b", "a", "g")):
        data += state.head.params[name].astype(">f8").tobytes()
    return bytes(data)


def run(code, closure, native, output):
    code, closure, native, output = map(Path, (code, closure, native, output))
    source = closure.read_bytes()
    hashes = json.loads(source)
    sys.path.insert(0, str(code.resolve()))
    from cell_field_state import CellTrainingState, dataset_digest
    from cell_field_policy_v7 import execute_policy, resume_policy
    from cell_field_repair_v7 import panel_losses
    from cell_learning_models import NumpyCellHead

    output.mkdir(parents=True, exist_ok=False)
    protocol = sha(b"synthetic native-handoff numerical qualification v7; not confirmatory science")
    cases, negatives = [], []
    for mode in ("linear", "gated"):
        rng = np.random.default_rng(4407)
        x, y = rng.normal(size=(48, 8)), np.arange(48) % 4
        train = x, y
        panels = [(x+scale*rng.normal(size=x.shape), y) for scale in (0., .02, -.02, .04)]
        origin = {name: hashes[name] for name in
            ("cell_field_state.py", "cell_learning_models.py", "cell_learning_metrics.py", "cell_field_features.py")}
        state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=7), seed=17,
            bindings={"task": "synthetic", "head_mode": mode, "seed": 7,
                "protocol_sha256": sha(b"synthetic original optimizer protocol"),
                "feature_identity": sha(b"synthetic unlabelled feature identity"), "executed_code_sha256": origin},
            contexts={"current_train": dataset_digest(*train)}, active_context="current_train")
        for _ in range(32):
            state.advance(*train)
        config = {"steps": 32, "dt": .02, "effort_price": .03, "action_bound": 4.,
            "old_weight": .25, "current_dispersion": .5, "relinearizations": 0}
        result = execute_policy(state, train, panels, panels, panel_losses(state.head, panels),
            "future_field_h8", config, controller_protocol_sha256=protocol,
            controller_source_sha256=sha(canonical(hashes)))
        require(result["record"]["status"] == "completed", "synthetic controller did not complete")
        previous = None
        for step in (0, 16, 17, 32):
            current, snapshot = result["states"][step], result["controllers"][step]
            contract, controller = snapshot["contract"], canonical(snapshot)
            item = checkpoint(current, controller, contract, code, source)
            raw = encode(serving(current, f"synthetic-{mode}-step{step}", 1 if step == 0 else 2),
                protocol, previous, [item])
            if step == 0:
                previous = sha(raw)
            payload, receipt = output/f"{mode}-{step}.bin", output/f"{mode}-{step}-native.json"
            payload.write_bytes(raw)
            subprocess.run([str(native), str(payload), sha(raw), protocol, str(receipt)], check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            native_result = json.loads(receipt.read_bytes())
            restored, loaded = restore_native_dump(native_result["checkpoints"][0], code, source,
                contract, output/f"{mode}-{step}-restored")
            require(restored.digest() == current.digest() and loaded == snapshot,
                    "native restoration changed full state or controller")
            case = {"mode": mode, "step": step, "state_sha256": current.digest(),
                "controller_sha256": sha(controller), "handoff_sha256": sha(raw),
                "native_receipt_sha256": sha(receipt.read_bytes()),
                "pending_actions": native_result["checkpoints"][0]["pending_actions"], "restored_exactly": True}
            if step == 17:
                resumed = resume_policy(restored, controller, contract, train, panels, panels,
                    expected_controller_sha256=sha(controller))
                require(resumed["state"].digest() == result["state"].digest()
                    and resumed["receipts"] == result["receipts"][17:]
                    and np.array_equal(resumed["actions"], result["actions"][17:])
                    and resumed["controllers"][-1]["receipt_chain"] == result["controllers"][-1]["receipt_chain"]
                    and resumed["record"]["steps"][0]["resume_verified_steps"] == 7,
                    "native mid-plan restore changed its exact continuation")
                case.update(remaining_first_block_actions=7, exact_remaining_steps=15,
                    identical_terminal_state=True, identical_receipt_chain=True)
                for mutation in ("state_bits", "anchor_contract", "source_closure"):
                    record, expected, closure_bytes = copy.deepcopy(native_result["checkpoints"][0]), copy.deepcopy(contract), source
                    if mutation == "state_bits":
                        value = bytearray.fromhex(record["state_vector_le_hex"]); value[0] ^= 1
                        record["state_vector_le_hex"] = value.hex()
                    elif mutation == "anchor_contract":
                        expected["original_old_anchors"][0] += .001
                    else:
                        closure_bytes = canonical({**hashes, "cell_field_state.py": "0"*64})
                    try:
                        restore_native_dump(record, code, closure_bytes, expected, output/f"invalid-{mode}-{mutation}")
                    except ValueError:
                        negatives.append({"mode": mode, "mutation": mutation, "rejected": True})
                    else:
                        raise AssertionError("altered native restoration accepted")
            cases.append(case)
    report = {"schema": "hepta.native-handoff-numerical-qualification.v7",
        "scope": "actual Adam/controller/native code over synthetic numerical fixtures; no scientific candidate acceptance",
        "protocol_sha256": protocol, "controller_source_closure_sha256": sha(canonical(hashes)),
        "controller_source_file_sha256": sha(source),
        "native_binary_sha256": sha(native.read_bytes()), "cases": cases, "negative_cases": negatives,
        "states_and_controllers_restored": len(cases), "midplan_continuations": 2,
        "scientific_acceptance": False, "candidate_published": False, "production_authority": False}
    (output/"qualification.json").write_bytes(canonical(report)+b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("code", "closure", "native", "output"):
        parser.add_argument("--"+field, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({"states_restored": len(result["cases"]), "negative_rejections": len(result["negative_cases"]),
        "midplan_continuations": result["midplan_continuations"], "scientific_acceptance": False}))

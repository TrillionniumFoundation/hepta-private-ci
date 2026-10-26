"""Synthetic numerical qualification of the actual V8 source/native/loader path.

All tensor updates and pending-plan continuations execute the pinned research
code. The small generated data are mechanics fixtures, never scientific evidence.
"""

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from handoff_profile import canonical, checkpoint, encode, require, restore_native_dump, sha

sys.path.insert(0, str(Path(__file__).resolve().parent / "../trained-cell-v7"))
from qualify_handoff_v7 import serving


def run(code, closure, native, output):
    code, closure, native, output = map(Path, (code, closure, native, output))
    source = closure.read_bytes()
    hashes = json.loads(source)
    require(all(sha((code / name).read_bytes()) == digest for name, digest in hashes.items()),
            "research source changed before qualification")
    sys.path.insert(0, str(code.resolve()))
    from cell_field_state import CellTrainingState, dataset_digest
    from cell_field_policy_v8 import execute_policy, resume_policy
    from cell_field_repair_v7 import panel_losses
    from cell_learning_models import NumpyCellHead
    from threadpoolctl import threadpool_info

    output.mkdir(parents=True, exist_ok=False)
    protocol = sha(b"synthetic native-handoff numerical qualification v8; not confirmatory science")
    cases, negatives, continuations = [], [], []
    cpu_started, wall_started = time.process_time_ns(), time.perf_counter_ns()
    for mode in ("linear", "gated"):
        for stride in (1, 2, 4, 8):
            rng = np.random.default_rng(4407)
            x, y = rng.normal(size=(48, 8)), np.arange(48) % 4
            train = x, y
            panels = [(x + scale * rng.normal(size=x.shape), y) for scale in (0., .02, -.02, .04)]
            origin = {name: hashes[name] for name in ("cell_field_state.py", "cell_learning_models.py",
                "cell_learning_metrics.py", "cell_field_features.py")}
            state = CellTrainingState(NumpyCellHead(8, 4, mode, seed=7), seed=17,
                bindings={"task": "synthetic", "head_mode": mode, "seed": 7,
                    "protocol_sha256": sha(b"synthetic original optimizer protocol"),
                    "feature_identity": sha(b"synthetic unlabelled feature identity"),
                    "executed_code_sha256": origin},
                contexts={"current_train": dataset_digest(*train)}, active_context="current_train")
            for _ in range(32):
                state.advance(*train)
            config = {"steps": 32, "dt": .02, "effort_price": .03, "action_bound": 4.,
                "old_weight": .25, "current_dispersion": .5, "relinearizations": 0,
                "commit_stride": stride}
            result = execute_policy(state, train, panels, panels, panel_losses(state.head, panels),
                "future_field_h8", config, controller_protocol_sha256=protocol,
                controller_source_sha256=sha(canonical(hashes)))
            require(result["record"]["status"] == "completed", "synthetic controller did not complete")
            predecessor = None
            for step in (0, 17, 32):
                current, snapshot = result["states"][step], result["controllers"][step]
                contract, controller = snapshot["contract"], canonical(snapshot)
                item = checkpoint(current, controller, contract, code, source, 8)
                raw = encode(serving(current, f"synthetic-{mode}-stride{stride}-step{step}",
                    1 if step == 0 else 2), protocol, predecessor, [item], 8)
                if step == 0:
                    predecessor = sha(raw)
                label = f"{mode}-stride{stride}-step{step}"
                payload, receipt = output / f"{label}.bin", output / f"{label}-native.json"
                payload.write_bytes(raw)
                completed = subprocess.run([str(native), "8", str(payload), sha(raw), protocol, str(receipt)],
                    capture_output=True, text=True)
                require(completed.returncode == 0, f"native decode failed: {completed.stderr}")
                native_result = json.loads(receipt.read_bytes())
                record = native_result["checkpoints"][0]
                restored, loaded = restore_native_dump(record, code, source, contract,
                    output / f"{label}-restored", 8)
                require(restored.digest() == current.digest() and loaded == snapshot,
                        "native restoration changed full state or controller")
                cases.append({"mode": mode, "stride": stride, "step": step,
                    "state_sha256": current.digest(), "controller_sha256": sha(controller),
                    "handoff_sha256": sha(raw), "native_receipt_sha256": sha(receipt.read_bytes()),
                    "forecast_horizon": snapshot["forecast_horizon"], "plan_horizon": snapshot["plan_horizon"],
                    "pending_actions": record["pending_actions"], "restored_exactly": True})
                if step != 17:
                    continue
                before_cpu, before_wall = time.process_time_ns(), time.perf_counter_ns()
                resumed = resume_policy(restored, controller, contract, train, panels, panels,
                    expected_controller_sha256=sha(controller))
                pending = stride - 1
                require(resumed["record"]["status"] == "completed"
                    and resumed["state"].digest() == result["state"].digest()
                    and resumed["receipts"] == result["receipts"][17:]
                    and np.array_equal(resumed["actions"], result["actions"][17:])
                    and resumed["controllers"][-1]["receipt_chain"] == result["controllers"][-1]["receipt_chain"]
                    and resumed["record"]["steps"][0].get("resume_verified_steps", 0) == pending,
                    "native mid-plan restoration changed exact physical continuation")
                continuations.append({"mode": mode, "stride": stride, "first_pending_actions": pending,
                    "remaining_committed_steps": 15, "terminal_state_sha256": resumed["state"].digest(),
                    "receipt_chain": resumed["controllers"][-1]["receipt_chain"],
                    "actions_sha256": sha(np.asarray(resumed["actions"], dtype="<f8").tobytes()),
                    "receipts_sha256": sha(canonical(resumed["receipts"])),
                    "physical_actions_receipts_and_terminal_exact": True,
                    "new_cost_and_resume_verification_ledger_identical_claimed": False,
                    "added_cpu_ns": time.process_time_ns() - before_cpu,
                    "added_wall_ns": time.perf_counter_ns() - before_wall})
                for mutation in ("state_bits", "anchor_contract", "source_closure", "old_schema"):
                    altered, expected, closure_bytes = copy.deepcopy(record), copy.deepcopy(contract), source
                    if mutation == "state_bits":
                        value = bytearray.fromhex(altered["state_vector_le_hex"])
                        value[0] ^= 1
                        altered["state_vector_le_hex"] = value.hex()
                    elif mutation == "anchor_contract":
                        expected["original_old_anchors"][0] += .001
                    elif mutation == "source_closure":
                        closure_bytes = canonical({**hashes, "cell_field_state.py": "0" * 64})
                    else:
                        wrapper = json.loads(altered["controller_metadata_json"])
                        wrapper["schema"] = "hepta.cell-controller-handoff.v7"
                        altered["controller_metadata_json"] = canonical(wrapper).decode()
                    try:
                        restore_native_dump(altered, code, closure_bytes, expected,
                            output / f"invalid-{label}-{mutation}", 8)
                    except ValueError:
                        negatives.append({"mode": mode, "stride": stride, "mutation": mutation, "rejected": True})
                    else:
                        raise AssertionError("altered native restoration accepted")
    require(all(sha((code / name).read_bytes()) == digest for name, digest in hashes.items()),
            "research source changed during qualification")
    report = {"schema": "hepta.native-handoff-numerical-qualification.v8",
        "scope": "actual Adam/controller/native code over synthetic numerical fixtures",
        "protocol_sha256": protocol, "controller_source_closure_sha256": sha(canonical(hashes)),
        "controller_source_file_sha256": sha(source), "native_binary_sha256": sha(native.read_bytes()),
        "cases": cases, "negative_cases": negatives, "continuations": continuations,
        "states_and_controllers_restored": len(cases), "midplan_continuations": len(continuations),
        "additional_qualification_cpu_ns": time.process_time_ns() - cpu_started,
        "additional_qualification_wall_ns": time.perf_counter_ns() - wall_started,
        "runtime_threadpools": threadpool_info(), "scientific_acceptance": False,
        "candidate_published": False, "production_authority": False}
    (output / "qualification.json").write_bytes(canonical(report) + b"\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("code", "closure", "native", "output"):
        parser.add_argument("--" + field, required=True)
    result = run(**vars(parser.parse_args()))
    print(json.dumps({"states_restored": len(result["cases"]),
        "negative_rejections": len(result["negative_cases"]), "midplan_continuations": result["midplan_continuations"],
        "scientific_acceptance": False}))

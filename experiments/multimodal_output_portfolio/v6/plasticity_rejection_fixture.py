"""Bind two preserved research contexts for an eligibility-prerequisite test.

No model runs, calibration changes, eligibility writes, or parameter proposals.
The terminal and rejected-neuron contexts remain distinct and explicitly named.
"""

import argparse
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def export(terminal_evidence, terminal_evidence_sha256, terminal_fixture,
           terminal_fixture_sha256, neuron_evidence, neuron_evidence_sha256,
           neuron_fixture, neuron_fixture_sha256, output):
    inputs = {}

    def retain(name, path, expected=None):
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Invalid bounded owner evidence file")
        path = path.resolve()
        raw = path.read_bytes()
        if expected is not None and sha(raw) != expected:
            raise ValueError("Independently retained source pin differs")
        inputs[name] = {"path": str(path), "sha256": sha(raw), "bytes": len(raw)}
        return raw

    terminal = json.loads(retain("terminal_evidence", terminal_evidence, terminal_evidence_sha256))
    original = json.loads(retain("terminal_fixture", terminal_fixture, terminal_fixture_sha256))
    rejected = json.loads(retain("neuron_evidence", neuron_evidence, neuron_evidence_sha256))
    neuron = json.loads(retain("neuron_fixture", neuron_fixture, neuron_fixture_sha256))
    if (terminal["state"] != "completed" or terminal["authority"] != "deny_all"
            or terminal["fixture_sha256"] != terminal_fixture_sha256
            or not terminal["persisted_and_reloaded_predictor"] or not terminal["recovered_owner_fit_identical"]
            or terminal["new_scientific_samples"] != 0 or terminal["production_authenticated"]):
        raise ValueError("Terminal artifact did not complete the declared research owner chain")
    if (rejected["status"] != "rejected" or rejected["native_error"] != "InvalidCalibration"
            or rejected["neuron_checkpoint_committed"] or rejected["daemon_activated"]
            or rejected["authority"] != "deny_all" or not rejected["model_executed"]
            or rejected["actual_inference_owner_terminal"] != "Completed"
            or rejected["specification_sha256"] != neuron["specification_sha256"]
            or rejected["calibration_summary_sha256"] != neuron["calibration_summary_sha256"]):
        raise ValueError("The native neuron failure must be the actual preserved calibration rejection")
    terminal_root, neuron_root = Path(terminal_evidence).resolve().parent, Path(neuron_evidence).resolve().parent
    retain("terminal_payload", terminal_root / "candidate.bin", terminal["payload_digest"])
    retain("terminal_registry", terminal_root / "artifact-registry.bin")
    retain("neuron_process", neuron_root / "process.json")
    journal = retain("neuron_journal", neuron_root / "neuron.journal")
    retain("neuron_witness", neuron_root / "witness.journal")
    if journal:
        raise ValueError("The rejected runtime unexpectedly contains a neuron checkpoint journal")
    calibration = json.loads(retain("calibration_summary", Path(neuron["calibration_directory"]) / "summary.json",
                                   neuron["calibration_summary_sha256"]))
    if (calibration["registration"]["checkpoint"] != neuron["pins"]["checkpoint_sha256"]
            or calibration["specification_sha256"] != neuron["specification_sha256"]
            or calibration["point_gates_passed"]
            or any(rejected[k] != calibration["native_" + k] for k in ("measured_ece_ppm", "measured_false_acceptance_ppm"))):
        raise ValueError("Rejected owner and measured calibration identities differ")

    policies = original["policy_ids"]
    if len(policies) != 7 or policies != sorted(set(policies)) or "abstain" in policies:
        raise ValueError("Unexpected terminal supported-action grammar")
    state = json.loads(original["state_json"])
    if (original["state_sha256"] != sha(canonical(state))
            or terminal["state_sha256"] != original["state_sha256"]
            or terminal["objective_sha256"] != original["objective_sha256"]
            or terminal["metric_sha256"] != original["metric_sha256"]):
        raise ValueError("Terminal evidence changed its actual context")
    candidates, sensor = sorted([*policies, "abstain"]), "old-v6:one-public-input-model-budget"
    profile = bytearray(b"hepta.terminal-cell.supported-profile.v1\0")
    profile += len(candidates).to_bytes(8, "big")
    for identity in candidates:
        profile += len(identity.encode()).to_bytes(8, "big") + identity.encode()
    profile += bytes.fromhex(terminal["state_sha256"]) + bytes.fromhex(terminal["metric_sha256"]) + (1).to_bytes(8, "big")
    for identity in [sensor, *policies]:
        profile += len(identity.encode()).to_bytes(8, "big") + identity.encode()
    action = "fixed_dev_tuned"  # Declared by role, never selected for its observed reward.
    record = next(r for r in terminal["records"] if r["action"] == action)
    observed = next(r for r in original["records"] if r["policy"] == action)
    if (record["value_q32"] != observed["value_q32"]
            or record["source_row_receipt"] != observed["row_receipt_sha256"]
            or not -(1 << 32) <= record["value_q32"] <= 1 << 32):
        raise ValueError("Projection value is not the declared real terminal observation")
    result = {"schema": "hepta.ndu-v6.plasticity-prerequisite-fixture.v1", "inputs": inputs,
              "terminal": {"objective_sha256": terminal["objective_sha256"], "subject_sha256": terminal["state_sha256"],
                           "artifact_sha256": terminal["artifact_digest"], "dataset_sha256": terminal["dataset_digest"],
                           "training_profile_sha256": sha(profile), "generation": 1, "sensor_id": sensor,
                           "action_id": action, "observed_value_q32": record["value_q32"],
                           "snapshot_sha256": state["snapshot_sha256"]},
              "neuron": {"objective_sha256": neuron["specification_sha256"],
                         "source_pair_sha256": neuron["request"]["input_source_sha256"],
                         "snapshot_sha256": neuron["pins"]["snapshot_sha256"],
                         "scope_sha256": sha(b"local-neuron-pilot-scope"), "generation": 1},
              "scope": "two distinct research contexts; missing genuine acknowledged neuron checkpoint; not a complete same-context proposal",
              "authority": "deny_all"}
    for item in inputs.values():
        if sha(Path(item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("Original owner evidence changed")
    output = Path(output).resolve()
    if any(root == output or root in output.parents for root in (terminal_root, neuron_root)):
        raise ValueError("Do not write into preserved source owner evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(result) + b"\n"
    with output.open("xb") as file:
        file.write(raw)
    return {"path": str(output), "sha256": sha(raw), "source_contexts_relabelled": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("terminal-evidence", "terminal-evidence-sha256", "terminal-fixture", "terminal-fixture-sha256",
                 "neuron-evidence", "neuron-evidence-sha256", "neuron-fixture", "neuron-fixture-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(export(**vars(parser.parse_args())), sort_keys=True))

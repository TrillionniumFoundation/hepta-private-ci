"""Bind genuine future forecasts and observed outputs to the exact native replay."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np

from ...abc_recovery.training_run import file_sha, write_json
from .boundaries import verified_data
from .forecast import ACTIONS, Q, runtime_predictions
from .prospective import predictions
from .qualify import check_freeze


def prepare(protocol, supplement, model, data, verification, contract, dynamics, output, hook=None):
    check_freeze(protocol, model, "calibrator-freeze.json")
    d = verified_data(data, protocol, "verification")
    spec = json.loads(protocol.read_text()); result = json.loads(verification.read_text())
    if result["data_sha256"] != file_sha(data / "data.npz"):
        raise ValueError("Verification belongs to another observed dataset")
    weights = json.loads((model / "weights.json").read_text())
    calibration = json.loads((model / "calibration.json").read_text())
    if contract == "future_correctness":
        registered = json.loads(supplement.read_text())
        for name, digest in registered["source_pins"].items():
            if file_sha(Path(__file__).parent / name) != digest:
                raise ValueError("Supplement source changed")
        if (result["supplement_sha256"] != file_sha(supplement)
                or result["study_qualified"] != all(result["gates"].values())):
            raise ValueError("Complete supplemental qualification mismatch")
        if hook is None or file_sha(hook) != registered["live_proposal_config_sha256"]:
            raise ValueError("Same-head live proposal hook was not frozen with the supplement")
        _, _, predicted, _, cp, op = predictions(weights, calibration, d["x_q24"] / Q,
                                                 d["future_q24"] / Q)
        qualified = result["study_qualified"]
    else:
        if result["protocol_sha256"] != file_sha(protocol):
            raise ValueError("Residual verification protocol changed")
        _, _, _, predicted, _, cp, op, _ = runtime_predictions(weights, calibration,
            d["x_q24"] / Q, d["future_q24"] / Q)
        before = json.loads((model / "calibration-result.json").read_text())
        upper = result["native_ood_false_acceptance_pair_upper95"]
        qualified = (result["native_config_point_qualified"] and all(before["native_point_gates"].values())
                     and all(result["native_point_gates"].values()) and upper is not None and upper <= .004999)
    with gzip.open(data / "rows.jsonl.gz", "rt") as stream:
        observed = [json.loads(line) for line in stream]
    if len(observed) != len(d["pair"]):
        raise ValueError("Observed row census mismatch")
    for i, row in enumerate(observed):
        if (row["pair"] != d["pair"][i] or ACTIONS.index(row["action"]) != d["action"][i]
                or row["joint_correct"] != d["y"][i]):
            raise ValueError("Observed rows not in frozen array order")
    selected = list(range(len(observed)))
    if contract == "future_correctness":
        id_pairs = np.unique(d["pair"][~d["ood"]])[:400]
        index = {(int(pair), int(action)): i for i, (pair, action) in enumerate(zip(d["pair"], d["action"]))}
        id_rows = [index[int(pair), action] for pair in id_pairs for action in (0, 1)]
        ood_rows = [index[int(pair), 1] for pair in np.unique(d["pair"][d["ood"]])]
        if len(id_rows) != 800 or len(ood_rows) != 800:
            raise ValueError("Prespecified bounded native stream census mismatch")
        selected = [i for pair in zip(ood_rows, id_rows) for i in pair]
    output.mkdir(parents=True, exist_ok=False)
    host = {"platform": platform.platform(), "cpuinfo": Path("/proc/cpuinfo").read_text(),
        "cpu_quota": Path("/sys/fs/cgroup/cpu.max").read_text(),
        "memory_limit": Path("/sys/fs/cgroup/memory.max").read_text(),
        "scope": "shared Linux host; not a production target qualification"}
    write_json(output / "host.json", host)
    rows = []
    for i in selected:
        row = observed[i]; utility = row["scores"]["utility"] * 2**32
        rows.append({"pair": int(d["pair"][i]), "action": row["action"],
            "features": np.concatenate((d["x_q24"][i], d["future_q24"][i])).tolist(),
            "expected_prediction": predicted[i].tolist(), "confidence_ppm": int(cp[i]), "ood_ppm": int(op[i]),
            "declared_ood": bool(d["ood"][i]), "joint_correct": int(d["y"][i]),
            "terminal_value_q32": int(np.floor(utility + .5) if utility >= 0 else np.ceil(utility - .5)),
            "observed_record_digest": hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "source_pair_digest": hashlib.sha256("\n".join(row["source_ids"]).encode()).hexdigest()})
    pins = {"protocol": file_sha(supplement if contract == "future_correctness" else protocol),
        "feature_profile": file_sha(Path(__file__).with_name("forecast.py")),
        "weights": file_sha(model / "weights.json"), "calibration": file_sha(model / "calibration.json"),
        "verification": file_sha(verification), "device": file_sha(output / "host.json"),
        "upstream_model": spec["input_sha256"]["model"], "source_manifest": spec["input_sha256"]["manifest"],
        "dataset": file_sha(data / "rows.jsonl.gz"), "measured_ece_ppm": result["native_measured_ece_ppm"],
        "measured_false_acceptance_ppm": result["native_measured_false_acceptance_ppm"]}
    packet = {"pins": pins, "rows": rows, "frozen_unix_ns": time.time_ns(),
        "weights_path": str((model / "weights.json").resolve()),
        "calibration_path": str((model / "calibration.json").resolve()), "verification_path": str(verification.resolve()),
        "future_output_model": True, "future_contract": contract, "dynamics_profile": dynamics,
        "study_qualified": bool(qualified), "new_independent_samples": 0}
    if hook is not None:
        packet["live_proposal"] = json.loads(hook.read_text())
    write_json(output / "packet.json", packet)
    write_json(output / "receipt.json", {"packet_sha256": file_sha(output / "packet.json"), "rows": len(rows),
        "contract": contract, "dynamics_profile": dynamics, "study_qualified": bool(qualified),
        "new_independent_samples": 0, "scope": "native replay of already observed outcomes; no prospective native dispatch or independent replication"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "supplement", "model", "data", "verification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--contract", choices=("state_residual", "future_correctness"), required=True)
    parser.add_argument("--dynamics", choices=("legacy", "bounded_balanced"), required=True)
    parser.add_argument("--hook", type=Path)
    args = parser.parse_args()
    prepare(args.protocol, args.supplement, args.model, args.data, args.verification,
            args.contract, args.dynamics, args.output, args.hook)

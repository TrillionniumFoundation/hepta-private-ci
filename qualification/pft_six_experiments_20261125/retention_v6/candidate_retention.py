"""One fixed candidate-only retention measurement against retained parent outputs.

No parent model replay, training, solving, derivative evaluation or candidate
selection occurs. The fixed synthetic panel was generated in the original
P2P study; its archived parent predictions are used as historical references.
"""

import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import resource
import signal
import sys
import time
import traceback
import types
import zipfile

ROOT = Path("/home/alex")
WORK = ROOT / "pft-continuation-20261126-8a32"
OLD = ROOT / "pft-hcsn-p2p-v2-20261125-root"
CANDIDATE = "981304e53920d71cf95672df6317a4f81b0aff4f7b380f6d3bdd8b3e4033ee1c"
PARENT = "0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f"
STATE = "15ad379aa068a2917692d0334b1f0b5e8641a6c995bd87a0199842d93516d59c"
SOURCE = "3146e2c56757ff7c818670aa3a9c229b26271c7336d573b1692b91ac8e7a00e9"
PROFILE_SHA = "3c628f2e9eac40fa51e0087a7bd9ab86fb9bc8a37c8120cd50641aa7f1ca904f"
BUDGET = {"model_loads": 1, "physical_forward_calls": 16, "examples": 256,
          "parent_forward_calls": 0, "training_updates": 0, "vjp_calls": 0,
          "quadratic_solves": 0, "candidate_exports": 0, "retries": 0,
          "cpu_seconds": 20, "wall_seconds": 55}
GATE = {"lost_parent_correct_max": 0, "accuracy_drop_max": 0,
        "mse_increase_max": 0.001, "per_population": True,
        "classification_rule": "margin > 0", "floating_tolerance": 0.0}
POPULATIONS = [
    {"node": "pocket4", "source": 730000,
     "data_sha256": "df1eb46f5e7ae172e8dca916b5fb2f0d64dd5de67f17f4e46130ede498e2d368",
     "prediction_sha256": "ea2d21a2c30f7041717112698e42c1ebe09ad70fe1d88e891d76f7feb6e5f149",
     "prediction_bytes": 2646},
    {"node": "ai395", "source": 730100,
     "data_sha256": "17ea301e49851990eb151a647bc31ce0dfb182e378d8fe672dcf588ac82fe7c4",
     "prediction_sha256": "cc77e3cbd7126d637cdf3b1d90f95b584718d6f6d220e08c5b0211a75f50685c",
     "prediction_bytes": 2654},
]


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_fixed(path, expected, cap=65536):
    with Path(path).open("rb") as stream:
        raw = stream.read(cap + 1)
    require(0 < len(raw) <= cap and digest(raw) == expected, "fixed bytes differ: " + str(path))
    return raw


def execute(args, protocol, result):
    require(protocol["schema"] == "hepta.smallhcsn.candidate-retention.v1"
            and protocol["ready_for_execution"] is True
            and protocol["candidate_sha256"] == CANDIDATE
            and protocol["parent_sha256"] == PARENT
            and protocol["budget"] == BUDGET and protocol["gate"] == GATE
            and protocol["populations"] == POPULATIONS
            and protocol["seed"] == 271901 and protocol["count_per_population"] == 128
            and protocol["chunk_size"] == 16 and protocol["steps"] == 12,
            "fixed retention protocol differs")
    require(digest(Path(__file__).read_bytes()) == protocol["evaluator_sha256"], "evaluator changed")
    retained = {}
    for name, pin in protocol["input_files"].items():
        raw = read_fixed(ROOT / pin["path"], pin["sha256"], pin["bytes"])
        require(len(raw) == pin["bytes"], "input size differs")
        retained[name] = raw
    module_dir = ROOT / protocol["profile_module_dir"]
    adapter_modules = {}
    for name in ("profile_io.py", "source_binding.py", "small_hcsn_profile.py"):
        module_name = name[:-3]
        require(module_name not in sys.modules, "fresh adapter module required")
        raw = read_fixed(module_dir / name, protocol["profile_sources"][name])
        module = types.ModuleType(module_name)
        module.__file__ = str(module_dir / name)
        module.__frozen_source_sha256__ = digest(raw)
        sys.modules[module_name] = module
        exec(compile(raw, module.__file__, "exec"), module.__dict__)
        adapter_modules[module_name] = module
    small_hcsn_profile = adapter_modules["small_hcsn_profile"]

    result["counts"]["model_loads"] += 1
    loaded = small_hcsn_profile.load_profile(
        WORK / "v5/aggregate_cold_execution_01/CANDIDATE_PROFILE.json", PROFILE_SHA, ROOT)
    require(loaded.candidate_sha256 == CANDIDATE and loaded.model_state_sha256 == STATE
            and loaded.source_binding_sha256 == SOURCE and loaded.constructor == "plain_linear",
            "candidate, full state or physical source differs")
    torch = loaded.torch
    import numpy as np

    features = types.ModuleType("retained_p2p_features_v6")
    features.__file__ = str(OLD / "code_v1/features.py")
    exec(compile(retained["features"], features.__file__, "exec"), features.__dict__)
    require(torch.get_num_threads() == torch.get_num_interop_threads() == 1, "thread bound differs")
    manifest = json.loads(retained["archive_manifest"])
    original_protocol = json.loads(retained["original_protocol"])
    require(manifest["result_sha256"] == digest(retained["evaluation"])
            and original_protocol["sources"]["features.py"] == digest(retained["features"])
            and original_protocol["evaluation_source_sha256"] == digest(retained["original_evaluator"]),
            "historical archive or source links differ")
    archived = [r for r in manifest["records"] if r["width"] == 8 and r["seed"] == 271901]
    historical = json.loads(retained["evaluation"])
    old_rows = [r for r in historical["rows"] if r["width"] == 8 and r["seed"] == 271901]
    require(len(archived) == len(old_rows) == 1 and old_rows[0]["saved_model_sha256"] == PARENT
            and archived[0]["files"]["adopted_n8_s271901.pt"]["sha256"] == PARENT,
            "historical prediction owner differs")
    parent_profile = json.loads(retained["parent_profile"])
    require(archived[0]["candidate_sha256"] == old_rows[0]["candidate_sha256"]
            == parent_profile["origin"]["coordinate_candidate_sha256"]
            and parent_profile["checkpoint"]["sha256"] == PARENT
            and historical["protocol_sha256"] == digest(retained["original_protocol"]),
            "historical coordinate or protocol binding differs")
    ready = []
    for panel in POPULATIONS:
        node = panel["node"]
        raw = retained["prediction_" + node]
        entry = archived[0]["files"]["predictions_n8_s271901_" + node + ".npz"]
        require(entry == {"bytes": len(raw), "sha256": digest(raw)}
                and len(raw) == panel["prediction_bytes"]
                and digest(raw) == panel["prediction_sha256"], "prediction archive pin differs")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            require(len(members) == 3 and sum(v.file_size for v in members) <= 8192,
                    "historical prediction archive bound")
        with np.load(io.BytesIO(raw), allow_pickle=False) as stored:
            require(set(stored.files) == {"prediction", "target", "expected"}, "prediction arrays differ")
            previous, target = stored["prediction"].copy(), stored["target"].copy()
        require(previous.shape == target.shape == (128,) and previous.dtype == target.dtype == np.float64
                and bool(np.isfinite(previous).all()) and set(target.tolist()) <= {-1.0, 1.0},
                "historical numeric contract differs")
        batch = features.corpus("test", node, 271901, 0, 128)
        require(features.array_hash(batch["x"], batch["margin"], batch["y"]) == panel["data_sha256"]
                and batch["source"] == panel["source"] and np.array_equal(batch["y"], target),
                "retained corpus bytes or labels differ")
        old_test = [v for v in old_rows[0]["test"] if v["test_source"] == panel["source"]]
        require(len(old_test) == 1 and old_test[0]["test_sha256"] == panel["data_sha256"],
                "original evaluation population differs")
        old_accuracy = float(np.mean((previous > 0) == (target > 0)))
        old_mse = float(np.mean((previous - target) ** 2))
        require(old_test[0]["candidate"] == {"accuracy": old_accuracy, "count": 128, "mse": old_mse},
                "historical reference metrics differ")
        ready.append((panel, batch, previous, target, old_accuracy, old_mse))
    result["all_panels_preflighted_before_first_forward"] = True
    for panel, batch, previous, target, old_accuracy, old_mse in ready:
        predictions = []
        started = time.monotonic()
        with torch.no_grad():
            for offset in range(0, 128, 16):
                x = torch.tensor(batch["x"][:, offset:offset + 16], dtype=torch.float64)
                margin = torch.tensor(batch["margin"][offset:offset + 16, None], dtype=torch.float64)
                state = loaded.initial_state(16, margin)
                require(state.step == 0, "fresh state required")
                result["counts"]["physical_forward_calls"] += 1
                logits, _, state = loaded.forward(x, state)
                require(state.step == 12, "complete original trajectory required")
                predictions.append((logits[-1, :, 1] - logits[-1, :, 0]).cpu().numpy())
        after = np.concatenate(predictions)
        require(after.shape == (128,) and bool(np.isfinite(after).all()), "prediction shape or finite gate")
        before_correct, after_correct = (previous > 0) == (target > 0), (after > 0) == (target > 0)
        lost = int(np.sum(before_correct & ~after_correct))
        accuracy, mse = float(np.mean(after_correct)), float(np.mean((after - target) ** 2))
        max_change = float(np.max(np.abs(after - previous)))
        require(all(math.isfinite(v) for v in (accuracy, mse, mse - old_mse, max_change)),
                "nonfinite retention metric")
        passed = lost == 0 and accuracy >= old_accuracy and mse - old_mse <= GATE["mse_increase_max"]
        result["panels"].append({**panel, "count": 128, "previous_correct": int(before_correct.sum()),
            "candidate_correct": int(after_correct.sum()), "lost_parent_correct": lost,
            "gained_correct": int(np.sum(~before_correct & after_correct)),
            "parent_accuracy": old_accuracy, "candidate_accuracy": accuracy,
            "parent_mse": old_mse, "candidate_mse": mse, "mse_increase": mse - old_mse,
            "prediction_max_abs_change": max_change,
            "candidate_predictions": after.tolist(), "parent_predictions": previous.tolist(),
            "targets": target.tolist(), "forward_wall_s": time.monotonic() - started,
            "gate_passed": bool(passed)})
        result["counts"]["examples"] += 128
    loaded.require_frozen()
    require(all(sys.modules[name] is module and module.__frozen_source_sha256__
                == protocol["profile_sources"][name + ".py"]
                for name, module in adapter_modules.items()), "adapter provenance changed")
    require(loaded.current_state_sha256() == STATE, "candidate mutated during retention evaluation")
    for name, pin in protocol["input_files"].items():
        require(read_fixed(ROOT / pin["path"], pin["sha256"], pin["bytes"]) == retained[name],
                "retained input changed")
    require(all(result["counts"][key] == BUDGET[key] for key in result["counts"]), "physical count differs")
    result["candidate_unchanged"] = True
    result["status"] = "COMPLETED_SINGLE_RETENTION_MEASUREMENT"
    result["decision"] = "PASSED_BOUNDED" if all(p["gate_passed"] for p in result["panels"]) else "REJECTED"


def expired(signum, _frame):
    raise TimeoutError("registered retention limit expired: " + str(signum))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    protocol_raw = read_fixed(args.protocol, args.protocol_sha256)
    protocol = json.loads(protocol_raw)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "RUN_CLAIM.json").write_bytes(protocol_raw)
    started, cpu = time.monotonic(), time.process_time()
    result = {"schema": "hepta.smallhcsn.candidate-retention-result.v1", "status": "FAILED",
        "decision": "INSUFFICIENT", "protocol_sha256": args.protocol_sha256,
        "candidate_sha256": CANDIDATE, "parent_sha256": PARENT, "model_state_sha256": STATE,
        "source_binding_sha256": SOURCE, "evaluator_sha256": digest(Path(__file__).read_bytes()),
        "registered_budget": BUDGET, "gate": GATE, "populations": POPULATIONS,
        "counts": {key: 0 for key in BUDGET if key not in ("cpu_seconds", "wall_seconds")},
        "panels": [], "candidate_unchanged": False, "all_panels_preflighted_before_first_forward": False,
        "scope": "fixed_two_population_synthetic_panel_against_archived_parent_predictions",
        "original_E1_E6_reopened": False, "original_model_experiments_repeated": False,
        "parent_model_loaded": False, "new_candidate_selected": False, "test_retuning": False,
        "genuine_independent_users": False, "prospective_B_acceptance": False,
        "statistical_population_noninferiority_proved": False, "production_adoption": False}
    signal.signal(signal.SIGALRM, expired)
    signal.signal(signal.SIGXCPU, expired)
    resource.setrlimit(resource.RLIMIT_CPU, (BUDGET["cpu_seconds"], BUDGET["cpu_seconds"] + 1))
    signal.alarm(BUDGET["wall_seconds"])
    try:
        execute(args, protocol, result)
    except Exception as error:
        result["error"] = repr(error)
        result["traceback"] = traceback.format_exc()
    finally:
        signal.alarm(0)
        result["wall_s"], result["cpu_s"] = time.monotonic() - started, time.process_time() - cpu
        raw = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        require(len(raw) <= 65536, "retention result byte bound")
        with (output / "RESULT.json").open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps({"status": result["status"], "decision": result["decision"],
                      "counts": result["counts"], "result_sha256": digest(raw)}))
    return 0 if result["status"] == "COMPLETED_SINGLE_RETENTION_MEASUREMENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())

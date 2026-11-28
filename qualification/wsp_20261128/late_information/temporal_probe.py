"""Source-bound temporal interventions on frozen actual SmallHCSN parents."""
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
PRIOR = ROOT.parent / "prior_evidence/nov26/neuron_audit"
PACKET = ROOT.parent / "prior_evidence/native_mcp/runtime/fullmodel_mcp_qualification_v3/packet/encoded_inputs"
TRACE = ROOT.parent / "runtime_wsp_audit/qualification/weight_trace_runtime_20261128/target/release/hepta-smallhcsn-trace-research"
PROTOCOL_SHA = "7482531f202a1e26851b5d976e9164f63c9b1c3791bd3399944ed507ae674f34"


def sha(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    with Path(path).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def previous():
    path = PRIOR / "frozen_readout_diagnostic.py"
    assert sha(path.read_bytes()) == "509ca451c61285927ae0e813870143a21503b9dc4808129744c56bdb34828b72"
    spec = importlib.util.spec_from_file_location("previous_frozen_readout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(parent, seed, source_pt, directory, input_bytes):
    tensors = {k: v for k, v in parent.items() if k.startswith("body.")}
    descriptor = {"__metadata__": {"source_checkpoint_sha256": source_pt,
                  "alias_map_json": json.dumps({"head.weight": "body.readout.weight", "head.bias": "body.readout.bias"}, separators=(",", ":")),
                  "origin": "actual frozen checkpoint; research-only serialization"}}
    data = bytearray()
    pins = []
    for name, array in sorted(tensors.items()):
        raw = array.astype(array.dtype.newbyteorder("<")).tobytes()
        pin = {"name": name, "dtype": "F32" if array.dtype.itemsize == 4 else "F64",
               "shape": list(array.shape), "data_offsets": [len(data), len(data) + len(raw)],
               "mutable": name == "body.readout.weight", "sha256": sha(raw)}
        descriptor[name] = {k: pin[k] for k in ("dtype", "shape", "data_offsets")}
        pins.append(pin)
        data.extend(raw)
    header = json.dumps(descriptor, separators=(",", ":"), sort_keys=True).encode()
    complete = struct.pack("<Q", len(header)) + header + data
    model_path = directory / f"parent{seed}.safetensors"
    model_path.write_bytes(complete)
    profile = json.loads((PACKET / "profile47.json").read_text())
    profile["profiles"] = [{"seed": seed, "source_pt_sha256": source_pt,
        "canonical_sha256": sha(complete), "file_bytes": len(complete),
        "header_sha256": sha(header), "header_length": len(header), "tensors": pins}]
    profile["source_declarations"] = {"source_commit": "bc4912ea657864d33b36a57da0b50eb35bee90af",
        "origin": "Actual selected checkpoint, parsed by the original restricted reader",
        "task_input": "explicit historical TRAIN-only intervention; not fresh natural data"}
    profile["input_sha256"] = sha(input_bytes)
    profile["input_bytes"] = len(input_bytes)
    return model_path, profile


def encode(x, baseline, labels, moments=None):
    assert x.shape == (len(labels), 6, 2, 9) and len(labels) <= 80
    if moments is None:
        moments = np.r_[np.zeros(9, dtype=np.float32), np.ones(10, dtype=np.float32)]
    return (b"HCSNIN1\0" + struct.pack("<4I", len(labels), 6, 2, 9)
            + np.asarray(moments, dtype="<f4").tobytes() + np.asarray(x, dtype="<f4").tobytes()
            + np.asarray(baseline, dtype="<f4").tobytes() + np.asarray(labels, dtype="<i8").tobytes())


def run():
    start = time.perf_counter()
    cpu_start = time.process_time()
    assert sha((ROOT / "LATE_INFORMATION_PROTOCOL.md").read_bytes()) == PROTOCOL_SHA
    out = ROOT / "temporal_results"
    out.mkdir(exist_ok=False)
    native = out / "native-trace-frozen"
    shutil.copy2(TRACE, native)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    raw = (PACKET / "train_raw.bin").read_bytes()
    assert sha(raw) == "c9bc1fdb60f146e5fe8a1b245d10a0d4a01967fa28cf0180c4873b666f5363dd"
    moments = np.frombuffer(raw[24:100], dtype="<f4").copy()
    x = np.frombuffer(raw[100:100+80*108*4], dtype="<f4").reshape(80, 6, 2, 9)[:16].copy()
    b = np.frombuffer(raw[100+80*108*4:-80*8], dtype="<f4").reshape(80, 2)[:16].copy()
    y = np.frombuffer(raw[-80*8:], dtype="<i8")[:16].copy()
    original = encode(x, b, y, moments)
    save(out / "SOURCE_SEAL.json", {"protocol_sha256": PROTOCOL_SHA,
        "source_sha256": sha(Path(__file__).read_bytes()), "binary_sha256": sha(native.read_bytes()),
        "original_input_sha256": sha(raw), "queries": 16, "seeds": [47, 83, 137],
        "observed_outcomes_before_this_seal": 0, "wall_started_unix": time.time()})
    old = previous()
    rows = []
    for seed in (47, 83, 137):
        parent = old.read_checkpoint(seed)
        work = out / str(seed)
        work.mkdir()
        checkpoint, base_profile = canonical(parent, seed, old.CHECKPOINT_SHA[seed], work, original)
        results = []
        for tick in (-1, 0, 1, 2, 3, 4, 5):
            xx = x.copy()
            if tick >= 0:
                norm = (xx[:, tick]-moments[:9])/moments[9:18]
                xx[:, tick] = (-norm+np.float32(.125))*moments[9:18]+moments[:9]
            inp = encode(xx, b, y, moments)
            name = "baseline" if tick == -1 else f"tick{tick}"
            input_path = work / f"{name}.bin"
            input_path.write_bytes(inp)
            profile = dict(base_profile, input_bytes=len(inp), input_sha256=sha(inp))
            profile_path = work / f"{name}.profile.json"
            save(profile_path, profile)
            output_path = work / f"{name}.json"
            cmd = [str(native), "trace", str(profile_path), sha(profile_path.read_bytes()),
                   str(checkpoint), sha(checkpoint.read_bytes()), str(checkpoint), sha(checkpoint.read_bytes()),
                   str(input_path), sha(inp), str(output_path)]
            launched = time.perf_counter()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            receipt = {"seed": seed, "tick": tick, "exit_code": proc.returncode,
                       "wall_seconds": time.perf_counter()-launched,
                       "stdout": proc.stdout, "stderr": proc.stderr}
            save(work / f"{name}.process.json", receipt)
            if proc.returncode:
                raise RuntimeError(receipt)
            r = json.loads(output_path.read_text())
            result = {"seed": seed, "tick": tick, "input_sha256": sha(inp),
                      "output_sha256": sha(output_path.read_bytes()), "physical_residuals": r["physical_residuals"],
                      "full_forward_calls": r["full_model_forward_calls"],
                      "feature_bytes": np.asarray(r["features"], dtype="<f4").tobytes(),
                      "score_bytes": np.asarray(r["scores"], dtype="<f4").tobytes(),
                      "features": np.asarray(r["features"], dtype=np.float32).reshape(16, 2, 4, 5)}
            results.append(result)
            if tick != -1:
                base = results[0]
                result["features_identical"] = result["feature_bytes"] == base["feature_bytes"]
                result["scores_identical"] = result["score_bytes"] == base["score_bytes"]
                diff = result["features"] != base["features"]
                result["changed_elements_by_feature"] = diff.sum(axis=(0, 1, 2)).tolist()
                result["max_abs_delta_by_feature"] = abs(result["features"]-base["features"]).max(axis=(0, 1, 2)).tolist()
                expected = ((result["features_identical"] and result["scores_identical"]) if tick % 2 else
                            (not diff[..., [0, 1, 3, 4]].any()) if tick == 4 else True)
                result["predicted_structural_equalities_pass"] = bool(expected)
            rows.append({k: v for k, v in result.items() if k not in ("feature_bytes", "score_bytes", "features")})
            save(work / f"{name}.summary.json", rows[-1])
            total = resource.getrusage(resource.RUSAGE_CHILDREN)
            if total.ru_utime + total.ru_stime - before.ru_utime - before.ru_stime > 120:
                raise TimeoutError("pre-registered child CPU cap")
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"protocol_sha256": PROTOCOL_SHA, "rows": rows,
              "all_predicted_equalities_pass": all(r.get("predicted_structural_equalities_pass", True) for r in rows),
              "full_model_evaluations": sum(r["full_forward_calls"] for r in rows),
              "wall_seconds": time.perf_counter()-start, "orchestrator_cpu_seconds": time.process_time()-cpu_start,
              "native_child_cpu_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
              "fitting_or_backward_calls": 0, "adoption": "none"}
    save(out / "RESULT.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    run()

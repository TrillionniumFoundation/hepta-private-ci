"""Restore complete experimental computation identity, retaining a wrong-graph control."""
import hashlib
import json
from pathlib import Path
import resource
import struct
import subprocess
import time

import numpy as np
from scipy.special import expit

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "late_results"
PROTOCOL_SHA = "cdbd86e61e6376bb3b4a84decb16ca6d7af0d3058f088153dd7149ab1411a51e"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def save(p, x):
    with p.open("x") as f:
        json.dump(x, f, indent=2, sort_keys=True)
        f.write("\n")


def exact(a, b, dtype="<f4"):
    return np.asarray(a, dtype=dtype).tobytes() == np.asarray(b, dtype=dtype).tobytes()


def run():
    started = time.perf_counter()
    cpu = time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    assert sha((ROOT / "GRAPH_ROLLBACK_PROTOCOL.md").read_bytes()) == PROTOCOL_SHA
    out = ROOT / "graph_rollback_results"
    out.mkdir(exist_ok=False)
    native = SOURCE / "native-bridge-frozen"
    save(out / "SEAL.json", {"protocol_sha256": PROTOCOL_SHA,
         "source_sha256": sha(Path(__file__).read_bytes()), "native_sha256": sha(native.read_bytes()),
         "start_unix": time.time(), "previous_late_task_results_known": True})
    rows, trace_rows = [], []
    for seed in (47, 83, 137):
        directory = SOURCE / str(seed)
        parent_path = directory / f"parent{seed}.safetensors"
        parent = parent_path.read_bytes()
        candidate_path = directory / "test_DIRECT_SIGN.safetensors"
        candidate = candidate_path.read_bytes()
        hlen = struct.unpack("<Q", parent[:8])[0]
        header = json.loads(parent[8:8+hlen])
        offset = 8+hlen+header["body.input_mark.weight"]["data_offsets"][0]
        allowed = set()
        reverse = []
        restored = bytearray(candidate)
        for row in range(4):
            begin = offset+(row*9+7)*4
            allowed.update(range(begin, begin+4))
            assert restored[begin:begin+4] == candidate[begin:begin+4]
            reverse.append({"offset": begin, "expected_candidate_hex": candidate[begin:begin+4].hex(),
                            "restore_parent_hex": parent[begin:begin+4].hex()})
            restored[begin:begin+4] = parent[begin:begin+4]
        assert len(candidate) == len(parent) and all(a == b or i in allowed for i, (a, b) in enumerate(zip(parent, candidate)))
        assert restored == parent
        restored_path = out / f"restored{seed}.safetensors"
        restored_path.write_bytes(restored)
        profile_path = directory / "retain_PARENT.profile.json"
        input_path = directory / "retain_PARENT.input.bin"
        old = json.loads((directory / "retain_PARENT.native.json").read_text())
        pair = []
        for mode in ("late-bridge", "mark-control"):
            output = out / f"{seed}_{mode}.json"
            command = [str(native), mode, str(profile_path), sha(profile_path.read_bytes()),
                       str(parent_path), sha(parent), str(restored_path), sha(restored),
                       str(input_path), sha(input_path.read_bytes()), str(output)]
            launch = time.perf_counter()
            proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
            save(out / f"{seed}_{mode}.process.json", {"exit_code": proc.returncode,
                "wall_seconds": time.perf_counter()-launch, "stdout": proc.stdout, "stderr": proc.stderr})
            if proc.returncode:
                raise RuntimeError(proc.stderr)
            current = json.loads(output.read_text())
            fields = {key: exact(current[key], old[key]) for key in ("features", "heads", "scores")}
            if mode == "mark-control":
                assert all(fields.values())
            pair.append({"graph_mode": mode, "outputs_equal_original": fields,
                         "correct": current["correct"], "original_correct": old["correct"],
                         "physical_residuals": current["physical_residuals"],
                         "full_model_forward_calls": current["full_model_forward_calls"],
                         "output_sha256": sha(output.read_bytes())})
        rows.append({"seed": seed, "parent_sha256": sha(parent), "candidate_sha256": sha(candidate),
            "restored_sha256": sha(restored), "inverse_bytes_exact": True, "reverse": reverse,
            "weights_were_identity": candidate == parent, "evaluations": pair})
        old_trace = json.loads((directory / "test_KEEP.native.json").read_text())["trace"]
        new_trace = json.loads((directory / "test_DIRECT_SIGN.native.json").read_text())["trace"]
        checks = {"boundary": True, "drift": True, "cost": True, "probability_features": True,
                  "receiver_pre_final_features": True}
        signed_changed = 0
        for a, b in zip(old_trace, new_trace, strict=True):
            assert (a["query"], a["choice"], a["tick"]) == (b["query"], b["choice"], b["tick"])
            checks["boundary"] &= exact(a["boundary_after"], b["boundary_after"], "<f8") and exact(a["boundary_before"], b["boundary_before"], "<f8")
            checks["drift"] &= exact(a["effective_drift"], b["effective_drift"], "<f8")
            checks["cost"] &= exact(a["effective_cost"], b["effective_cost"], "<f8")
            f0, f1 = np.asarray(a["features"], dtype=np.float32), np.asarray(b["features"], dtype=np.float32)
            checks["probability_features"] &= exact(f0[:, [0, 1, 3, 4]], f1[:, [0, 1, 3, 4]])
            if a["tick"] < 5:
                checks["receiver_pre_final_features"] &= exact(f0[4:], f1[4:])
            signed_changed += int((f0[4:, 2] != f1[4:, 2]).sum())
        assert all(checks.values())
        trace_rows.append({"seed": seed, "trace_records": len(old_trace), "checks": checks,
                           "changed_receiver_signed_elements": signed_changed,
                           "new_model_calls": 0})
        now = resource.getrusage(resource.RUSAGE_CHILDREN)
        if now.ru_utime+now.ru_stime-before.ru_utime-before.ru_stime > 30:
            raise TimeoutError("graph rollback CPU cap exceeded")
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"schema": "hepta.graph-and-weight-restoration-research.v1", "protocol_sha256": PROTOCOL_SHA,
        "rows": rows, "trace_checks": trace_rows, "new_model_calls": 6, "new_fits": 0,
        "wall_seconds": time.perf_counter()-started, "self_cpu_seconds": time.process_time()-cpu,
        "native_child_cpu_seconds": after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        "persistent_runtime_transaction_executed": False,
        "conclusion": "The graph and request route must join parameter bytes in transaction identity and restoration."}
    save(out / "RESULT.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("rows", "trace_checks")}))


if __name__ == "__main__":
    run()

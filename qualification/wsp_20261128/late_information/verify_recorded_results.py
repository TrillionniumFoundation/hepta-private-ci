"""Verify recorded predictions and input identities without executing a model.

This check was saved after the original inline audit. It does not regenerate
TEST, choose candidates, run a forward, or change any recorded result.
"""
import hashlib
import json
from pathlib import Path
import struct

import numpy as np


def digest(value):
    return hashlib.sha256(value).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    out = root / "late_results"
    result = json.loads((out / "RESULT.json").read_text())
    audit = json.loads((root / "POSTEXECUTION_AUDIT.json").read_text())
    assert digest((out / "RESULT.json").read_bytes()) == audit["result_sha256"]
    seal = json.loads((out / "CANDIDATES_SEALED_BEFORE_TEST.json").read_text())
    with np.load(out / "new_test_inputs.npz", allow_pickle=False) as z:
        x, y = z["x"], z["y"]
    assert x.shape == (80, 6, 2, 9)
    assert np.array_equal(y, x[:, -1, :, 7].argmin(1))
    assert np.array_equal(y[::2], 1-y[1::2])
    assert np.array_equal(x[:, :-1, 0], x[:, :-1, 1])
    assert np.array_equal(x[:, -1, 0, :7], x[:, -1, 1, :7])
    assert np.array_equal(x[:, -1, 0, 8:], x[:, -1, 1, 8:])
    assert np.array_equal(x[::2], x[1::2, :, ::-1])
    checked = 0
    for row in result["records"]:
        if row["phase"] != "FRESH_SYNTHETIC_TEST":
            continue
        seed, arm = row["seed"], row["arm"]
        original = arm.startswith("ORIGINAL_GRAPH_")
        name = ("oldgraph_test_" + arm.removeprefix("ORIGINAL_GRAPH_")) if original else "test_" + arm
        work = out / str(seed)
        native = json.loads((work / (name + ".native.json")).read_text())
        scores = np.asarray(native["scores"], dtype=np.float32).reshape(80, 2)
        m = scores[:, 1].astype(float)-scores[:, 0].astype(float)
        p = 1/(1+np.exp(-m))
        correct = int((scores.argmax(1) == y).sum())
        assert row["correct"] == native["correct"] == correct
        assert abs(row["ce"]-np.mean(np.logaddexp(0., m)-y*m)) < 1e-13
        assert abs(row["brier"]-np.mean((p-y)**2)) < 1e-13
        if original:
            assert np.array_equal(scores[:, 0], scores[:, 1])
        else:
            raw = (work / (name + ".safetensors")).read_bytes()
            assert digest(raw) == native["selected_artifact_sha256"]
            n = struct.unpack("<Q", raw[:8])[0]
            header = json.loads(raw[8:8+n])
            offset = header["body.input_mark.weight"]["data_offsets"][0]
            theta = np.frombuffer(raw, dtype="<f4", count=36, offset=8+n+offset).reshape(4, 9)[:, 7].copy()
            candidate = seal["candidates"][str(seed)][arm]
            assert digest(theta.tobytes()) == candidate["sha256"]
            assert np.array_equal(theta, np.asarray(candidate["values"], dtype=np.float32))
        checked += 1
    assert checked == 21
    for seed in (47, 83, 137):
        work = out / str(seed)
        parent = json.loads((work / "retain_PARENT.native.json").read_text())
        scoped = json.loads((work / "retain_SCOPED_DIRECT.native.json").read_text())
        for key in ("features", "heads", "scores"):
            assert np.asarray(parent[key], dtype="<f4").tobytes() == np.asarray(scoped[key], dtype="<f4").tobytes()
    print(json.dumps({"status": "PASS", "checked_test_rows": checked, "new_model_calls": 0,
                      "new_fits": 0, "test_queries": len(y), "independent_contexts": len(y)//2}))


if __name__ == "__main__":
    main()

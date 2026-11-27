"""Read-only arithmetic/source verification. No model/kernel imports or calls."""

import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    root = Path(__file__).resolve().parent
    repo = root.parents[1]
    ids = ["new-near800-atol14-001", "new-near800-atol16-001",
           "new-near800-atol18-001", "new-near960-atol18-001"]
    rows = 0
    for identity in ids:
        folder = root / "evidence" / identity
        summary = json.loads((folder / "SUMMARY.json").read_text())
        assert summary["source_unchanged"] and summary["status"] == "HOLD_NO_GO"
        before, after = summary["source_sha256_before"], summary["source_sha256_after"]
        assert before == after
        for recorded, digest in before.items():
            relative = "qualification/" + recorded.split("/qualification/", 1)[1]
            assert hashlib.sha256((repo / relative).read_bytes()).hexdigest() == digest
        path = folder / "RAW.npz"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == summary["raw_sha256"]
        with np.load(path, allow_pickle=False) as a:
            for i, row in enumerate(summary["rows"]):
                assert float(a["time"][i]) == row["time"]
                assert float(a["dde_events"][i, 0]) == row["dde_M"]
                assert float(a["positive_M"][i]) == row["positive"]["M"]
                ref = float(a["reference128_M"][i])
                expected = (row["dde_M"] - ref) / ref
                assert abs(expected - row["dde_relative_error"]) <= 1e-14 * max(1, abs(expected))
            # Signed channel is the same linear flow, never a different rollout.
            for key in ("active", "upper", "refractory", "events", "discounted_events",
                        "discounted_active_time", "discounted_remaining_phase"):
                value = a["dde_" + key]
                assert np.max(np.abs(value[..., 1] + 0.7 * value[..., 0])) < 1e-9
            total = a["dde_active"].sum(axis=1) + a["dde_upper"] + a["dde_refractory"]
            assert np.max(np.abs(total - [1.0, -0.7])) < 1e-9
            rows += len(a["time"])
    core = (root / "controlled_core.py").read_text()
    original = (repo / "qualification/hcsn_joint_dde/model.py").read_text()
    assert original.count("not 1e-14 <= atol") == 1
    assert core == original.replace("not 1e-14 <= atol", "not 1e-18 <= atol")
    receipt = json.loads((root / "reference/attempt001/EXECUTION.json").read_text())
    # Independent reference original stdout remains JSON, not a rewritten table.
    reference = json.loads((root / "reference/attempt001/REFERENCE.stdout").read_text())
    assert reference["source_sha256_before"] == reference["source_sha256_after"]
    ref_source = root / "reference/phase_reference.py"
    assert hashlib.sha256(ref_source.read_bytes()).hexdigest() == reference["source_sha256_before"]
    assert reference["model_or_kernel_executions"] == 0
    assert receipt
    print(json.dumps({"read_only": True, "retained_dde_runs": len(ids),
                      "query_rows": rows, "new_model_calls": 0, "new_kernel_calls": 0,
                      "original_loss_preserved": True, "status": "HOLD_NO_GO"}))


if __name__ == "__main__":
    main()

"""Read retained sweep arithmetic/source only; no model/kernel imports."""

import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    root = Path(__file__).resolve().parent
    repo = root.parents[1]
    folder = root / "evidence/new-fixed-sweep-001"
    summary = json.loads((folder / "SUMMARY.json").read_text())
    assert summary["source_and_inputs_unchanged"] and not summary["all_closed"]
    assert summary["source_sha256_before"] == summary["source_sha256_after"]
    assert summary["input_sha256_before"] == summary["input_sha256_after"]
    for recorded, digest in summary["source_sha256_before"].items():
        relative = "qualification/" + recorded.split("/qualification/", 1)[1]
        assert hashlib.sha256((repo / relative).read_bytes()).hexdigest() == digest
    path = folder / "RAW.npz"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == summary["raw_sha256"]
    with np.load(path, allow_pickle=False) as a:
        resets, times, reference = a["resets"], a["times"], a["reference128_M"]
        assert len(resets) == 188 and a["original_reset"].sum() == 184
        assert reference.shape == (6, 188)
        count = 0
        for panel in summary["panels"]:
            values = a[panel["profile"] + "_M"]
            assert values.shape == reference.shape
            for i, row in enumerate(panel["rows"]):
                assert times[i] == row["time"]
                eligible = reference[i] >= 1e-12
                assert eligible.sum() == row["eligible_rows"]
                assert (~eligible).sum() == row["below_floor_rows"]
                if eligible.any():
                    error = np.abs(values[i] - reference[i]) / reference[i]
                    maximum = np.max(error[eligible])
                    assert maximum == row["maximum_eligible_relative_M"]
                    assert error[np.flatnonzero(resets == row["worst_reset"])[0]] == maximum
                else:
                    assert row["maximum_eligible_relative_M"] is None
                assert np.max(np.abs(values[i] - reference[i])) == row["maximum_absolute_M"]
                count += len(resets)
    print(json.dumps({"read_only": True, "retained_reset_time_profile_rows": count,
                      "new_model_calls": 0, "new_kernel_calls": 0,
                      "post_failure_development": True, "status": "HOLD_NO_GO"}))


if __name__ == "__main__":
    main()

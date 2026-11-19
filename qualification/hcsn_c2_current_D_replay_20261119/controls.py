"""Synthetic D-scope/order guards and independent multiclass arithmetic."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time

import numpy as np
from audit_io import read_dev
from independent_metrics import compare_metrics, metrics


def run():
    started = time.monotonic()
    passed = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        def put(name, value):
            raw = (json.dumps(value, sort_keys=True) + "\n").encode()
            (root / name).write_bytes(raw)
            return hashlib.sha256(raw).hexdigest()
        row = {"id": "D01-0", "partition": "dev", "sequence": "D01", "x": [[0.] * 12 + [1.] * 12 + [0.]],
               "y": [3], "dt": [0.], "delta_ticks": [0], "source_rows": [1]}
        entry = {"id": "D01-0", "partition": "dev", "events": 1, "path": "D01-0.json", "sha256": put("D01-0.json", row)}
        manifest = {"mode": "all-development", "confirmation_access": False, "episodes": [entry],
                    "selection_sha256": put("selection.json", [{"id": "D01-0"}]),
                    "frontend_sha256": put("frontend.json", {"test_used": False, "fit_subjects": list("ABC")})}
        plan = {"prepared": str(root), "data_manifest_sha256": put("data-manifest.json", manifest),
                "dev_entries": [entry], "expected_dev_episodes": 1, "expected_dev_events": 1}
        assert read_dev(plan, {}) == [row]
        passed.append("valid_D_fixture")
        for label, update in [("confirmation_manifest", {"confirmation_access": True}),
                              ("duplicate_window", {"episodes": [entry, entry]}),
                              ("unapproved_partition", {"episodes": [{**entry, "partition": "test"}]})]:
            bad = copy.deepcopy(manifest); bad.update(update)
            badplan = {**plan, "data_manifest_sha256": put("data-manifest.json", bad)}
            try:
                read_dev(badplan, {})
                raise AssertionError(label + " accepted")
            except ValueError:
                passed.append(label + "_rejected")
        put("data-manifest.json", manifest)
        (root / "D01-0.json").write_text("{}")
        try:
            read_dev(plan, {})
            raise AssertionError("changed row accepted")
        except ValueError:
            passed.append("changed_D_payload_rejected")
    logits = np.eye(11) * 4
    labels = np.arange(11)
    value = metrics(logits, labels)
    assert value["accuracy"] == value["macro_f1_11_classes"] == 1.
    assert abs(value["nll"] - np.log1p(10 * np.exp(-4))) < 1e-14
    passed.append("eleven_class_closed_form_NLL")
    wrong = metrics(logits, np.roll(labels, 1))
    assert wrong["accuracy"] == wrong["macro_f1_11_classes"] == 0.
    try:
        compare_metrics(wrong, value, 2e-12)
        raise AssertionError("row-label permutation accepted")
    except ValueError:
        passed.append("misaligned_labels_rejected")
    try:
        metrics(logits, np.full(11, 11))
        raise AssertionError("invalid labels accepted")
    except ValueError:
        passed.append("invalid_class_rejected")
    print(json.dumps({"schema": "current-D-synthetic-controls-v1", "passed": passed,
                      "count": len(passed), "wall_seconds": time.monotonic() - started,
                      "production_model_D_E_reads": 0}, sort_keys=True, indent=2))


if __name__ == "__main__":
    run()

"""End-to-end label boundaries and independent scoring rejection tests."""

import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from cell_field_action_evaluate import evaluate
from cell_field_action_score_audit import audit_evaluation
from cell_field_action_io import source_hashes


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def seal_run(root, protocol):
    files = {p.relative_to(root).as_posix(): {"bytes": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in root.rglob("*") if p.is_file() and p.name != "pre_evaluation_seal.json"}
    put(root / "pre_evaluation_seal.json", {"files": files, "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "sourcecode_hashes": json.loads((root / "runs.json").read_text())["sourcecode_hashes"],
        "record_count": 342, "validation_labels_opened": False, "final_labels_opened": False})


def fixture(directory, *, missing_hard_seed=False):
    root, data, output = directory / "run", directory / "data", directory / "evaluation"
    root.mkdir(); data.mkdir()
    protocol_path = directory / "protocol.json"
    protocol = json.loads(Path(__file__).with_name("cell_field_action_protocol.json").read_text())
    put(protocol_path, protocol)
    rows, payloads = [], {kind: {"schema": "hepta.cell-action-news.v3", "classes": 4, "roles": {}}
                         for kind in ("train", "validation", "final")}
    for role in protocol["source_role_plan"]:
        start = len(rows)
        for i in range(role["rows"]):
            rows.append({"source_id": f"source-{start+i}", "component_id": f"component-{start+i}", "role": role["role"]})
        payloads[role["access"]]["roles"][role["role"]] = {
            "indices": list(range(start, len(rows))), "labels": [i % 4 for i in range(role["rows"])],
            "source_ids": [r["source_id"] for r in rows[start:]]}
    put(data / "sources.json", {"rows": rows})
    for kind, payload in payloads.items(): put(data / f"{kind}_labels.json", payload)
    receipt = {"files": {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                        for p in data.glob("*.json")}}
    put(data / "data_receipt.json", receipt)
    warmups, initials, records = [], [], []
    methods = [("zero", 0, "zero")] + [(obs, lookahead, objective) for objective in protocol["objectives"]
               for obs in protocol["observations"] for lookahead in protocol["lookaheads"]]
    for seed, head in itertools.product(protocol["seeds"], protocol["head_modes"]):
        wi = len(warmups)
        warmups.append({"seed": seed, "head": head, "status": "completed", "checkpoint_path": f"warmup/{wi}"})
        for anchor in protocol["anchor_offsets"]:
            ai = len(initials)
            initials.append({"seed": seed, "head": head, "anchor_offset": anchor, "status": "completed", "checkpoint_path": f"initial/{ai}"})
            for obs, lookahead, objective in methods:
                method = "zero" if obs == "zero" else f"{obs}_h{lookahead}_{objective}"
                failure = missing_hard_seed and seed == 29 and head == "linear" and anchor == 16 and method == "loss2_h8_direct_hard"
                records.append({"run_id": f"branch-{len(records)}", "seed": seed, "head": head, "anchor_offset": anchor,
                    "observation": obs, "lookahead": lookahead, "objective": objective, "method_id": method,
                    "status": "tangent_infeasible" if failure else "completed", "initial_index": ai, "warmup_index": wi, "paths": {},
                    "predicted_scores": {obs: {key: 0.0 for key in ("direct_soft_total", "tracking_soft_total")} for obs in ("loss2", "full")},
                    "actual_scores": {key: 0.0 for key in ("direct_soft_total", "tracking_soft_total")}})
    for state in warmups + initials:
        put(root / state["checkpoint_path"] / "manifest.json", {"synthetic": True})
        np.savez(root / state["checkpoint_path"] / "state.npz", synthetic=np.array([0]))
    retention = [i for i, row in enumerate(rows) if row["role"] in ("old_validation", "old_test")]
    runs = {"records": records, "record_count": 342, "warmup_order": warmups, "initial_order": initials,
        "sourcecode_hashes": source_hashes(),
        "source_ids": [r["source_id"] for r in rows], "row_roles": [r["role"] for r in rows], "retention_indices": retention,
        "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "data_receipt_sha256": hashlib.sha256((data / "data_receipt.json").read_bytes()).hexdigest()}
    put(root / "runs.json", runs)
    terminal = np.full((342, len(rows), 4), 0.25)
    trace = np.full((342, 9, len(retention), 4), 0.25)
    for i, row in enumerate(records):
        if row["status"] != "completed": terminal[i].fill(np.nan); trace[i].fill(np.nan)
    np.savez_compressed(root / "predictions.npz", terminal_probabilities=terminal, retention_probabilities=trace,
        warmup_probabilities=np.full((6, len(rows), 4), 0.25), initial_probabilities=np.full((18, len(rows), 4), 0.25))
    seal_run(root, protocol_path)
    return root, data, protocol_path, output


class ActionScoreAuditTests(unittest.TestCase):
    def test_validation_sealed_before_final_and_missing_seed_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root, data, protocol, output = fixture(Path(temp), missing_hard_seed=True)
            original = Path.read_bytes
            order = []

            def read(path):
                if path == data / "validation_labels.json": order.append("validation")
                if path == data / "final_labels.json":
                    self.assertTrue((output / "validation_seal.json").is_file())
                    self.assertTrue((output / "validation.json").is_file())
                    order.append("final")
                return original(path)

            with patch.object(Path, "read_bytes", read):
                result = evaluate(root, data, protocol, output)
            self.assertEqual(order, ["validation", "final"])
            audit = audit_evaluation(root, data, protocol, output)
            self.assertEqual(audit["maximum_absolute_error"], 0)
            self.assertEqual(audit["primary_comparisons_checked"], 8)
            self.assertEqual(audit["primary_intervals_recomputed"], 6)
            self.assertEqual(result["primary_contrasts"][2]["status"], "unavailable_registered_seed")

    def test_broken_census_rejected_before_any_heldout_label_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root, data, protocol, output = fixture(Path(temp))
            runs = json.loads((root / "runs.json").read_text())
            runs["records"].pop()
            put(root / "runs.json", runs)
            seal_run(root, protocol)
            original = Path.read_bytes
            opened = []

            def read(path):
                if path in (data / "validation_labels.json", data / "final_labels.json"): opened.append(path)
                return original(path)

            with patch.object(Path, "read_bytes", read):
                with self.assertRaisesRegex(ValueError, "census"):
                    evaluate(root, data, protocol, output)
            self.assertEqual(opened, [])

    def test_independent_audit_rejects_changed_primary_interval(self):
        with tempfile.TemporaryDirectory() as temp:
            root, data, protocol, output = fixture(Path(temp))
            evaluate(root, data, protocol, output)
            result = json.loads((output / "evaluation.json").read_text())
            result["primary_contrasts"][0]["bonferroni_percentile_interval"][0] += 0.01
            put(output / "evaluation.json", result)
            with self.assertRaisesRegex(ValueError, "independent heldout score or interval"):
                audit_evaluation(root, data, protocol, output)

    def test_changed_imported_legacy_helper_rejects_before_heldout_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root, data, protocol, output = fixture(Path(temp))
            original = Path.read_bytes
            opened = []

            def read(path):
                if path in (data / "validation_labels.json", data / "final_labels.json"):
                    opened.append(path)
                value = original(path)
                if path == Path(__file__).with_name("cell_field_evaluate.py"):
                    return value + b"\n# synthetic imported-helper modification\n"
                return value

            with patch.object(Path, "read_bytes", read):
                with self.assertRaisesRegex(ValueError, "scoring source changed"):
                    evaluate(root, data, protocol, output)
            self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()

"""Independent metric, tamper and failed-denominator checks; no Torch needed."""

import gzip
import json
import math
from pathlib import Path
import tempfile
import unittest

from . import pft_structure_audit as audit


def write(path, value):
    path.write_text(json.dumps(value))


def fixture(root):
    slots = [{"id": "good", "seed": 1}, {"id": "failed", "seed": 2}]
    protocol = {
        "slots": slots,
        "training": {"max_updates": 512},
        "validation": {
            "min_final_accuracy": 0.8,
            "min_gain_over_initial": 0.1,
            "min_gain_over_prelate": 0.1,
        },
        "data": {
            "train_sources": [1],
            "dev_sources": [2],
            "test_sources": [3],
            "test_per_source": 2,
            "length": 2,
        },
    }
    write(root / "PROTOCOL.json", protocol)
    seal = {"protocol_sha256": audit.identity(protocol), "attempts": {}}
    payload = {
        "labels": [0, 1],
        "source": [3, 3],
        "late_step": [1, 1],
        "ids": ["a", "b"],
        "protocol_sha256": audit.identity(protocol),
        "data_sha256": "fixture-data",
        "slot": slots[0],
    }
    selected = [[[0.0, 0.0], [0.0, 0.0]], [[2.0, 0.0], [0.0, 2.0]]]
    initial = [[[0.0, 0.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]]]
    payload["prefix_logits"] = {
        "selected": selected,
        "initial": initial,
        "cpu_prefix": initial,
    }
    for index, slot in enumerate(slots):
        directory = root / slot["id"]
        directory.mkdir()
        status = "completed" if index == 0 else "failed"
        result = {
            "slot": slot,
            "protocol_sha256": audit.identity(protocol),
            "smoke": False,
            "status": status,
            "updates": 512 if index == 0 else 0,
            "selected_step": 512 if index == 0 else 0,
            "checkpoint_sha256": None,
            "error": "preserved numerical failure" if index else None,
        }
        if index == 0:
            (directory / "checkpoint.pt").write_bytes(
                b"known fixture checkpoint bytes; not deserialized"
            )
            result["checkpoint_sha256"] = audit.digest(directory / "checkpoint.pt")
        write(directory / "result.json", result)
        write(directory / "history.json", [])
        write(directory / "worker_cost.json", {"status": status, "error": None})
        write(
            directory / "parent_cost.json",
            {"returncode": int(index != 0), "error": None},
        )
        seal["attempts"][slot["id"]] = {
            p.name: audit.digest(p) for p in directory.iterdir()
        }
        tested = {"slot": slot, "status": "unavailable"}
        if index == 0:
            path = directory / "test_predictions.json.gz"
            with gzip.open(path, "wt") as handle:
                json.dump(payload, handle)
            tested.update(
                status="evaluated",
                predictions_sha256=audit.digest(path),
                data_sha256="fixture-data",
                learning_gate=True,
                metrics={
                    key: audit.reconstruct(value, payload)
                    for key, value in payload["prefix_logits"].items()
                },
            )
        write(directory / "test_result.json", tested)
        write(
            directory / "test_worker_cost.json",
            {"status": tested["status"], "error": None},
        )
        write(directory / "test_parent_cost.json", {"returncode": 0, "error": None})
    write(root / "SEAL.json", seal)
    write(
        root / "TEST_CLAIM.json",
        {
            "protocol_sha256": audit.identity(protocol),
            "seal_sha256": audit.digest(root / "SEAL.json"),
        },
    )
    return payload


class StructureAuditTests(unittest.TestCase):
    def test_binary_metrics_have_independent_known_answer(self):
        payload = {
            "labels": [0, 1],
            "source": [7, 8],
            "late_step": [1, 1],
            "ids": ["a", "b"],
        }
        score = audit.reconstruct(
            [[[0.0, 0.0], [0.0, 0.0]], [[1000.0, 1000.0], [-1000.0, -1000.0]]], payload
        )
        self.assertAlmostEqual(score.pop("stopping_utility"), 0.46)
        self.assertEqual(
            score,
            {
                "accuracy": 0.5,
                "brier": 0.5,
                "cross_entropy": math.log(2),
                "early_accuracy": 0.5,
                "pre_late_accuracy": 0.5,
                "stop_accuracy": 0.5,
                "mean_stop_step": 1,
                "stop_before_late_fraction": 0,
                "source_accuracy": {"7": 1, "8": 0},
                "worst_source_accuracy": 0,
                "examples": 2,
                "sources": 2,
            },
        )

    def test_failure_and_corruption_stay_in_declared_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            original = audit.audit_study(root, 2)
            self.assertEqual(
                original["status_counts"], {"evaluated": 1, "unavailable": 1}
            )
            self.assertEqual(
                next(iter(original["groups"].values()))["declared_denominator"], 2
            )
            path = root / "good/test_predictions.json.gz"
            path.write_bytes(path.read_bytes() + b"tampered")
            changed = audit.audit_study(root, 2)
            self.assertEqual(
                changed["status_counts"], {"unverified": 1, "unavailable": 1}
            )
            self.assertEqual(changed["audit_errors"], 1)
            self.assertEqual(
                next(iter(changed["groups"].values()))["declared_denominator"], 2
            )

    def test_changed_sealed_history_is_rejected_before_predictions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            write(root / "good/history.json", [{"selected_using_test": True}])
            result = audit.audit_study(root, 2)
            self.assertEqual(
                result["rows"][0]["audit_error"], "sealed bytes changed: history.json"
            )

    def test_invalid_time_and_roster_cannot_be_scored(self):
        with self.assertRaisesRegex(ValueError, "late indices"):
            audit.reconstruct(
                [[[0, 0]], [[1, 0]]],
                {"labels": [0], "source": [1], "late_step": [0], "ids": ["a"]},
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            with self.assertRaisesRegex(ValueError, "roster"):
                audit.audit_study(root, 3)


if __name__ == "__main__":
    unittest.main()

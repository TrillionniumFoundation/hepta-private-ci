"""Adversarial saved-byte checks; no new actor or model execution."""

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from .observation_audit import FILES, _digest, audit


class ObservationAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)
        directory = (
            Path(__file__).resolve().parents[2]
            / "qualification/verify5-observation-20261111"
        )
        archive = directory / "ENGINEERING.zip"
        if archive.exists():
            raw = archive.read_bytes()
        else:
            parts = json.loads((directory / "ARCHIVE_PARTS.json").read_text())["parts"]
            raw = b"".join((directory / part["name"]).read_bytes() for part in parts)
        with zipfile.ZipFile(BytesIO(raw)) as source:
            for name in FILES:
                (self.path / name).write_bytes(source.read("observation-run/" + name))

    def mutate(self, name, change):
        path = self.path / name
        values = (
            [json.loads(s) for s in path.read_text().splitlines()]
            if name.endswith(".jsonl")
            else json.loads(path.read_text())
        )
        change(values)
        path.write_text(
            "\n".join(json.dumps(v) for v in values) + "\n"
            if name.endswith(".jsonl")
            else json.dumps(values)
        )

    def rejected(self):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            audit(self.path)

    def test_original_recomputes_without_mutating_saved_bytes(self):
        before = {p.name: p.read_bytes() for p in self.path.iterdir()}
        result = audit(self.path)
        self.assertEqual(result["status"], "CONSISTENT_COMPLETE_RECORDS")
        self.assertEqual(result["trajectories"], 132)
        self.assertEqual(
            (
                result["actor_executions"],
                result["model_fits"],
                result["model_predictions"],
            ),
            (0, 0, 0),
        )
        self.assertEqual({p.name: p.read_bytes() for p in self.path.iterdir()}, before)

    def test_missing_or_duplicate_trajectory_cannot_shrink_denominator(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                path = self.path / "trajectories.jsonl"
                original = path.read_bytes()
                self.mutate(
                    path.name,
                    lambda rows: (
                        rows.append(deepcopy(rows[0])) if duplicate else rows.pop()
                    ),
                )
                self.rejected()
                path.write_bytes(original)

    def test_late_or_missing_event_is_rejected(self):
        self.mutate(
            "events.jsonl",
            lambda rows: rows[1].update(
                available_monotonic_ns=rows[2]["available_monotonic_ns"] + 1
            ),
        )
        self.rejected()

    def test_join_requires_every_event_and_cost(self):
        self.mutate("events.jsonl", lambda rows: rows.pop(2))
        self.rejected()

    def test_false_bool_alias_and_unknown_label_are_rejected(self):
        for value in (0, None):
            with self.subTest(value=value):
                path = self.path / "trajectories.jsonl"
                original = path.read_bytes()
                self.mutate(
                    path.name, lambda rows: rows[0].update(terminal_error=value)
                )
                self.rejected()
                path.write_bytes(original)

    def test_cost_alias_negative_duplicate_and_failed_are_rejected(self):
        for update in (
            {"cpu_ns": True},
            {"wall_ns": -1},
            {"operation_id": "meter/2"},
            {"status": "failed"},
        ):
            with self.subTest(update=update):
                path = self.path / "costs.jsonl"
                original = path.read_bytes()
                self.mutate(path.name, lambda rows: rows[0].update(update))
                self.rejected()
                path.write_bytes(original)

    def test_prediction_model_and_feature_binding_are_checked(self):
        self.mutate(
            "events.jsonl",
            lambda rows: next(e for e in rows if e["kind"] == "frequency_prediction")[
                "value"
            ]["snapshot"].update(features=[0.0, 0.0, 0.0]),
        )
        self.rejected()

    def test_cost_cannot_move_to_another_policy(self):
        self.mutate(
            "costs.jsonl",
            lambda rows: next(c for c in rows if c["arm"] == "risk_triggered").update(
                arm="probe"
            ),
        )
        with self.assertRaisesRegex(ValueError, "cost policy binding"):
            audit(self.path)

    def test_consistent_prediction_rewrite_does_not_replace_model_arithmetic(self):
        events = [
            json.loads(s) for s in (self.path / "events.jsonl").read_text().splitlines()
        ]
        key = next(
            e["trajectory_id"] for e in events if e["kind"] == "frequency_prediction"
        )
        self.mutate(
            "events.jsonl",
            lambda rows: next(e for e in rows if e["kind"] == "frequency_prediction")[
                "value"
            ].update(probability=0.5),
        )
        self.mutate(
            "trajectories.jsonl",
            lambda rows: next(r for r in rows if r["trajectory_id"] == key)[
                "probabilities"
            ].update(readback=0.5),
        )
        with self.assertRaisesRegex(ValueError, "saved model cell arithmetic"):
            audit(self.path)

    def test_self_hashed_model_cannot_change_its_retained_fit_input(self):
        model_path = self.path / "MODEL.json"
        model = json.loads(model_path.read_text())
        model["training_label_count"] += 1
        identity = {k: v for k, v in model.items() if k != "model_sha256"}
        identity.update(version="verify-shadow-frequency-v2", prior=[1, 1])
        model["model_sha256"] = _digest(identity)
        model_path.write_text(json.dumps(model))
        self.mutate(
            "RESULT.json",
            lambda result: result.update(model_sha256=model["model_sha256"]),
        )
        with self.assertRaisesRegex(ValueError, "retained fit inputs"):
            audit(self.path)

    def test_terminal_receipt_tamper_is_rejected(self):
        self.mutate(
            "trajectories.jsonl",
            lambda rows: rows[0]["terminal_label"].update(evidence_sha256="0" * 64),
        )
        self.rejected()

    def test_report_arithmetic_and_diagnostics_are_recomputed(self):
        self.mutate(
            "RESULT.json",
            lambda result: result["arms"]["risk_triggered"].update(optional_checks=0),
        )
        self.rejected()

    def test_strict_json_and_incomplete_originals_fail_closed(self):
        path = self.path / "RESULT.json"
        original = path.read_bytes()
        for payload in ('{"duplicate":1,"duplicate":2}', '{"x":NaN}', '{"x":1e999}'):
            with self.subTest(payload=payload):
                path.write_text(payload)
                self.rejected()
        path.write_bytes(original)
        (self.path / "FAILURE.json").write_text("{}")
        self.rejected()


if __name__ == "__main__":
    unittest.main()

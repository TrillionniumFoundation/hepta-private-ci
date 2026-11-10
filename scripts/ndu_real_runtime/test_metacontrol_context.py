"""Same-value producer drift and original-receipt binding regressions."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from . import test_metacontrol as fixtures
from . import metacontrol_study as study
from .critic_context import CriticContext, CriticContextError, context_digest
from .metacontrol import fit_heads
from .metacontrol_checkpoint import load_heads, save_heads
from .test_metacontrol_study import fixture_rows


class MetacontrolContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MetacontrolTests()
        self.context = fixtures.CRITIC
        self.rows = self.fixture.rows("train")

    def test_same_values_under_new_dependencies_cannot_reuse_predictions(self):
        model = fit_heads(self.rows, context=self.context)
        model.calibrate(self.fixture.rows("cal"), context=self.context)
        before = model.identity()
        changes = [
            None,
            *[
                replace(self.context, **{name: "b" * 64})
                for name in CriticContext.__dataclass_fields__
            ],
        ]
        for changed in changes:
            with self.assertRaisesRegex(CriticContextError, "recalibration_required"):
                model.predict(self.fixture.state(), "WRITE_TEXT", context=changed)
            action, detail = model.choose(
                self.fixture.state(),
                context=changed,
                light_action="WRITE_TEXT",
                action_cost_bounds={"WRITE_TEXT": 1.0},
            )
            self.assertEqual(
                (action, detail["scores_relative_to_stop"]), ("STOP", {"STOP": 0.0})
            )
            self.assertTrue(detail["recalibration_required"])
            self.assertIn("recalibration_required", detail["reason"])
        self.assertEqual(model.identity(), before)
        with self.assertRaises(ValueError):
            model.choose(SimpleNamespace(legal_actions=("WRITE_TEXT",)), context=None)
        model._context = None
        self.assertTrue(
            model.choose(self.fixture.state(), context=self.context)[1][
                "recalibration_required"
            ]
        )
        del model._context
        with self.assertRaisesRegex(CriticContextError, "recalibration_required"):
            model.predict(self.fixture.state(), "WRITE_TEXT", context=self.context)
        self.assertEqual(
            model.choose(self.fixture.state(), context=self.context)[0], "STOP"
        )

    def test_fresh_refit_and_calibration_restore_the_new_context(self):
        changed = replace(self.context, encoder_sha256="b" * 64)
        # These are newly declared manufactured observations, not relabelled
        # historical evidence or a claim that new native data were collected.
        phases = {
            phase: [
                replace(
                    row,
                    context=changed,
                    evidence_context_sha256=context_digest(changed),
                )
                for row in self.fixture.rows("new-" + phase)
            ]
            for phase in ("train", "calibration")
        }
        model = fit_heads(phases["train"], context=changed)
        model.calibrate(phases["calibration"], context=changed)
        selected, detail = model.choose(
            self.fixture.state(),
            mode="conditional",
            context=changed,
            action_cost_bounds={"WRITE_TEXT": 1.0},
        )
        self.assertEqual(
            (selected, detail["fallback"], detail["recalibration_required"]),
            ("WRITE_TEXT", False, False),
        )
        self.assertEqual(
            model.calibration["critic_context_sha256"], context_digest(changed)
        )
        with self.assertRaises(CriticContextError):
            model.predict(self.fixture.state(), "WRITE_TEXT", context=self.context)

    def test_mixed_contexts_and_relabelled_evidence_refuse_fit_and_calibration(self):
        changed = replace(self.context, answer_sha256="b" * 64)
        with self.assertRaisesRegex(CriticContextError, "evidence context"):
            replace(self.rows[0], context=changed)
        mixed = [
            replace(
                self.rows[0],
                context=changed,
                evidence_context_sha256=context_digest(changed),
            ),
            *self.rows[1:],
        ]
        for rows, context in ((self.rows, None), (mixed, self.context)):
            with self.assertRaises(CriticContextError):
                fit_heads(rows, context=context)
        model = fit_heads(self.rows, context=self.context)
        calibration = self.fixture.rows("cal")
        calibration[0] = replace(
            calibration[0],
            context=changed,
            evidence_context_sha256=context_digest(changed),
        )
        before = model.identity()
        with self.assertRaises(CriticContextError):
            model.calibrate(calibration, context=self.context)
        self.assertEqual(model.identity(), before)
        self.assertIsNone(model.calibration)
        model.calibrate(self.fixture.rows("cal"), context=self.context)
        with self.assertRaises(CriticContextError):
            model.diagnostics(calibration, context=self.context)

    def test_cold_load_requires_current_context_and_rejects_legacy_or_rebound_receipts(
        self,
    ):
        model = fit_heads(self.rows, context=self.context)
        model.calibrate(self.fixture.rows("cal"), context=self.context)
        changed = replace(self.context, generator_sha256="b" * 64)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "head.json"
            with self.assertRaises(CriticContextError):
                save_heads(model, path, context=changed)
            self.assertFalse(path.exists())
            pin = save_heads(model, path, context=self.context)
            restored = load_heads(path.read_bytes(), pin, context=self.context)
            self.assertEqual(restored.snapshot(), model.snapshot())
            for context in (None, changed):
                with self.assertRaises(CriticContextError):
                    load_heads(path.read_bytes(), pin, context=context)
        legacy = model.snapshot()
        del legacy["context"]
        del legacy["critic_context_sha256"]
        rebound = model.snapshot()
        rebound["calibration"]["critic_context_sha256"] = context_digest(changed)
        for snapshot in (legacy, rebound):
            raw = json.dumps(snapshot).encode()
            with self.assertRaises(ValueError):
                load_heads(raw, hashlib.sha256(raw).hexdigest(), context=self.context)

    def test_study_checks_original_profile_pins_and_rejects_legacy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            for field in (
                "critic_context_sha256",
                "evaluator_sha256",
                "utility_profile_sha256",
                "tariff_sha256",
                "legacy",
            ):
                rows = fixture_rows("fixture", 2)
                if field == "legacy":
                    rows[0]["schema"] = "ndu.real.metacontrol-observation.v1"
                else:
                    rows[0]["evidence"][field] = "b" * 64
                raw = b"".join((json.dumps(row) + "\n").encode() for row in rows)
                path.write_bytes(raw)
                with self.assertRaisesRegex(
                    CriticContextError, "recalibration_required"
                ):
                    study.read_input(
                        path,
                        hashlib.sha256(raw).hexdigest(),
                        allow_fixtures=True,
                        context=self.context,
                    )


if __name__ == "__main__":
    unittest.main()

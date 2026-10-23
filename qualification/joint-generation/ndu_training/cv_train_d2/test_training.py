"""Hand-input single-step math, paired streams and reference-cost isolation."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from independent.accounting import WorkLedger
from independent.native_adam import NativeAdam
from model import JointModel
from ndu_training.cv_train_d2.budget import ROOT, plan, quote, update_quote
from ndu_training.cv_train_d2.driver import Meter, train_round
from ndu_training.cv_train_d2.optimizer import AnchorAdam
from ndu_training.diagnostics import gradient
from ndu_training.estimators import WeightedObjective
from ndu_training.mechanism_readout.anchor_cv import correct
from ndu_training.reinfer_d1.kernels import Reference, flat


class TrainingTests(unittest.TestCase):
    def fixture(self, arm, cv, weighted):
        rng = np.random.default_rng(8102)
        full = rng.normal(size=(64, 202)) * 0.1
        pixels = full[:, :192].reshape(64, 4, 2, 4, 2, 3)
        low = np.concatenate(
            (
                pixels.mean(axis=(2, 4))
                .repeat(2, axis=1)
                .repeat(2, axis=2)
                .reshape(64, 192),
                full[:, 192:],
            ),
            axis=1,
        )
        labels = np.arange(64) % 12
        base = JointModel(202, 12, 192, hidden=32, seed=8103)
        ref = Reference(
            base,
            np.concatenate((full, low)),
            np.tile(labels, 2),
            WorkLedger("hand-reference"),
        )
        model = base.clone()
        library = ROOT / plan()["original_run"] / "build/libjoint.so"
        ledger = WorkLedger("hand-step")
        optimizer = AnchorAdam(NativeAdam(model, library), ledger, ref if cv else None)
        objective = WeightedObjective(arm, model, ledger=ledger, optimizer=optimizer)
        draw = (
            rng.integers(64, size=64),
            rng.uniform(0.5, 1.5, size=64) if weighted else None,
            rng.random(64) < 0.5,
        )
        state = {
            "model": model,
            "objective": objective,
            "optimizer": optimizer,
            "steps": 0,
            "stream": hashlib.sha256(),
            "prefix128": None,
            "loss_trace": [],
            "pool": [draw],
        }
        return (
            base,
            ref,
            state,
            ledger,
            {"full": full, "low": low, "labels": labels},
            draw,
        )

    def test_single_step_matches_dense_corrected_gradient_and_original_adam(self):
        for arm in ("A", "N"):
            for cv in (False, True):
                for weighted in (False, True):
                    with self.subTest(arm=arm, cv=cv, weighted=weighted):
                        base, ref, state, ledger, arrays, (idx, weights, full) = (
                            self.fixture(arm, cv, weighted)
                        )
                        expected = base.clone()
                        obj = WeightedObjective(arm, expected)
                        values = gradient(
                            expected,
                            np.where(
                                full[:, None], arrays["full"][idx], arrays["low"][idx]
                            ),
                            arrays["labels"][idx],
                            obj,
                            weights,
                            WorkLedger("hand-expected"),
                        )
                        grads, offset = {}, 0
                        for key in ref.mean:
                            shape = expected.params[key].shape
                            size = expected.params[key].size
                            grads[key] = values[offset : offset + size].reshape(shape)
                            offset += size
                        if cv:
                            batch = ref.pull(
                                idx + np.where(full, 0, 64),
                                weights,
                                WorkLedger("hand-pull"),
                                "hand",
                            )
                            grads = correct(grads, ref.mean, batch)
                        expected.apply_gradients(grads, 0.003)
                        group = arm + ("-CV" if cv else "-plain")
                        kind = "stratified" if weighted else "iid"
                        before = ledger.consumed_units
                        with tempfile.TemporaryDirectory() as tmp:
                            train_round(
                                group, {f"{kind}-11": state}, ledger, arrays, Path(tmp)
                            )
                        self.assertEqual(
                            ledger.consumed_units - before,
                            update_quote(group, kind, int((~full).sum()), True),
                        )
                        for key in expected.params:
                            np.testing.assert_allclose(
                                state["model"].params[key],
                                expected.params[key],
                                rtol=1e-12,
                                atol=1e-13,
                            )
                        for key in ref.mean:
                            for actual, wanted in zip(
                                state["model"]._moments[key][:2],
                                expected._moments[key][:2],
                            ):
                                np.testing.assert_allclose(
                                    actual, wanted, rtol=1e-12, atol=1e-14
                                )
                        self.assertEqual(state["steps"], 1)
                        self.assertEqual(state["model"].updates, 1)

    def test_complete_step_admission_precedes_mutation(self):
        base, ref, state, _, arrays, draw = self.fixture("N", True, True)
        exact = update_quote("N-CV", "stratified", int((~draw[2]).sum()), True)
        insufficient = WorkLedger("hand-insufficient", exact - 1)
        state["optimizer"].ledger = insufficient
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "before parameter mutation"):
                train_round(
                    "N-CV", {"stratified-11": state}, insufficient, arrays, Path(tmp)
                )
        self.assertEqual(state["model"].updates, 0)
        self.assertEqual(state["steps"], 0)
        np.testing.assert_array_equal(flat(state["model"].params), flat(base.params))
        self.assertEqual(insufficient.consumed_units, 0)

    def test_only_CV_recipients_pay_shared_reference_load(self):
        clock = [0.0]
        groups = ("A-plain", "N-plain", "A-CV", "N-CV")
        with patch("ndu_training.cv_train_d2.driver.cpu", side_effect=lambda: clock[0]):
            meter = Meter({group: 0.0 for group in groups})
            with meter.phase(("A-CV", "N-CV"), "reference_cache_load"):
                clock[0] = 1.0
            self.assertEqual(
                meter.totals(),
                {"A-plain": 0.0, "N-plain": 0.0, "A-CV": 1.0, "N-CV": 1.0},
            )
            clock[0] += 0.1
            totals = meter.totals()
            for group in groups:
                self.assertAlmostEqual(
                    totals[group], 1.1 if group.endswith("CV") else 0.1
                )

    def test_forecast_attributes_reference_only_to_CV_and_keeps_all_opportunities(self):
        q = quote()
        self.assertTrue(q["ready_for_review"])
        self.assertEqual(q["service_requests_each_group"], 18432)
        self.assertEqual(q["service_requests_total"], 73728)
        for arm in ("A", "N"):
            plain, cv = (q["groups"][f"{arm}-{e}"] for e in ("plain", "CV"))
            self.assertEqual(
                cv["historical_units_fully_attributed"]
                - plain["historical_units_fully_attributed"],
                q["history"]["reference_units"],
            )
            self.assertGreater(
                plain["possible_rounds_by_operator_envelope"],
                cv["possible_rounds_by_operator_envelope"],
            )


if __name__ == "__main__":
    unittest.main()

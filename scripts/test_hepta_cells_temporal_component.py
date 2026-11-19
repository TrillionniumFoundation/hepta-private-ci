"""Integration through the common durable owner, real weights and reset adoption."""

from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from hepta_cells.bundle import Bundle, OPTIONAL, REQUIRED, validate_local_update
from hepta_cells.lifecycle import (
    Budget,
    CellError,
    CellOwner,
    Partition,
    Qualification,
    StepContext,
)
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


class TemporalComponentTests(unittest.TestCase):
    def setUp(self):
        self.kernel = TemporalKernel("predictor", TemporalConfig(3, 2, 2, hidden_dim=6))
        self.parts = {
            name: fingerprint("fixture-artifact-" + name) for name in REQUIRED
        }
        self.parts.update({name: None for name in OPTIONAL})
        self.parts.update(
            base=self.kernel.kernel_sha256,
            heads=self.kernel.heads_sha256,
            composition=self.kernel.config.sha256,
        )
        self.bundle = Bundle("temporal-test", 1, self.parts)
        self.component = TemporalComponent(self.kernel, self.bundle, "run-1")
        self.partition = Partition("research", "agent", "predictor", "run-1")

    def test_durable_retry_and_trained_candidate_adoption_reset(self):
        admitted_evaluation = fingerprint("fixture-only-evaluation")
        with tempfile.TemporaryDirectory() as tmp:
            owner = CellOwner(
                Path(tmp) / "cells.sqlite",
                qualify=lambda q: q.evaluation_digest == admitted_evaluation,
            )
            try:
                owner.create(self.partition, self.component)
                payload = {
                    "operation": "observe",
                    "cursor": 0,
                    "observation": [1, 0, -1],
                }
                with patch.object(
                    self.kernel, "observe", wraps=self.kernel.observe
                ) as observed:
                    first = owner.step(
                        self.partition, self.component, "observation-0", payload
                    )
                    repeated = owner.step(
                        self.partition, self.component, "observation-0", payload
                    )
                    self.assertEqual(first, repeated)
                    self.assertEqual(observed.call_count, 1)
                predicted = owner.step(
                    self.partition,
                    self.component,
                    "prediction-1",
                    {"operation": "predict", "action": [0, 1]},
                )
                state_before = owner.checkpoint(self.partition)["state"]
                self.assertEqual(state_before["cursor"], 1)
                self.assertEqual(predicted["output"]["cursor"], 1)
                self.assertEqual(first["work_units"], self.kernel.parameter_count)
                self.assertIsNone(predicted["output"]["cost"]["energy_joules"])

                candidate, receipt = self.kernel.train_candidate(
                    np.array([[[1, 0, -1]], [[-1, 0, 1]]]),
                    np.zeros((2, 2)),
                    np.eye(2, dtype=bool),
                    updates=3,
                )
                changed = {
                    **self.parts,
                    "base": candidate.kernel_sha256,
                    "heads": candidate.heads_sha256,
                }
                successor = self.bundle.successor(
                    "temporal-trained",
                    changed,
                    receipt["data_sha256"],
                    fingerprint("adam-step-rule"),
                    admitted_evaluation,
                )
                validate_local_update(
                    "stateful_temporal", self.bundle, successor, "kernel_and_heads"
                )
                component = TemporalComponent(candidate, successor, "run-1")
                qualification = Qualification(
                    self.component.identity.digest,
                    component.identity.digest,
                    admitted_evaluation,
                )
                adopted = owner.adopt(self.partition, component, qualification)
                self.assertEqual(adopted["state"], candidate.initial_state("run-1"))
                self.assertNotEqual(
                    adopted["state"]["weights_sha256"], state_before["weights_sha256"]
                )
                with self.assertRaises(CellError):
                    owner.step(
                        self.partition, self.component, "obsolete-source", payload
                    )
                current = owner.step(
                    self.partition, component, "new-observation-0", payload
                )
                self.assertEqual(current["output"]["cursor"], 1)
                self.assertEqual(current["bundle_digest"], successor.digest())
                restored = owner.rollback(
                    self.partition, self.component, component.identity.digest
                )
                self.assertEqual(restored["state"], self.kernel.initial_state("run-1"))
            finally:
                owner.close()

    def test_budget_scope_and_bundle_rejections_happen_before_kernel_work(self):
        context = StepContext(
            self.partition, "request", self.component.identity, None, Budget()
        )
        state = self.component.initial_state()
        payload = {"operation": "observe", "cursor": 0, "observation": [1, 0, -1]}
        for invalid in (
            replace(
                context, budget=Budget(max_work_units=self.kernel.parameter_count - 1)
            ),
            replace(context, partition=replace(self.partition, cell_id="foreign-cell")),
            replace(context, partition=replace(self.partition, run_id="foreign-run")),
        ):
            with (
                self.subTest(context=invalid),
                patch.object(
                    self.kernel, "observe", wraps=self.kernel.observe
                ) as observed,
            ):
                with self.assertRaises(CellError):
                    self.component.step(payload, state, invalid)
                observed.assert_not_called()
        for part in ("base", "heads", "composition"):
            altered = replace(
                self.bundle,
                components={**self.parts, part: fingerprint("wrong-artifact")},
            )
            with self.subTest(part=part), self.assertRaises(CellError):
                TemporalComponent(self.kernel, altered, "run-1")


if __name__ == "__main__":
    unittest.main()

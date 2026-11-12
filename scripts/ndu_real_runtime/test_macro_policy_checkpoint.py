"""Manufactured cold-state regressions, with no model or task efficacy claim."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from .critic_context import CriticContext, CriticContextError
from .macro_policy_checkpoint import read_checkpoint


class MacroCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(
            Path(__file__).with_name("macro_checkpoint_fixture.json").read_bytes()
        )
        self.context = CriticContext.from_wire(self.data["context"])

    def read(self, data=None, **changes):
        value = self.data if data is None else data
        raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
        options = {
            "context": self.context,
            "expected_action_sha256": self.context.action_sha256,
            "expected_source_sha256": "a" * 64,
        }
        return read_checkpoint(
            raw, hashlib.sha256(raw).hexdigest(), **(options | changes)
        )

    def test_frozen_fixture_roundtrip_and_external_digest(self):
        self.assertEqual(self.read(), self.data)
        with self.assertRaises(ValueError):
            read_checkpoint(
                b"{}",
                "0" * 64,
                context=self.context,
                expected_action_sha256=self.context.action_sha256,
                expected_source_sha256="a" * 64,
            )

    def test_changed_context_source_or_macro_semantics_rejected(self):
        changed = {**self.data["context"], "answer_sha256": "b" * 64}
        with self.assertRaises(CriticContextError):
            self.read(context=CriticContext.from_wire(changed))
        for key in ("expected_action_sha256", "expected_source_sha256"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.read(**{key: "b" * 64})

    def test_nonfinite_and_wrong_width_parameters_rejected(self):
        for name in ("center", "value", "minimum", "maximum", "scale"):
            data = deepcopy(self.data)
            data[name] = data[name][:-1]
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.read(data)
        data = deepcopy(self.data)
        data["scale"][0] = 0
        with self.assertRaises(ValueError):
            self.read(data)

    def test_source_and_denominator_contradictions_rejected(self):
        for mutation in (
            lambda d: d.update(calibration_sources=d["fit_sources"]),
            lambda d: d["counts"].update(fit_known_value=d["counts"]["fit"] + 1),
            lambda d: d["counts"].update(calibration_known_value=0),
            lambda d: (
                d.update(full_cost_observed=False, tuned_fixed="STOP"),
                d["counts"].update(calibration_known_value=9),
            ),
        ):
            data = deepcopy(self.data)
            mutation(data)
            with self.subTest(data=data["counts"]), self.assertRaises(ValueError):
                self.read(data)

    def test_unobserved_probability_cannot_become_success(self):
        data = deepcopy(self.data)
        data["probability_heads"]["acquired"]["constant"] = 0.99
        with self.assertRaises(ValueError):
            self.read(data)

    def test_invalid_calibration_rank_and_future_fields_rejected(self):
        for mutation in (
            lambda d: d["calibration"]["unconditional"].update(rank=999),
            lambda d: d.update(future_reference="answer"),
            lambda d: d["light"].update({"[false,false,99]": 1.0}),
        ):
            data = deepcopy(self.data)
            mutation(data)
            with self.subTest(), self.assertRaises(ValueError):
                self.read(data)


if __name__ == "__main__":
    unittest.main()

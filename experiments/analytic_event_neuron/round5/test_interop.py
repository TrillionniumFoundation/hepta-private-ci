"""Small conformance checks, not new efficacy or calibration evidence."""

from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import unittest

import numpy as np

from ..round4 import runtime_codec, runtime_law
from .interop import (
    BoundarySide, BrownianPath, CellParameters, CycleObservation, EventObservation,
    FirstPassageForecast, TerminalForecast, decode_communication, forecast,
    new_regenerative_cell, observe_cycle, restore_regenerative_cell,
)


class InteropTests(unittest.TestCase):
    def test_terminal_and_first_passage_are_different_events(self):
        law = runtime_law.make_law([1], [1], [1])
        terminal = forecast(TerminalForecast(law, 0, 1, 0, 2))
        path = BrownianPath(1, 0, 1, 0, BoundarySide.LOWER)
        hitting = forecast(FirstPassageForecast(path, 0, 1))
        gaussian_tail = .5 * math.erfc(1 / math.sqrt(2))
        self.assertAlmostEqual(terminal["physical_probabilities"][0], gaussian_tail, places=14)
        self.assertAlmostEqual(hitting["hit_probability"], 2 * gaussian_tail, places=14)
        self.assertEqual((terminal["semantics"], hitting["semantics"]),
                         ("terminal_state", "first_passage_cycle"))

    def test_two_one_sided_hits_are_not_a_call_put_partition(self):
        lower = BrownianPath(0, 0, 1, -.1, BoundarySide.LOWER)
        upper = BrownianPath(0, 0, 1, .1, BoundarySide.UPPER)
        left, right = [forecast(FirstPassageForecast(p, 0, 1)) for p in (lower, upper)]
        expected = math.erfc(.1 / math.sqrt(2))
        self.assertAlmostEqual(left["hit_probability"], expected, places=14)
        self.assertAlmostEqual(right["hit_probability"], expected, places=14)
        self.assertGreater(left["hit_probability"] + right["hit_probability"], 1.8)
        for value in (left, right):
            self.assertAlmostEqual(value["hit_probability"] + value["survival_probability"], 1)
        reflected = [forecast(FirstPassageForecast(p, 0, 1))["hit_probability"]
                     for p in (replace(lower, drift=.3), replace(upper, drift=-.3))]
        self.assertAlmostEqual(*reflected, places=14)

    def test_no_marginal_or_communication_conversion(self):
        law = runtime_law.make_law([.5, .5], [-1, 1], [.4, .4])
        for request in (law, FirstPassageForecast(law, 0, 1),
                        {"semantics": "signed_terminal_law_communication", "law": law}):
            with self.assertRaises(TypeError):
                forecast(request)
        with self.assertRaises(TypeError):
            new_regenerative_cell(law, initial_level=0, seed=1)
        with self.assertRaises(TypeError):
            forecast(FirstPassageForecast(BrownianPath(1, 0, 1, 0, "lower"), 0, 1))

    def test_boundary_atom_zero_horizon_and_discount_are_explicit(self):
        query = FirstPassageForecast(BrownianPath(1, 0, 1, 0, BoundarySide.LOWER), 2, 0)
        before = forecast(query)
        atom = forecast(replace(query, path=replace(query.path, initial_level=0)))
        self.assertEqual((before["hit_probability"], before["survival_probability"], before["time"]),
                         (0., 1., 2.))
        self.assertEqual((atom["hit_probability"], atom["survival_probability"],
                          atom["hit_density_per_time"], atom["discounted_hit_weight"]), (1., 0., 0., 1.))
        discounted = forecast(replace(query, horizon=1, discount=.7))
        self.assertGreater(discounted["discounted_hit_weight"], 0)
        self.assertLess(discounted["discounted_hit_weight"], discounted["hit_probability"])
        with self.assertRaises(ValueError):
            forecast(replace(query, condition_time=-1))

    def test_missing_retains_event_atom_survival_conditions_it_away(self):
        query = CycleObservation((.25, 1., 2.), (.2, .5, .3), 0., -.1, .8, 0, .4,
                                 EventObservation.MISSING)
        missing = observe_cycle(query)
        survived = observe_cycle(replace(query, observation=EventObservation.OBSERVED_SURVIVAL))
        absorbed = observe_cycle(replace(query, observation=EventObservation.OBSERVED_EVENT))
        self.assertGreater(missing["event_mass"], 0)
        self.assertAlmostEqual(sum(missing["alive_mass"]) + missing["event_mass"], 1)
        self.assertEqual((missing["log_likelihood"], survived["event_mass"]), (0., 0.))
        np.testing.assert_allclose(survived["alive_mass"],
                                   np.asarray(missing["alive_mass"]) / sum(missing["alive_mass"]),
                                   rtol=1e-13, atol=1e-15)
        self.assertEqual((absorbed["alive_mass"], absorbed["event_mass"]), ([0., 0., 0.], 1.))
        later = observe_cycle(replace(query, live_mass=tuple(missing["alive_mass"]),
                                      prior_event_mass=missing["event_mass"], condition_time=.4))
        self.assertGreater(later["event_mass"], missing["event_mass"])
        self.assertAlmostEqual(sum(later["alive_mass"]) + later["event_mass"], 1)
        with self.assertRaises(ValueError):
            observe_cycle(replace(query, sensor=(.5, .1)))

    def test_actual_cell_refractory_multiple_events_and_checkpoint_replay(self):
        parameters = CellParameters(-3., (.2, -.1), .2, 0., .3, .06)
        cell = new_regenerative_cell(parameters, initial_level=0, seed=11)
        immediate = cell.advance(0, (0, 0))
        self.assertEqual(immediate["events"], [{"time": 0., "kind": "first_passage", "ordinal": 1}])
        checkpoint = json.loads(json.dumps(cell.checkpoint()))
        restored = restore_regenerative_cell(checkpoint, expected_model_digest=parameters.digest())
        for duration in (.03, .4, .2):
            actual = cell.advance(duration, (.1, -.2))
            replay = restored.advance(duration, (.1, -.2))
            self.assertEqual(actual, replay)
            if duration == .03:
                self.assertEqual(actual["events"], [])
                self.assertAlmostEqual(actual["refractory_remaining"], .03)
            if duration == .4:
                self.assertGreaterEqual(len(actual["events"]), 2)
        self.assertEqual(cell.checkpoint(), restored.checkpoint())
        self.assertGreater(cell.rng.counter, checkpoint["payload"]["random_counter"])
        count = cell.event_count
        cell.repair()
        self.assertEqual((cell.event_count, cell.level, cell.refractory_remaining), (count, .3, .06))

    def test_checkpoint_rejects_other_model_and_other_state_schema(self):
        parameters = CellParameters(-.5, (0., 0.), .3, 0., 1.)
        cell = new_regenerative_cell(parameters, initial_level=1, seed=7)
        for checkpoint, expected in ((cell.checkpoint(), "0" * 64),
                                     (runtime_codec.Decoder("event").snapshot(), parameters.digest())):
            with self.assertRaises(ValueError):
                restore_regenerative_cell(checkpoint, expected_model_digest=expected)

    def test_signed_transport_preserves_observation_kind_even_with_zero_delta(self):
        encoder, decoder = runtime_codec.Encoder("event"), runtime_codec.Decoder("event")
        law = runtime_law.make_law([1], [1], [1])
        outputs = [decode_communication(decoder, encoder.encode(law, seq, seq - 1, kind))
                   for seq, kind in enumerate(("observed", "missing", "observed"), 1)]
        self.assertEqual([(x["packet_kind"], x["zero_delta"]) for x in outputs],
                         [("observed", False), ("missing", True), ("observed", True)])
        self.assertEqual(outputs[1]["law"], outputs[2]["law"])
        changed = runtime_law.make_law([1], [-1], [.5])
        negative = decode_communication(decoder, encoder.encode(changed, 4, 3, "observed"))
        self.assertEqual(negative["law"]["means"], [-1.])
        self.assertFalse(negative["zero_delta"])
        with self.assertRaises(TypeError):
            forecast(negative)

    def test_reused_sources_match_recorded_pinned_blobs(self):
        here = Path(__file__).resolve().parent
        dependencies = json.loads((here / "DEPENDENCIES.json").read_text())
        root = here.parents[2]
        for item in dependencies["files"]:
            content = (root / item["local_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), item["sha256"], item["local_path"])
            blob = b"blob " + str(len(content)).encode() + b"\0" + content
            self.assertEqual(hashlib.sha1(blob).hexdigest(), item["git_blob_sha1"], item["local_path"])


if __name__ == "__main__":
    unittest.main()

"""Four-slot coverage, real two-output binding, and fail-closed ingress tests."""

from dataclasses import replace
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from .data import Observation
from .joint_contract import EventSpan, JointState, MediaClock, Modality, ModalitySlot
from .joint_contract import bind_v6_output, latent_digest, require_v6_capabilities
from .joint_contract import PROFILE
from .neural import NeuralPortfolio, NeuralSnapshot
from .observer import METRIC, read_bundle, write_bundle
from .plan_training import ControlledSnapshot, PlanHead
from .run import digest, rollout, run
from .reporting import summarize
from . import test_reporting as reporting_fixtures


class JointContractTests(unittest.TestCase):
    def setUp(self):
        self.clock = MediaClock("clock:case", "presentation", 1000, 100, 2)
        self.event = EventSpan("event:case", self.clock.clock_id, 10, 60)
        self.slots = tuple(
            ModalitySlot(modality, "complete", "a" * 64, "b" * 64, (self.event,))
            if modality in (Modality.TEXT, Modality.IMAGE)
            else ModalitySlot(modality, "unsupported", None, None, ())
            for modality in Modality)
        self.state = JointState("c" * 64, "d" * 64, "e" * 64,
                                (Modality.TEXT, Modality.IMAGE), self.clock,
                                (self.event,), self.slots)

    def test_current_pair_passes_and_all_four_slots_remain_explicit(self):
        self.state.validate(3)
        self.assertEqual(len(self.state.slots), 4)
        for slot in self.state.slots[2:]:
            self.assertEqual((slot.status, slot.latent_sha256, slot.output_sha256, slot.anchors),
                             ("unsupported", None, None, ()))
        required = require_v6_capabilities(["image", "text"])
        self.assertEqual(digest({"metric": METRIC, "requirements": required}),
                         digest({"metric": METRIC, "requirements": ["text", "image"]}))

    def test_unimplemented_unknown_duplicate_and_missing_requirements_reject(self):
        for values in (["text", "image", "audio", "video"], ["text", "audio"]):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "Unimplemented"):
                require_v6_capabilities(values)
        for values in (None, [], "text", ["text", "text"], ["text", "sound"], ["image"]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                require_v6_capabilities(values)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            replace(self.state, required=tuple(Modality)).validate(15)

    def test_exact_mask_complete_slots_and_event_coverage_are_required(self):
        for mask in (0, 1, 7, 15, True):
            with self.subTest(mask=mask), self.assertRaisesRegex(ValueError, "mask"):
                self.state.validate(mask)
        pending = replace(self.slots[0], status="pending", output_sha256=None, anchors=())
        partial = replace(self.state, slots=(pending, *self.slots[1:]))
        partial.validate(3, complete=False)
        with self.assertRaisesRegex(ValueError, "Pending"):
            partial.validate(3)
        for bad in (replace(self.slots[0], anchors=()),
                    replace(self.slots[0], anchors=(self.event, self.event))):
            with self.assertRaisesRegex(ValueError, "coverage"):
                replace(self.state, slots=(bad, *self.slots[1:])).validate(3)
        with self.assertRaisesRegex(ValueError, "four ordered"):
            replace(self.state, slots=self.slots[:2]).validate(3)
        with self.assertRaisesRegex(ValueError, "fabricated"):
            audio = replace(self.slots[2], latent_sha256="f" * 64)
            replace(self.state, slots=(*self.slots[:2], audio, self.slots[3])).validate(3)

    def test_shared_clock_bounds_and_tolerance_are_enforced(self):
        for delta in (-2, 2):
            aligned = replace(self.event, start_tick=10 + delta, end_tick=60 + delta)
            text = replace(self.slots[0], anchors=(aligned,))
            replace(self.state, slots=(text, *self.slots[1:])).validate(3)
        bad_anchors = (replace(self.event, start_tick=13),
                       replace(self.event, clock_id="other-clock"),
                       replace(self.event, start_tick=-1),
                       replace(self.event, end_tick=101),
                       replace(self.event, end_tick=10),
                       replace(self.event, start_tick=10.0))
        for anchor in bad_anchors:
            with self.subTest(anchor=anchor), self.assertRaises(ValueError):
                text = replace(self.slots[0], anchors=(anchor,))
                replace(self.state, slots=(text, *self.slots[1:])).validate(3)
        for clock in (replace(self.clock, ticks_per_second=0),
                      replace(self.clock, max_skew_ticks=101),
                      replace(self.clock, basis="logical_event")):
            with self.subTest(clock=clock), self.assertRaises(ValueError):
                replace(self.state, clock=clock).validate(3)

    def test_all_four_request_fails_before_source_or_dataset_preparation(self):
        config = {"hard_output_modalities": [modality.value for modality in Modality]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with patch("experiments.multimodal_output_portfolio.v6.run.source_identity") as source, \
                 patch("experiments.multimodal_output_portfolio.v6.run.load_corpus") as load:
                with self.assertRaisesRegex(ValueError, "Unimplemented required decoder"):
                    run(config, Path(directory) / "cache", output)
                source.assert_not_called()
                load.assert_not_called()
            status = json.loads((output / "status.json").read_text())
            self.assertEqual((status["state"], status["rows"]), ("failed", 0))
            self.assertEqual(json.loads((output / "requested-config.json").read_text()), config)

    def test_real_decoder_state_and_reopened_outputs_bind_without_fake_media(self):
        torch.set_num_threads(2)
        torch.manual_seed(59)
        snapshot = ControlledSnapshot(NeuralSnapshot(NeuralPortfolio(hidden=16)), PlanHead(16))
        observation = Observation(torch.zeros(1, 1, 28, 56), torch.ones(1, 1, 28, 56),
                                  torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]))
        forecast = SimpleNamespace(backend=lambda *_: SimpleNamespace())
        pixels, caption, trace = rollout(snapshot, forecast, observation, "fixed", 64,
                                        {"inference_horizon": 0, "control": {}}, "case", 59)
        with tempfile.TemporaryDirectory() as directory:
            paths = write_bundle(Path(directory) / "raw", caption, pixels)
            _, _, hashes = read_bundle(paths)
            record = bind_v6_output(["text", "image"], snapshot.fingerprint,
                                    trace["final_state_sha256"], trace["latent_sha256"], hashes, "case")
        self.assertEqual(record["required_mask"], 3)
        self.assertEqual(record["clock"]["basis"], "logical_event")
        self.assertIsNone(record["clock"]["ticks_per_second"])
        for slot in record["slots"][:2]:
            self.assertEqual(slot["output_sha256"], hashes[slot["modality"]])
        for outputs in ({"image": hashes["image"]}, {**hashes, "audio": "a" * 64}):
            with self.assertRaisesRegex(ValueError, "set differs"):
                bind_v6_output(["text", "image"], snapshot.fingerprint,
                               trace["final_state_sha256"], trace["latent_sha256"], outputs, "case")
        self.assertNotEqual(latent_digest(torch.zeros(1)), latent_digest(torch.ones(1)))
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            latent_digest(torch.tensor([float("nan")]))
        json.dumps(record, allow_nan=False)

    def test_reporter_rejects_resealed_contract_drift_and_preserves_legacy_scope(self):
        fixture = reporting_fixtures.ReportingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        legacy = {**fixture.protocol, "hard_output_modalities": ["text", "image"]}
        summarize(fixture.rows, legacy)  # Historical runs did not declare this profile.
        protocol = {**legacy, "joint_contract": deepcopy(PROFILE)}
        rows = deepcopy(fixture.rows)
        for row in rows:
            row.update(final_state_sha256="d" * 64,
                       latent_sha256={"shared": "e" * 64, "text": "a" * 64, "image": "b" * 64})
            row["joint_output_contract"] = bind_v6_output(
                ["text", "image"], row["snapshot_sha256"], row["final_state_sha256"],
                row["latent_sha256"], row["output_hashes"], row["case_id"])
            reporting_fixtures.seal(row)
        persisted = json.loads(json.dumps(rows))
        self.assertEqual(summarize(persisted, protocol)["rows"], len(rows))
        for field, value in (("required_mask", 15), ("snapshot_sha256", "f" * 64)):
            changed = deepcopy(rows)
            changed[0]["joint_output_contract"][field] = value
            reporting_fixtures.seal(changed[0])
            with self.assertRaisesRegex(ValueError, "changed joint"):
                summarize(changed, protocol)
        changed = deepcopy(rows)
        del changed[0]["joint_output_contract"]
        reporting_fixtures.seal(changed[0])
        with self.assertRaisesRegex(ValueError, "Missing or changed"):
            summarize(changed, protocol)
        with self.assertRaisesRegex(ValueError, "Unannounced"):
            summarize(rows, legacy)
        bad = {**protocol, "joint_contract": {**PROFILE, "physical_media_sync_observed": True}}
        with self.assertRaisesRegex(ValueError, "profile"):
            summarize(rows, bad)
        with self.assertRaisesRegex(ValueError, "Unimplemented"):
            summarize(rows, {**protocol, "hard_output_modalities": list(Modality)})


if __name__ == "__main__":
    unittest.main()

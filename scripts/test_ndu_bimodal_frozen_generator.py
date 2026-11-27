"""Real Torch checks of private learning, shared freeze and temporal kernels."""

from pathlib import Path
import json
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from scripts.joint_generation_v4_model import JointGeneratorV4
from scripts.ndu_bimodal.frozen_generator import (
    PRIVATE_PREFIXES,
    deliver,
    forward_graph,
    load_with_kernel,
    private_training_parameters,
    shared_digest,
)
from scripts.ndu_bimodal.frozen_training import (
    BaseCapabilityError,
    _fit,
    run_frozen_study,
)
from scripts.ndu_bimodal.generator_training import colour_card
from scripts.ndu_bimodal.native import encode_input, load_generator
from scripts.ndu_bimodal.semantic_eval import PROMPT, expected_caption


class FrozenGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def model(self):
        with torch.random.fork_rng():
            torch.manual_seed(117)
            return JointGeneratorV4(
                allow_initial_stop=True, suppress_redundant_verify=True
            )

    def test_private_optimizer_changes_content_without_shared_changes(self):
        model = self.model()
        before = {key: value.clone() for key, value in model.state_dict().items()}
        frozen = shared_digest(model)
        optimizer = torch.optim.Adam(private_training_parameters(model), lr=0.01)
        _, source = colour_card(903)
        public = encode_input(PROMPT, source)
        state = forward_graph(model, public)
        text_loss, _ = model.text_loss(state, expected_caption(source))
        image_loss = (
            (model.outputs(state)["image"].sigmoid() - public["image"].flatten(1))
            .square()
            .mean()
        )
        optimizer.zero_grad(set_to_none=True)
        (text_loss + image_loss).backward()
        optimizer.step()
        changed = {
            name
            for name, parameter in model.named_parameters()
            if not torch.equal(before[name], parameter)
        }
        self.assertTrue(any(name.startswith("adapters.text.") for name in changed))
        self.assertTrue(any(name.startswith("adapters.image.") for name in changed))
        self.assertTrue(all(name.startswith(PRIVATE_PREFIXES) for name in changed))
        self.assertEqual(shared_digest(model), frozen)
        self.assertTrue(
            all(
                not parameter.requires_grad and parameter.grad is None
                for name, parameter in model.named_parameters()
                if not name.startswith(PRIVATE_PREFIXES)
            )
        )
        loaded = load_generator(model.export_weights())
        self.assertEqual(deliver(model, public), deliver(loaded, public))

    def test_kernel_swap_preserves_tensors_and_changes_identity(self):
        model = self.model()
        raw = model.export_weights()
        ordinary = load_with_kernel(raw, kernel="ordinary")
        self.assertEqual(set(model.state_dict()), set(ordinary.state_dict()))
        for name, value in model.state_dict().items():
            torch.testing.assert_close(
                value, ordinary.state_dict()[name], rtol=0, atol=0
            )
        self.assertNotEqual(shared_digest(model), shared_digest(ordinary))
        _, source = colour_card(904)
        public = encode_input(PROMPT, source)
        self.assertFalse(
            torch.equal(
                forward_graph(model, public).shared,
                forward_graph(ordinary, public).shared,
            )
        )
        restored = load_with_kernel(ordinary.export_weights(), kernel="dual")
        self.assertEqual(restored.export_weights(), raw)
        with self.assertRaises(ValueError):
            load_with_kernel(raw, kernel="unknown")

    def test_study_keeps_unqualified_outcome_and_disjoint_future(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with patch(
                "scripts.ndu_bimodal.frozen_training.colour_card", wraps=colour_card
            ) as generate:
                with self.assertRaises(BaseCapabilityError):
                    run_frozen_study(
                        output, seed=52, base_steps=2, adapter_steps=2, future_sources=3
                    )
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["error_type"], "BaseCapabilityError")
            self.assertFalse(report["bounded_content_passed"])
            self.assertEqual(report["production_update"], "no-update")
            self.assertFalse(report["private_training_started"])
            self.assertFalse(report["future_materialized"])
            groups = [
                set(report["registration"][name])
                for name in (
                    "base_training_seeds",
                    "adapter_training_seeds",
                    "base_calibration_seeds",
                    "future_seeds",
                )
            ]
            for i, group in enumerate(groups):
                for other in groups[i + 1 :]:
                    self.assertFalse(group & other)
            observed = {call.args[0] for call in generate.call_args_list}
            self.assertEqual(observed, groups[0] | groups[2])
            self.assertTrue((output / "baseline.heptapk").is_file())
            self.assertTrue((output / "base-training.jsonl").is_file())
            for name in (
                "adapter-training.jsonl",
                "candidate.heptapk",
                "candidate-freeze.json",
                "baseline-future",
                "candidate-future",
            ):
                self.assertFalse((output / name).exists())
            with self.assertRaises(FileExistsError):
                run_frozen_study(
                    output, base_steps=1, adapter_steps=1, future_sources=3
                )

    def test_final_update_overrun_keeps_trace_and_rejects_candidate(self):
        clock = iter((0.0, 0.0, 2.0))
        controlled_time = SimpleNamespace(
            perf_counter=lambda: next(clock), process_time=time.process_time
        )
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "updates.jsonl"
            with patch("scripts.ndu_bimodal.frozen_training.time", controlled_time):
                with self.assertRaises(TimeoutError):
                    _fit(
                        self.model(),
                        [903],
                        private=True,
                        deadline=1.0,
                        trace_path=trace,
                    )
            self.assertEqual(len(trace.read_text().splitlines()), 1)

    def test_visual_warmup_learns_images_without_updating_text_emission(self):
        model = self.model()
        before = {name: value.clone() for name, value in model.state_dict().items()}
        with tempfile.TemporaryDirectory() as directory:
            report = _fit(
                model,
                [903],
                private=False,
                deadline=time.perf_counter() + 30,
                trace_path=Path(directory) / "visual.jsonl",
                visual_warmup_steps=1,
            )
        self.assertEqual(report["visual_warmup_steps"], 1)
        self.assertEqual(report["losses"][0]["phase"], "visual-warmup")
        self.assertIsNone(report["losses"][0]["caption_nll"])
        self.assertIsNone(report["losses"][0]["padding_nll"])
        changed = {
            name
            for name, value in model.state_dict().items()
            if not torch.equal(before[name], value)
        }
        self.assertTrue(any(name.startswith("emissions.image.") for name in changed))
        self.assertFalse(any(name.startswith("emissions.text.") for name in changed))
        self.assertTrue(any(name.startswith("encoder_fusion.") for name in changed))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "only.*base"):
                _fit(
                    model,
                    [903],
                    private=True,
                    deadline=time.perf_counter() + 30,
                    trace_path=Path(directory) / "private.jsonl",
                    visual_warmup_steps=1,
                )


if __name__ == "__main__":
    unittest.main()

"""Synthetic V3 contracts only: no MNIST assets, role labels, or study outputs."""

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
import torch

from ..v6.data import SourceCorpus, SourceSplit
from ..v6.neural import NeuralPortfolio
from ..v6.observer import Recognizer, observe_tensors
from ..field_bridge_20261027.adapters import local_parameters
from ..field_bridge_v3_20261027 import learning as L
from ..field_bridge_v3_20261027.training_common import Costs, configuration, object_hash
from ..field_bridge_v3_20261027.training_features import measure_state, probe_losses, tensor_hash


class LearningContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(2)
        torch.use_deterministic_algorithms(True)
        cls.protocol = json.loads((Path(__file__).parent.parent / "field_bridge_v3_20261027/PROTOCOL.json").read_text())

    def setUp(self):
        torch.manual_seed(23017)
        self.original = NeuralPortfolio(hidden=16).eval().requires_grad_(False)
        self.observer = Recognizer().eval().requires_grad_(False)
        generator, splits = torch.Generator().manual_seed(83017), {}
        for role in ("fit_gradient", "fit_rehearsal", "fit_probe", "fit_guard"):
            n = 32 if role.endswith(("gradient", "rehearsal")) else 4
            pixels = torch.randint(256, (n, 1, 28, 28), dtype=torch.uint8, generator=generator)
            labels = torch.arange(n) % 10
            ids = tuple(f"synthetic:{role}:{i}" for i in range(n))
            splits[role] = SourceSplit(pixels, labels, ids, ids)
        self.corpus = SourceCorpus(splits, {"synthetic": True})
        self.context = L.make_context(self.original, self.corpus, {"reward": self.observer},
                                      17, "fit", self.protocol)
        self.model = L.make_model(self.original, 17, self.protocol)
        self.optimizer = L.new_optimizer(self.model, self.protocol)

    def gradient(self, model=None, optimizer=None, step=0, multiplier=1.):
        row = L.schedule(17, 5000, step, 1, self.protocol)[0]
        adapt, clean = self.context.batches(row)
        return L.update(self.model if model is None else model, self.original,
                        self.optimizer if optimizer is None else optimizer, adapt, clean,
                        self.context.action, multiplier, row["noise_seed"], self.protocol, self.context.costs)

    def test_weighted_objective_matches_independent_mean_and_anchor(self):
        row = L.schedule(17, 5000, 0, 1, self.protocol)[0]
        adapt, clean = self.context.batches(row)
        actual = L.objective(self.model, self.original, adapt, clean, 0, row["noise_seed"],
                             self.protocol, self.context.costs, "contract")
        components = []
        for index, batch in enumerate((adapt, clean)):
            output = L.fixed_output(self.model, batch, 0, row["noise_seed"] + index * 1000003, teacher=True)
            with torch.no_grad():
                reference = L.fixed_output(self.original, batch, 0, row["noise_seed"] + index * 1000003, teacher=True)
            joint = self.model.loss(output, batch.target)["joint"].mean()
            penalty = (output.image_logits.sigmoid() - reference.image_logits.sigmoid()).square().mean()
            penalty += .1 * torch.nn.functional.kl_div(output.text_logits.log_softmax(-1),
                reference.text_logits.softmax(-1), reduction="batchmean")
            components.append(joint + .1 * penalty)
        expected = (components[0] + .5 * components[1]) / 1.5
        self.assertTrue(torch.equal(actual, expected))

    def test_zero_action_holds_existing_momentum_and_parameters(self):
        self.gradient()
        before, costs = L.state_identity(self.model, self.optimizer), self.context.costs.snapshot()
        self.gradient(step=1, multiplier=0.)
        self.assertEqual(before, L.state_identity(self.model, self.optimizer))
        self.assertEqual(self.context.costs.since(costs)["scheduled_gradient_microsteps"], 1)
        self.assertEqual(self.context.costs.since(costs)["gradient_backward_examples"], 96)

    def test_complete_clone_preserves_future_updates(self):
        self.gradient()
        clone, optimizer = L.clone_state(self.model, self.optimizer, self.protocol)
        for step in (1, 2):
            self.gradient(step=step, multiplier=.25)
            self.gradient(clone, optimizer, step, multiplier=.25)
        self.assertEqual(L.state_identity(self.model, self.optimizer), L.state_identity(clone, optimizer))

    def test_guard_reject_restores_full_state_but_charges_and_advances(self):
        self.gradient()
        before = L.state_identity(self.model, self.optimizer)
        self.context.baseline_guard["values"]["reward"] += 3.  # Synthetic forced rejection, not a study rule.
        costs = self.context.costs.snapshot()
        receipt = L.guarded_block(self.context, self.model, self.optimizer, 0, 2, 5000)
        self.assertFalse(receipt["accepted"])
        self.assertEqual(receipt["end"], 48)
        self.assertNotEqual(receipt["candidate"], before)
        self.assertEqual(L.state_identity(self.model, self.optimizer), before)
        self.assertEqual(self.context.costs.since(costs)["discarded_gradient_microsteps"], 48)
        self.assertEqual(self.context.costs.since(costs)["gradient_backward_calls"], 48)

    def test_directional_measurement_is_invariant_and_matches_central_difference(self):
        self.gradient()
        for parameter in local_parameters(self.model):
            parameter.grad = torch.ones_like(parameter) * .013
        incoming = [parameter.grad for parameter in local_parameters(self.model)]
        before = L.state_identity(self.model, self.optimizer)
        rng = torch.get_rng_state().clone()
        state, current, receipt = measure_state(self.context, self.model, self.optimizer, 0, 5000)
        self.assertEqual(len(state), 30)
        self.assertEqual(before, L.state_identity(self.model, self.optimizer))
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertTrue(all(parameter.grad is gradient for parameter, gradient in zip(local_parameters(self.model), incoming)))
        clone, optimizer = L.clone_state(self.model, self.optimizer, self.protocol)
        self.gradient(clone, optimizer, step=0, multiplier=0.)
        direction = [parameter.grad.detach().clone() + .9 * optimizer.state[parameter]["momentum_buffer"]
                     for parameter in local_parameters(clone)]
        self.assertEqual(tensor_hash(direction), receipt["measured"]["direction_sha256"])
        epsilon, losses = .002, []
        for sign in (-1., 1.):
            perturbed, _ = L.clone_state(self.model, self.optimizer, self.protocol)
            with torch.no_grad():
                for parameter, vector in zip(local_parameters(perturbed), direction, strict=True):
                    parameter.add_(vector, alpha=sign * epsilon)
            measured = probe_losses(self.context, perturbed)
            losses.append(np.array([float(measured["adapt"]["image_bce"].detach()),
                float(measured["adapt"]["text_ce"].detach()), float(measured["clean"]["joint"].detach())]))
        np.testing.assert_allclose((losses[1] - losses[0]) / (2 * epsilon), state[9:12], atol=3e-4, rtol=.02)

    def test_hard_bytes_survive_png_utf8_and_scores_are_identical(self):
        score = L.hard_panel(self.model, self.context.guard, {"reward": self.observer}, 0,
                            self.protocol, self.context.costs, "contract_hard", retain=True)
        reread = []
        for pixels in score["pixels_u8"]:
            stream = io.BytesIO()
            Image.fromarray(pixels[0]).save(stream, format="PNG")
            stream.seek(0)
            reread.append(np.asarray(Image.open(stream)).copy())
        decoded = torch.from_numpy(np.stack(reread)[:, None]).float() / 255
        captions = [text.encode("utf-8").decode("utf-8") for text in score["captions_utf8"]]
        batch = self.context.guard[0].batch
        measured = observe_tensors(self.observer, decoded, captions, batch.target.pixels, batch.target.labels)
        np.testing.assert_array_equal([row["utility"] - .002 for row in measured], score["values"]["reward"])

    def test_checkpoint_reloads_optimizer_and_next_update(self):
        self.gradient()
        with tempfile.TemporaryDirectory(prefix="hepta-v3-contract-") as temporary:
            path = Path(temporary) / "model.pt"
            L.save_checkpoint(path, self.model, self.optimizer, self.protocol, {"seed": 17})
            restored, optimizer, _ = L.load_checkpoint(path, self.original, 17, self.protocol)
            self.gradient(step=1)
            self.gradient(restored, optimizer, step=1)
            self.assertEqual(L.state_identity(self.model, self.optimizer), L.state_identity(restored, optimizer))


if __name__ == "__main__":
    unittest.main()

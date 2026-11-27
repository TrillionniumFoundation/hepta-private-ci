"""Real CPU Torch checks; tiny fixtures do not establish training adequacy."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from capacity import adamw
from gradient_diagnostics import gradient_activity
from models import _inputs, build_model


def legacy_forward(model, x, dt):
    """Original PLIF computation, without the new observational reductions."""
    _inputs(x, dt)
    model._reset(model)
    current = x.new_zeros(x.shape[0], model.input.out_features)
    outputs = []
    for observation in x.unbind(1):
        current = model.node(model.input(observation) + model.recurrent(current))
        outputs.append(model.head(current))
    return torch.stack(outputs, dim=1)


def fixture_fit(destination):
    """Run the actual trainer on an explicit in-memory integration fixture."""
    from train_development import fit

    generator = torch.Generator().manual_seed(811)
    entry = {
        "id": "synthetic-diagnostics-A",
        "x": torch.randn(4, 25, generator=generator).tolist(),
        "dt": [0.0, 0.01, 0.01, 0.01],
        "y": [0, 1, 0, 1],
    }
    development = dict(entry, id="synthetic-diagnostics-D")
    manifest = {
        "mode": "test-fixture",
        "frontend_sha256": "f" * 64,
        "selection_sha256": "e" * 64,
    }
    args = SimpleNamespace(
        output=Path(destination),
        prepared=Path("unused-test-input"),
        manifest_sha256="d" * 64,
        arm="snn_plif",
        s4_repo=None,
        width=4,
        seed=811,
        epochs=2,
        max_updates=2,
        memorization_updates=1,
        learning_rate=0.001,
        weight_decay=0.01,
        gradient_norm_cap=0.25,
        wall_seconds=30.0,
        rss_bytes=2**30,
    )
    with patch(
        "train_development.read_episodes",
        return_value=(
            {"train": [entry], "dev": [development]},
            {"class_weights": [1.0] * 11},
            manifest,
        ),
    ):
        return fit(args)


class TrainingDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_spike_roster_matches_actual_node_and_resets_per_forward(self):
        model = build_model("snn_plif", width=3)
        with torch.no_grad():
            model.input.weight.zero_()
            model.input.bias.copy_(torch.tensor([2.0, 0.0, 0.0]))
            model.input.weight[2, 0] = 1.0
            model.recurrent.weight.zero_()
        x = torch.zeros(2, 4, 25, dtype=torch.float64)
        x[:, :, 0] = torch.tensor([0.0, 2.0, 0.0, 2.0])
        dt = torch.full((2, 4), 0.01, dtype=torch.float64)
        captured = []
        hook = model.node.register_forward_hook(
            lambda _module, _inputs, output: captured.append(output.detach().clone())
        )
        model(x, dt)
        hook.remove()
        actual = torch.stack(captured)
        counts = actual.ne(0).sum(dim=(0, 1))
        expected = {
            "spike_fraction": float(actual.mean()),
            "spikes_per_neuron": counts.tolist(),
            "spike_fraction_per_neuron": (counts.double() / 8).tolist(),
            "per_neuron_event_opportunities": 8,
            "total_event_opportunities": 24,
            "silent_neuron_indices": [1],
            "spike_observation_scope": "current forward; batch and time axes only",
            "learned_tau": 2.0,
        }
        self.assertEqual(model.last_diagnostics, expected)
        self.assertEqual(counts.tolist(), [8, 0, 4])
        model(x[:1, :2], dt[:1, :2])
        self.assertEqual(model.last_diagnostics["spikes_per_neuron"], [2, 0, 1])
        self.assertEqual(model.last_diagnostics["per_neuron_event_opportunities"], 2)

    def test_logits_gradients_rng_and_optimizer_match_uninstrumented_forward(self):
        torch.manual_seed(208)
        observed = build_model("snn_plif", width=5)
        reference = copy.deepcopy(observed)
        optimizers = [adamw(model, 0.003, 0.01)[0] for model in (observed, reference)]
        generator = torch.Generator().manual_seed(52)
        x = torch.randn(2, 7, 25, generator=generator, dtype=torch.float64)
        dt = torch.full((2, 7), 0.02, dtype=torch.float64)
        for _ in range(2):
            for optimizer in optimizers:
                optimizer.zero_grad(set_to_none=True)
            rng = torch.get_rng_state().clone()
            logits, original = observed(x, dt), legacy_forward(reference, x, dt)
            torch.testing.assert_close(logits, original, rtol=0, atol=0)
            torch.testing.assert_close(rng, torch.get_rng_state(), rtol=0, atol=0)
            logits.square().mean().backward()
            original.square().mean().backward()
            before = {
                name: value.grad.detach().clone()
                for name, value in observed.named_parameters()
            }
            activity = gradient_activity(observed)
            self.assertEqual(activity["missing"], 0)
            self.assertEqual(activity["nonfinite"], 0)
            for name, value in observed.named_parameters():
                torch.testing.assert_close(value.grad, before[name], rtol=0, atol=0)
                torch.testing.assert_close(
                    value.grad,
                    dict(reference.named_parameters())[name].grad,
                    rtol=0,
                    atol=0,
                )
            torch.testing.assert_close(rng, torch.get_rng_state(), rtol=0, atol=0)
            for model, optimizer in zip((observed, reference), optimizers):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 0.25)
                optimizer.step()
            torch.testing.assert_close(
                observed.state_dict(), reference.state_dict(), rtol=0, atol=0
            )
            torch.testing.assert_close(
                optimizers[0].state_dict(), optimizers[1].state_dict(), rtol=0, atol=0
            )

    def test_real_complex_missing_zero_and_frozen_gradients_are_distinct(self):
        model = torch.nn.Module()
        model.real = torch.nn.Parameter(torch.ones(3, dtype=torch.float64))
        model.complex = torch.nn.Parameter(torch.ones(2, dtype=torch.complex128))
        model.unused = torch.nn.Parameter(torch.ones(4, dtype=torch.float64))
        model.frozen = torch.nn.Parameter(torch.ones(2), requires_grad=False)
        (2 * model.real[1] + 3 * model.complex[0].imag).backward()
        result = gradient_activity(model)
        self.assertEqual(
            {
                key: result[key]
                for key in (
                    "real_scalars",
                    "missing",
                    "zero",
                    "active",
                    "nonfinite",
                    "frozen_real_scalars",
                )
            },
            dict(
                real_scalars=11,
                missing=4,
                zero=5,
                active=2,
                nonfinite=0,
                frozen_real_scalars=2,
            ),
        )
        self.assertEqual(
            result["parameters"][1],
            dict(
                name="complex",
                shape=[2],
                real_scalars=4,
                missing=0,
                zero=3,
                active=1,
                nonfinite=0,
            ),
        )

    def test_weight_decay_changes_are_not_gradient_credit_and_nonfinite_is_recorded(
        self,
    ):
        model = torch.nn.Linear(2, 1, bias=False).double()
        with torch.no_grad():
            model.weight.fill_(1.0)
        optimizer, _ = adamw(model, 0.1, 0.2)
        (model.weight.sum() * 0).backward()
        before = model.weight.detach().clone()
        result = gradient_activity(model)
        optimizer.step()
        self.assertEqual(
            (result["active"], result["zero"], result["missing"]), (0, 2, 0)
        )
        self.assertFalse(result["weight_decay_counted_as_gradient"])
        self.assertTrue(bool((before != model.weight).all()))
        optimizer.zero_grad(set_to_none=True)
        (model.weight.sum() * float("inf")).backward()
        result = gradient_activity(model)
        self.assertEqual((result["active"], result["nonfinite"]), (0, 2))
        json.dumps(result, allow_nan=False)

    def test_trainer_binds_every_preclip_record_to_original_update(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "fixture-fit"
            process = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--trainer-fixture",
                    str(destination),
                ],
                capture_output=True,
                text=True,
                timeout=45,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            result = json.loads((destination / "result.json").read_text())
            self.assertFalse(result["training_adequacy_established"])
            self.assertEqual(result["formal_fits_started"], 0)
            self.assertEqual(
                (
                    result["diagnostic_updates_completed"],
                    result["main_updates_completed"],
                ),
                (1, 2),
            )
            events = [
                json.loads(line)
                for line in (destination / "events.jsonl").read_text().splitlines()
            ]
            gradients = [row for row in events if row["event"] == "gradient_observed"]
            started = [row for row in events if row["event"] == "update_started"]
            self.assertEqual(
                [(row["phase"], row["number"], row["episode"]) for row in gradients],
                [(row["phase"], row["number"], row["episode"]) for row in started],
            )
            for record in gradients:
                subsequent = next(
                    row
                    for row in events
                    if row["event"] == "optimizer_step_started"
                    and (row["phase"], row["number"])
                    == (record["phase"], record["number"])
                )
                self.assertLess(events.index(record), events.index(subsequent))
                activity = record["gradient_activity"]
                self.assertEqual(
                    activity["real_scalars"],
                    sum(
                        activity[key]
                        for key in ("missing", "zero", "active", "nonfinite")
                    ),
                )
                self.assertEqual(
                    activity["stage"], "post_backward_pre_clip_pre_optimizer"
                )
                self.assertEqual(
                    record["diagnostics"]["per_neuron_event_opportunities"], 4
                )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--trainer-fixture":
        raise SystemExit(fixture_fit(sys.argv[2]))
    unittest.main()

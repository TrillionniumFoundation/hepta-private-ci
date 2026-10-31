"""Behavioral checks for shared capacity, causality, learned flow and evidence."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch
from torch.nn import functional as F

from .content import ContentModel, parameter_hash
from .content_train import group_gradients, run
from .data import causal_windows, copy_prefix_addresses, load_data, synthetic_data, tensor_batch
from .binding_data import binding_data, verify_single_modality_marginals


class ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def batch(self):
        values = synthetic_data("mqar", "train", 16, 4, 91091)
        return tensor_batch(values, np.arange(4))

    def test_shared_parameters_are_identical_across_both_adapters(self):
        models = [ContentModel("mqar", family, width=8, depth=1, seed=19)
                  for family in ("shared", "two_gate", "analytic")]
        identities = [parameter_hash(model.common) for model in models]
        self.assertEqual(identities, [identities[0]] * 3)
        self.assertEqual([sum(p.numel() for p in model.common.parameters()) for model in models],
                         [sum(p.numel() for p in models[0].common.parameters())] * 3)

    def test_future_content_and_padding_do_not_change_past_logits(self):
        batch = self.batch()
        for family in ("shared", "two_gate", "analytic"):
            model = ContentModel("mqar", family, width=8, depth=1, seed=17).eval()
            with torch.no_grad():
                original = model(batch["x"], batch["dt"], batch["observed"], batch["valid"])
                changed = batch["x"].clone()
                changed[:, 8:] = torch.randn_like(changed[:, 8:])
                alternative = model(changed, batch["dt"], batch["observed"], batch["valid"])
                prefix = model(batch["x"][:, :8], batch["dt"][:, :8],
                               batch["observed"][:, :8], batch["valid"][:, :8])
            torch.testing.assert_close(original[:, :8], alternative[:, :8], rtol=2e-5, atol=2e-6)
            torch.testing.assert_close(original[:, :8], prefix, rtol=2e-5, atol=2e-6)

    def test_all_five_analytic_groups_receive_task_gradients(self):
        batch = self.batch()
        model = ContentModel("mqar", "analytic", width=8, depth=1, seed=18)
        logits = model(batch["x"], batch["dt"], batch["observed"], batch["valid"])
        F.cross_entropy(logits.flatten(0, 1), batch["y"].flatten(), ignore_index=-100).backward()
        norms = group_gradients(model)
        self.assertTrue(all(np.isfinite(value) and value > 0 for value in norms.values()), norms)

    def test_frozen_trained_shared_content_is_exact_while_adapter_learns(self):
        batch = self.batch()
        shared = ContentModel("mqar", "shared", width=8, depth=1, seed=21)
        optimizer = torch.optim.Adam(shared.parameters(), lr=.01)
        loss = F.cross_entropy(shared(batch["x"], batch["dt"]).flatten(0, 1),
                               batch["y"].flatten(), ignore_index=-100)
        loss.backward()
        optimizer.step()
        donor = dict(config=shared.config, common_state=shared.common.state_dict(),
                     common_sha256=parameter_hash(shared.common))
        model = ContentModel("mqar", "analytic", width=8, depth=1, seed=21)
        model.load_shared(donor)
        model.freeze(shared=True)
        before_common, before_model = parameter_hash(model.common), parameter_hash(model)
        optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=.01)
        F.cross_entropy(model(batch["x"], batch["dt"]).flatten(0, 1),
                        batch["y"].flatten(), ignore_index=-100).backward()
        optimizer.step()
        self.assertEqual(before_common, parameter_hash(model.common))
        self.assertNotEqual(before_model, parameter_hash(model))

    def test_mqar_query_counterfactual_changes_gold_with_binding(self):
        original = synthetic_data("mqar", "val", 32, 16, 2047)
        changed = synthetic_data("mqar", "val", 32, 16, 2047, "query_permute")
        np.testing.assert_array_equal(original["x"][:, :-4], changed["x"][:, :-4])
        for values in (original, changed):
            for x, y in zip(values["x"], values["y"], strict=True):
                bindings = {int(row[:8].argmax()): int(row[8:16].argmax()) for row in x if row[16]}
                expected = [bindings[int(row[:8].argmax())] for row in x[-4:]]
                self.assertEqual(expected, y[-4:].tolist())

    def test_copy_addresses_are_prefix_invariant_and_do_not_read_labels(self):
        values = synthetic_data("selective_copy", "train", 32, 8, 7151)
        source = values["x"].copy()
        source[:, :, 10:16] = 0
        prefix = copy_prefix_addresses(source[:, :16])
        np.testing.assert_array_equal(values["x"][:, :16], prefix)
        source[:, 16:, 8:10] = 1 - source[:, 16:, 8:10]
        changed = copy_prefix_addresses(source)
        np.testing.assert_array_equal(changed[:, :16], prefix)
        for row, labels in zip(values["x"], values["y"], strict=True):
            for query in np.flatnonzero(row[:, 9]):
                source_index = np.flatnonzero((row[:, 8] > 0) &
                    (row[:, 12:16] == row[query, 12:16]).all(axis=1))
                self.assertEqual(len(source_index), 1)
                self.assertEqual(int(row[source_index[0], :8].argmax()), int(labels[query]))

    def test_causal_windows_release_only_already_acquired_payload(self):
        times = np.array([.01, .03, .08, .11, .17, .23])
        modality = np.array([0, 1, 0, 1, 0, 1])
        x = np.zeros((len(times), 40), np.float32)
        x[:, 0] = np.arange(len(times))
        x[np.arange(len(times)), 34 + modality] = 1
        output, release = causal_windows(x, times, modality, 0, .1)
        np.testing.assert_array_equal(output[:, 0], [2, 1, 4, 3, 5])
        np.testing.assert_allclose(release, [.1, .1, .2, .2, .23])
        modified = x.copy()
        modified[3:] += 10
        changed, changed_release = causal_windows(modified, times, modality, 0, .1)
        np.testing.assert_array_equal(output[:2], changed[:2])
        np.testing.assert_array_equal(release, changed_release)

    def test_heldout_access_is_denied_without_permission(self):
        for split in ("test", "ood"):
            with self.assertRaises(PermissionError):
                load_data(dict(task="async_av", av_directory="/does/not/exist"), split)

    def test_binding_has_exact_single_modality_marginals_and_actor_groups(self):
        directory = Path(__file__).resolve().parents[1] / "hcsn_task_value_v1/results/async_frontend001/data"
        job = dict(av_directory=str(directory), av_window_seconds=.1, binding_deadline_seconds=1.5)
        full = binding_data(job, "train")
        audio = binding_data(job, "train", "missing_video")
        video = binding_data(job, "train", "missing_audio")
        metadata = binding_data(job, "train", "metadata_only")
        receipt = verify_single_modality_marginals(audio, video)
        self.assertEqual(receipt["pairs"], 48)
        np.testing.assert_array_equal(full["group_ids"], full["donor_group_ids"])
        np.testing.assert_array_equal(full["y"][:, -1], np.r_[np.ones(24), np.zeros(24)])
        self.assertEqual(len(np.unique(full["video_source_ids"][24:])), 24)
        self.assertFalse(np.any(metadata["x"][:, :, :32]))
        np.testing.assert_array_equal(metadata["x"][:, :, 32:], full["x"][:, :, 32:])

    def test_worker_checkpoint_replay_freeze_and_create_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "job"
            job = dict(task="mqar", family="analytic", width=8, depth=1, seed=71001,
                       updates=2, batch_size=4, train_size=8, validation_size=8,
                       length=16, validate_every=1, freeze_groups=["reset"])
            result = run(job, output)
            self.assertFalse(result["heldout_access"])
            records = [json.loads(line) for line in (output / "access.jsonl").read_text().splitlines()]
            self.assertEqual([row["split"] for row in records], ["train", "val"])
            initial = torch.load(output / "initial_parameters.pt", weights_only=False)
            selected = torch.load(output / "selected.pt", weights_only=False)
            final = torch.load(output / "final.pt", weights_only=False)
            for name in initial["groups"]["reset"]:
                self.assertTrue(torch.equal(initial["parameters"][name], selected["model_state"][name]))
                self.assertTrue(torch.equal(initial["parameters"][name], final["model_state"][name]))
            model = ContentModel(**selected["config"])
            model.load_state_dict(selected["model_state"])
            self.assertEqual(parameter_hash(model), result["model_parameter_sha256"])
            profile = json.loads((output / "inference_profile_validation.json").read_text())
            self.assertEqual(len(profile["request_ids"]), 8)
            self.assertGreater(profile["p50_wall_seconds"], 0)
            self.assertGreaterEqual(profile["p95_wall_seconds"], profile["p50_wall_seconds"])
            self.assertEqual(profile["selected_checkpoint_sha256"], result["selected_checkpoint_sha256"])
            sources = json.loads((output / "source_identity.json").read_text())
            self.assertTrue(any(path.endswith("binding_data.py") for path in sources))
            self.assertTrue(any(path.endswith("content_train.py") for path in sources))
            with self.assertRaises(FileExistsError):
                run(job, output)


if __name__ == "__main__":
    unittest.main()


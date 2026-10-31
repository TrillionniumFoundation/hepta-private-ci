"""Qualification boundary and retained-input replay tests using synthetic data."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

import torch

from ..v6.data import SourceCorpus, SourceSplit
from ..v6.neural import parameter_hash
from ..v6.observer import METRIC_DIGEST, Recognizer
from ..v7.evaluation import load_reward
from .base_recovery import file_sha
from .qualification import qualification_ids, read_inputs, save_inputs, score_inputs, select_qualification


class QualificationTests(unittest.TestCase):
    def test_registered_source_boundary_rejects_task_overlap_and_role_leak(self):
        ids = [f"source-{i}" for i in range(2000)]
        manifest = {"roles": {"development": {"source_ids": ids}, "reward": {"source_ids": ["reward-source"]}}}
        protocol = {"known_previous_development_pair_interval": [0, 608], "roles": {
            "evaluation": {"role": "development", "pair_start": 608, "pair_count": 128},
            "static_tuning": {"role": "development", "pair_start": 736, "pair_count": 32},
            "observer_qualification": {"role": "development", "pair_start": 768, "pair_count": 128}},
            "observer_qualification": {"individual_source_interval": [1536, 1792]}}
        self.assertEqual(qualification_ids(manifest, protocol), tuple(ids[1536:1792]))
        pixels = torch.randint(256, (2000, 1, 28, 28), generator=torch.Generator().manual_seed(7), dtype=torch.uint8)
        labels = torch.arange(2000) % 10
        pool = SourceSplit(pixels, labels, tuple(ids),
                           tuple(hashlib.sha256(image.numpy().tobytes()).hexdigest() for image in pixels))
        corpus = SourceCorpus({"development": pool}, manifest)
        selected = select_qualification(corpus, protocol)
        self.assertEqual(selected.ids, tuple(ids[1536:1792]))
        self.assertTrue(torch.equal(selected.images, pixels[1536:1792]))
        self.assertTrue(torch.equal(selected.labels, labels[1536:1792]))
        pixels[1536, 0, 0, 0] ^= 1
        with self.assertRaisesRegex(ValueError, "pixels differ"):
            select_qualification(corpus, protocol)
        overlap = deepcopy(protocol)
        overlap["roles"]["static_tuning"]["pair_count"] = 33
        with self.assertRaisesRegex(ValueError, "overlap"):
            qualification_ids(manifest, overlap)
        mismatch = deepcopy(protocol)
        mismatch["observer_qualification"]["individual_source_interval"][0] += 1
        with self.assertRaisesRegex(ValueError, "boundaries disagree"):
            qualification_ids(manifest, mismatch)
        manifest["roles"]["reward"]["source_ids"] = [ids[1536]]
        with self.assertRaisesRegex(ValueError, "overlap"):
            qualification_ids(manifest, protocol)

    def test_saved_actual_inputs_rescore_identically_after_checkpoint_reload(self):
        torch.set_num_threads(2)
        generator = torch.Generator().manual_seed(315)
        pixels = torch.randint(256, (8, 1, 28, 28), generator=generator, dtype=torch.uint8)
        source = SourceSplit(pixels, torch.randint(10, (8,), generator=generator), tuple(map(str, range(8))),
                             tuple(hashlib.sha256(image.numpy().tobytes()).hexdigest() for image in pixels))
        policy = {"bernoulli_seeds": [9022001, 9022002], "individual_source_interval": [1536, 1544],
                  "original_images_min_accuracy": 0.95, "bernoulli_original_images_min_accuracy": 0.90}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            input_path = directory / "inputs.pt"
            input_sha = save_inputs(source, policy, input_path)
            inputs = read_inputs(input_path, input_sha)
            second = directory / "same-inputs.pt"
            torch.manual_seed(98765)
            second_inputs = read_inputs(second, save_inputs(source, policy, second))
            self.assertTrue(torch.equal(inputs["pixels"], second_inputs["pixels"]))
            models, paths = {}, {}
            for seed, name in enumerate(("primary", "secondary"), 21):
                torch.manual_seed(seed)
                model = Recognizer().eval().requires_grad_(False)
                path = directory / (name + ".pt")
                torch.save({"schema": "hepta.ndu-v7.reward-observer.v1", "metric_sha256": METRIC_DIGEST,
                            "state_dict": model.state_dict(), "parameter_sha256": parameter_hash(model)}, path)
                models[name], _ = load_reward(path, file_sha(path))
                paths[name] = path
            expected = score_inputs(models, inputs, policy)
            torch.manual_seed(555)
            reloaded = {name: load_reward(path, file_sha(path))[0] for name, path in paths.items()}
            actual = score_inputs(reloaded, read_inputs(input_path, input_sha), policy)
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual[0]), 24)
            self.assertEqual({name: report["bernoulli_pooled"]["n"] for name, report in actual[1].items()},
                             {"primary": 16, "secondary": 16})
            with input_path.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                read_inputs(input_path, input_sha)


if __name__ == "__main__":
    unittest.main()

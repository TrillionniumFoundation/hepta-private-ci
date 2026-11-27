"""Checkpoint rejection cases that could otherwise invalidate a recovery claim."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

from .model import build_model
from .runtime_eval import numeric_state, read_state, verified_training_run


class RuntimeCheckpointTests(unittest.TestCase):
    def test_state_roundtrip_and_invalid_shapes_mass_and_numbers(self):
        model = build_model("distribution_free_dual", 64, 10, width=32, depth=1, seed=9201)
        with torch.inference_mode():
            _, state, _ = model.step(torch.zeros(2, 64), torch.ones(2), None)
        original = numeric_state(state)
        schema = {key: dict(shape=list(value.shape), dtype=str(value.dtype))
                  for key, value in original.items()}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.npz"
            np.savez_compressed(path, **original)
            result = numeric_state(read_state(path, model.config, 2, schema))
            for key in original:
                np.testing.assert_array_equal(result[key], original[key])
            for corruption in ("shape", "dtype", "mass", "nan", "elapsed", "field"):
                bad = {key: value.copy() for key, value in original.items()}
                if corruption == "shape":
                    bad["layer_0.probability"] = bad["layer_0.probability"][..., :-1]
                elif corruption == "dtype":
                    bad["layer_0.content"] = bad["layer_0.content"].astype(np.float64)
                elif corruption == "mass":
                    bad["layer_0.probability"] *= .5
                elif corruption == "nan":
                    bad["layer_0.boundary"][0, 0] = np.nan
                elif corruption == "elapsed":
                    bad["elapsed"][0] = -1
                else:
                    del bad["layer_0.boundary"]
                np.savez_compressed(path, **bad)
                with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                    read_state(path, model.config, 2, schema)

    def test_identical_weight_shapes_cannot_substitute_an_ordinary_arm(self):
        # Ordinary and dual arms have compatible state_dict shapes. Metadata must
        # reject the wrong arm before a shape-compatible checkpoint can be used.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            job = dict(task="mnist", model="distribution_free_ordinary", seed=9201)
            fixtures = {
                "summary.json": {"status": "completed"},
                "selection.json": {},
                "IDENTITY.json": {"status": "completed", "job": job},
                "EXECUTION.json": {"returncode": 0, "job": job},
            }
            for name, value in fixtures.items():
                (path / name).write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "distribution_free_dual"):
                verified_training_run(path)


if __name__ == "__main__":
    torch.set_num_threads(1)
    unittest.main()

"""Process-independent suffix replay against the genuine observation/gap model."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
import numpy as np

from .checkpoint import load_checked, save_v2

try:
    from tools.hcsn.task_flow_20261030.flow import api
    from .recover import suffix
    ORIGINAL_AVAILABLE = True
except ImportError:
    ORIGINAL_AVAILABLE = False


@unittest.skipUnless(ORIGINAL_AVAILABLE, "Original flow module not available")
class IndependentColdReplay(unittest.TestCase):
    def run_case(self, precision):
        dtype = getattr(jnp, precision)
        params = api.init_parameters(seed=31, dtype=dtype)
        state = api.observe(params, jnp.asarray([1., -.5, .2], dtype=dtype), api.initial_state(params))
        expected = suffix(params, state)
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "original.npz"
            resumed = Path(directory) / "resumed.npz"
            save_v2(original, params, state, precision=precision)
            command = [sys.executable, "-m", "tools.hcsn.task_flow_20261030.precision_restore_v1.recover",
                       "--checkpoint", str(original), "--destination", str(resumed), "--precision", precision]
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[4],
                                    env=dict(os.environ, JAX_ENABLE_X64="1"),
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            replay_params, actual = load_checked(resumed, expected_precision=precision)
            for key in params:
                self.assertTrue(np.array_equal(np.asarray(params[key]), np.asarray(replay_params[key])), key)
            for key in expected:
                self.assertTrue(np.array_equal(np.asarray(expected[key]), np.asarray(actual[key])), key)
            self.assertEqual(int(actual["observations"]), int(state["observations"]) + 2)
            self.assertAlmostEqual(float(actual["elapsed"] - state["elapsed"]), 1.77, places=5)

    def test_float64_independent_process_exact_recovery(self):
        self.run_case("float64")

    def test_float32_independent_process_exact_recovery(self):
        self.run_case("float32")

    def test_float64_disabled_process_refuses_before_writing(self):
        params = api.init_parameters(seed=19, dtype=jnp.float64)
        state = api.initial_state(params)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.npz"
            dest = Path(directory) / "must_not_exist.npz"
            save_v2(source, params, state, precision="float64")
            command = [sys.executable, "-m", "tools.hcsn.task_flow_20261030.precision_restore_v1.recover",
                       "--checkpoint", str(source), "--destination", str(dest), "--precision", "float64"]
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[4],
                                    env=dict(os.environ, JAX_ENABLE_X64="0"),
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing float64 restore", result.stderr)
            self.assertFalse(dest.exists())

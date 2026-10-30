"""Deterministic positive/adversarial tests of precision-preserving HCSN restore."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
import numpy as np

from .checkpoint import load_checked, save_v2, SCHEMA_V1


def fixture(dtype):
    f = lambda a: np.asarray(a, dtype=dtype)
    params = dict(input=f(np.ones((3, 4)) / 9), recurrent=f(np.eye(4) * .1),
                  bias=f(np.zeros(4)), gate_input=f(np.zeros((3, 4))),
                  gate_physical=f(np.ones((10, 4)) / 20), gate_bias=f(np.zeros(4)),
                  dynamics=f(np.ones((3, 3)) / 10), raw_physical=f(np.zeros(5)),
                  raw_decay=f(np.ones(4) * -.5), raw_cost=f(-1.))
    state = dict(probability=f([.25, .25, .25, .25, 0, 0, 0, 0, 0, 0]),
                 content=f(np.arange(4) / 10), physical=f([.1, .4, .9, -.1, .75]),
                 decay=f([.05, .08, .1, .16]), cost=f(.2), elapsed=f(4.),
                 events=f(1.2), reward=f(-.1), observations=np.asarray(3, np.int32))
    return params, state


def pack(path, params, state, version=SCHEMA_V1, extra=None):
    arrays = {**{f"params__{k}": v for k, v in params.items()},
              **{f"state__{k}": v for k, v in state.items()},
              "schema": np.asarray(version)}
    if extra:
        arrays.update(extra)
    np.savez(path, **arrays)


class PrecisionRestoreContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ckpt.npz"

    def test_v2_float64_exact_and_duplicate_denied(self):
        p, s = fixture(np.float64)
        save_v2(self.path, p, s, precision="float64")
        rp, rs = load_checked(self.path, expected_precision="float64")
        for k in p:
            self.assertTrue(np.array_equal(p[k], np.asarray(rp[k])), k)
        for k in s:
            self.assertTrue(np.array_equal(s[k], np.asarray(rs[k])), k)
        with self.assertRaises(FileExistsError):
            save_v2(self.path, p, s, precision="float64")

    def test_v2_float32(self):
        p, s = fixture(np.float32)
        save_v2(self.path, p, s, precision="float32")
        rp, rs = load_checked(self.path, expected_precision="float32")
        self.assertEqual(rp["input"].dtype, jnp.float32)
        self.assertEqual(rs["elapsed"].dtype, jnp.float32)

    def test_legacy_v1_explicit_type(self):
        p, s = fixture(np.float64)
        pack(self.path, p, s)
        self.assertEqual(load_checked(self.path, expected_precision="float64")[1]["elapsed"].dtype, jnp.float64)

    def test_reject_wrong_explicit_precision(self):
        p, s = fixture(np.float64)
        save_v2(self.path, p, s, precision="float64")
        with self.assertRaisesRegex(ValueError, "dtype"):
            load_checked(self.path, expected_precision="float32")

    def test_reject_automatic_x64_downgrade_in_new_process(self):
        p, s = fixture(np.float64)
        save_v2(self.path, p, s, precision="float64")
        module = "tools.hcsn.task_flow_20261030.precision_restore_v1.checkpoint"
        statement = (f"from {module} import load_checked; "
                     f"load_checked({str(self.path)!r}, expected_precision='float64')")
        env = dict(os.environ, JAX_ENABLE_X64="0")
        result = subprocess.run([sys.executable, "-c", statement], cwd=Path(__file__).resolve().parents[4],
                                env=env, capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing float64 restore", result.stderr)

    def test_checksum_tampering_rejected(self):
        p, s = fixture(np.float64)
        save_v2(self.path, p, s, precision="float64")
        with np.load(self.path) as data:
            arrays = {k: np.asarray(data[k]).copy() for k in data.files}
        arrays["state__content"][0] += .125
        np.savez(self.path, **arrays)
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_checked(self.path, expected_precision="float64")

    def test_mixed_dtype_rejected(self):
        p, s = fixture(np.float64)
        p["recurrent"] = p["recurrent"].astype(np.float32)
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "dtype"):
            load_checked(self.path, expected_precision="float64")

    def test_unknown_field_rejected(self):
        p, s = fixture(np.float64)
        pack(self.path, p, s, extra={"state__authority": np.asarray(1.)})
        with self.assertRaisesRegex(ValueError, "fields"):
            load_checked(self.path, expected_precision="float64")

    def test_missing_field_rejected(self):
        p, s = fixture(np.float64)
        del s["physical"]
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "fields"):
            load_checked(self.path, expected_precision="float64")

    def test_nonfinite_parameter_rejected(self):
        p, s = fixture(np.float64)
        p["input"][0, 0] = np.nan
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            load_checked(self.path, expected_precision="float64")

    def test_shape_rejected(self):
        p, s = fixture(np.float64)
        p["gate_physical"] = np.ones((11, 4), np.float64)
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            load_checked(self.path, expected_precision="float64")

    def test_nonconservative_mass_rejected(self):
        p, s = fixture(np.float64)
        s["probability"][0] -= .02
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "mass"):
            load_checked(self.path, expected_precision="float64")

    def test_bad_physical_and_counters_rejected(self):
        p, s = fixture(np.float32)
        s["physical"][2] = 10.
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "Physical"):
            load_checked(self.path, expected_precision="float32")
        s["physical"][2] = .9
        s["observations"] = np.asarray(-1, np.int32)
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "counters"):
            load_checked(self.path, expected_precision="float32")

    def test_bounded_uncompressed_archive(self):
        p, s = fixture(np.float64)
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            load_checked(self.path, expected_precision="float64", max_bytes=64)

    def test_duplicate_zip_member_rejected(self):
        p, s = fixture(np.float64)
        pack(self.path, p, s)
        with zipfile.ZipFile(self.path, mode="a") as zf:
            zf.writestr("state__reward.npy", b"duplicate")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_checked(self.path, expected_precision="float64")

    def test_missing_precision_input_rejected(self):
        p, s = fixture(np.float32)
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "Caller must"):
            load_checked(self.path, expected_precision="auto")

    def test_wrong_counter_dtype_rejected(self):
        p, s = fixture(np.float64)
        s["observations"] = np.asarray(3, np.int64)
        pack(self.path, p, s)
        with self.assertRaisesRegex(ValueError, "int32"):
            load_checked(self.path, expected_precision="float64")

    def test_optional_real_api_propagation(self):
        try:
            from tools.hcsn.task_flow_20261030.flow import api
        except ImportError:
            self.skipTest("Original flow/api.py not installed in this standalone test tree")
        params = api.init_parameters(input_dim=3, width=4, seed=7, dtype=jnp.float64)
        state = api.checked_propagate(api.initial_state(params), .125)
        save_v2(self.path, params, state, precision="float64")
        p, s = load_checked(self.path, expected_precision="float64")
        new = api.checked_propagate(s, .125)
        self.assertAlmostEqual(float(np.asarray(new["probability"]).sum()), 1., places=9)
        self.assertGreater(float(new["elapsed"]), float(s["elapsed"]))


if __name__ == "__main__":
    unittest.main()

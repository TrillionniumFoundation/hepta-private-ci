"""Exact old/new output parity on hand arrays; no dataset or speed threshold.

The retained manual five-pair probe had two slower vectorized pairs; its median
paired saving was 145553ns/64 requests. It is a diagnostic, not qualification.
"""

import base64
import hashlib
import io
import json
import math
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from data import caption
from independent.accounting import BudgetExceeded, WorkLedger
from independent.evaluation import _Observer, _outputs, output_work
from independent.inference import FrozenGenerator
from model import JointModel


def raw_baseline(generator, p, q, ledger, sample_rng):
    """Frozen pre-vectorization method, including its old work declaration."""
    n, k = p.shape
    pixels = generator.dimensions[2]
    ledger.charge_kernel("output", "sample_and_quantize",
        scalar_ops=n * (2 * k + 2 * pixels),
        compare_ops=n * (2 * math.ceil(math.log2(k + 1)) + 2 * pixels))
    random_values = sample_rng.random((n, 2))
    choices = [[min(int(np.searchsorted(np.cumsum(prob), draw)), k - 1)
                for prob, draw in zip((pp, qq), draws)]
               for pp, qq, draws in zip(p, q, random_values)]
    ledger.decoder("output", rows=n, pixels=pixels)
    images = _Observer(generator).decode_images(np.asarray([row[1] for row in choices])).reshape(n, 8, 8, 3)
    outputs, sizes = [], []
    for choice, image in zip(choices, images):
        encoded = io.BytesIO()
        Image.fromarray(np.rint(np.clip(image, 0, 1) * 255).astype(np.uint8)).save(encoded, format="PNG")
        png = encoded.getvalue()
        receipt = {"caption": caption(choice[0]), "choices": {"text": choice[0], "image": choice[1]},
                   "png_sha256": hashlib.sha256(png).hexdigest(),
                   "png_base64": base64.b64encode(png).decode("ascii")}
        payload = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        outputs.append(receipt)
        sizes.append(len(png) + len(payload))
    ledger.record("output", output_bytes=sum(sizes), serialized_requests=n)
    return outputs, sizes


class FixedDraws:
    def __init__(self, values):
        self.values, self.calls = np.asarray(values), 0

    def random(self, shape):
        if shape != self.values.shape:
            raise AssertionError("random draw shape/order changed")
        self.calls += 1
        return self.values.copy()


class OutputParityTests(unittest.TestCase):
    def setUp(self):
        self.model = JointModel(202, 12, 192, hidden=4, seed=602)
        self.gen = FrozenGenerator(self.model, prepare_low=False)

    def test_seeded_batches_preserve_every_output_byte_and_next_random_draw(self):
        rng = np.random.default_rng(71029)
        original = self.model.digest()
        for n in (1, 7, 64):
            p, q = (rng.random((n, 12)) for _ in range(2))
            p /= p.sum(axis=1, keepdims=True)
            q /= q.sum(axis=1, keepdims=True)
            # Noncontiguous read-only rows exercise per-row cumulative order.
            p, q = p[::-1], q[::-1]
            p.flags.writeable = q.flags.writeable = False
            before_p, before_q = p.copy(), q.copy()
            old_rng, new_rng = np.random.default_rng(901), np.random.default_rng(901)
            old_ledger, new_ledger = WorkLedger("old"), WorkLedger("new")
            old = raw_baseline(self.gen, p, q, old_ledger, old_rng)
            new = _outputs(self.gen, p, q, new_ledger, new_rng)
            self.assertEqual(new, old)
            self.assertEqual(new_rng.bit_generator.state, old_rng.bit_generator.state)
            np.testing.assert_array_equal(new_rng.random(9), old_rng.random(9))
            np.testing.assert_array_equal(p, before_p)
            np.testing.assert_array_equal(q, before_q)
            self.assertEqual(new_ledger.totals["output_bytes"], old_ledger.totals["output_bytes"])
            self.assertEqual(new_ledger.totals["serialized_requests"], n)
            self.assertGreater(new_ledger.consumed_units, old_ledger.consumed_units)
        self.assertEqual(self.model.digest(), original)

    def test_zero_probabilities_exact_cdf_ties_and_final_clamp(self):
        p = np.zeros((4, 12))
        p[0, 1] = 1
        p[1, :3] = (0.25, 0.25, 0.5)
        p[2, -1] = np.nextafter(1.0, 0.0)
        p[3, 0] = 1
        draws = [[0.0, 0.0], [0.25, 0.5], [1.0, np.nextafter(1.0, 0.0)], [1.0, 0.99]]
        old_rng, new_rng = FixedDraws(draws), FixedDraws(draws)
        old = raw_baseline(self.gen, p, p, WorkLedger("old"), old_rng)
        new = _outputs(self.gen, p, p, WorkLedger("new"), new_rng)
        self.assertEqual(new, old)
        self.assertEqual([row["choices"] for row in new[0]], [
            {"text": 0, "image": 0}, {"text": 0, "image": 1},
            {"text": 11, "image": 11}, {"text": 0, "image": 0}])
        self.assertEqual((old_rng.calls, new_rng.calls), (1, 1))

    def test_batch_quantization_preserves_clipping_rounding_and_png_pixels(self):
        pixels = np.resize(np.array([-0.1, 0.0, 0.5 / 255, 1.5 / 255, 127.5 / 255, 1.0, 1.1]), 2 * 192).reshape(2, 8, 8, 3)
        p = np.eye(12)[:2]
        with patch.object(_Observer, "decode_images", return_value=pixels.reshape(2, 192)):
            old = raw_baseline(self.gen, p, p, WorkLedger("old"), np.random.default_rng(5))
            new = _outputs(self.gen, p, p, WorkLedger("new"), np.random.default_rng(5))
        self.assertEqual(new, old)
        expected = np.rint(np.clip(pixels, 0, 1) * 255).astype(np.uint8)
        for index, output in enumerate(new[0]):
            png = base64.b64decode(output["png_base64"])
            with Image.open(io.BytesIO(png)) as image:
                np.testing.assert_array_equal(np.asarray(image), expected[index])

    def test_insufficient_sampling_budget_rejects_before_rng_and_decode(self):
        quote = WorkLedger("quote").estimate_kernel(**output_work())
        ledger, rng = WorkLedger("tight", total_cap=quote - 1), Mock()
        rng.random.side_effect = AssertionError("RNG must not run")
        with patch.object(_Observer, "decode_images", side_effect=AssertionError("decode must not run")):
            with self.assertRaises(BudgetExceeded):
                _outputs(self.gen, np.eye(12)[:1], np.eye(12)[:1], ledger, rng)
        self.assertEqual(ledger.consumed_units, 0)
        rng.random.assert_not_called()


if __name__ == "__main__":
    unittest.main()

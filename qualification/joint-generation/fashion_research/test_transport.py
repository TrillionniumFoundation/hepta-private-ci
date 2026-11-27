import inspect
import json
import unittest

import numpy as np

from contracts import ContractError
from fashion_research import transport


class FashionTransportTests(unittest.TestCase):
    def test_real_bytes_preserve_float32_pixels_and_ten_canonical_words(self):
        p = np.eye(10)
        mu = np.linspace(0, 1, 10 * 784).reshape(10, 28, 28)
        payload = transport.encode(p, mu)
        self.assertIs(type(payload), bytes)
        words, decoded = transport.decode(payload)
        self.assertEqual(words, transport.WORDS)
        np.testing.assert_array_equal(decoded, mu.astype(np.float32))
        self.assertEqual(decoded.dtype, np.float32)
        self.assertFalse(decoded.flags.writeable)
        wire = json.loads(payload)
        rgb = np.array(wire["rows"][4]["image"]["pixels"], dtype=np.float32)
        np.testing.assert_array_equal(rgb, np.repeat(decoded[4, :, :, None], 3, axis=2))

    def test_scores_use_transmitted_word_and_pixels_for_all_rows(self):
        clean = np.zeros((2, 28, 28))
        clean[:, 0, 0] = 1
        p = np.eye(10)[[0, 0]]
        payload = transport.encode(p, clean)
        wire = json.loads(payload)
        wire["rows"][1]["text"]["text"] = "Trouser"
        wire["rows"][1]["image"]["pixels"][0][0] = [.5, .5, .5]
        transmitted = json.dumps(wire).encode()
        values = transport.score(transmitted, clean, np.array([0, 0]))
        expected_mse = np.array([0, .25 / 784])
        np.testing.assert_array_equal(values["accuracy"], [1, 0])
        np.testing.assert_array_equal(values["mse"], expected_mse)
        np.testing.assert_array_equal(values["utility"], [1, 0])
        np.testing.assert_array_equal(values["support_mse"], [0, .25])
        np.testing.assert_array_equal(values["background_mse"], [0, 0])
        np.testing.assert_array_equal(values["support_pixels"], [1, 1])
        np.testing.assert_array_equal(values["background_pixels"], [783, 783])
        self.assertTrue(np.isposinf(values["psnr"][0]))
        self.assertEqual(values["psnr"][1], -10 * np.log10(.25 / 784))

    def test_utility_uses_actual_float_output_and_no_uint8_quantization(self):
        mu = np.full((1, 28, 28), .1001)
        clean = np.full((1, 28, 28), .1)
        values = transport.score(transport.encode(np.eye(10)[[2]], mu), clean, np.array([2]))
        expected = (float(np.float32(.1001)) - .1) ** 2
        self.assertAlmostEqual(values["mse"][0], expected, places=20)
        self.assertEqual(values["accuracy"][0], 1)
        self.assertAlmostEqual(values["utility"][0], np.exp(-expected / .04), places=15)

    def test_decode_rejects_inconsistent_rgb_and_malformed_payloads(self):
        original = json.loads(transport.encode(np.eye(10)[[0]], np.zeros((1, 28, 28))))
        for fault in ("rgb", "shape", "nan", "range", "dtype", "word", "extra", "label"):
            value = json.loads(json.dumps(original))
            row = value["rows"][0]
            if fault == "rgb": row["image"]["pixels"][0][0][1] = .5
            elif fault == "shape": row["image"]["pixels"].pop()
            elif fault == "nan": row["image"]["pixels"][0][0][0] = float("nan")
            elif fault == "range": row["image"]["pixels"][0][0] = [1.1] * 3
            elif fault == "dtype": row["image"]["dtype"] = "uint8"
            elif fault == "word": row["text"]["text"] = "shirt"
            elif fault == "extra": value["reference"] = "forbidden"
            else: row["labels"] = [0]
            with self.subTest(fault=fault), self.assertRaises(ContractError):
                transport.decode(json.dumps(value).encode())
        for payload in (b"not json", b"\xff", b'{"schema":1,"schema":2,"rows":[]}', b"{}"):
            with self.subTest(payload=payload), self.assertRaises(ContractError):
                transport.decode(payload)

    def test_encode_rejects_invalid_shapes_values_and_probability_laws(self):
        valid_p, valid_mu = np.eye(10)[[0]], np.zeros((1, 28, 28))
        bad = [(valid_p[0], valid_mu), (np.zeros((65, 10)), np.zeros((65, 28, 28))),
               (valid_p[:, :9], valid_mu), (valid_p, np.zeros((1, 784))),
               (valid_p, np.zeros((1, 28, 28), dtype=np.uint8)),
               (np.zeros((1, 10)), valid_mu), (np.full((1, 10), .2), valid_mu),
               (np.full((1, 10), np.nan), valid_mu),
               ([[.1] * 10, [.1]], np.zeros((2, 28, 28))),
               (valid_p, np.full((1, 28, 28), np.inf)),
               (valid_p, np.full((1, 28, 28), -.1))]
        for p, mu in bad:
            with self.subTest(p_type=type(p).__name__, mu_shape=np.shape(mu)), self.assertRaises(ContractError):
                transport.encode(p, mu)

    def test_empty_scoring_regions_preserve_rows_and_expose_denominators(self):
        clean = np.stack((np.zeros((28, 28)), np.ones((28, 28))))
        values = transport.score(transport.encode(np.eye(10)[[0, 1]], clean), clean, np.array([0, 1]))
        np.testing.assert_array_equal(values["accuracy"], [1, 1])
        np.testing.assert_array_equal(values["support_pixels"], [0, 784])
        np.testing.assert_array_equal(values["background_pixels"], [784, 0])
        self.assertTrue(np.isnan(values["support_mse"][0]))
        self.assertTrue(np.isnan(values["background_mse"][1]))
        np.testing.assert_array_equal(values["support_squared_error"], [0, 0])
        np.testing.assert_array_equal(values["background_squared_error"], [0, 0])

    def test_ground_truth_only_enters_the_offline_scorer(self):
        self.assertEqual(tuple(inspect.signature(transport.encode).parameters), ("p", "mu"))
        self.assertEqual(tuple(inspect.signature(transport.decode).parameters), ("payload",))
        payload = transport.encode(np.eye(10)[[3]], np.zeros((1, 28, 28)))
        for clean, labels in ((np.zeros((1, 784)), np.array([3])),
                              (np.zeros((1, 28, 28)), np.array([3.])),
                              (np.zeros((1, 28, 28)), np.array([10]))):
            with self.assertRaises(ContractError):
                transport.score(payload, clean, labels)


if __name__ == "__main__":
    unittest.main()

"""New algebra and admission tests; no model execution or frozen gate replay."""

from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import unittest

import readout_inverse as inverse


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(request):
    raw = (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return raw, digest(raw)


def fixture(features=(1.0, 3.0), targets=(2.0, 4.0), weights=(1.0, 1.0)):
    binding = {key: digest(key.encode()) for key in inverse.IDENTITY_FIELDS}
    binding["model_source_sha256"] = inverse.MODEL_SHA256
    return {
        "schema": inverse.SCHEMA,
        "observation": "final_logit_1_minus_logit_0",
        "freeze_rule": "all_parameters_buffers_config_inputs_and_initial_state_except_two_listed_coordinates",
        "coordinates": json.loads(json.dumps(inverse.COORDINATES)),
        "binding": binding,
        "rows": [{"row_id": f"fixture_{i}", "source_row_sha256": digest(str(i).encode()),
                  "feature0_hex": features[i].hex(), "base_margin_hex": 0.0.hex(),
                  "target_margin_hex": targets[i].hex(), "weight_hex": weights[i].hex()}
                 for i in range(2)],
    }


def fraction(record):
    return Fraction(int(record["numerator"]), int(record["denominator"]))


class ReadoutInverseTests(unittest.TestCase):
    def test_known_readout_edit(self):
        result = inverse.propose_readout_edit(*encoded(fixture()))
        self.assertEqual([fraction(value) for value in result["delta_exact"]], [Fraction(-1), Fraction(-1)])
        self.assertEqual(fraction(result["exact_max_abs_residual"]), 0)
        self.assertEqual(fraction(result["inverse_linf_norm"]), 2)

    def test_positive_weights_preserve_exact_interpolation(self):
        result = inverse.propose_readout_edit(*encoded(fixture(weights=(0.25, 16.0))))
        self.assertEqual([fraction(value) for value in result["delta_exact"]], [Fraction(-1), Fraction(-1)])

    def test_peer_order_preserves_full_statistics(self):
        _, rows, binding = inverse.read_request(*encoded(fixture()))
        parts = tuple(inverse.local_statistics(row, binding) for row in rows)
        ids = tuple(row.identity for row in rows)
        self.assertEqual(inverse.merge_statistics(parts, binding, ids),
                         inverse.merge_statistics(tuple(reversed(parts)), binding, ids))

    def test_incompatible_and_duplicate_peer_rejected(self):
        _, rows, binding = inverse.read_request(*encoded(fixture()))
        parts = tuple(inverse.local_statistics(row, binding) for row in rows)
        ids = tuple(row.identity for row in rows)
        with self.assertRaises(ValueError):
            inverse.merge_statistics((parts[0], replace(parts[1], binding_sha256="0" * 64)), binding, ids)
        with self.assertRaises(ValueError):
            inverse.merge_statistics((parts[0], parts[0]), binding, ids)
        with self.assertRaises(ValueError):
            inverse.merge_statistics((parts[0],), binding, ids)

    def test_request_replacement_rejected(self):
        raw, expected = encoded(fixture())
        with self.assertRaises(ValueError):
            inverse.propose_readout_edit(raw + b" ", expected)

    def test_rank_loss_rejected(self):
        with self.assertRaises(ValueError):
            inverse.propose_readout_edit(*encoded(fixture(features=(1.0, 1.0))))

    def test_duplicate_observation_identity_rejected(self):
        for field in ("row_id", "source_row_sha256"):
            request = fixture()
            request["rows"][1][field] = request["rows"][0][field]
            with self.assertRaises(ValueError):
                inverse.propose_readout_edit(*encoded(request))

    def test_nonfinite_or_noncanonical_value_rejected(self):
        for value in ("nan", "inf", "1", "0x1p+0", 1.0):
            request = fixture()
            request["rows"][0]["feature0_hex"] = value
            with self.assertRaises(ValueError):
                inverse.propose_readout_edit(*encoded(request))

    def test_nonpositive_weight_rejected(self):
        for weight in (0.0, -1.0):
            with self.assertRaises(ValueError):
                inverse.propose_readout_edit(*encoded(fixture(weights=(weight, 1.0))))

    def test_unfrozen_body_and_wrong_model_rejected(self):
        request = fixture()
        request["freeze_rule"] = "only_readout_frozen"
        with self.assertRaises(ValueError):
            inverse.propose_readout_edit(*encoded(request))
        request = fixture()
        request["binding"]["model_source_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            inverse.propose_readout_edit(*encoded(request))

    def test_coordinate_order_and_boolean_index_rejected(self):
        request = fixture()
        request["coordinates"].reverse()
        with self.assertRaises(ValueError):
            inverse.propose_readout_edit(*encoded(request))
        request = fixture()
        request["coordinates"][0]["flat_index"] = False
        with self.assertRaises(ValueError):
            inverse.propose_readout_edit(*encoded(request))

    def test_duplicate_json_key_rejected(self):
        raw, _ = encoded(fixture())
        changed = b'{"schema":"bad",' + raw[1:]
        with self.assertRaises(ValueError):
            inverse.propose_readout_edit(changed, digest(changed))

    def test_nonfinite_json_constant_rejected(self):
        raw, _ = encoded(fixture())
        changed = raw.replace(b'"weight_hex":"0x1.0000000000000p+0"', b'"weight_hex":NaN', 1)
        with self.assertRaises(ValueError):
            inverse.propose_readout_edit(changed, digest(changed))

    def test_rounding_bound_is_separate_from_exact_residual(self):
        result = inverse.propose_readout_edit(*encoded(fixture(features=(1.0, 4.0), targets=(0.0, 1.0))))
        self.assertEqual([fraction(value) for value in result["delta_exact"]], [Fraction(-1, 3), Fraction(1, 3)])
        self.assertEqual(fraction(result["exact_max_abs_residual"]), 0)
        self.assertGreater(fraction(result["binary64_delta_projection_max_abs_residual"]), 0)
        self.assertEqual(fraction(result["inverse_linf_norm"]), Fraction(5, 3))


if __name__ == "__main__":
    unittest.main()

"""Structural gate tests, not native execution receipts."""
import copy
import unittest
from verify_platform_types_semantic_bounds import verify


class SemanticBoundsTests(unittest.TestCase):
    def test_native_schema_and_hptc_agree_or_fail_closed(self):
        catalog = {"protocols": [{"id": "PromptDeliveryObservationV2", "fields": [
            {"name": "observed_token_positions", "wireType": "required_nullable_u32_array", "maximumEncodedBytes": 16384}]}]}
        schema = {"required": ["observed_token_positions"], "properties": {
            "observed_token_positions": {"oneOf": [{"type": "null"}, {
                "type": "array", "minItems": 1, "maxItems": 4096,
                "items": {"type": "integer", "minimum": 0, "maximum": 4294967295},
                "x-hepta-invariant": "strictly_increasing"}]}}}
        self.assertEqual(verify(catalog, schema)["maximumPositions"], 4096)
        for mutation in (
            lambda c, s: c["protocols"][0]["fields"][0].update(maximumEncodedBytes=32768),
            lambda c, s: s["properties"]["observed_token_positions"]["oneOf"][1].update(maxItems=8192),
            lambda c, s: s["properties"]["observed_token_positions"]["oneOf"][1]["items"].update(maximum=9007199254740991),
            lambda c, s: s["required"].clear(),
        ):
            c, s = copy.deepcopy(catalog), copy.deepcopy(schema)
            mutation(c, s)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify(c, s)


if __name__ == "__main__":
    unittest.main()

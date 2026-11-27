"""Shared-support selector behavior; supplied logits are not a model execution."""

import copy
from dataclasses import replace
import unittest

from .candidate_memory import CandidateScope
from .candidate_selector import BINDINGS, PROFILE, paired_selection, validate_profile
from .objective import canonical_sha


def inputs(field="total"):
    vector = [0.0] * 126
    vector[100], vector[104], vector[107], vector[119] = 0.9, 1.0, 1.0, 1.0
    if field != "total":
        vector[119] = 0.0
        vector[116 + ("company", "date", "address", "total").index(field)] = 1.0
    return {
        "mode": "frozen_neural",
        "field": field,
        "scope": CandidateScope("operation", "case", "a" * 64, 100, 100),
        "candidates": [
            {"text": "noise", "bbox": [0, 0, 50, 10], "origin": "pixel_ocr"},
            {"text": "RM 12.50", "bbox": [0, 80, 50, 90], "origin": "pixel_ocr"},
        ],
        "features": [list(vector), list(vector)],
        "neural_logits": [2.0, 1.0],
        "bindings": {k: "b" * 64 for k in BINDINGS},
    }


class SelectorTests(unittest.TestCase):
    def test_two_modes_share_exact_support_and_do_not_mutate_caller(self):
        kwargs = inputs()
        frozen = copy.deepcopy(kwargs)
        a = paired_selection(**kwargs)
        kwargs["mode"] = "public_rule"
        b = paired_selection(**kwargs)
        self.assertEqual((a["selected_index"], b["selected_index"]), (0, 1))
        for key in (
            "support_sha256",
            "candidate_metadata_sha256",
            "candidate_features_sha256",
            "neural_logits_sha256",
            "frozen_neural_index",
            "public_rule_index",
        ):
            self.assertEqual(a[key], b[key])
        kwargs["mode"] = "frozen_neural"
        self.assertEqual(kwargs, frozen)
        self.assertFalse(a["upstream_model_and_ocr_cost_included"])
        self.assertGreaterEqual(a["selection_cpu_seconds"], 0.0)

    def test_ascii_escaping_matches_existing_runtime_hash_and_scope_is_bound(self):
        kwargs = inputs()
        kwargs["candidates"][0]["text"] = "München 商店"
        a = paired_selection(**kwargs)
        self.assertEqual(
            a["candidate_metadata_sha256"], canonical_sha(kwargs["candidates"])
        )
        self.assertEqual(
            a["candidate_features_sha256"], canonical_sha(kwargs["features"])
        )
        kwargs["scope"] = replace(kwargs["scope"], original_operation_id="next")
        self.assertNotEqual(
            a["support_sha256"], paired_selection(**kwargs)["support_sha256"]
        )
        kwargs["features"][0][100] = 0.8
        self.assertNotEqual(
            a["candidate_features_sha256"],
            paired_selection(**kwargs)["candidate_features_sha256"],
        )

    def test_private_fields_and_incomplete_identity_are_rejected(self):
        for change in ("candidate_label", "binding_label", "missing_binding"):
            kwargs = inputs()
            if change == "candidate_label":
                kwargs["candidates"][0]["expected_text"] = "hidden"
            elif change == "binding_label":
                kwargs["bindings"]["reference_sha256"] = "c" * 64
            else:
                kwargs["bindings"].pop("weights_sha256")
            with self.subTest(change=change), self.assertRaises(ValueError):
                paired_selection(**kwargs)
        with self.assertRaises(TypeError):
            paired_selection(**inputs(), reference="hidden")
        profile = {
            "schema": PROFILE["schema"],
            "mode": "public_rule",
            "profile_sha256": canonical_sha(PROFILE),
        }
        checked = validate_profile(profile)
        checked["mode"] = "frozen_neural"
        self.assertEqual(profile["mode"], "public_rule")
        for change in (
            {"mode": "unknown"},
            {"profile_sha256": "0" * 64},
            {"reference": "hidden"},
        ):
            with self.subTest(profile=change), self.assertRaises(ValueError):
                validate_profile({**profile, **change})

    def test_malformed_features_logits_and_original_image_bounds_are_rejected(self):
        changes = (
            lambda k: k["features"][0].pop(),
            lambda k: k["features"][0].__setitem__(0, float("nan")),
            lambda k: k["features"][0].__setitem__(0, True),
            lambda k: k["features"][0].__setitem__(104, 0.5),
            lambda k: k["features"][0].__setitem__(116, 1.0),
            lambda k: k["features"][0].__setitem__(100, 1.1),
            lambda k: k["neural_logits"].__setitem__(0, float("inf")),
            lambda k: k["candidates"][0]["bbox"].__setitem__(2, 101),
            lambda k: k["candidates"].__setitem__(1, copy.deepcopy(k["candidates"][0])),
        )
        for index, change in enumerate(changes):
            kwargs = inputs()
            change(kwargs)
            with self.subTest(index=index), self.assertRaises(ValueError):
                paired_selection(**kwargs)

    def test_public_ties_follow_content_while_neural_ties_keep_first_index(self):
        kwargs = inputs()
        kwargs["neural_logits"] = [1.0, 1.0]
        kwargs["candidates"][0]["text"], kwargs["candidates"][1]["text"] = (
            "20.00",
            "10.00",
        )
        first = paired_selection(**kwargs)
        self.assertEqual(
            (first["frozen_neural_index"], first["public_rule_index"]), (0, 1)
        )
        kwargs["candidates"].reverse()
        kwargs["features"].reverse()
        second = paired_selection(**kwargs)
        self.assertEqual(
            (second["frozen_neural_index"], second["public_rule_index"]), (0, 0)
        )
        self.assertNotEqual(first["support_sha256"], second["support_sha256"])

    def test_empty_ocr_support_and_historical_candidates_remain_admissible(self):
        kwargs = inputs()
        kwargs["candidates"] = [
            {"text": "", "bbox": [0, 0, 100, 100], "origin": "no_recognized_text"}
        ]
        kwargs["features"], kwargs["neural_logits"] = [[0.0] * 126], [0.0]
        a = paired_selection(**kwargs)
        self.assertEqual((a["frozen_neural_index"], a["public_rule_index"]), (0, 0))
        original = inputs()
        kwargs["candidates"].append(original["candidates"][1])
        kwargs["features"].append(original["features"][1])
        kwargs["neural_logits"].append(1.0)
        self.assertEqual(paired_selection(**kwargs)["public_rule_index"], 1)


if __name__ == "__main__":
    unittest.main()

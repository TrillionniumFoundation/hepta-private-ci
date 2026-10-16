"""V19 negative-case tests: historic SHA cannot double as numeric-parity policy."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import v19_replay_equivalence_gate as audit

HERE = Path(__file__).resolve().parent
HISTORY = HERE / "STEM_V18_SOURCE_FIRST_20261016.json"
HOLD = HERE / "STEM_V18_FUTURE_SOURCE_HOLD_20261016.json"


class SourceOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original, cls.old_hold = audit.history(HISTORY, HOLD)

    def test_historical_is_byte_pinned(self):
        self.assertEqual(audit.sha(HISTORY.read_bytes()), audit.FROZEN_RECEIPT_SHA)
        self.assertEqual(audit.sha(HOLD.read_bytes()), audit.FROZEN_HOLD_SHA)

    def test_historical_is_only_calibration(self):
        self.assertFalse(self.original["production_authorized"])
        self.assertEqual(self.original["resampling_units"], 32)
        self.assertEqual(self.original["prospective_outcomes"], 0)
        self.assertEqual(self.old_hold["new_signed_window_count"], 0)

    def test_exact_historical_compare(self):
        result = audit.bounded_compare(self.original, copy.deepcopy(self.original))
        self.assertEqual(result["max_absolute_delta"], 0)
        self.assertEqual(result["changed_numbers"], 0)

    def test_strict_finite_numeric_replay_small_drift(self):
        clone = copy.deepcopy(self.original)
        clone["arms"]["geo_aligned_oof"]["case_mean"] += 1e-8
        clone["v17_sealed_sha256"] = "0" * 64
        out = audit.bounded_compare(self.original, clone)
        self.assertGreater(out["changed_numbers"], 0)
        self.assertGreater(out["max_absolute_delta"], 0)
        self.assertLess(out["max_absolute_delta"], audit.MAX_ABSOLUTE_NUMERIC_DRIFT)

    def test_rehashed_favorable_outcome_does_not_pass(self):
        clone = copy.deepcopy(self.original)
        clone["arms"]["geo_aligned_oof"]["case_mean"] += .002
        with self.assertRaisesRegex(ValueError, "unqualified score"):
            audit.bounded_compare(self.original, clone)

    def test_missing_or_extra_arm_fails(self):
        clone = copy.deepcopy(self.original)
        clone["arms"].pop("constant0")
        with self.assertRaises(ValueError):
            audit.bounded_compare(self.original, clone)
        clone = copy.deepcopy(self.original)
        clone["arms"]["nonexistent"] = clone["arms"]["constant0"]
        with self.assertRaises(ValueError):
            audit.bounded_compare(self.original, clone)

    def test_changed_source_roster_fails(self):
        clone = copy.deepcopy(self.original)
        clone["calibration_case_roster_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            audit.bounded_compare(self.original, clone)

    def test_changed_family_or_seed_count_fails(self):
        clone = copy.deepcopy(self.original)
        clone["correlated_training_seeds"] = ["41", "47", "54"]
        with self.assertRaises(ValueError):
            audit.bounded_compare(self.original, clone)

    def test_changed_authority_flags_fail(self):
        for key, value in (("production_authorized", True),
                           ("scientific_promotion_authorized", True),
                           ("prospective_outcomes", 200),
                           ("future_utility_gain", .1)):
            clone = copy.deepcopy(self.original)
            clone[key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                audit.bounded_compare(self.original, clone)

    def test_booleans_cannot_be_replaced_by_ints(self):
        clone = copy.deepcopy(self.original)
        clone["production_authorized"] = 0
        with self.assertRaisesRegex(ValueError, "type changed"):
            audit.bounded_compare(self.original, clone)

    def test_nonfinite_and_wrong_numeric_type_fail(self):
        for value in (float("nan"), float("inf"), -100, ".3"):
            clone = copy.deepcopy(self.original)
            clone["arms"]["geo_aligned_oof"]["case_mean"] = value
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                audit.bounded_compare(self.original, clone)

    def test_v17_seal_digest_must_be_hex(self):
        for new in ("!" * 64, "not-a-sha", "0" * 63):
            clone = copy.deepcopy(self.original)
            clone["v17_sealed_sha256"] = new
            with self.subTest(new=new), self.assertRaises(ValueError):
                audit.bounded_compare(self.original, clone)

    def test_duplicate_json_fields_denied(self):
        with self.assertRaises(ValueError):
            audit.parse(b'{"status":"a","status":"b"}\n')
        for string in (b'{"n":NaN}', b'{"n":Infinity}'):
            with self.assertRaises(ValueError):
                audit.parse(string)

    def test_frozen_historical_rewrite_rejected_even_when_rehashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "report.json"
            clone = copy.deepcopy(self.original)
            clone["arms"]["constant0"]["case_mean"] += 1e-8
            bad.write_bytes(audit.canonical(clone))
            with self.assertRaisesRegex(ValueError, "historical V18 receipt bytes modified"):
                audit.history(bad, HOLD)

    def test_frozen_hold_rewrite_rejected_even_when_rehashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "hold.json"
            clone = copy.deepcopy(self.old_hold)
            clone["new_source_roots"] = 200
            bad.write_bytes(audit.canonical(clone))
            with self.assertRaisesRegex(ValueError, "historical V18 HOLD bytes modified"):
                audit.history(HISTORY, bad)

    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "receipt.json"
            link.symlink_to(HISTORY)
            with self.assertRaises(ValueError):
                audit.history(link, HOLD)

    def test_create_only_write_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "once.json"
            with path.open("xb") as f:
                f.write(audit.canonical({"authority": "DENY_ALL"}))
            with self.assertRaises(FileExistsError):
                with path.open("xb") as f:
                    f.write(b"{}")


@unittest.skipUnless(all(os.environ.get(x) for x in
    ("HEPTA_V18_INPUTS", "HEPTA_V18_V15", "HEPTA_V18_V16", "HEPTA_V18_V17")),
    "exact original trained tensor snapshots not present; never call this original suite PASS")
class Original(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folders = [os.environ[k] for k in
            ("HEPTA_V18_INPUTS", "HEPTA_V18_V15", "HEPTA_V18_V16", "HEPTA_V18_V17")]
        cls.result = audit.execute(*cls.folders, HISTORY, HOLD)

    def test_actual_original_full_replay_and_negative_gate(self):
        self.assertEqual(self.result["independently_replayed_model_files"], 82)
        self.assertEqual(self.result["historical_calibration_cases"], 32)
        self.assertEqual(self.result["candidate_arm_count"], 12)
        self.assertLess(self.result["numerical_check"]["max_absolute_delta"], 5e-7)
        self.assertFalse(self.result["scientific_promotion_authorized"])
        self.assertFalse(self.result["production_authorized"])
        self.assertIsNone(self.result["new_model_utility_gain"])
        self.assertEqual(self.result["authority_posture"], "DENY_ALL")

    def test_historical_and_replay_sha_separated(self):
        self.assertEqual(self.result["frozen_v18_receipt_sha256"], audit.FROZEN_RECEIPT_SHA)
        self.assertTrue(len(self.result["replay_v18_receipt_sha256"]) == 64)
        self.assertIs(type(self.result["byte_identical"]), bool)

    def test_rehashed_original_prediction_tamper_fails(self):
        inp, v15, v16, v17 = self.folders
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "v17"
            shutil.copytree(v17, out)
            sealed = out / "sealed.json"
            obj = json.loads(sealed.read_bytes())
            obj["seeds"]["41"]["calibration_probabilities"]["geo_aligned_oof"][0] = [1, 0, 0, 0]
            sealed.write_bytes(audit.canonical(obj))
            with self.assertRaises(ValueError):
                audit.execute(inp, v15, v16, out, HISTORY, HOLD)

    def test_injected_original_hold_label_fails(self):
        inp, v15, v16, v17 = self.folders
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "inputs"
            shutil.copytree(inp, out)
            label = out / "input.json"
            obj = json.loads(label.read_bytes())
            obj["labels"][str(obj["partitions"]["holdout"][0])] = 1
            label.write_bytes(audit.canonical(obj))
            with self.assertRaises(ValueError):
                audit.execute(out, v15, v16, v17, HISTORY, HOLD)


if __name__ == "__main__":
    unittest.main()

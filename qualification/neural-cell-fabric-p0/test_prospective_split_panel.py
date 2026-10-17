"""Negative, source-bound controls for P0.6. Synthetic fixtures are not efficacy."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from prospective_split_panel import ARMS, GOLD_SCHEMA, PRED_SCHEMA, Rejected, _read_file, _write_exclusive, review


def packet():
    pre = {"schema": PRED_SCHEMA, "study_id": "synthetic-p06", "source_families": ["fam1", "fam2"],
           "fit_roots": ["fit-1"], "calibration_roots": ["cal-1"], "arms": list(ARMS),
           "work": {arm: {"encoder_calls": 1, "head_calls": 4, "cpu_us": 1000,
                          "resident_bytes": 4096} for arm in ARMS},
           "predictions": [], "authority": "DENY_ALL"}
    gold = {"schema": GOLD_SCHEMA, "study_id": pre["study_id"], "source_families": list(pre["source_families"]),
            "outcomes": [], "authority": "DENY_ALL"}
    for family in pre["source_families"]:
        for group in range(3):
            for case in range(2):
                case_id = f"{family}-{group}-{case}"
                root = f"{family}-root-{group}"
                y = (group + case) % 2
                gold["outcomes"].append({"case_id": case_id, "root": root, "family": family, "label": y})
                for arm in ARMS:
                    # Split dominates the other four arms, but cannot issue authority.
                    p = (.95 if y else .05) if arm == "split" else (.05 if y else .95)
                    pre["predictions"].append({"case_id": case_id, "root": root, "family": family,
                                               "arm": arm, "p1": p})
    return pre, gold


def encoded(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def run(pre, gold):
    pred = encoded(pre)
    return review(pred, encoded(gold), hashlib.sha256(pred).hexdigest())


class PanelTests(unittest.TestCase):
    def test_perfect_synthetic_split_never_promotes(self):
        p, g = packet()
        r = run(p, g)
        self.assertEqual((r["status"], r["authority"]), ("HOLD_NO_GO", "DENY_ALL"))
        self.assertFalse(r["model_selection_authorized"])
        self.assertFalse(r["cell_split_authorized"])
        self.assertFalse(r["production_accepted"])
        self.assertFalse(r["ndu_utility_verified"])
        for f in ("fam1", "fam2"):
            q = r["source_families"][f]
            self.assertEqual(q["cases"], 6)
            self.assertEqual(q["independent_roots_declared"], 3)
            self.assertEqual(q["arm_metrics"]["split"]["correct"], 6)
            self.assertEqual(q["arm_metrics"]["equal_budget_single"]["correct"], 0)
            self.assertEqual(q["paired_vs_split"]["zero_feature"]["split_only_correct"], 6)
            self.assertEqual(q["paired_vs_split"]["type_prior"]["baseline_only_correct"], 0)
            self.assertIsNotNone(q["paired_vs_split"]["no_change"]["root_bootstrap_95pct_descriptive"])

    def test_changed_prelabel_denied_by_pinned_hash(self):
        p, g = packet()
        raw = encoded(p)
        pinned = hashlib.sha256(raw).hexdigest()
        p["predictions"][0]["p1"] = 0.73
        with self.assertRaises(Rejected):
            review(encoded(p), encoded(g), pinned)

    def test_duplicate_json_key_denied(self):
        p, g = packet()
        content = encoded(p).replace(b'"study_id":"synthetic-p06"',
                                     b'"study_id":"synthetic-p06","study_id":"forged"')
        with self.assertRaises(Rejected):
            review(content, encoded(g), hashlib.sha256(content).hexdigest())

    def test_bad_nonfinite_probability(self):
        p, g = packet()
        p["predictions"][0]["p1"] = float("nan")
        raw = json.dumps(p).encode()
        with self.assertRaises(Rejected):
            review(raw, encoded(g), hashlib.sha256(raw).hexdigest())

    def test_missing_physical_arm_row(self):
        p, g = packet()
        p["predictions"].pop()
        with self.assertRaisesRegex(Rejected, "incomplete paired"):
            run(p, g)

    def test_fake_unmatched_gold_or_missing(self):
        p, g = packet()
        g["outcomes"][0]["root"] = "other"
        with self.assertRaises(Rejected):
            run(p, g)
        p, g = packet()
        g["outcomes"].pop()
        with self.assertRaises(Rejected):
            run(p, g)

    def test_fit_and_calibration_overlap(self):
        p, g = packet()
        p["calibration_roots"].append("fit-1")
        with self.assertRaisesRegex(Rejected, "fit/calibration overlap"):
            run(p, g)
        p, g = packet()
        p["fit_roots"].append("fam1-root-0")
        with self.assertRaisesRegex(Rejected, "held source root"):
            run(p, g)

    def test_cross_family_root_reuse(self):
        p, g = packet()
        row = next(v for v in p["predictions"] if v["family"] == "fam2")
        row["root"] = "fam1-root-0"
        with self.assertRaises(Rejected):
            run(p, g)

    def test_duplicate_prediction_or_missing_control(self):
        p, g = packet()
        p["predictions"].append(copy.deepcopy(p["predictions"][0]))
        with self.assertRaisesRegex(Rejected, "duplicate physical"):
            run(p, g)
        p, g = packet()
        p["work"].pop("zero_feature")
        with self.assertRaisesRegex(Rejected, "resource census"):
            run(p, g)

    def test_bool_work_and_gold_denied(self):
        p, g = packet()
        p["work"]["split"]["head_calls"] = True
        with self.assertRaises(Rejected):
            run(p, g)
        p, g = packet()
        g["outcomes"][0]["label"] = True
        with self.assertRaises(Rejected):
            run(p, g)

    def test_cross_task_pooled_p_value_not_claimed(self):
        p, g = packet()
        q = run(p, g)
        self.assertNotIn("pooled_p", q)
        self.assertEqual(set(q["source_families"]), {"fam1", "fam2"})
        self.assertIn("cluster_bootstrap_is_descriptive_not_prospective_inference", q["limitations"])

    def test_symlink_or_output_overwrite_denied(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "data.json"
            path.write_bytes(b"{}")
            shortcut = Path(root) / "link"
            shortcut.symlink_to(path)
            with self.assertRaises(Rejected):
                _read_file(shortcut)
            with self.assertRaises(Rejected):
                _write_exclusive(shortcut, b"fake")
            with self.assertRaises(Rejected):
                _write_exclusive(path, b"fake")
            fresh = Path(root) / "new.json"
            _write_exclusive(fresh, b"test")
            self.assertEqual(fresh.read_bytes(), b"test")
            self.assertEqual(fresh.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(Rejected):
                _write_exclusive(fresh, b"rewrite")

    def test_absent_and_invalid_gold_fields_denied(self):
        p, g = packet()
        g.pop("study_id")
        with self.assertRaises(Rejected):
            run(p, g)
        p, g = packet()
        g["outcomes"][0]["gold_label"] = g["outcomes"][0]["label"]
        with self.assertRaises(Rejected):
            run(p, g)


if __name__ == "__main__":
    unittest.main()

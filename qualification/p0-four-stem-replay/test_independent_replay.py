"""Tamper controls for the actual Actions-pinned four-model numeric replay."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from independent_replay import (AuditError, HEADS, SOURCE_ARCHIVE_SHA,
    PHYSICAL_ARCHIVE_SHA, SOURCE_PANEL_SHA, audit, canonical, compute_arm,
    exact_mcnemar, nearest_rank, parse, parse_reports, read_archive,
    sha_bytes, validate_panel)


class PhysicalFourModelReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = os.environ.get("HEPTA_P0_HISTORICAL_ZIP")
        cls.real = os.environ.get("HEPTA_P0_PHYSICAL_ZIP")
        if not cls.old or not cls.real:
            raise RuntimeError("Pinned real ZIPs are mandatory; no synthetic fallback")
        cls.ref = read_archive(cls.old, SOURCE_ARCHIVE_SHA)
        cls.physical = read_archive(cls.real, PHYSICAL_ARCHIVE_SHA)
        cls.panel = parse(cls.ref["stem-agnews-new-source-panel.json"])
        cls.labels = validate_panel(cls.panel)

    def test_exact_128_source_records_and_predictions(self):
        result = audit(self.old, self.real)
        self.assertEqual(result["observed_source_groups"], 128)
        self.assertEqual(result["real_stem_models"]["granite97"]["arms"]["learned_gate"]["correct"], 122)
        self.assertEqual(result["real_stem_models"]["mmbert_small"]["arms"]["learned_gate"]["correct"], 73)
        self.assertEqual(result["historical_context"]["laya421_frozen"]["correct"], 124)
        self.assertFalse(result["production_accepted"])
        self.assertFalse(result["full_four_model_equal_resource_winner"])

    def test_fixed_run_and_original_historical_archive_identity(self):
        self.assertEqual(sha_bytes(Path(self.old).read_bytes()), SOURCE_ARCHIVE_SHA)
        self.assertEqual(sha_bytes(Path(self.real).read_bytes()), PHYSICAL_ARCHIVE_SHA)
        self.assertEqual(sha_bytes(canonical(self.panel)), SOURCE_PANEL_SHA)

    def test_recompute_128_rows_not_trust_report_aggregates(self):
        report = parse(self.physical["granite97.report.json"])
        rows = {x["case_id"]: (x["probs"]["learned_gate"],
                (x["group_id"],x["joint_input_digest"]))
                for x in report["future_predictions"] if x["split"]=="new_holdout"}
        counts, _ = compute_arm(rows, self.labels)
        self.assertEqual(counts["correct"], 122)
        self.assertAlmostEqual(counts["brier"], 0.03988751591276781, places=12)

    def test_paired_counts_against_real_independent_historical_labels(self):
        pair = audit(self.old, self.real)["paired_new_holdout"]
        self.assertEqual((pair["granite97 vs mmbert_small learned_gate"]["left_correct_only"],
                          pair["granite97 vs mmbert_small learned_gate"]["right_correct_only"]), (53,4))
        self.assertEqual((pair["granite97 vs laya421 frozen"]["left_correct_only"],
                          pair["granite97 vs laya421 frozen"]["right_correct_only"]), (1,3))

    def test_exact_mcnemar(self):
        self.assertAlmostEqual(exact_mcnemar(53,4), 5.910882894255565e-12)
        self.assertEqual(exact_mcnemar(0,0), 1)
        self.assertEqual(exact_mcnemar(1,3), .625)

    def test_missing_latency_rejected(self):
        with self.assertRaises(AuditError):
            nearest_rank([.1]*99, .99)

    def test_bad_latency_rejected(self):
        for v in [float("nan"), float("inf"), -1, True]:
            with self.subTest(v=v), self.assertRaises(AuditError):
                nearest_rank([.1]*100+[v], .99)

    def test_panel_source_text_changed_rejected(self):
        x = copy.deepcopy(self.panel)
        x["cases"][0]["joint_input"]["state"] += " ATTACK"
        with self.assertRaises(AuditError):validate_panel(x)

    def test_panel_label_changed_rejected(self):
        x=copy.deepcopy(self.panel); x["cases"][0]["label"] ^= 1
        with self.assertRaises(AuditError):validate_panel(x)

    def test_duplicated_or_missing_source_rejected(self):
        for op in ("duplicate", "missing"):
            x=copy.deepcopy(self.panel)
            if op=="duplicate": x["cases"][0]=copy.deepcopy(x["cases"][1])
            else: x["cases"].pop()
            with self.assertRaises(AuditError):validate_panel(x)

    def test_model_report_changed_without_original_seals_rejected(self):
        x=copy.deepcopy(self.physical)
        report=parse(x["granite97.report.json"])
        report["future_predictions"][0]["probs"]["learned_gate"] = .999
        x["granite97.report.json"] = canonical(report)
        with self.assertRaises(AuditError):parse_reports(self.ref,x,self.labels)

    def test_report_labels_cannot_be_smuggled(self):
        x=copy.deepcopy(self.physical)
        rep=parse(x["granite97.report.json"])
        rep["future_predictions"][0]["label"]=1
        x["granite97.report.json"]=canonical(rep)
        with self.assertRaises(AuditError):parse_reports(self.ref,x,self.labels)

    def test_absent_model_report_fails_closed(self):
        x=dict(self.physical); del x["mmbert_small.report.json"]
        with self.assertRaises(KeyError):parse_reports(self.ref,x,self.labels)

    def test_historical_arms_complete(self):
        x=copy.deepcopy(self.ref);arr=parse(x["stem-gemma-fresh-arms.json"]);arr.pop()
        x["stem-gemma-fresh-arms.json"]=canonical(arr)
        with self.assertRaises(AuditError):parse_reports(x,self.physical,self.labels)

    def test_declared_output_no_production_authority(self):
        x=audit(self.old,self.real)
        for k in ("production_accepted", "pretrained_weight_origin_authenticated",
                  "full_four_model_equal_resource_winner", "full_encoder_4096_cell_execution",
                  "native_neuron_checkpoint_witness", "future_observation_time_verified"):
            self.assertIs(x[k],False)
        self.assertEqual(x["authority"],"DENY_ALL")

    def test_changed_archive_bytes_rejected_before_parsing(self):
        source=Path(self.real)
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"mutated.zip"
            blob=bytearray(source.read_bytes()); blob[-25]^=1
            dest.write_bytes(blob)
            with self.assertRaises(AuditError):read_archive(dest, PHYSICAL_ARCHIVE_SHA)

    def test_truncated_archive_rejected(self):
        source=Path(self.real)
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"truncated.zip"
            dest.write_bytes(source.read_bytes()[:-50])
            with self.assertRaises(AuditError):read_archive(dest, PHYSICAL_ARCHIVE_SHA)


if __name__ == "__main__":unittest.main()

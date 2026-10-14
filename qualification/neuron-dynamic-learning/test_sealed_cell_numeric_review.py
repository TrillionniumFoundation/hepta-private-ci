"""Adversarial standalone numeric reviewer, with synthetic model outputs only."""
from __future__ import annotations

import copy
import sys
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from sealed_cell_checkpoint import _canonical, _sha, seal_checkpoint
from sealed_cell_replay import evaluate
from sealed_cell_numeric_review import NumericReviewError, review
from test_sealed_cell_checkpoint import FakeDynamicCell, fake_cell, fixture_args
from test_sealed_cell_replay import DummyRunner, fixtures
import public_agnews_confirmatory as confirm


class NumericReview(unittest.TestCase):
    def setUp(self):
        self.mock=patch.dict(sys.modules,{"cell_learning":types.SimpleNamespace(
            DynamicCell=FakeDynamicCell,
            rust_candidate_digest=lambda value:_sha(_canonical(value)))})
        self.mock.start()
        self.dir=tempfile.TemporaryDirectory()
        self.path=Path(self.dir.name)/"new-candidate.json"
        self.original,self.val2,self.digest=fixtures()
        seal_checkpoint(self.path,fake_cell(),fake_cell(.002),
                        **dict(fixture_args(),source_panel_digest=self.digest))
        with patch.object(confirm,"SOURCE_PANEL_SHA256",self.digest):
            self.result=evaluate(original_panel=self.original,val2_panel=self.val2,
                                 runner=DummyRunner(),bundle_path=self.path)
        from sealed_cell_checkpoint import load_checkpoint
        self.receipt=load_checkpoint(self.path,source_panel_digest=self.digest,
                model_revision="c"*40,pipeline_digest="a"*64,
                scope_id="public.agnews",purpose_id="capability.noeffects",
                generation=1, authority_epoch=1)["receipt"]
        self.rows=[{"text":f"new.holdout.{i}","label":i%2} for i in range(200)]

    def tearDown(self):
        self.dir.cleanup()
        self.mock.stop()

    def check(self,report=None,val2=None,rows=None,receipt=None):
        with patch.object(confirm,"SOURCE_PANEL_SHA256",self.digest):
            return review(original=self.original,val2=val2 or self.val2,
                raw_source_rows=rows or self.rows,report=report or self.result,
                bundle=self.path,runtime_receipt=receipt or self.receipt)

    def test_new_candidate_replay_screens_are_not_finaluse(self):
        r=self.check()
        self.assertTrue(r["new_snapshot_exact_float64_reloaded"])
        self.assertEqual(r["val2_panel_sha256"],self.result["val2_panel_digest"])
        self.assertFalse(r["historical_old_head_exact_replay_claimed"])
        self.assertFalse(r["future_time_window_independently_attested"])
        self.assertEqual(r["production_promotion"],"DENY_ALL")
        self.assertEqual(len(r["metrics"]),3)

    def test_bad_source_labels_and_recycled_cases_rejected(self):
        for issue in ("label","duplicate_case","input_digest"):
            panel=copy.deepcopy(self.val2)
            if issue=="label":
                panel["cases"][0]["label"]=1-panel["cases"][0]["label"]
            if issue=="duplicate_case":
                panel["cases"][1]["case_id"]=panel["cases"][0]["case_id"]
            if issue=="input_digest":
                panel["cases"][0]["joint_input_digest"]="0"*64
            with self.subTest(issue=issue),self.assertRaises((NumericReviewError,ValueError)):
                self.check(val2=panel)

    def test_tampered_metric_model_scope_scale_or_snapshot_rejected(self):
        for issue in ("metric","case","scale","promotion","snapshot","receipt"):
            output=copy.deepcopy(self.result)
            source=copy.deepcopy(self.receipt)
            if issue=="metric":
                output["arms"]["gemma2_trained_head"]["metrics"]["accuracy"]=.999
            if issue=="case":
                output["arms"]["gemma2_frozen_head"]["rows"][0]["source_digest"]="0"*64
            if issue=="scale":
                output["arms"]["gemma2_trained_head_scaled_1024"]["rows"][0]["prob_sports"]=.8
            if issue=="promotion":output["production_promotion"]="ALLOW"
            if issue=="snapshot":output["snapshot_file_sha256"]="0"*64
            if issue=="receipt":source["snapshot_file_sha256"]="0"*64
            with self.subTest(issue=issue),self.assertRaises(NumericReviewError):
                self.check(report=output,receipt=source)

    def test_old_model_history_not_fabricated(self):
        out=copy.deepcopy(self.result)
        out["historical_20261014_head_byte_identity_claimed"]=True
        with self.assertRaises(NumericReviewError):self.check(report=out)


if __name__=='__main__':unittest.main()

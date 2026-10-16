"""Original E3 P2 byte-admission workflow graph, independent source-only tests.

No model weights, media or retrospective TEST labels are ever loaded.
These validate exact prerequisite ordering, not physical execution.
"""
from __future__ import annotations
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/hepta-e3-five-arm-original-physical.yml"

def split():
    text = WORKFLOW.read_text(encoding="utf-8")
    header, jobs = text.split("\njobs:\n", 1)
    ocr = jobs.split("  physical-ocr-granite:\n", 1)[1].split("  physical-native-gemma2:\n", 1)[0]
    native = jobs.split("  physical-native-gemma2:\n", 1)[1].split("  independent-five-arm-review:\n", 1)[0]
    review = jobs.split("  independent-five-arm-review:\n", 1)[1]
    return text, header, ocr, native, review

class SourceByteCiInvariant(unittest.TestCase):
    def test_experimental_workflow_only_child_pushes(self):
        raw, header, *_ = split()
        self.assertIn('branches: ["research/e3-five-arm-byte-mutation-audit-20261016"]', header)
        self.assertIn("hepta-e3-five-real-", header)
        self.assertIn("github.event_name", header)
        self.assertNotIn("HELD_SHA", header)
        self.assertIn("  pull_request:\n", header)

    def test_original_predictors_have_identical_prepost_gate(self):
        _, _, ocr, native, _ = split()
        for job, name in ((ocr,"ocr"), (native,"native")):
            with self.subTest(name=name):
                self.assertIn("if: github.event_name == 'push'", job)
                self.assertIn("--predictor-source-only", job)
                self.assertIn("private_test_labels_sha256", job)
                self.assertIn(" is None", job)
                self.assertIn("test ! -e \"$RUNNER_TEMP/e3-source-cache\"", job)
                self.assertNotIn("HELD_SHA", job)
                self.assertIn("e3_model_entry_ledger.py", job)
                self.assertEqual(job.count("e3_model_entry_ledger.py"), 2)
                self.assertIn(f'e3-{name}-pre-view.json', job)
                self.assertIn(f'e3-{name}-post-view.json', job)
                self.assertIn(f'cmp "$RUNNER_TEMP/e3-{name}-pre-view.json" "$RUNNER_TEMP/e3-{name}-post-view.json"', job)

    def test_ocr_gate_runs_before_pretrained_acquisition(self):
        _, _, ocr, _, _=split()
        stages=["--predictor-source-only",
                "Validate no-TEST-target source tree BEFORE OCR/Granite97 inference",
                "Physically OCR all 192 sources and encode with original Granite97",
                "Independently recheck source tree AFTER OCR/Granite97 inference",
                "Save numeric OCR predictions, no media/model/labels"]
        ix=[ocr.index(s) for s in stages]
        self.assertEqual(ix, sorted(ix))

    def test_native_gate_runs_before_model_weight_download(self):
        _, _, _, native, _=split()
        stages=["--predictor-source-only",
                "Validate no-TEST-target source tree BEFORE native Gemma2 inference",
                "Download and verify reviewed native Google model snapshot",
                "Actually encode same natural images jointly with text and train 769 Head",
                "Independently recheck source tree AFTER native Gemma2 inference",
                "Save numeric native predictions, no raw weights/media/heldout targets"]
        ix=[native.index(s) for s in stages]
        self.assertEqual(ix,sorted(ix))

    def test_prepost_sources_are_uploaded_but_no_original_photos_or_targets(self):
        _, _, ocr, native, _=split()
        for job,name in ((ocr,"ocr"),(native,"native")):
            block=job.split("uses: actions/upload-artifact@",1)[1]
            self.assertIn(f'/e3-{name}-pre-view.json',block)
            self.assertIn(f'/e3-{name}-post-view.json',block)
            self.assertNotIn("e3-original-sources/",block)
            self.assertNotIn("test_labels",block)
            self.assertNotIn("images/",block)

    def test_independent_reviewer_blocks_wrong_tree_before_original_test_labels(self):
        _, _, _, _, review=split()
        stages=["Obtain three original source-matched REAL prediction artifacts",
                "Independently verify both physical model jobs excluded TEST label bytes before source scoring",
                "Seal exactly all five source-matched arms before opening heldout labels",
                "Independently restage ORIGINAL 64 TEST labels after predictions are sealed"]
        ix=[review.index(v) for v in stages]
        self.assertEqual(ix, sorted(ix))
        for assertion in ("hepta.e3-path-byte-sha256.v2",
                          "tree_fingerprint_file_count']==196",
                          "'tree_fingerprint'",
                          "'image_bytes_total'",
                          "test_target_bytes_or_digest_admitted"):
            self.assertIn(assertion, review)

    def test_negative_regression_if_original_source_tree_ledger_removed(self):
        _, _, _, _, review=split()
        self.assertIn("assert original.read_bytes()==successor.read_bytes()", review)
        self.assertIn("assert records[0][field]==records[1][field]", review)
        self.assertIn("result['production_accepted'] is False",review)

    def test_exact_model_identity_source_and_no_selected_production_owner(self):
        raw, *_=split()
        self.assertIn("835ad14087e140460703cf0fae09f97d469d65c2", (
            ROOT / "experiments/shared_stem_cell/e3_five_arm_historical.py").read_text())
        self.assertIn("914f7f89142e33e77833254d9c9b90c3cef7303b",raw)
        self.assertIn("DENY_ALL",raw)
        self.assertNotIn("on:\n  push:\n    branches: [\"main\"]",raw)

if __name__=="__main__":
    unittest.main()

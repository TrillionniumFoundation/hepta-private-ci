"""Actual Torch generated-task integration; neither BBH nor pretrained evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from fbsde_tracking_study import run
from fbsde_tracking_records import COMPACT, audit_recording
from fbsde_tracking_feature_audit import audit


class SerializedStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)/'study'
        cls.report = run(cls.root, feature_profile='local_participant_v2', record_profile=COMPACT)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_all_source_bound_state_outputs_remain_auditable(self):
        originals = json.loads((self.root/'originals.json').read_text())
        self.assertEqual(audit(self.root, originals)['state_outputs_checked'],1536)
        self.assertEqual(self.report['summary']['verified_recurrent']['correct'],192)

    def test_retention_and_outer_envelope_include_actual_record_work(self):
        r = audit_recording(self.root)
        self.assertEqual(r['streams'],9); self.assertEqual(r['rows'],5376)
        outer = json.loads((self.root/'completion-envelope.json').read_text())
        retained = json.loads((self.root/'record-retention.json').read_text())
        self.assertGreater(retained['recording_cpu_ns'],0)
        self.assertGreaterEqual(outer['cpu_through_audits_ns'],retained['recording_cpu_ns'])
        self.assertFalse(outer['production_promotion_permitted'])

    def test_original_budget_and_cheap_controls_remain(self):
        proposals = json.loads((self.root/'proposals.json').read_text())
        self.assertTrue(all(r['cpu_ns']==r['ended_cpu_ns']-r['started_cpu_ns'] for r in proposals))
        self.assertTrue(all(r['returned']==(r['cpu_ns']<=100_000_000) for r in proposals))
        self.assertEqual(self.report['summary']['exact_reverse']['correct'],192)
        self.assertEqual(self.report['summary']['exact_forward']['correct'],192)
        self.assertFalse(self.report['real_pretrained_executed'])


if __name__=='__main__':unittest.main()

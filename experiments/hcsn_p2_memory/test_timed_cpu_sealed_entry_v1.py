"""Prevent future scientific evidence from being silently overwritten."""
import tempfile
from pathlib import Path
from unittest import TestCase, mock
from . import timed_cpu_sealed_entry_v1 as subject
from .sealed_run_records_v1 import EvidenceUnresolved, verify_receipt

ID='copy-s2-aggregate_count-20261031-unique001'
GOOD={'schema':subject.timed_cpu_matched_v2.SCHEMA,'task':'copy','seed':2,
      'arm':'aggregate_count','production_activation':False,
      'all_scientific_blockers_closed':False,'reached_cpu_budget':True,'reached_step_cap':False,
      'training_cpu_seconds':25.0004}

class SealedEntryTests(TestCase):
    def test_cli_record_and_collision_without_retraining(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(subject.timed_cpu_matched_v2,'run',return_value=GOOD) as runner:
            r=subject.run_and_record('copy',2,'aggregate_count',Path(d),ID)
            runner.assert_called_once_with('copy',2,'aggregate_count')
            e=verify_receipt(Path(d),r)
            self.assertEqual(e['result']['source_sha256'],subject._source_seals())
            self.assertFalse(r['scientific_superiority_certified'])
            with self.assertRaises(EvidenceUnresolved):
                subject.run_and_record('copy',2,'aggregate_count',Path(d),ID)
            self.assertEqual(runner.call_count,1)

    def test_wrong_label_or_invalid_arm_refused_before_training(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(subject.timed_cpu_matched_v2,'run') as runner:
            for args in [('copy',2,'aggregate_count','copy-s4-aggregate_count-wrong11'),
                         ('copy',4,'aggregate_count',ID),
                         ('copy',2,'garbage','copy-s2-garbage-longunique'),
                         ('copy',2,'aggregate_count','short')]:
                with self.subTest(args=args),self.assertRaises(EvidenceUnresolved):
                    subject.run_and_record(*args[:3],Path(d),args[3])
            runner.assert_not_called()

    def test_failed_training_or_gate_never_published(self):
        for mutated in ({'reached_cpu_budget':False},{'reached_step_cap':True},
                        {'all_scientific_blockers_closed':True},{'task':'mqar4'}):
            with tempfile.TemporaryDirectory() as d, mock.patch.object(subject.timed_cpu_matched_v2,'run',return_value={**GOOD,**mutated}):
                with self.subTest(mutated=mutated),self.assertRaises(EvidenceUnresolved):
                    subject.run_and_record('copy',2,'aggregate_count',Path(d),ID)
                self.assertEqual(list(Path(d).glob('*.json')),[])

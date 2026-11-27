"""Wrapper smoke without retraining; do not claim 25-second runs here."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from .test_immutable_trial_receipts import record
from .immutable_trial_receipts import UnresolvedReceipt,publish
from .timed_cpu_matched_v3_immutable import run_and_publish,main

class V3RunnerTests(unittest.TestCase):
    def test_live_v2_result_written_without_mutable_intermediate(self):
        calls=[]
        def fake_run(task,seed,arm):
            calls.append((task,seed,arm))
            return record(task,seed,arm)
        fake=SimpleNamespace(run=fake_run)
        module=__package__+'.timed_cpu_matched_v2'
        with TemporaryDirectory() as td,patch.dict(sys.modules,{module:fake}):
            receipt=run_and_publish('mqar4',3,'physical_event_timestamp',Path(td))
            self.assertEqual(receipt.key,'mqar4.3.physical_event_timestamp')
            self.assertEqual(calls,[('mqar4',3,'physical_event_timestamp')])
            self.assertEqual(list(Path(td).glob('*.json')),[])

    def test_existing_key_refuses_before_training(self):
        with TemporaryDirectory() as td:
            publish(td,record())
            with self.assertRaises(UnresolvedReceipt):
                run_and_publish('copy',2,'aggregate_count',Path(td))

    def test_cli_verify_cannot_claim_incomplete_archive(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(UnresolvedReceipt):main(['verify','--archive',td])

    def test_invalid_seed_refused_before_training(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(UnresolvedReceipt):
                run_and_publish('copy',99,'aggregate_count',Path(td))

if __name__=='__main__':unittest.main()

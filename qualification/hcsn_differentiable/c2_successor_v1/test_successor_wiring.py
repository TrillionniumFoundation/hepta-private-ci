"""Successor runner/controller integration tests; no actual experiment launched."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import torch
import c2_io
from c2_io import immutable_checkpoint, exclusive_json, identity, state_equal
from c2_durable import producer_roster, append_receipt


class SuccessorWiringTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_actual_torch_optimizer_rng_and_frozen_data_roundtrip(self):
        torch.manual_seed(3)
        model = torch.nn.Linear(3, 2, dtype=torch.float64)
        opt = torch.optim.AdamW(model.parameters())
        opt.zero_grad()
        model(torch.ones((1,3),dtype=torch.float64)).square().sum().backward()
        opt.step()
        frozen = {'model':model.state_dict(), 'optimizer':opt.state_dict(),
          'torch_rng':torch.get_rng_state(), 'order_rng':(3,(1,2,3),None),
          'source_sha256':'b'*64, 'data_manifest_sha256':'a'*64}
        target = self.root/'epoch.pt'
        original=immutable_checkpoint(target, frozen)
        loaded=torch.load(target,weights_only=True,map_location='cpu')
        self.assertTrue(state_equal(loaded,frozen))
        self.assertEqual(identity(target),original)
        self.assertGreater(original['bytes'],0)
        with self.assertRaises(FileExistsError):
            immutable_checkpoint(target, frozen)
        self.assertEqual(identity(target),original)

    def test_serialize_exception_never_creates_zero_final_checkpoint(self):
        target=self.root/'interrupted.pt'
        def fail_during_save(value,stream):
            stream.write(b'partial-state')
            raise RuntimeError('simulate failure before publish')
        with mock.patch.object(c2_io.torch,'save',side_effect=fail_during_save):
            with self.assertRaises(RuntimeError):
                immutable_checkpoint(target,{'x':1})
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob('.c2-pending-*')),[])

    def test_checkpoint_incomplete_semantic_roundtrip_never_publishes(self):
        target=self.root/'mismatch.pt'
        real_load=c2_io.torch.load
        with mock.patch.object(c2_io.torch,'load',return_value={'incorrect':1}):
            with self.assertRaises(Exception):
                immutable_checkpoint(target,{'x':1})
        self.assertFalse(target.exists())

    def test_result_file_create_only_even_after_failure(self):
        target=self.root/'RESULT.json'
        before=exclusive_json(target,{'status':'failed'})
        with self.assertRaises(FileExistsError):
            exclusive_json(target,{'status':'completed'})
        self.assertEqual(identity(target),before)
        self.assertEqual(json.loads(target.read_text())['status'],'failed')

    def test_completed_producer_roster_remains_hold(self):
        root=self.root/'receipts'
        names=['hcsn-s101-lr0.001','hcsn-s211-lr0.003']
        for name in names:
            append_receipt(root,owner_start_id='owner-start-1',attempt_id=name,
               event_type='terminal',payload={'status':'failed',
               'native_job_id':'local-pid-12','result_sha256':'a'*64,
               'resource_sha256':'b'*64})
        state=producer_roster(root,owner_start_id='owner-start-1',expected_attempts=names)
        self.assertTrue(state['producer_complete'])
        self.assertFalse(state['independent_native_verification'])
        self.assertEqual(state['scientific_admission'],'HOLD')

    def test_both_real_c2_entrypoints_wired(self):
        runner=(Path(__file__).parent/'c2_runner.py').read_text()
        ctl=(Path(__file__).parent/'c2_controller.py').read_text()
        self.assertIn("append_receipt(out / 'runner-receipts'",runner)
        self.assertIn("append_receipt(out / 'controller-receipts'",ctl)
        self.assertIn("record(row, final=True)",ctl)
        self.assertIn("os.fsync(journal.fileno())",runner)
        self.assertIn("os.fsync(journal.fileno())",ctl)
        self.assertIn("HCSN_C2_OWNER_START_ID",ctl)
        self.assertIn("HCSN_C2_OWNER_START_ID",runner)


if __name__ == '__main__':
    unittest.main()

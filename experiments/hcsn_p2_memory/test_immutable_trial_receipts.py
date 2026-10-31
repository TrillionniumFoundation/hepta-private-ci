"""Process/filesystem regression tests for immutable P2 evidence publication."""
import copy
import os
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from .immutable_trial_receipts import (publish,read,audit,seal,verify_seal,recover_stages,
                                      UnresolvedReceipt,ARMS,SEEDS,TASKS)


def record(task='copy',seed=2,arm='aggregate_count'):
    return dict(schema='hcsn-p2-timed-cpu-matched-followup-v2',task=task,
                seed=seed,arm=arm,params=5186,
                initial_model_sha256='a'*64,trained_model_sha256='b'*64,
                train_data_sha256='c'*64,training_cpu_seconds=25.01,
                reached_step_cap=False,reached_cpu_budget=True,
                id={'correct':100,'queries':128,'accuracy':.78125},
                ood={'correct':90,'queries':128,'accuracy':.703125},
                unblinded_exploratory_followup=True,
                negative_evidence_retained=True,
                production_activation=False,all_scientific_blockers_closed=False)

class ReceiptTests(unittest.TestCase):
    def test_publish_read_back_and_refuse_overwrite(self):
        with TemporaryDirectory() as td:
            original=record()
            receipt=publish(td,original)
            read_back,out=read(td,receipt.key)
            self.assertEqual(read_back.file_sha256,receipt.file_sha256)
            self.assertEqual(original,out)
            with self.assertRaises(UnresolvedReceipt):publish(td,original)
            self.assertEqual(read(td,receipt.key)[1],original)

    def test_different_content_cannot_replace_same_key(self):
        with TemporaryDirectory() as td:
            publish(td,record())
            altered=record();altered['ood']['correct']=0
            with self.assertRaises(UnresolvedReceipt):publish(td,altered)
            self.assertEqual(read(td,'copy.2.aggregate_count')[1]['ood']['correct'],90)

    def test_twelve_record_seal_survives_new_process(self):
        with TemporaryDirectory() as td:
            for t in TASKS:
                for s in SEEDS:
                    for a in ARMS:publish(td,record(t,s,a))
            self.assertEqual(len(audit(td)),12)
            digest=seal(td)
            self.assertEqual(digest,verify_seal(td)['sealed_sha256'])
            code='from hcsn_p2_20261031.immutable_trial_receipts import verify_seal; import sys; print(verify_seal(sys.argv[1])["record_count"])'
            run=subprocess.run([sys.executable,'-c',code,td],
                    env={**os.environ,'PYTHONPATH':'/mnt/data'},
                    capture_output=True,text=True,check=True)
            self.assertEqual(run.stdout.strip(),'12')
            with self.assertRaises(UnresolvedReceipt):seal(td)

    def test_missing_record_prevents_seal(self):
        with TemporaryDirectory() as td:
            publish(td,record())
            with self.assertRaises(UnresolvedReceipt):seal(td)

    def test_real_crash_after_file_fsync_is_not_published(self):
        with TemporaryDirectory() as td:
            code=('import os,sys;from hcsn_p2_20261031.immutable_trial_receipts '
                  'import publish;from hcsn_p2_20261031.test_immutable_trial_receipts import record;'
                  'publish(sys.argv[1],record(),crash_hook=lambda s:os._exit(73))')
            p=subprocess.run([sys.executable,'-c',code,td],
                             env={**os.environ,'PYTHONPATH':'/mnt/data'})
            self.assertEqual(p.returncode,73)
            self.assertFalse((Path(td)/'records'/'copy.2.aggregate_count.json').exists())
            with self.assertRaises(UnresolvedReceipt):audit(td,require_complete=False)
            recovered=recover_stages(td,quiescent=True)
            self.assertEqual(recovered,(('copy.2.aggregate_count','QUARANTINED_UNCOMMITTED'),))
            self.assertFalse((Path(td)/'records'/'copy.2.aggregate_count.json').exists())
            self.assertEqual(len(audit(td,require_complete=False)),0)
            publish(td,record())

    def test_real_crash_after_link_has_complete_self_checking_receipt(self):
        with TemporaryDirectory() as td:
            code=('import os,sys;from hcsn_p2_20261031.immutable_trial_receipts '
                  'import publish;from hcsn_p2_20261031.test_immutable_trial_receipts import record;'
                  'publish(sys.argv[1],record(),crash_hook=lambda s:os._exit(74) '
                  'if s=="after_create_only_link" else None)')
            p=subprocess.run([sys.executable,'-c',code,td],
                             env={**os.environ,'PYTHONPATH':'/mnt/data'})
            self.assertEqual(p.returncode,74)
            with self.assertRaises(UnresolvedReceipt):read(td,'copy.2.aggregate_count')
            with self.assertRaises(UnresolvedReceipt):audit(td,require_complete=False)
            self.assertEqual(recover_stages(td,quiescent=True),
                             (('copy.2.aggregate_count','FINALIZED_ALREADY_LINKED'),))
            self.assertEqual(read(td,'copy.2.aggregate_count')[1],record())
            self.assertEqual(len(audit(td,require_complete=False)),1)

    def test_recovery_refuses_without_writer_quiescence(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(UnresolvedReceipt):recover_stages(td,quiescent=False)

    def test_mutation_detected_by_seal(self):
        with TemporaryDirectory() as td:
            for t in TASKS:
                for s in SEEDS:
                    for a in ARMS:publish(td,record(t,s,a))
            seal(td)
            file=Path(td)/'records'/'copy.2.aggregate_count.json'
            raw=file.read_bytes()
            file.write_bytes(raw.replace(b'"correct":100',b'"correct":101',1))
            with self.assertRaises(UnresolvedReceipt):verify_seal(td)

    def test_unregistered_and_malformed_rejected(self):
        with TemporaryDirectory() as td:
            for update in ({'seed':True},{'seed':99},{'task':'other'},
                           {'production_activation':True},
                           {'training_cpu_seconds':float('nan')},
                           {'all_scientific_blockers_closed':True},
                           {'initial_model_sha256':'0'},
                           {'id':{'correct':float('nan')}}):
                bad=record();bad.update(update)
                with self.subTest(update=update),self.assertRaises(UnresolvedReceipt):
                    publish(td,bad)

    def test_symlinked_records_directory_refused(self):
        with TemporaryDirectory() as td,TemporaryDirectory() as other:
            (Path(td)/'records').symlink_to(other)
            with self.assertRaises(UnresolvedReceipt):publish(td,record())

    def test_duplicate_key_with_parallel_processes_uses_link_exclusive(self):
        with TemporaryDirectory() as td:
            code=('import sys;from hcsn_p2_20261031.immutable_trial_receipts '
                  'import publish;from hcsn_p2_20261031.test_immutable_trial_receipts import record;'
                  'publish(sys.argv[1],record())')
            env={**os.environ,'PYTHONPATH':'/mnt/data'}
            workers=[subprocess.Popen([sys.executable,'-c',code,td],
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
                     for _ in range(4)]
            codes=[p.wait() for p in workers]
            self.assertEqual(codes.count(0),1)
            self.assertEqual(len(audit(td,require_complete=False)),1)

    def test_trailing_extra_file_refused_even_if_sealed(self):
        with TemporaryDirectory() as td:
            for t in TASKS:
                for s in SEEDS:
                    for a in ARMS:publish(td,record(t,s,a))
            seal(td)
            (Path(td)/'records'/'unexpected.json').write_text('{}')
            with self.assertRaises(UnresolvedReceipt):verify_seal(td)

if __name__=='__main__':unittest.main()

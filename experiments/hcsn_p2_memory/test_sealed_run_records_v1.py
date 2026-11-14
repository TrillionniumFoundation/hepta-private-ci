"""Safety regressions for local P2 create-only immutable-ish run evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from .sealed_run_records_v1 import (
    EvidenceUnresolved, publish_create_only, verify_receipt,
)

RUN_ID = 'copy-seed02-timed-unique0001'
BASE = {'task':'copy', 'seed':2,'production_activation':False,
        'all_scientific_blockers_closed':False,'operator':'physical_event_timestamp',
        'training_cpu_seconds':25.009304758}

class TestSealedRunRecords(unittest.TestCase):
    def test_create_only_and_byte_mutation_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            receipt=publish_create_only(Path(d), RUN_ID, BASE)
            self.assertTrue(receipt['readback_verified'])
            verified=verify_receipt(Path(d), receipt)
            self.assertEqual(verified['result'],BASE)
            self.assertFalse(verified['provenance_authenticated'])
            with self.assertRaises(EvidenceUnresolved):
                publish_create_only(Path(d), RUN_ID, {**BASE,'training_cpu_seconds':26})
            self.assertEqual(verify_receipt(Path(d),receipt)['result'],BASE)
            p=Path(d)/(RUN_ID+'.json')
            p.write_bytes(p.read_bytes().replace(b'25.009304758',b'24.009304758'))
            with self.assertRaises(EvidenceUnresolved):
                verify_receipt(Path(d),receipt)

    def test_bad_ids_nan_and_gate_escalation_refused_without_output(self):
        for id,rec in [('../escape-x',BASE),('short',BASE),
                       (RUN_ID,{**BASE,'production_activation':True}),
                       (RUN_ID,{**BASE,'all_scientific_blockers_closed':True}),
                       (RUN_ID,{**BASE,'loss':float('nan')}),
                       (RUN_ID,{**BASE,'run_id':'different-run-id-01'})]:
            with tempfile.TemporaryDirectory() as d:
                with self.subTest(id=id,rec=str(rec)),self.assertRaises(EvidenceUnresolved):
                    publish_create_only(Path(d),id,rec)
                self.assertEqual(list(Path(d).glob('*.json')),[])

    def test_real_new_process_read_and_receipt_tamper_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            receipt=publish_create_only(Path(d),RUN_ID,BASE)
            code=('import json,sys;from pathlib import Path;from '
                  'experiments.hcsn_p2_memory.sealed_run_records_v1 import verify_receipt;'
                  'a=verify_receipt(Path(sys.argv[1]),json.loads(sys.argv[2]));'
                  'print(a["run_id"])')
            import os
            root=Path(__file__).resolve().parents[2]
            env={**os.environ,'PYTHONPATH':str(root)}
            out=subprocess.run([sys.executable,'-c',code,d,json.dumps(receipt)],
                               capture_output=True,text=True,timeout=15,check=True,env=env)
            self.assertEqual(out.stdout.strip(),RUN_ID)
            wrong={**receipt,'sha256':'a'*64}
            with self.assertRaises(EvidenceUnresolved):verify_receipt(Path(d),wrong)
            wrong={**receipt,'all_scientific_blockers_closed':True}
            with self.assertRaises(EvidenceUnresolved):verify_receipt(Path(d),wrong)

    def test_symlink_directory_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'real').mkdir();(root/'alias').symlink_to(root/'real',target_is_directory=True)
            with self.assertRaises(EvidenceUnresolved):
                publish_create_only(root/'alias',RUN_ID,BASE)

if __name__=='__main__':unittest.main()

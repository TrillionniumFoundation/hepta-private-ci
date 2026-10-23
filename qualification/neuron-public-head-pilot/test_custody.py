import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import custody as c

SOURCE = Path(__file__).resolve().parent

class CustodyTests(unittest.TestCase):
    def fixture(self, folder):
        for name in ['plan.json', 'rows.json']:
            shutil.copyfile(SOURCE/name, folder/name)
        actual=json.loads((SOURCE/'observed/extraction.json').read_text())
        arrays={k:np.zeros((v['rows'],640),dtype=np.float32) for k,v in actual['splits'].items()}
        for a in arrays.values():a[:,0]=1
        np.savez_compressed(folder/'features.npz',**arrays)
        actual['features_file_sha256']=c.digest(folder/'features.npz')
        self.write(folder/'extraction.json',actual)
        return actual,arrays
    def write(self,path,data):path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
    def test_plan_edits_cannot_reseal(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);actual,_=self.fixture(p)
            plan=json.loads((p/'plan.json').read_text());plan['dataset']['original_archive_sha256']='0'*64;self.write(p/'plan.json',plan)
            actual['plan_sha256']=c.digest(p/'plan.json');self.write(p/'extraction.json',actual)
            with self.assertRaisesRegex(ValueError,'Frozen plan mismatch'):c.validate_inputs(p)
    def test_row_label_edit_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.fixture(p);rows=json.loads((p/'rows.json').read_text());rows['test'][0]['label']=(rows['test'][0]['label']+1)%4;self.write(p/'rows.json',rows)
            with self.assertRaisesRegex(ValueError,'Frozen row manifest mismatch'):c.validate_inputs(p)
    def test_joint_feature_and_receipt_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);actual,arrays=self.fixture(p)
            for k,a in arrays.items():actual['splits'][k]['feature_sha256']=hashlib.sha256(a.tobytes()).hexdigest()
            self.write(p/'extraction.json',actual)
            with self.assertRaisesRegex(ValueError,'Receipt frozen identity mismatch: splits'):c.validate_inputs(p)
    def test_lie_about_tensor_hash_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.fixture(p)
            with self.assertRaisesRegex(ValueError,'frozen feature tensor mismatch'):c.validate_inputs(p)
    def test_changed_anchor_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.fixture(p);source=p/'source';(source/'observed').mkdir(parents=True);(source/'observed/extraction.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'Observed extraction anchor mismatch'):c.validate_inputs(p,source)
    def test_exact_arrays_accept_repacking(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);a=np.zeros((1,640),dtype=np.float32);a[:,0]=1
            expected={'splits':{'test':{'rows':1,'feature_sha256':hashlib.sha256(a.tobytes()).hexdigest()}}}
            np.savez(p/'a.npz',test=a);np.savez_compressed(p/'b.npz',test=a)
            self.assertNotEqual(c.digest(p/'a.npz'),c.digest(p/'b.npz'))
            np.testing.assert_array_equal(c.checked_arrays(p/'a.npz',expected)['test'],c.checked_arrays(p/'b.npz',expected)['test'])
    def test_dtype_and_extra_arrays_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);a=np.zeros((1,640),dtype=np.float32);a[:,0]=1;expected={'splits':{'test':{'rows':1,'feature_sha256':hashlib.sha256(a.tobytes()).hexdigest()}}}
            np.savez(p/'x.npz',test=a.astype(np.float64))
            with self.assertRaisesRegex(ValueError,'dtype'):c.checked_arrays(p/'x.npz',expected)
            np.savez(p/'x.npz',test=a,extra=a)
            with self.assertRaisesRegex(ValueError,'inventory'):c.checked_arrays(p/'x.npz',expected)
    def test_optimized_cli_rejects_before_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.fixture(p)
            r=subprocess.run([sys.executable,'-O',str(SOURCE/'analyze.py'),'--output-dir',str(p)],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0);self.assertIn('optimized Python forbidden',r.stderr)
            self.assertFalse((p/'results.json').exists());self.assertFalse((p/'head-artifacts.npz').exists())
    def test_cli_rejects_before_training_runtime_and_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);self.fixture(p)
            r=subprocess.run([sys.executable,str(SOURCE/'analyze.py'),'--output-dir',str(p)],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0);self.assertIn('frozen feature tensor mismatch',r.stderr);self.assertNotIn('ModuleNotFoundError',r.stderr)
            self.assertFalse((p/'results.json').exists());self.assertFalse((p/'head-artifacts.npz').exists())

if __name__=='__main__':unittest.main()

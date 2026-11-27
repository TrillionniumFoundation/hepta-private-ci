"""R18 adversarial real-artifact tamper rejection; original run tree read-only."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

def digest(data):return hashlib.sha256(data).hexdigest()
def write(path,obj):path.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')

class TamperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs=Path(os.environ.get('NDU_R18_RUNS',ROOT/'runs'))
        cls.source=Path(os.environ.get('NDU_R18_SOURCE',ROOT/'source'))
        if not (cls.runs/'COMPLETE.json').exists():raise unittest.SkipTest('requires frozen full artifact')

    def mutate(self,kind):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);fake=base/'runs';fake.mkdir()
            for name in ('PLAN.json','COMPLETE.json'):
                shutil.copy2(self.runs/name,fake/name)
            done=json.loads((fake/'COMPLETE.json').read_text());first=done['entries'][0]['name']
            for e in done['entries']:
                if e['name']==first:shutil.copytree(self.runs/first,fake/first)
                else:(fake/e['name']).symlink_to(self.runs/e['name'],target_is_directory=True)
            folder=fake/first;rep=json.loads((folder/'REPORT.json').read_text())
            seal=json.loads((folder/'FIT_SEAL.json').read_text())
            expect={
                'missing':'missing/reordered cases',
                'weight':'checkpoint endpoints altered',
                'score':'final cost mismatch',
                'checkpoint':'checkpoint cost mismatch',
                'qualification':'post-fit reference leaked',
                'time':'falsified fit CPU',
                'source':'source hashes changed',
                'leaf':'leaf hash mismatch',
                'initial':'not paired original start'}[kind]
            src=self.source
            if kind=='missing':done['entries'].pop()
            if kind=='weight':
                with np.load(folder/'WEIGHTS.npz',allow_pickle=False) as q:theta=q['theta'].copy()
                theta[0]+=.1;np.savez_compressed(folder/'WEIGHTS.npz',theta=theta)
                seal['weights']=digest(theta.tobytes());rep['weights_sha']=seal['weights']
            if kind=='score':rep['final_cost']+=.12
            if kind=='qualification':rep['qualification']=True
            if kind=='time':
                rep['fit_cpu']=0;seal['fit_cpu']=0
            if kind=='checkpoint':
                with np.load(folder/'CHECKPOINTS.npz',allow_pickle=False) as q:
                    arr={k:q[k].copy() for k in q.files}
                arr['cost'][0]+=.11
                np.savez_compressed(folder/'CHECKPOINTS.npz',**arr)
                seal['checkpoints']=digest((folder/'CHECKPOINTS.npz').read_bytes())
            if kind=='leaf':
                with np.load(folder/'LEAVES.npz',allow_pickle=False) as q:ar=q['values'].copy()
                ar[0,9]+=.1;np.savez_compressed(folder/'LEAVES.npz',values=ar)
            if kind=='initial':
                with np.load(folder/'INITIAL.npz',allow_pickle=False) as q:theta=q['theta'].copy()
                theta[0]+=.1;np.savez_compressed(folder/'INITIAL.npz',theta=theta)
                seal['initial']=digest(theta.tobytes());rep['initial_sha']=seal['initial']
            if kind=='source':
                src=base/'source';src.mkdir()
                for p in self.source.glob('*.py'):shutil.copy2(p,src/p.name)
                (src/'certificate.py').write_bytes((src/'certificate.py').read_bytes()+b'\n# tampered\n')
            write(folder/'FIT_SEAL.json',seal)
            write(folder/'REPORT.json',rep)
            done['entries'][0]['report_sha']=digest((folder/'REPORT.json').read_bytes())
            write(fake/'COMPLETE.json',done)
            cmd=[sys.executable,'-O',str(Path(__file__).with_name('verify.py')),
                 '--source',str(src),'--runs',str(fake),'--out',str(base/'audit')]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=40)
            self.assertNotEqual(result.returncode,0,f'{kind} unexpectedly accepted')
            self.assertIn(expect,result.stderr)
            self.assertFalse((base/'audit/AUDIT.json').exists())

    def test_01_incomplete_census(self):self.mutate('missing')
    def test_02_weight_substitution(self):self.mutate('weight')
    def test_03_rehashed_false_cost(self):self.mutate('score')
    def test_04_rehashed_checkpoint(self):self.mutate('checkpoint')
    def test_05_rehashed_oracle_leak(self):self.mutate('qualification')
    def test_06_rehashed_falsified_time(self):self.mutate('time')
    def test_07_source_drift(self):self.mutate('source')
    def test_08_changed_leaf_table(self):self.mutate('leaf')
    def test_09_changed_initial_bytes(self):self.mutate('initial')

if __name__=='__main__':unittest.main(verbosity=2)

"""R17 real saved-file manipulations; refuse forged outputs even under python -O."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np

def digest(b):return hashlib.sha256(b).hexdigest()

class TamperTests(unittest.TestCase):
    def attempt(self,mode,message):
        root=Path(os.environ['R17_RUNS']);source=Path(__file__).with_name('audit.py')
        with tempfile.TemporaryDirectory(prefix='r17-adversarial-') as temp:
            here=Path(temp);runs=here/'runs';runs.mkdir()
            for n in ('SWEEP_PLAN.json','COMPLETE.json'):
                shutil.copy2(root/n,runs/n)
            completed=json.loads((runs/'COMPLETE.json').read_text())
            first=completed['results'][0]['name']
            for row in completed['results']:
                if row['name']==first:
                    shutil.copytree(root/first,runs/first)
                else:
                    (runs/row['name']).symlink_to(root/row['name'],target_is_directory=True)
            candidate=runs/first;report=json.loads((candidate/'REPORT.json').read_text())
            seal=json.loads((candidate/'FIT_SEAL.json').read_text())
            if mode=='census':
                completed['results'].pop()
            elif mode=='weights':
                p=candidate/'WEIGHTS.npz'
                with np.load(p,allow_pickle=False) as z:th=z['theta'].copy()
                th[0]+=.2
                np.savez_compressed(p,theta=th)
            elif mode=='cost':
                report['cost']+=.08
            elif mode=='transfers':
                report['transfers']['biased_input']+=.03
            elif mode=='initial':
                p=candidate/'INITIAL.npz'
                with np.load(p,allow_pickle=False) as z:th=z['theta'].copy()
                th[0]+=.04
                np.savez_compressed(p,theta=th)
            elif mode=='checkpoint':
                p=candidate/'CHECKPOINTS.npz'
                with np.load(p,allow_pickle=False) as z:
                    arrays={name:z[name].copy() for name in z.files}
                self.assertGreater(len(arrays['theta']),2)
                arrays['theta'][1,0]+=.1
                np.savez_compressed(p,**arrays)
                seal['checkpoints_sha']=digest(p.read_bytes())
                report['fit']=seal
            elif mode=='clock':
                seal['fit_cpu']=0.
                report['fit']=seal
            if mode in ('cost','transfers','checkpoint','clock'):
                (candidate/'REPORT.json').write_text(json.dumps(report))
                completed['results'][0]['report_sha']=digest((candidate/'REPORT.json').read_bytes())
            if mode in ('checkpoint','clock'):
                (candidate/'FIT_SEAL.json').write_text(json.dumps(seal))
            (runs/'COMPLETE.json').write_text(json.dumps(completed))
            cmd=[sys.executable,'-O',str(source),'--runs',str(runs),'--out',str(here/'checked')]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=55)
            self.assertNotEqual(r.returncode,0,(mode,r.stdout,r.stderr))
            self.assertIn(message,r.stderr)
            self.assertFalse((here/'checked/AUDIT.json').exists())
    def test_incomplete_census(self):self.attempt('census','incomplete census')
    def test_wrong_initial(self):self.attempt('initial','initial mismatch')
    def test_changed_weights(self):self.attempt('weights','weight mismatch')
    def test_rehashed_false_cost(self):self.attempt('cost','false final cost')
    def test_rehashed_false_transfer(self):self.attempt('transfers','false transfer panel')
    def test_rehashed_checkpoint_values(self):self.attempt('checkpoint','checkpoint cost mismatch')
    def test_rehashed_shortened_fit_time(self):self.attempt('clock','invalid checkpoint CPU chronology')
if __name__=='__main__':unittest.main(verbosity=2)

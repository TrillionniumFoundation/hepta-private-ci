"""R19 tamper checks with ACTUAL archived fit files, running under python -O."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
SOURCE=Path(os.environ.get('NDU_R19_SOURCE', HERE.parent/'nonquotient_bnb')).resolve()
RUNS=Path(os.environ.get('NDU_R19_RUNS', HERE.parent/'runs')).resolve()
PROOF=Path(os.environ.get('NDU_R19_PROOF', HERE.parent/'CERTIFICATE.json')).resolve()

class Tests(unittest.TestCase):
    def try_attack(self,kind,phrase):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);fake=base/'runs';fake.mkdir()
            for name in ('PLAN.json','COMPLETE.json'):
                shutil.copy2(RUNS/name,fake/name)
            done=json.loads((fake/'COMPLETE.json').read_text())
            first=done['entries'][0]['name']
            for entry in done['entries']:
                source=RUNS/entry['name']
                dest=fake/entry['name']
                if entry['name']==first: shutil.copytree(source,dest)
                else:dest.symlink_to(source,target_is_directory=True)
            folder=fake/first
            report=json.loads((folder/'REPORT.json').read_text())
            if kind=='missing_case':
                done['entries'].pop()
            elif kind=='tensor':
                with np.load(folder/'WEIGHTS.npz',allow_pickle=False) as r:theta=r['theta'].copy()
                theta[0]+=.1;np.savez_compressed(folder/'WEIGHTS.npz',theta=theta)
            elif kind=='checkpoint':
                with np.load(folder/'CHECKPOINTS.npz',allow_pickle=False) as r:
                    v={name:r[name].copy() for name in r.files}
                v['cost'][0]+=.1
                np.savez_compressed(folder/'CHECKPOINTS.npz',**v)
            elif kind=='initial':
                with np.load(folder/'INITIAL.npz',allow_pickle=False) as r:theta=r['theta'].copy()
                theta[0]+=.1;np.savez_compressed(folder/'INITIAL.npz',theta=theta)
            elif kind=='false_cost':report['final_cost']+=.1
            elif kind=='time':report['whole_child_cpu']=0
            elif kind=='oracle':report['global_qualification']=True
            elif kind=='source':
                plan=json.loads((fake/'PLAN.json').read_text())
                plan['source_sha']['model.py']='f'*64
                (fake/'PLAN.json').write_text(json.dumps(plan))
                done['plan_sha']=hashlib.sha256((fake/'PLAN.json').read_bytes()).hexdigest()
            if kind in ('false_cost','time','oracle'):
                (folder/'REPORT.json').write_text(json.dumps(report))
                done['entries'][0]['report_sha']=hashlib.sha256((folder/'REPORT.json').read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(done))
            cmd=[sys.executable,'-O',str(HERE/'verify.py'),'--source',str(SOURCE),'--runs',str(fake),
                 '--proof',str(PROOF),'--out',str(base/'verified')]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=45,env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            self.assertNotEqual(r.returncode,0,kind)
            self.assertIn(phrase,r.stderr,kind)
            self.assertFalse((base/'verified/AUDIT.json').exists(),kind)
    def test_missing(self):self.try_attack('missing_case','incomplete case census')
    def test_tensor(self):self.try_attack('tensor','weight digest mismatch')
    def test_checkpoint(self):self.try_attack('checkpoint','checkpoint digest mismatch')
    def test_initial(self):self.try_attack('initial','initial mismatch')
    def test_rehashed_cost(self):self.try_attack('false_cost','rehashed false cost')
    def test_rehashed_time(self):self.try_attack('time','unmetered work')
    def test_rehashed_oracle(self):self.try_attack('oracle','reference in fitting')
    def test_source_forgery(self):self.try_attack('source','source mismatch')

if __name__=='__main__':unittest.main(verbosity=2)

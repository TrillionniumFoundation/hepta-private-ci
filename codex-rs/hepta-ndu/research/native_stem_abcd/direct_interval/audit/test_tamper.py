"""R20 genuine sealed 80-case artifact mutations tested under optimized Python."""
import copy,hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np
RUNS=Path(os.environ['NDU_R20_RUNS'])
EVIDENCE=Path(os.environ['NDU_R20_EVIDENCE'])
SOURCE=Path(os.environ['NDU_R20_SOURCE'])
HERE=Path(__file__).resolve().parent

def h(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,obj):path.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')

class RealArtifactTamperTests(unittest.TestCase):
    def attack(self,kind,expected):
        with tempfile.TemporaryDirectory(prefix='ndu-r20-tamper-') as tmp:
            root=Path(tmp);runs=root/'runs';runs.mkdir();ev=root/'evidence';ev.mkdir()
            for n in ('PLAN.json','COMPLETE.json'):
                shutil.copy2(RUNS/n,runs/n)
            for p in EVIDENCE.glob('CERT_*.json'):
                shutil.copy2(p,ev/p.name)
            for p in EVIDENCE.glob('FRONTIER_*.jsonl'):
                (ev/p.name).symlink_to(p)
            done=json.loads((runs/'COMPLETE.json').read_text())
            first=done['entries'][0]['name']
            for e in done['entries']:
                if e['name']==first:shutil.copytree(RUNS/first,runs/first)
                else:(runs/e['name']).symlink_to(RUNS/e['name'],target_is_directory=True)
            d=runs/first
            if kind=='missing':
                done['entries'].pop()
            elif kind=='weights':
                with np.load(d/'WEIGHTS.npz',allow_pickle=False) as data:theta=data['theta'].copy()
                theta[0]+=.123
                np.savez_compressed(d/'WEIGHTS.npz',theta=theta)
                seal=json.loads((d/'FIT_SEAL.json').read_text());seal['weights']=hashlib.sha256(theta.tobytes()).hexdigest()
                save(d/'FIT_SEAL.json',seal)
                report=json.loads((d/'REPORT.json').read_text());report['weights_sha']=seal['weights']
                save(d/'REPORT.json',report);done['entries'][0]['report_sha']=h(d/'REPORT.json')
            elif kind=='checkpoint':
                with np.load(d/'CHECKPOINTS.npz',allow_pickle=False) as data:
                    arrays={k:data[k].copy() for k in data.files}
                arrays['cost'][0]+=1.
                np.savez_compressed(d/'CHECKPOINTS.npz',**arrays)
                seal=json.loads((d/'FIT_SEAL.json').read_text());seal['checkpoints']=h(d/'CHECKPOINTS.npz')
                save(d/'FIT_SEAL.json',seal)
            elif kind=='false_success':
                report=json.loads((d/'REPORT.json').read_text());report['global_qualification']=True
                save(d/'REPORT.json',report);done['entries'][0]['report_sha']=h(d/'REPORT.json')
            elif kind=='certificate':
                obj=json.loads((ev/'CERT_NEW.json').read_text());obj['global_cost_lower']='0'
                save(ev/'CERT_NEW.json',obj)
            elif kind=='initial':
                with np.load(d/'INITIAL.npz',allow_pickle=False) as data:theta=data['theta'].copy()
                theta[1]+=.5
                np.savez_compressed(d/'INITIAL.npz',theta=theta)
            else:raise ValueError(kind)
            save(runs/'COMPLETE.json',done)
            command=[sys.executable,'-O',str(HERE/'verify.py'),'--source',str(SOURCE),
                     '--runs',str(runs),'--evidence',str(ev),'--out',str(root/'checked')]
            result=subprocess.run(command,capture_output=True,text=True,timeout=90,
                                  env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
            self.assertNotEqual(result.returncode,0,kind)
            self.assertIn(expected,result.stderr,kind)
            self.assertFalse((root/'checked'/'AUDIT.json').exists(),kind)

    def test_01_missing_case(self):self.attack('missing','incomplete eighty census')
    def test_02_rehashed_weight(self):self.attack('weights','endpoint checkpoint mismatch')
    def test_03_rehashed_checkpoint(self):self.attack('checkpoint','falsified checkpoint cost')
    def test_04_rehashed_false_success(self):self.attack('false_success','pre-fit oracle')
    def test_05_modified_certificate(self):self.attack('certificate','changed global certificate')
    def test_06_changed_initial(self):self.attack('initial','initial tensor mismatch')

if __name__=='__main__':unittest.main(verbosity=2)

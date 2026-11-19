"""R6 real-archive adversarial tests under optimized Python; originals read-only."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np


class TamperTests(unittest.TestCase):
    def attempt(self,kind):
        source=Path(os.environ['NDU_R6_SOURCE']);runs=Path(os.environ['NDU_R6_RUNS'])
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fake=root/'runs';fake.mkdir()
            for f in ('PLAN.json','COMPLETE.json','EVALUATION_LAWS.npz'):shutil.copy2(runs/f,fake/f)
            c=json.loads((fake/'COMPLETE.json').read_text());first=c['census'][0]['name']
            for r in c['census']:
                if r['name']==first:shutil.copytree(runs/first,fake/first)
                else:(fake/r['name']).symlink_to(runs/r['name'],target_is_directory=True)
            reportpath=fake/first/'REPORT.json';report=json.loads(reportpath.read_text())
            if kind=='census':c['census'].pop()
            elif kind=='weight':
                path=fake/first/'WEIGHTS.npz';z=np.load(path,allow_pickle=False)['theta'];z[0]+=.1;np.savez_compressed(path,theta=z)
            elif kind=='law':
                path=fake/first/'TRAIN_LAW.npz';old=np.load(path,allow_pickle=False);s=old['states'];w=old['weights'].copy()
                w[0]+=.001;w[1]-=.001;np.savez_compressed(path,states=s,weights=w)
                report['law_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            else:report['metrics']['cc17']+=.1
            if kind in ('law','metric'):
                reportpath.write_text(json.dumps(report));c['census'][0]['report_sha256']=hashlib.sha256(reportpath.read_bytes()).hexdigest()
            (fake/'COMPLETE.json').write_text(json.dumps(c))
            cmd=[sys.executable,'-O',str(Path(__file__).with_name('verify.py')),'--source',str(source),
                 '--runs',str(fake),'--out',str(root/'out')]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=60)
            self.assertNotEqual(r.returncode,0)
            expected={'census':'census mismatch','weight':'weight hash mismatch',
                      'law':'training integration weights mismatch','metric':'metric mismatch'}[kind]
            self.assertIn(expected,r.stderr);self.assertFalse((root/'out'/'AUDIT.json').exists())
    def test_missing_case(self):self.attempt('census')
    def test_real_weight_change(self):self.attempt('weight')
    def test_rehashed_integration_weights(self):self.attempt('law')
    def test_rehashed_false_metric(self):self.attempt('metric')

if __name__=='__main__':unittest.main(verbosity=2)

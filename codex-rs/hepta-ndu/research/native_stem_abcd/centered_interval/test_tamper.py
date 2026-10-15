"""R22 genuine saved-file tamper rejection; -O must not disable checks."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
EVIDENCE=Path(os.environ.get('NDU_R22_EVIDENCE',str(HERE.parent/'experiments')))
LEGACY=Path(os.environ.get('NDU_R22_R21', '/mnt/data/ndu_round21_evidence'))
PARENT_ZIP=Path(os.environ.get('NDU_R22_R21ZIP','/mnt/data/hepta_native_ndu_four_weight_round21_20261015.zip'))

def dump(p,obj):p.write_text(json.dumps(obj,sort_keys=True,indent=2)+'\n')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

class CorruptionTests(unittest.TestCase):
    def setup_proof(self,root,width=2,mode='hybrid'):
        trial=root/'proof';trial.mkdir()
        source=EVIDENCE/f'w{width}-{mode}'
        for n in ('SPLITS.jsonl','FRONTIER.jsonl','CERTIFICATE.json'):
            shutil.copyfile(source/n,trial/n)
        return trial
    def check_proof_fails(self,trial):
        code='from audit import verify_proof; from pathlib import Path; verify_proof(Path("'+str(trial)+'"),2,"hybrid")'
        env=os.environ.copy();env['PYTHONPATH']=str(HERE)
        result=subprocess.run([sys.executable,'-O','-c',code],capture_output=True,text=True,env=env,timeout=100)
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertIn('ValueError',result.stderr)
    def modify_split(self,trial,kind):
        lines=(trial/'SPLITS.jsonl').read_text().splitlines()
        rec=json.loads(lines[0])
        if kind=='cost':rec['children'][0]['lower']='1234567'
        elif kind=='box':rec['children'][0]['box'][0][0]='-101'
        else:raise ValueError(kind)
        lines[0]=json.dumps(rec,separators=(',',':'))
        (trial/'SPLITS.jsonl').write_text('\n'.join(lines)+'\n')
        c=json.loads((trial/'CERTIFICATE.json').read_text())
        c['splits_sha256']=digest(trial/'SPLITS.jsonl')
        dump(trial/'CERTIFICATE.json',c)
    def test_01_forged_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_proof(Path(folder));c=json.loads((p/'CERTIFICATE.json').read_text());c['node_cap']=4001;dump(p/'CERTIFICATE.json',c)
            self.check_proof_fails(p)
    def test_02_rehashed_false_child_cost(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_proof(Path(folder));self.modify_split(p,'cost');self.check_proof_fails(p)
    def test_03_rehashed_false_child_box(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_proof(Path(folder));self.modify_split(p,'box');self.check_proof_fails(p)
    def test_04_deleted_split_rehashed(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_proof(Path(folder));lines=(p/'SPLITS.jsonl').read_text().splitlines()[1:];(p/'SPLITS.jsonl').write_text('\n'.join(lines)+'\n');c=json.loads((p/'CERTIFICATE.json').read_text());c['splits_sha256']=digest(p/'SPLITS.jsonl');dump(p/'CERTIFICATE.json',c);self.check_proof_fails(p)
    def test_05_rehashed_false_final_gap(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_proof(Path(folder));c=json.loads((p/'CERTIFICATE.json').read_text());c['global_regret_upper']='0';dump(p/'CERTIFICATE.json',c);self.check_proof_fails(p)
    def test_06_deleted_frontier_leaf_rehashed(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_proof(Path(folder));lines=(p/'FRONTIER.jsonl').read_text().splitlines()[:-1];(p/'FRONTIER.jsonl').write_text('\n'.join(lines)+'\n');c=json.loads((p/'CERTIFICATE.json').read_text());c['frontier_sha256']=digest(p/'FRONTIER.jsonl');dump(p/'CERTIFICATE.json',c);self.check_proof_fails(p)
    def test_07_parent_binary64_weights(self):
        with tempfile.TemporaryDirectory() as folder:
            tmp=Path(folder);ev=tmp/'ev';ev.mkdir();shutil.copyfile(LEGACY/'WEIGHTS_HEX.csv',ev/'WEIGHTS_HEX.csv')
            (ev/'runs').symlink_to(LEGACY/'runs',target_is_directory=True)
            (ev/'verified').symlink_to(LEGACY/'verified',target_is_directory=True)
            text=(ev/'WEIGHTS_HEX.csv').read_text();text=text.replace('0x1.8c06274fde6e6p+0','0x1.8c06274fde6e7p+0',1)
            if text==(ev/'WEIGHTS_HEX.csv').read_text():self.fail('expected original row not found')
            (ev/'WEIGHTS_HEX.csv').write_text(text)
            cmd='from audit import verify_legacy; from pathlib import Path; verify_legacy(Path("'+str(PARENT_ZIP)+'"),Path("'+str(HERE.parent/'legacy')+'"),Path("'+str(ev)+'"))'
            result=subprocess.run([sys.executable,'-O','-c',cmd],capture_output=True,text=True,timeout=100,env={**os.environ,'PYTHONPATH':str(HERE)})
            self.assertNotEqual(result.returncode,0)
            self.assertIn('ValueError',result.stderr)

if __name__=='__main__':unittest.main(verbosity=2)

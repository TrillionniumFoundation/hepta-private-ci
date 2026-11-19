"""R24 real proof-tree and witness corruption rejection, including python -O."""
import hashlib,json,os,shutil,tempfile,unittest
from pathlib import Path
import audit,witness

EVIDENCE=Path(os.environ['R24_EVIDENCE'])
INPUT=Path(os.environ['R24_WITNESS_INPUT'])

def save(path,obj):path.write_text(json.dumps(obj,sort_keys=True,indent=2)+'\n')

class TamperTests(unittest.TestCase):
    def check_bad(self,mode,expected):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);folder=root/'w2';shutil.copytree(EVIDENCE/'w2',folder)
            receipt=folder/'CERTIFICATE.json';proof=json.loads(receipt.read_text())
            if mode=='frontier':
                with (folder/'FRONTIER.jsonl').open('ab') as f:f.write(b'garbage\n')
            elif mode=='rehashed_frontier':
                data=(folder/'FRONTIER.jsonl').read_bytes().splitlines(keepends=True)
                (folder/'FRONTIER.jsonl').write_bytes(b''.join(data[:-1]))
                proof['frontier_sha256']=hashlib.sha256((folder/'FRONTIER.jsonl').read_bytes()).hexdigest()
            elif mode=='child_id':
                spl=(folder/'SPLITS.jsonl').read_text().splitlines()
                x=json.loads(spl[0]);x['children'][0]['id']=0;spl[0]=json.dumps(x)
                (folder/'SPLITS.jsonl').write_text('\n'.join(spl)+'\n')
                proof['splits_sha256']=hashlib.sha256((folder/'SPLITS.jsonl').read_bytes()).hexdigest()
            elif mode=='false_gap':
                proof['global_regret_upper']='0'
            elif mode=='false_candidate':
                proof['candidate'][0]='0'
            elif mode=='source_hash':
                proof['source_sha256']['eliminate.py']='0'*64
            else:raise ValueError('bad test setup')
            save(receipt,proof)
            with self.assertRaisesRegex(ValueError,expected):
                audit.validate(root,selected=(2,),sample_size=3)
    def test_unhashed_frontier_change(self):self.check_bad('frontier','evidence hash mismatch')
    def test_rehashed_missing_frontier(self):self.check_bad('rehashed_frontier','lost frontier|lost active|frontier coverage')
    def test_rehashed_child_identity(self):self.check_bad('child_id','child identity/cover failure')
    def test_false_certified_gap(self):self.check_bad('false_gap','false global gap')
    def test_false_candidate(self):self.check_bad('false_candidate','candidate changed')
    def test_forged_source_hash(self):self.check_bad('source_hash','source hash mismatch')
    def test_tampered_existing_weights(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'WITNESS_INPUT.csv';txt=INPUT.read_text()
            src.write_text(txt.replace('0x1.8c06274d7fadfp+0','0x1.9c06274d7fadfp+0'))
            with self.assertRaisesRegex(ValueError,'forged witness tensor sha256'):
                witness.run(src,Path(td)/'out')

if __name__=='__main__':unittest.main(verbosity=2)

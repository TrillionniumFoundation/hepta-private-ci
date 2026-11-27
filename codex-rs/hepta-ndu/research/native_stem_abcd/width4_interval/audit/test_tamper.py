"""Genuine sealed R21 corruption tests, run with python -O and original run files."""
import copy,hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
def overwrite(path,obj):path.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
class TamperTests(unittest.TestCase):
 def attack(self,kind,needle):
  source=Path(os.environ['R21_SOURCE']);runs=Path(os.environ['R21_RUNS']);cert=Path(os.environ['R21_CERT'])
  with tempfile.TemporaryDirectory() as name:
   base=Path(name);fake=base/'runs';fake.mkdir()
   shutil.copy2(runs/'CENSUS_PLAN.json',fake/'CENSUS_PLAN.json')
   shutil.copy2(runs/'COMPLETE.json',fake/'COMPLETE.json')
   complete=json.loads((fake/'COMPLETE.json').read_text())
   first=complete['cases'][0]['name'];folder=fake/first
   for e in complete['cases']:
    nm=e['name']
    if nm==first:shutil.copytree(runs/nm,folder)
    else:(fake/nm).symlink_to(runs/nm,target_is_directory=True)
   if kind=='census':complete['cases'].pop()
   elif kind=='weights':
    with np.load(folder/'WEIGHTS.npz',allow_pickle=False) as data:z=data['theta'].copy()
    z[0]+=.1
    with (folder/'WEIGHTS.npz').open('wb') as f:np.savez_compressed(f,theta=z)
   elif kind=='checkpoints':
    with np.load(folder/'CHECKPOINTS.npz',allow_pickle=False) as data:h={k:data[k].copy() for k in data.files}
    h['cost'][0]+=.1
    with (folder/'CHECKPOINTS.npz').open('wb') as f:np.savez_compressed(f,**h)
   elif kind=='leaves':
    with np.load(folder/'LEAVES.npz',allow_pickle=False) as data:x=data['values'].copy()
    x[0,9]+=.5
    with (folder/'LEAVES.npz').open('wb') as f:np.savez_compressed(f,values=x)
   elif kind in ('false_cost','oracle'):
    report=json.loads((folder/'REPORT.json').read_text())
    if kind=='false_cost':report['final_cost']+=.5
    else:report['global_quality']=True
    overwrite(folder/'REPORT.json',report)
    complete['cases'][0]['report_sha']=digest(folder/'REPORT.json')
   elif kind=='source':
    source=base/'source';shutil.copytree(os.environ['R21_SOURCE'],source,ignore=shutil.ignore_patterns('__pycache__'))
    with (source/'model.py').open('a') as stream:stream.write('\n# corrupted after fitting\n')
   elif kind=='frontier':
    cert=base/'cert';cert.mkdir()
    for n in (2,3,4):
     old=Path(os.environ['R21_CERT'])/f'cert_w{n}'
     if n==2:
      shutil.copytree(old,cert/'cert_w2')
      with (cert/'cert_w2'/'FRONTIER.jsonl').open('a') as f:f.write('{}\n')
     else:(cert/f'cert_w{n}').symlink_to(old,target_is_directory=True)
   else:raise ValueError('unknown tamper')
   overwrite(fake/'COMPLETE.json',complete)
   cmd=[sys.executable,'-O',str(ROOT/'audit/verify.py'),'--source',str(source),
        '--runs',str(fake),'--cert',str(cert),'--out',str(base/'audit'),'--no-replay-nodes']
   result=subprocess.run(cmd,capture_output=True,text=True,timeout=100)
   self.assertNotEqual(result.returncode,0,kind)
   self.assertIn(needle,result.stderr,kind)
   self.assertFalse((base/'audit'/'AUDIT.json').exists())
 def test_census(self):self.attack('census','incomplete or failed census')
 def test_weights(self):self.attack('weights','final weights modified')
 def test_checkpoints(self):self.attack('checkpoints','checkpoints modified')
 def test_leaves(self):self.attack('leaves','leaf archive modified')
 def test_rehashed_false_cost(self):self.attack('false_cost','final cost falsified')
 def test_rehashed_oracle(self):self.attack('oracle','oracle used in fit')
 def test_source(self):self.attack('source','source mutation')
 def test_frontier(self):self.attack('frontier','frontier hash modified')
if __name__=='__main__':unittest.main(verbosity=2)

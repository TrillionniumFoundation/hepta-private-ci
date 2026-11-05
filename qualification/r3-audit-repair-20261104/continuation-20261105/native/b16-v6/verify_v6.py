"""Cloud-only four guard controls and isolated Git delta reconstruction."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent/'cli-duplicate-flag-v5'/'v5-candidate'
OUT=ROOT/'v6-candidate'
EVIDENCE=ROOT/'cloud-verification-v1'
assert not EVIDENCE.exists()
EVIDENCE.mkdir()

def ident(path):
    data=path.read_bytes()
    return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}

commands=[]
def run(label,args,cwd):
    start=time.monotonic()
    result=subprocess.run(args,cwd=cwd,capture_output=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    stdout=EVIDENCE/(label+'.stdout');stderr=EVIDENCE/(label+'.stderr')
    stdout.write_bytes(result.stdout);stderr.write_bytes(result.stderr)
    row={'label':label,'argv':args,'cwd':str(cwd),'exit_code':result.returncode,'seconds':time.monotonic()-start,
         'stdout':ident(stdout),'stderr':ident(stderr)}
    commands.append(row)
    if result.returncode != 0: raise RuntimeError(row)
    return result

run('four-provenance-guard-controls',['python3','-m','unittest','-v','test_build_only_guard'],OUT)
with tempfile.TemporaryDirectory(prefix='hepta-b16-v6-patch-') as d:
    tree=Path(d)
    for p in BASE.iterdir():
        if p.is_file():shutil.copyfile(p,tree/p.name)
    run('git-init',['git','init','-q'],tree)
    run('git-add-preimages',['git','add','--all'],tree)
    patch=ROOT/'v5-to-v6.delta.patch'
    run('git-apply-check',['git','apply','--check',str(patch)],tree)
    run('git-apply',['git','apply',str(patch)],tree)
    expected={p.name for p in OUT.iterdir() if p.is_file()}
    observed={p.name for p in tree.iterdir() if p.is_file()}
    assert expected==observed,(expected^observed)
    verification=[]
    for name in sorted(expected):
        assert (tree/name).read_bytes()==(OUT/name).read_bytes(),name
        verification.append({'path':name,'exact':True,**{k:v for k,v in ident(OUT/name).items() if k!='path'}})
    run('git-diff-check',['git','diff','--check'],tree)
report={'schema':'hepta-b16-v6-cloud-guard-and-delta-verification-v1','completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_map':ident(ROOT/'source-map-v6.json'),'commands':commands,'reconstructed_files':verification,
        'four_guard_controls_passed':True,'test_inputs':'Synthetic tiny files; only provenance guards. No native build, B case, production test, peak-capacity or actual P4 proof.',
        'native_started':False,'refs_changed':False,'new_mode_enabled':False}
(EVIDENCE/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'verification':ident(EVIDENCE/'verification.json'),'commands':[(x['label'],x['exit_code']) for x in commands],
                  'reconstructed_files':len(verification)},indent=2))

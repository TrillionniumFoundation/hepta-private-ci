import base64
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import numpy as np

PACKED = None
EXPECTED = None
REQUEST='hcsn-public-rematerialize-1140569-20261128'


def expand(root):
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(base64.b85decode(PACKED)))) as tar:
        for m in tar:
            assert m.isfile() and m.name in EXPECTED
            raw=tar.extractfile(m).read();assert hashlib.sha256(raw).hexdigest()==EXPECTED[m.name]
            (root/m.name).write_bytes(raw)
    assert {p.name for p in root.iterdir()}==set(EXPECTED)
    with np.load(io.BytesIO(lzma.decompress((root/'law_delta.xz').read_bytes())),allow_pickle=False) as z:
        fields={k:z[k] for k in z.files if k!='third'};d=z['third'].T.copy()
    for _ in range(3):d=np.cumsum(d,axis=0,dtype=np.uint32)
    fields['kernel']=d.copy(order='C').view(np.float32).reshape(4097,4,5)
    for k,h in json.loads((root/'law_hashes.json').read_text()).items():assert hashlib.sha256(fields[k].tobytes()).hexdigest()==h
    np.savez(root/'law4.npz',**fields)


def main():
    begin=time.perf_counter();out=Path.cwd();r={'request_id':REQUEST,'terminal':False}
    (out/'ingress.json').write_text('{}');np.savez_compressed(out/'scores.npz');np.savez_compressed(out/'mismatches.npz')
    try:
        import torch
        assert torch.cuda.is_available() and 'T4' in torch.cuda.get_device_name()
        dot=torch.arange(8,dtype=torch.float32,device='cuda');r.update(torch=str(torch.__version__),cuda=torch.version.cuda,device=torch.cuda.get_device_name(),dot=float(dot@dot));assert r['dot']==140
        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);expand(root);sys.path.insert(0,str(root))
            p=subprocess.Popen([sys.executable,str(root/'ingress.py'),str(root)],start_new_session=True)
            try:p.wait(timeout=max(10,365-(time.perf_counter()-begin)))
            except subprocess.TimeoutExpired:
                os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=12);r['ingress_budget_terminated']=True
            ingress=json.loads((root/'ingress.json').read_text());(out/'ingress.json').write_text(json.dumps(ingress,indent=1)+'\n')
            r['decoded']=len(ingress.get('entries',[]));r['input_errors']=len(ingress.get('errors',{}));r['ingress_elapsed']=time.perf_counter()-begin;r['tier_checks']=ingress.get('tiers',[]);r['ingress_terminal']=ingress.get('complete',False)
            mismatch={}
            for e in [x for x in ingress.get('entries',[]) if x.get('match_reference') is False][:8]:
                with np.load(root/'data/clips'/(e['id']+'.npz'),allow_pickle=False) as z:
                    for k in ('video','audio'):mismatch[str(e['index'])+'_'+k]=z[k]
            np.savez_compressed(out/'mismatches.npz',**mismatch)
            import panel
            r['experiment'],scores=panel.run(root,ingress);np.savez_compressed(out/'scores.npz',**scores)
            r['terminal']=True
    except Exception:r['error']=traceback.format_exc()[-4800:]
    r['wall_s']=time.perf_counter()-begin;(out/'result.json').write_text(json.dumps(r,indent=1,allow_nan=False)+'\n')

if __name__=='__main__':main()

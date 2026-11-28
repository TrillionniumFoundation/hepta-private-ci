import base64
import hashlib
import io
import json
import lzma
from pathlib import Path
import sys
import tarfile
import tempfile
import time
import traceback
import numpy as np

PACKED = None
EXPECTED = None
REQUEST = 'hcsn-lowband-full-crema-1140569-20261128'


def expand(folder):
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(base64.b85decode(PACKED)))) as archive:
        for m in archive:
            assert m.isfile() and m.name in EXPECTED
            data=archive.extractfile(m).read()
            assert hashlib.sha256(data).hexdigest()==EXPECTED[m.name]
            (folder/m.name).write_bytes(data)
    assert {p.name for p in folder.iterdir()}==set(EXPECTED)
    with np.load(io.BytesIO(lzma.decompress((folder/'law_delta.xz').read_bytes())),allow_pickle=False) as z:
        fields={k:z[k] for k in z.files if k!='third'}
        d=z['third'].T.copy()
    for _ in range(3):d=np.cumsum(d,axis=0,dtype=np.uint32)
    fields['kernel']=d.copy(order='C').view(np.float32).reshape(4097,4,5)
    for k,h in json.loads((folder/'law_hashes.json').read_text()).items():
        assert hashlib.sha256(fields[k].tobytes()).hexdigest()==h
    np.savez(folder/'law4.npz',**fields)


if __name__=='__main__':
    start=time.time()
    dest=Path.cwd()/'result.json'
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expand(folder)
            sys.path.insert(0,str(folder))
            from panel import run
            run(folder,dest,Path.cwd()/'cold.npz',Path.cwd()/'weights.zip')
        result=json.loads(dest.read_text())
        result.update(request_id=REQUEST,cloud_program_wall_s=time.time()-start)
        dest.write_text(json.dumps(result,indent=1,allow_nan=False)+'\n')
    except Exception:
        old=json.loads(dest.read_text()) if dest.is_file() else {}
        old.update(request_id=REQUEST,terminal=False,error=traceback.format_exc()[-3400:],cloud_program_wall_s=time.time()-start)
        dest.write_text(json.dumps(old,allow_nan=False)+'\n')

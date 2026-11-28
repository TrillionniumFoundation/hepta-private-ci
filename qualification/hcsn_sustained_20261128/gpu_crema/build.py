"""Build one small private source from the full low-bandwidth cohort."""
import base64
import hashlib
import io
import json
import lzma
from pathlib import Path
import tarfile
import numpy as np

here=Path(__file__).resolve().parent
base=here.parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def delta_table(path):
    body=path.read_bytes()
    assert sha(body)=='de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4'
    with np.load(io.BytesIO(body),allow_pickle=False) as a:
        fields={k:a[k] for k in a}
    hashes={k:sha(v.tobytes()) for k,v in fields.items()}
    kernel=fields.pop('kernel')
    d=kernel.view(np.uint32).reshape(4097,20).copy()
    for _ in range(3):d[1:]-=d[:-1]
    out=io.BytesIO();np.savez(out,**fields,third=d.T.copy())
    return lzma.compress(out.getvalue(),preset=9),hashes


def build():
    temporal=base/'billion_recovery/original/scripts/hcsn_temporal.py'
    assert sha(temporal.read_bytes())=='1c5ee332f549e3d9ffbff21bfeeef0e181d34e0606e5c27b38bcc66a48ae5eec'
    delta,hashes=delta_table(base/'clock_study/law4.npz')
    inputs={'law_delta.xz':delta,'law_hashes.json':json.dumps(hashes,sort_keys=True).encode(),
            'hcsn_temporal.py':temporal.read_bytes()}
    for n in ('all.xz','data_identity.json','panel.py'):inputs[n]=(here/n).read_bytes()
    data_info=json.loads(inputs['data_identity.json'])
    assert sha(inputs['all.xz'])==data_info['sha']
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w:') as t:
        for n,b in inputs.items():
            i=tarfile.TarInfo(n);i.size=len(b);i.mtime=0;t.addfile(i,io.BytesIO(b))
    payload=base64.b85encode(lzma.compress(buf.getvalue(),preset=9)).decode('ascii')
    expectation={n:sha(b) for n,b in inputs.items()}
    template=(here/'entry.py').read_text()
    text=template.replace('PACKED = None','PACKED = '+repr(payload)).replace('EXPECTED = None','EXPECTED = '+repr(expectation))
    dest=here/'sealed.py';dest.write_text(text)
    size=dest.stat().st_size
    if size>262144:raise ValueError(f'Colab source {size} exceeds 256KiB')
    manifest={'source_sha256':sha(dest.read_bytes()),'bytes':size,'component_sha256':expectation,
              'source_table_bytes_sha256':'de7378f3c170750fb16d1280bcaa376a8904a207da32d268cac82525469e2ea4',
              'protocol_sha256':sha((here/'PROTOCOL.md').read_bytes())}
    (here/'inputs.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(size,manifest['source_sha256'])


if __name__=='__main__':build()

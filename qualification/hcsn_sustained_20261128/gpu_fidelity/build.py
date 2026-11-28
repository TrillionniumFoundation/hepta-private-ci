"""Prepare the job using public corpus metadata and original private network sources."""
import base64
import hashlib
import io
import json
import lzma
from pathlib import Path
import runpy
import tarfile
import numpy as np

here=Path(__file__).resolve().parent;base=here.parent
prior=runpy.run_path(str(base/'gpu_crema/build.py'))
sha=prior['sha'];delta,hashes=prior['delta_table'](base/'clock_study/law4.npz')
parts={'law_delta.xz':delta,'law_hashes.json':json.dumps(hashes,sort_keys=True).encode()}
for n in ('hcsn_temporal.py','encoder.py'):
    parts[n]=(base/'billion_recovery/original/scripts'/n).read_bytes()
parts['prepare_original.py']=(base/'clock_study/prepare_original.py').read_bytes()
assert sha(parts['encoder.py'])=='1c5ee669c47adaca3bec2ae3def64aec117596c8628345beb300e143628824df'
assert sha(parts['hcsn_temporal.py'])=='1c5ee332f549e3d9ffbff21bfeeef0e181d34e0606e5c27b38bcc66a48ae5eec'
for n in ('reference.py','reference.json','ingress.py','panel.py','pointers.bin'):parts[n]=(here/n).read_bytes()
meta=json.loads(parts['reference.json']);assert sha(parts['pointers.bin'])=='7e6fae46ff002ac361210fb22dad8037da795ecd54d077f91bf29e69391838bb'
with np.load(io.BytesIO(lzma.decompress((base/'gpu_crema/all.xz').read_bytes())),allow_pickle=False) as z:
    fields={k:z[k] for k in ('ids','split','labels','tokens')}
for k,a in fields.items():assert sha(a.tobytes())==meta['arrays'][k]['sha256']
npz=io.BytesIO();np.savez(npz,**fields);parts['meta.npz']=npz.getvalue()
buf=io.BytesIO()
with tarfile.open(fileobj=buf,mode='w:') as archive:
    for n,b in sorted(parts.items()):
        el=tarfile.TarInfo(n);el.size=len(b);el.mtime=0;archive.addfile(el,io.BytesIO(b))
expected={n:sha(b) for n,b in parts.items()};payload=base64.b85encode(lzma.compress(buf.getvalue(),preset=9)).decode('ascii')
text=(here/'entry.py').read_text().replace('PACKED = None','PACKED = '+repr(payload)).replace('EXPECTED = None','EXPECTED = '+repr(expected))
f=here/'sealed.py';f.write_text(text);assert f.stat().st_size<=262144
j={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size,'components':expected,'protocol':sha((here/'PROTOCOL.md').read_bytes())}
(here/'inputs.json').write_text(json.dumps(j,indent=1)+'\n');print(f.stat().st_size,j['sha256'])

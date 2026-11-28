"""Build the native decoder recovery source by applying an explicit delta to the parent."""
from pathlib import Path
import base64,hashlib,io,json,lzma,runpy,tarfile

here=Path(__file__).resolve().parent;p=here.parent/'gpu_fidelity'
parent=runpy.run_path(str(p/'sealed.py'));parts={}
with tarfile.open(fileobj=io.BytesIO(lzma.decompress(base64.b85decode(parent['PACKED'])))) as a:
    for m in a:parts[m.name]=a.extractfile(m).read()
for n,b in parts.items():assert hashlib.sha256(b).hexdigest()==parent['EXPECTED'][n]
ing=parts['ingress.py'].decode().replace("rep['decoder']=decoder(root/'env/ffmpeg');save();original.download=fetch", "from recovery import choose\n        rep['decoder']=choose(root,fetch,rep,save);save();original.download=fetch")
start=ing.index('def decoder(path):');end=ing.index('def persist(',start);ing=ing[:start]+ing[end:]
parts['ingress.py']=ing.encode();parts['recovery.py']=(here/'recovery.py').read_bytes()
b=io.BytesIO()
with tarfile.open(fileobj=b,mode='w:') as a:
    for n,raw in sorted(parts.items()):
        m=tarfile.TarInfo(n);m.size=len(raw);m.mtime=0;a.addfile(m,io.BytesIO(raw))
sha=lambda b:hashlib.sha256(b).hexdigest();expected={n:sha(v) for n,v in parts.items()};body=base64.b85encode(lzma.compress(b.getvalue(),preset=9)).decode()
s=(p/'entry.py').read_text().replace('hcsn-public-rematerialize-1140569-20261128','hcsn-native-decoder-fidelity-1140569-20261128').replace('PACKED = None','PACKED = '+repr(body)).replace('EXPECTED = None','EXPECTED = '+repr(expected))
(here/'sealed.py').write_text(s)
r={'sha256':sha(s.encode()),'bytes':len(s.encode()),'parent_source_sha256':sha((p/'sealed.py').read_bytes()),'protocol_sha256':sha((here/'PROTOCOL.md').read_bytes()),'components':expected};assert r['bytes']<=262144
(here/'inputs.json').write_text(json.dumps(r,indent=1)+'\n');print(r['bytes'],r['sha256'])

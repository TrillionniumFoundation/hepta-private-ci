"""Rejoin the private research evidence and extract after checking both chunk and original-file hashes."""
import hashlib,json,zipfile,io,sys
from pathlib import Path
here=Path(__file__).resolve().parent
root=Path(sys.argv[1] if len(sys.argv)>1 else 'restored').resolve()
manifest=json.loads((here/'manifest.json').read_bytes())
chunks=[]
for item in manifest['chunks']:
    b=(here/item['name']).read_bytes()
    assert len(b)==item['size'] and hashlib.sha256(b).hexdigest()==item['sha256'];chunks.append(b)
data=b''.join(chunks)
assert len(data)==manifest['bytes'] and hashlib.sha256(data).hexdigest()==manifest['package_sha256']
with zipfile.ZipFile(io.BytesIO(data)) as z:
    assert set(z.namelist())==set(manifest['file_sha256'])
    for name,sha in manifest['file_sha256'].items():
        path=(root/name).resolve();assert path.is_relative_to(root)
        b=z.read(name);assert hashlib.sha256(b).hexdigest()==sha
        if path.exists():assert path.read_bytes()==b
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b)
print('Restored',len(manifest['file_sha256']),'verified files to',root)

"""Fetch immutable public input files; validate both SHA-256 and Git object identities."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

source=json.loads(Path(__file__).with_name('SOURCE.json').read_text())
directory=Path(sys.argv[1])
directory.mkdir(exist_ok=True,parents=True)
for name, expected in source['data'].items():
    path=directory/name
    data=path.read_bytes() if path.exists() else urllib.request.urlopen(source['data_base']+'/'+name,timeout=120).read()
    assert hashlib.sha256(data).hexdigest()==expected
    assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==source['git_blob_sha1'][name]
    if not path.exists():
        with path.open('xb') as out:out.write(data)

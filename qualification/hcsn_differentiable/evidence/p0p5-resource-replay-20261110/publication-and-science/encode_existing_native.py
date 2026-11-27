"""Encode already verified files into bounded text transport; no downloads or publication."""
import base64
import hashlib
import json
from pathlib import Path
import time

start, cpu = time.monotonic(), time.process_time()
base = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/best-D-publication-and-science-artifact-collection-v1')
output = base / 'text-transport-v1'
output.mkdir(exist_ok=False)
expected = {
    'full-D-publication-originals-v1.zip': (82271, 'd42daa4bc1d65328b9f34d921a5e4c1f181aa89ed44b916a939434bb9ffdf6b8'),
    'science-run-42890048946-attempt1-artifact-13797877354.zip': (77859, 'cab12a2f8f73660e3436e68c2dc84f072f1be857dc5513e8f956c995f2e7d743'),
}
manifest = {}
for name, (size, digest) in expected.items():
    raw = (base / name).read_bytes()
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('input identity differs')
    chunks=[]
    for index, offset in enumerate(range(0,len(raw),30720)):
        chunk=raw[offset:offset+30720]
        filename=name+'.part'+str(index)+'.b64'
        text=base64.b64encode(chunk)
        with (output/filename).open('xb') as stream:
            stream.write(text)
        chunks.append(dict(filename=filename,offset=offset,bytes=len(chunk),sha256=hashlib.sha256(chunk).hexdigest(),
                           text_bytes=len(text),text_sha256=hashlib.sha256(text).hexdigest()))
    manifest[name]=dict(bytes=len(raw),sha256=digest,chunks=chunks)
receipt=dict(schema='immutable-archive-text-transport-v1',files=manifest,
    main_entry_wall_seconds=time.monotonic()-start,main_CPU_seconds=time.process_time()-cpu,
    process_CPU_seconds=time.process_time(),network_downloads=0,release_mutations=0,model_reads=0,
    scope='Local bounded base64 encoding of existing exact archives. Import/startup overhead and tool transport excluded; no second artifact GET or asset upload.')
with (output/'MANIFEST.json').open('x') as stream:
    stream.write(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps(dict(status='encoded_existing_archives',output=str(output),manifest_sha256=hashlib.sha256((output/'MANIFEST.json').read_bytes()).hexdigest(),files=len(expected))),flush=True)

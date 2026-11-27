"""Pack an immutable training resume bundle without interrupting the active campaign."""
import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

def main(source,destination,budget):
    destination.mkdir(exist_ok=True,parents=True)
    raw=io.BytesIO(); hashes={}
    markers=sorted(source.glob(f'*/m{budget}.json'))
    assert len(markers)==16
    with tarfile.open(fileobj=raw,mode='w') as archive:
        for marker in markers:
            for path in (marker,marker.with_suffix('.pt'),marker.parent/'resume.pt'):
                data=path.read_bytes();key=str(path.relative_to(source))
                if path==marker.with_suffix('.pt'):
                    assert hashlib.sha256(data).hexdigest()==json.loads(marker.read_text())['weights_sha256']
                info=tarfile.TarInfo(key);info.size=len(data);info.mtime=0
                archive.addfile(info,io.BytesIO(data));hashes[key]=hashlib.sha256(data).hexdigest()
    packed=gzip.compress(raw.getvalue(),mtime=0,compresslevel=6);chunk=128*1024;names=[]
    for i in range(0,len(packed),chunk):
        path=destination/f'states.tgz.part{i//chunk:03}'
        path.write_bytes(packed[i:i+chunk]);names.append(path.name)
    manifest={'rung_cpu_s':budget,'members_sha256':hashes,'archive_bytes':len(packed),'archive_sha256':hashlib.sha256(packed).hexdigest(),'parts':names,'note':'Each atomically written resume includes the actual most recent optimizer and sampler at time of capture. Some have advanced past the validation rung. The per-rung parameter snapshots and validation receipts are exact.'}
    (destination/'index.json').write_text(json.dumps(manifest,indent=2)+'\n')
    summary=[json.loads(x.read_text()) for x in markers]
    (destination/'development.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(len(packed),len(names))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('destination',type=Path);p.add_argument('budget',type=int)
    a=p.parse_args();main(a.source,a.destination,a.budget)

"""Verify every bounded regular member before materializing frozen research inputs."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT=Path(__file__).resolve().parent


def main(output):
    manifest=json.loads((ROOT/'INPUT_ARCHIVE.json').read_text())
    archive=(ROOT/manifest['archive']).read_bytes()
    if len(archive)!=manifest['bytes'] or hashlib.sha256(archive).hexdigest()!=manifest['sha256']:
        raise ValueError('archive identity mismatch')
    if output.exists():raise FileExistsError('choose a fresh output directory')
    expected=manifest['members'];pending={};total=0
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
        for member in tar:
            name=PurePosixPath(member.name)
            if (not member.isfile() or name.is_absolute() or '..' in name.parts or member.name in pending
                    or member.name not in expected or member.size>4*1024*1024):
                raise ValueError('unsafe, duplicate, unrecognized or oversized input member')
            blob=tar.extractfile(member).read(member.size+1);total+=len(blob)
            if total>32*1024*1024 or len(blob)!=member.size or hashlib.sha256(blob).hexdigest()!=expected[member.name]:
                raise ValueError('member identity or size mismatch')
            pending[member.name]=blob
    if set(pending)!=set(expected):raise ValueError('incomplete input archive')
    output.mkdir(parents=True,exist_ok=False)
    for name,blob in pending.items():
        target=output.joinpath(*PurePosixPath(name).parts);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as out:out.write(blob)
    print(json.dumps({'verified_members':len(pending),'sha256':manifest['sha256'],'output':str(output)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    main(parser.parse_args().output)

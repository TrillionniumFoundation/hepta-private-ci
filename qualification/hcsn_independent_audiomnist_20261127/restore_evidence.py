"""Restore the published immutable evidence to a fresh directory."""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path


def checksum(b):return hashlib.sha256(b).hexdigest()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    dest=args.destination.resolve()
    if dest.exists() and any(dest.iterdir()):raise FileExistsError('choose an empty directory')
    src=Path(__file__).resolve().parent
    info=json.loads((src/'evidence_manifest.json').read_bytes())
    chunks=[]
    for row in info['parts']:
        b=(src/row['file']).read_bytes()
        if checksum(b)!=row['sha256'] or len(b)!=row['bytes']:raise ValueError(row['file'])
        chunks.append(b)
    payload=b''.join(chunks)
    if checksum(payload)!=info['archive_sha256']:raise ValueError('archive hash mismatch')
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        if set(z.namelist())!=set(info['members']):raise ValueError('unexpected archive members')
        for name,expected in info['members'].items():
            path=(dest/name).resolve()
            if not path.is_relative_to(dest):raise ValueError(name)
            b=z.read(name)
            if checksum(b)!=expected:raise ValueError(name)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b)
    print('restored',len(info['members']),'verified files to',dest)

"""Verify and unpack the released experiment. Expects the repository evidence directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from zipfile import ZipFile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unpack(evidence,destination):
    config=json.loads((evidence/'archive_manifest.json').read_text())
    destination.mkdir(parents=True,exist_ok=False)
    seen=set()
    for name,rec in config['archives'].items():
        path=evidence/name
        if path.parent!=evidence or sha(path.read_bytes())!=rec['sha256']:
            raise ValueError('archive digest differs')
        with ZipFile(path) as archive:
            if set(archive.namelist())!=set(rec['files']):raise ValueError('archive coverage')
            for member,identity in rec['files'].items():
                rel=PurePosixPath(member)
                if rel.is_absolute() or '..' in rel.parts or member in seen:raise ValueError('ambiguous member')
                b=archive.read(member)
                if len(b)!=identity['bytes'] or sha(b)!=identity['sha256']:raise ValueError('member digest differs')
                target=destination/rel
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as fh:fh.write(b)
                seen.add(member)
    return config


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('evidence',type=Path);p.add_argument('destination',type=Path);p.add_argument('--verify',action='store_true')
    args=p.parse_args();manifest=unpack(args.evidence,args.destination)
    if args.verify:
        for trial in manifest['confirmed_trials']:
            subprocess.run([sys.executable,'-m','qualification.hcsn_intervention_value.verify_policy',
                str(args.destination/trial/'discovery'),str(args.destination/trial/'policies')],check=True)
    print(f"Verified {len(manifest['archives'])} archives.")

"""Wait for independent verification, preserve all seven-site weight patches, and seal a release manifest."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tarfile
import time


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write_json(p,v):
    tmp=p.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(v,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    tmp.replace(p)


def run(base):
    out=base/'run';vault=base/'verified_archive';vault.mkdir(exist_ok=True)
    with (vault/'archive.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verification=out/'independent_verification.json'
        while not verification.is_file():time.sleep(30)
        checked=json.loads(verification.read_text());term=out/'terminal.json';seal=out/'development_seal.json'
        if checked['verified'] is not True or checked['candidates']!=27 or checked['terminal_sha256']!=sha(term):
            raise ValueError('verified terminal identity required')
        terminal=json.loads(term.read_text())
        if sha(seal)!=terminal['development_seal_sha256']:raise ValueError('original seal mismatch')
        design=json.loads(seal.read_text());candidates=[item for group in design['candidates'].values() for item in group]
        if len(candidates)!=27 or len({x['cell'] for x in candidates})!=27:raise ValueError('candidate panel')
        wmeta=out/'model_patches_archive.json';bundle=vault/'all-27-seven-site-patches.tar'
        members={}
        for row in sorted(candidates,key=lambda x:x['cell']):
            name=row['cell']+'/writes.pt';p=out/name
            if sha(p)!=row['weights_sha256']:raise ValueError('weight checksum')
            members[name]={'size':p.stat().st_size,'sha256':row['weights_sha256']}
        if bundle.exists():
            # Reconcile an interrupted receipt write by comparing contents to the original files.
            with tarfile.open(bundle,mode='r:') as archive:
                if set(archive.getnames())!=set(members):raise ValueError('irregular archive')
                for it in archive:
                    if not it.isreg() or it.size!=members[it.name]['size']:raise ValueError('archive member')
                    if hashlib.file_digest(archive.extractfile(it),'sha256').hexdigest()!=members[it.name]['sha256']:
                        raise ValueError('archive member hash')
        else:
            tmp=bundle.with_suffix('.part')
            with tarfile.open(tmp,'w',format=tarfile.USTAR_FORMAT) as tar:
                for name,item in members.items():
                    info=tarfile.TarInfo(name);info.size=item['size'];info.mode=0o600
                    info.uid=info.gid=0;info.mtime=0;info.uname=info.gname=''
                    with (out/name).open('rb') as f:tar.addfile(info,f)
            with tmp.open('rb') as f:os.fsync(f.fileno())
            os.replace(tmp,bundle)
        recap={'storage':'original-executor task-owned verified_archive','filename':bundle.name,
               'sha256':sha(bundle),'bytes':bundle.stat().st_size,'member_count':len(members),
               'members':members,'recovery':'Rebuild each exact seeded AVText parent and load the named six read matrices and shared projection.',
               'scope':'Seven-matrix training patches for every candidate. The seeded frozen model is defined by the source and seed.'}
        if wmeta.exists() and json.loads(wmeta.read_text())!=recap:raise ValueError('archive changed')
        write_json(wmeta,recap)
        names=['design.json','events.jsonl','development_seal.json','terminal.json','independent_verification.json','model_patches_archive.json']
        for row in candidates:
            names.extend(f'{row["cell"]}/{leaf}' for leaf in
                         ('fit.json','development.json','dev/scores.npz','dev/timing.json','cold/scores.npz','cold/timing.json'))
        files={n:{'sha256':sha(out/n),'size':(out/n).stat().st_size} for n in sorted(names)}
        release={'terminal_sha256':sha(term),'development_seal_sha256':sha(seal),'verified_sha256':sha(verification),
                 'weights_archive_sha256':recap['sha256'],'files':files}
        manifest=out/'release_manifest.json'
        if manifest.exists() and json.loads(manifest.read_text())!=release:raise ValueError('release changed')
        write_json(manifest,release);print(json.dumps({'files':len(files),'archive':str(bundle),
               'archive_sha256':recap['sha256'],'manifest_sha256':sha(manifest)}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);run(p.parse_args().base.resolve())

"""Preserve every fixed historical checkpoint on the verified second physical host."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

SRC = '/home/qq/.local/share/hepta-research/hcsn-9de7-sustained-history'
ROOT = Path('/home/qian-qi/.local/share/hepta-research/hcsn-9de7-sustained-history')
CAPTURE = '/home/qq/.local/share/hepta-research/hcsn-9de7-capture-history.py'
SSH = ['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=12']
SOURCE_ID='425aa533e64f94429710d565b262368df1ccf2a6b99521a02fcd82a62916b4d2'
DEST_ID='d90fa41f7e59edf2f2a732ea082cac83085a2a3695a503cd82b6b4eef9cab9f3'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def update():
    payload = subprocess.check_output(SSH+['ai395','/usr/bin/python3',CAPTURE],timeout=180)
    manifest = json.loads(payload)
    if manifest['source_machine_sha256']!=SOURCE_ID or digest(Path('/etc/machine-id'))!=DEST_ID:
        raise ValueError('unexpected source or destination host')
    previous = ROOT/'receipt.json'
    before = json.loads(previous.read_text()) if previous.exists() else {}
    if hashlib.sha256(payload).hexdigest()==before.get('source_manifest_sha256') and not manifest['complete']:
        return False
    objects = {v['sha256']:v['bytes'] for v in manifest['weights'].values()}
    missing = [k for k in objects if not (ROOT/'objects'/(k+'.pt')).exists()]
    if shutil.disk_usage(ROOT).free < sum(objects[k] for k in missing) + (8<<30):
        raise OSError('insufficient receiver headroom')
    if missing:
        transfer=''.join('objects/'+k+'.pt\n' for k in sorted(missing)).encode()
        subprocess.run(['rsync','-r','--files-from=-','-e',' '.join(SSH),
                        'ai395:'+SRC+'/',str(ROOT)+'/'],input=transfer,check=True,timeout=600)
    for k,size in objects.items():
        path=ROOT/'objects'/(k+'.pt')
        if path.stat().st_size!=size or digest(path)!=k:
            raise ValueError('destination object verification failed')
    receipt={'complete':manifest['complete'],'weights':len(manifest['weights']),
             'unique_objects':len(objects),'bytes':sum(objects.values()),'utc_unix':time.time(),
             'source_manifest_sha256':hashlib.sha256(payload).hexdigest(),
             'first_copy_control':'original native trainer history and recorded hashes',
             'cold_arrays_acquired':False}
    snap=ROOT/'manifests'/(receipt['source_manifest_sha256']+'.json')
    if not snap.exists():
        snap.write_bytes(payload)
    if digest(snap)!=receipt['source_manifest_sha256']:
        raise ValueError('changed inventory')
    temp=ROOT/'receipt.next'
    temp.write_text(json.dumps(receipt,indent=2)+'\n')
    temp.replace(previous)
    print(json.dumps(receipt),flush=True)
    return manifest['complete']


if __name__=='__main__':
    os.umask(0o077)
    ROOT.mkdir(exist_ok=True,parents=True,mode=0o700)
    (ROOT/'manifests').mkdir(exist_ok=True,mode=0o700)
    with (ROOT/'mirror.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for attempt in range(750):
            try:
                if update():
                    break
            except (OSError, subprocess.SubprocessError) as err:
                print(type(err).__name__,str(err)[:200],flush=True)
            time.sleep(120)
        else:
            raise TimeoutError('finite mirror observation window exhausted')

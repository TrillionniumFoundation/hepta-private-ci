"""Desktop relay for the independent verified billion-parameter CPU study, sharing the results branch."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REMOTE='/home/qq/.local/share/hepta-research/hcsn-billion-edit-1140569/run'
PREFIX='qualification/hcsn_sustained_20261128/'
KIND='billion_edit_raw'
BRANCH='research/hcsn-sustained-boundary-20261128-1140569-results'
HELPER_SHA='0f182311ca3e2904e469580ecab2b58240991fbac2d3254e3286f3e5570ac60d'


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def handle(root,helper):
    if sha(helper)!=HELPER_SHA:raise ValueError('unexpected shared publisher')
    sys.path.insert(0,str(helper.parent))
    spec=importlib.util.spec_from_file_location('pinned_results_publisher',helper)
    pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)
    pub.PREFIX=PREFIX
    if pub.BRANCH!=BRANCH:raise ValueError('unexpected publication branch')
    root.mkdir(exist_ok=True);dest=root/KIND;dest.mkdir(exist_ok=True)
    done=root/'publication_receipt.json'
    with (root/'billion-relay.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if done.exists():
            print(done.read_text(),flush=True);return
        script=f"""import hashlib,json
from pathlib import Path
p=Path({REMOTE!r})/'release_manifest.json'
if p.is_file():
 b=p.read_bytes(); print(json.dumps(dict(sha256=hashlib.sha256(b).hexdigest(),document=json.loads(b))))
else:print('null')
"""
        while True:
            try:
                receipt=json.loads(pub.run(pub.SSH+['python3','-'],script.encode(),timeout=60))
                if receipt is None:time.sleep(40);continue
                manifest=receipt['document'];files=manifest['files'];names=list(files)+['release_manifest.json']
                if len(files)!=168 or any(Path(n).is_absolute() or '..' in Path(n).parts or '\n' in n for n in names):
                    raise ValueError('release manifest paths')
                pub.run(['rsync','-a','--files-from=-','-e','ssh -o BatchMode=yes -o StrictHostKeyChecking=yes',
                         'ai395:'+REMOTE+'/',str(dest)+'/'],('\n'.join(names)+'\n').encode(),timeout=600)
                if sha(dest/'release_manifest.json')!=receipt['sha256']:raise ValueError('manifest transfer checksum')
                for name,e in files.items():
                    p=dest/name
                    if p.stat().st_size!=e['size'] or sha(p)!=e['sha256']:raise ValueError('transferred file mismatch '+name)
                commit=pub.push(KIND,[dest/n for n in names],root)
                # Ensure the exact released commit contains the expected nested file blob.
                expected=(dest/'terminal.json').read_bytes()
                oid=hashlib.sha1(b'blob '+str(len(expected)).encode()+b'\0'+expected).hexdigest()
                path=PREFIX+KIND+'/terminal.json'
                info=pub.gh('GET','repos/TrillionniumFoundation/hepta-private-ci/contents/'+path+'?ref='+commit)
                if info['sha']!=oid:raise ValueError('published content mismatch')
                note={'commit':commit,'branch':BRANCH,'prefix':PREFIX+KIND+'/','files':len(names),'verified_terminal_blob':oid,
                      'weights_retained_on':'ai395','terminal_sha256':manifest['terminal_sha256'],
                      'release_manifest_sha256':receipt['sha256'],'weights_archive_sha256':manifest['weights_archive_sha256'],
                      'utc_unix':time.time()}
                tmp=done.with_suffix('.tmp');tmp.write_text(json.dumps(note,indent=2)+'\n');tmp.replace(done)
                print(json.dumps(note),flush=True);return
            except (RuntimeError,subprocess.TimeoutExpired,ConnectionError) as exc:
                print(type(exc).__name__,str(exc),flush=True);time.sleep(55)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('helper',type=Path)
    a=ap.parse_args();handle(a.root.resolve(),a.helper.resolve())

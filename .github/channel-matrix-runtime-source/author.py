"""Publish Git objects for reviewed Matrix source; NEVER move a branch or qualify a release."""
import base64
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path.cwd().resolve()
BASE = '8ce2dcde1d1dbdd9965263a5317acad83a146976'
STAGING = '.github/channel-matrix-runtime-source'
WORKFLOW = '.github/workflows/channel-matrix-runtime-author.yml'
PACKED = '51fd64052dd4144007c8589a0368b9cd30561301e56e6aa32163d569db18f979'
RAW = '47173ee0a297af56f68acc2668e01c492109c8d73f8ef52953449040844c2a7f'
REPO = 'TrillionniumFoundation/hepta-private-ci'
OUT = Path(os.environ['RUNNER_TEMP']) / 'matrix-runtime-authoring'
OUT.mkdir(exist_ok=True)

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()

def digest(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

def allowed(path):
    return (path.startswith(('codex-rs/hepta-matrix-store/', 'codex-rs/hepta-matrixd/',
                            'codex-rs/hepta-matrix-sdk/', 'docs/modules/channel.matrix/',
                            'scripts/channel_matrix_', 'scripts/tests/test_channel_matrix'))
            or path in ('scripts/verify_channel_matrix_candidate.py', '.github/workflows/channel-matrix-preserve-unknown.yml'))

def load():
    head = git('rev-parse', 'HEAD')
    if head != os.environ['EXPECTED_SHA'] or git('rev-parse', 'HEAD^') != BASE:
        raise RuntimeError('publication parent changed')
    initial = set(git('diff', '--name-only', BASE, 'HEAD').splitlines())
    expected = {STAGING+'/part-'+str(i).zfill(3) for i in range(1,5)} | {STAGING+'/author.py', WORKFLOW}
    if initial != expected:
        raise RuntimeError('authoring commit contains unexpected paths')
    packed = base64.b64decode(''.join((ROOT/STAGING/('part-'+str(i).zfill(3))).read_text() for i in range(1,5)), validate=True)
    if len(packed) != 23740 or hashlib.sha256(packed).hexdigest() != PACKED:
        raise RuntimeError('reviewed package checksum mismatch')
    decoder = lzma.LZMADecompressor(memlimit=128*1024*1024)
    raw = decoder.decompress(packed, max_length=1000001)
    if len(raw) != 97592 or not decoder.eof or decoder.unused_data or hashlib.sha256(raw).hexdigest() != RAW:
        raise RuntimeError('reviewed source checksum mismatch')
    data = json.loads(raw)
    if data['base'] != BASE or len(data['files']) != 30:
        raise RuntimeError('reviewed source scope mismatch')
    return data

def apply(data):
    seen = set()
    for entry in data['files']:
        relative = entry['path']; path = ROOT/relative
        if relative in seen or not allowed(relative) or '..' in Path(relative).parts or path.resolve() != path or path.is_symlink():
            raise RuntimeError('unsafe or duplicate reviewed path')
        seen.add(relative)
        old = path.read_bytes() if path.is_file() else None
        if (digest(old) if old is not None else None) != entry['old']:
            raise RuntimeError('reviewed preimage changed: '+relative)
        if entry['new'] is None:
            path.unlink(); continue
        if old is None:
            new = entry['text'].encode()
        else:
            lines = old.decode().splitlines(keepends=True)
            end = len(lines)
            for i,j,text in reversed(entry['edits']):
                if type(i) is not int or type(j) is not int or not 0 <= i <= j <= end:
                    raise RuntimeError('invalid edit range')
                lines[i:j] = text.splitlines(keepends=True); end = i
            new = ''.join(lines).encode()
        if digest(new) != entry['new']:
            raise RuntimeError('reviewed result mismatch: '+relative)
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(new)
    (OUT/'reviewed-package.json').write_text(json.dumps({'base':BASE,'paths':sorted(seen),'packedSha256':PACKED,'rawSha256':RAW,'nativeQualified':False},indent=2)+'\n')

def api(path, payload):
    request = urllib.request.Request('https://api.github.com/repos/'+REPO+path,
        data=json.dumps(payload).encode(), method='POST',
        headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'], 'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)

def publish(data):
    # The connector performs the eventual non-force ref update after inspecting
    # this receipt. This authoring job has no branch-update or promotion action.
    changed = set(git('diff','--name-only').splitlines())
    changed.update(git('ls-files','--others','--exclude-standard').splitlines())
    changed.discard('')
    if len(changed)>200 or any(not allowed(p) for p in changed):
        raise RuntimeError('formatter/source escaped Matrix owner scope')
    tree=[]; inventory=[]
    for relative in sorted(changed):
        path=ROOT/relative
        if path.is_symlink() or path.resolve()!=path:
            raise RuntimeError('non-regular publication input')
        if not path.is_file():
            tree.append({'path':relative,'mode':'100644','type':'blob','sha':None});continue
        content=path.read_bytes()
        if len(content)>2*1024*1024:
            raise RuntimeError('source budget exceeded')
        tree.append({'path':relative,'mode':'100644','type':'blob','content':content.decode()})
        inventory.append({'path':relative,'gitBlob':digest(content),'sha256':hashlib.sha256(content).hexdigest()})
    for relative in [STAGING+'/part-'+str(i).zfill(3) for i in range(1,5)]+[STAGING+'/author.py',WORKFLOW]:
        tree.append({'path':relative,'mode':'100644','type':'blob','sha':None})
    result=api('/git/trees',{'base_tree':git('rev-parse','HEAD^{tree}'),'tree':tree})
    receipt={'schema':'hepta.channel-matrix-reviewed-tree.v1','parentSha':git('rev-parse','HEAD'),
             'reviewedBase':BASE,'treeSha':result['sha'],'files':inventory,
             'scope':'source_authoring_python_sqlite_and_rustfmt_not_native_execution',
             'nativeQualified':False,'independentAcceptance':False,'activation':False,'release':False}
    (OUT/'publication.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('REVIEWED_MATRIX_TREE='+result['sha'])

if __name__=='__main__':
    data=load()
    if sys.argv[1]=='apply': apply(data)
    elif sys.argv[1]=='tree': publish(data)
    else: raise RuntimeError('unknown authoring command')

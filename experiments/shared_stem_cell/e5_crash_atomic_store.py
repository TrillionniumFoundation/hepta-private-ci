#!/usr/bin/env python3
"""Research-only atomic packed SGD checkpoint publication with process SIGKILL injection.

Immutable content-addressed JSON checkpoint + commit manifest + fsynced atomic
HEAD; non-authoritative, unsigned, POSIX local-filesystem experiment only.
Does NOT implement a production WAL, CAS service, current FinalUse, or power-loss proof.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import uuid
from contextlib import contextmanager

SCHEMA='hepta.e5.crash-atomic-head.v1'
MANIFEST='hepta.e5.crash-checkpoint-commit.v1'
LOCK='LOCK'
ZERO='0'*64
MAX_BYTES=750*1024*1024
FAILPOINTS=('blob_partial','blob_fsynced','blob_published',
            'manifest_partial','manifest_fsynced','manifest_published',
            'head_partial','head_fsynced','head_replaced','head_dirsynced')
class Invalid(ValueError):pass

def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')
def _pairs(seq):
    d={}
    for k,v in seq:
        if k in d:raise Invalid('duplicate JSON key')
        d[k]=v
    return d

def parse(blob):
    try:
        return json.loads(blob,object_pairs_hook=_pairs,
                          parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON')))
    except (ValueError,UnicodeError,TypeError) as e:raise Invalid('invalid checkpoint JSON') from e

def hexdigest(v,allow_zero=False):
    if (type(v) is not str or len(v)!=64 or (v==ZERO and not allow_zero) or
        any(c not in '0123456789abcdef' for c in v)):
        raise Invalid('noncanonical SHA256')
    return v

def stable(s):
    if type(s) is not str or not 1<=len(s)<=128 or any(not(c.isascii() and (c.isalnum() or c in '._:-')) for c in s):
        raise Invalid('invalid scoped identity')
    return s

def _normal_file(path):
    if path.is_symlink():raise Invalid('symlink forbidden')
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
    try:fd=os.open(path,flags)
    except OSError as exc:raise Invalid('missing/unreadable immutable file') from exc
    return fd

def _read(path,limit):
    fd=_normal_file(path)
    try:
        size=os.fstat(fd)
        if not stat.S_ISREG(size.st_mode) or not 0<size.st_size<=limit:raise Invalid('wrong file type/size')
        with os.fdopen(fd,'rb',closefd=False) as f:return f.read(limit+1)
    finally:os.close(fd)

def _dirsync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0))
    try:os.fsync(fd)
    finally:os.close(fd)

def _mkdir(path):
    if path.is_symlink():raise Invalid('symlinked store directory')
    if not path.exists():path.mkdir(mode=0o700)
    if not path.is_dir():raise Invalid('not a directory')

def _inject(point,at):
    if point!=at:return
    if os.environ.get('HEPTA_E5_CRASH_INJECTION')!='research-only':
        raise Invalid('fault injection requires explicitly bounded test child')
    os.kill(os.getpid(),signal.SIGKILL)
    raise AssertionError('unreachable')

@contextmanager
def _lock(root):
    root=Path(root)
    if not root.is_dir() or root.is_symlink():raise Invalid('unsafe store root')
    for name in ('objects','commits'):_mkdir(root/name)
    _dirsync(root)
    lock=root/LOCK
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):raise Invalid('unsafe lock file')
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield root
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)

def _immutable(folder,name,data,stage,crash):
    if type(data) is not bytes or not 0<len(data)<=MAX_BYTES:raise Invalid('unbounded object')
    target=folder/name
    if target.is_symlink():raise Invalid('target symlink')
    temporary=folder/('.stage-'+uuid.uuid4().hex)
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        offset=0
        for start in range(0,len(data),65536):
            block=memoryview(data)[start:start+65536]
            while block:
                n=os.write(fd,block)
                if n<=0:raise OSError('short write')
                offset+=n;block=block[n:]
                if offset>0 and start==0:_inject(crash,stage+'_partial')
        os.fsync(fd)
        _inject(crash,stage+'_fsynced')
    finally:os.close(fd)
    try:os.link(temporary,target,follow_symlinks=False)
    except FileExistsError:
        if _read(target,MAX_BYTES)!=data:raise Invalid('content address collision/corruption')
    _dirsync(folder)
    _inject(crash,stage+'_published')
    temporary.unlink(missing_ok=True)
    _dirsync(folder)

def _load_manifest(root,hash_):
    hexdigest(hash_)
    blob=_read(root/'commits'/(hash_+'.json'),4096)
    if sha(blob)!=hash_:raise Invalid('manifest byte hash mismatch')
    manifest=parse(blob)
    required={'schema','seq','scope','generation','fence_sha256','model_sha256',
              'snapshot_sha256','checkpoint_steps','parent_manifest_sha256',
              'authority','production_promotion_permitted'}
    if type(manifest) is not dict or set(manifest)!=required or manifest.get('schema')!=MANIFEST:
        raise Invalid('bad commit manifest fields')
    for key in ('scope',):stable(manifest[key])
    for key in ('fence_sha256','model_sha256','snapshot_sha256'):hexdigest(manifest[key])
    hexdigest(manifest['parent_manifest_sha256'],allow_zero=True)
    if (type(manifest['seq']) is not int or manifest['seq']<0 or
        type(manifest['generation']) is not int or manifest['generation']<1 or
        type(manifest['checkpoint_steps']) is not int or not 0<=manifest['checkpoint_steps']<=6 or
        manifest['production_promotion_permitted'] is not False or manifest['authority']!='DENY_ALL'):
        raise Invalid('bad commit state')
    if manifest['seq']==0 and manifest['parent_manifest_sha256']!=ZERO:raise Invalid('bad genesis')
    if manifest['seq']>0 and manifest['parent_manifest_sha256']==ZERO:raise Invalid('parent absent')
    return manifest

def _current(root):
    head=root/'HEAD.json'
    if not head.exists() and not head.is_symlink():
        # A missing HEAD after any committed manifest exists is a rollback, not an empty store.
        if any((root/'commits').glob('*.json')):raise Invalid('lost HEAD with existing commits')
        return None,None
    data=parse(_read(head,1024))
    if type(data) is not dict or set(data)!={'schema','manifest_sha256'} or data['schema']!=SCHEMA:
        raise Invalid('malformed HEAD')
    current=hexdigest(data['manifest_sha256'])
    return current,_load_manifest(root,current)

def load(root,scope,generation,fence_sha256,model_sha256,logical):
    stable(scope);hexdigest(fence_sha256);hexdigest(model_sha256)
    if type(generation) is not int or generation<1 or logical not in (64,256,1024,4096):raise Invalid('invalid requested generation/cohort')
    with _lock(root) as path:
        tip,manifest=_current(path)
        if tip is None:return None
        if (manifest['scope']!=scope or manifest['generation']!=generation or
            manifest['fence_sha256']!=fence_sha256 or manifest['model_sha256']!=model_sha256):
            raise Invalid('Scope, model, generation or fence mismatch')
        if manifest['seq']:
            parent=_load_manifest(path,manifest['parent_manifest_sha256'])
            if (parent['seq']!=manifest['seq']-1 or parent['scope']!=scope or
                parent['generation']!=generation or parent['fence_sha256']!=fence_sha256 or
                parent['model_sha256']!=model_sha256 or parent['checkpoint_steps']>=manifest['checkpoint_steps']):
                raise Invalid('parent chain or step monotonicity violation')
        raw=_read(path/'objects'/(manifest['snapshot_sha256']+'.json'),MAX_BYTES)
        if sha(raw)!=manifest['snapshot_sha256']:raise Invalid('corrupt committed checkpoint bytes')
        snapshot=parse(raw)
        if type(snapshot) is not dict or snapshot.get('scope')!=scope or snapshot.get('generation')!=generation or snapshot.get('logical')!=logical or snapshot.get('steps')!=manifest['checkpoint_steps']:
            raise Invalid('checkpoint semantic identity mismatch')
        # This is a local integrity check; it does NOT authenticate model origin or authority.
        from e5_packed_momentum_replay import restore
        restore(snapshot,scope,generation,logical)
        return {'manifest_sha256':tip,'manifest':manifest,'snapshot':snapshot,
                'local_file_integrity_verified':True,'signed_origin_verified':False,
                'unclean_power_loss_recovery_verified':False,
                'production_promotion_permitted':False,'authority':'DENY_ALL'}

def commit(root,snapshot,scope,generation,fence_sha256,model_sha256,expected_manifest_sha256,crash=None):
    stable(scope);hexdigest(fence_sha256);hexdigest(model_sha256)
    hexdigest(expected_manifest_sha256,allow_zero=True)
    if crash is not None and crash not in FAILPOINTS:raise Invalid('unknown crash step')
    if type(snapshot) is not dict or snapshot.get('scope')!=scope or snapshot.get('generation')!=generation:
        raise Invalid('checkpoint source Scope/generation')
    from e5_packed_momentum_replay import restore
    logical=snapshot.get('logical')
    if logical not in (64,256,1024,4096):raise Invalid('unregistered size')
    restore(snapshot,scope,generation,logical)
    with _lock(root) as path:
        tip,prev=_current(path)
        if (tip or ZERO)!=expected_manifest_sha256:raise Invalid('compare-and-swap mismatch')
        if prev is not None and (prev['scope']!=scope or prev['generation']!=generation or
             prev['fence_sha256']!=fence_sha256 or prev['model_sha256']!=model_sha256 or
             prev['checkpoint_steps']>=snapshot['steps']):
            raise Invalid('stale generation, model or nonadvancing optimizer')
        seq=prev['seq']+1 if prev else 0
        payload=canonical(snapshot)
        snapshot_sha=sha(payload)
        manifest={'schema':MANIFEST,'seq':seq,'scope':scope,'generation':generation,
                  'fence_sha256':fence_sha256,'model_sha256':model_sha256,
                  'snapshot_sha256':snapshot_sha,'checkpoint_steps':snapshot['steps'],
                  'parent_manifest_sha256':tip or ZERO,
                  'authority':'DENY_ALL','production_promotion_permitted':False}
        encoded_manifest=canonical(manifest)
        manifest_sha=sha(encoded_manifest)
        _immutable(path/'objects',snapshot_sha+'.json',payload,'blob',crash)
        _immutable(path/'commits',manifest_sha+'.json',encoded_manifest,'manifest',crash)
        # Only HEAD.json confers local visibility. Unreferenced immutable files are orphans.
        temporary=path/('.head-'+uuid.uuid4().hex)
        content=canonical({'schema':SCHEMA,'manifest_sha256':manifest_sha})
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            mid=max(1,len(content)//2)
            os.write(fd,content[:mid]);_inject(crash,'head_partial')
            os.write(fd,content[mid:]);os.fsync(fd);_inject(crash,'head_fsynced')
        finally:os.close(fd)
        os.replace(temporary,path/'HEAD.json');_inject(crash,'head_replaced')
        _dirsync(path);_inject(crash,'head_dirsynced')
        return {'schema':'hepta.e5.crash-atomic-commit-receipt.v1','seq':seq,
                'manifest_sha256':manifest_sha,'snapshot_sha256':snapshot_sha,
                'source_authority_authenticated':False,'native_wal_verified':False,
                'power_cut_durability_independently_verified':False,
                'production_promotion_permitted':False,'authority':'DENY_ALL'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store',type=Path,required=True)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--scope',required=True);p.add_argument('--generation',type=int,required=True)
    p.add_argument('--fence',required=True);p.add_argument('--model',required=True)
    p.add_argument('--expected',required=True);p.add_argument('--crash',choices=FAILPOINTS)
    p.add_argument('--receipt',type=Path)
    args=p.parse_args()
    snapshot=parse(_read(args.snapshot,MAX_BYTES))
    result=commit(args.store,snapshot,args.scope,args.generation,args.fence,args.model,args.expected,crash=args.crash)
    if args.receipt is not None:
        with args.receipt.open('x',encoding='utf8') as out:json.dump(result,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n')
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__':main()

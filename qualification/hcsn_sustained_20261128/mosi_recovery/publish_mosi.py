"""Verify the two MOSI evidence scopes locally, then publish to distinct private result directories."""
import argparse
import fcntl
import hashlib
import builtins
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import stat
from types import MappingProxyType, ModuleType
import tempfile
import time

HERE=Path(__file__).resolve().parent
SHARED='/home/qian-qi/.local/state/hcsn-1140569-result-relay/publish_results.py'
HELPER_SHA='0f182311ca3e2904e469580ecab2b58240991fbac2d3254e3286f3e5570ac60d'
BRANCH='research/hcsn-sustained-boundary-20261128-1140569-results'
PREFIX='qualification/hcsn_sustained_20261128/'
REPO='https://github.com/TrillionniumFoundation/hepta-private-ci.git'
API='repos/TrillionniumFoundation/hepta-private-ci/git'


class PublicationIncomplete(ValueError):
    """A completion claim is unproven; retain it without skipping or republishing."""


# Explicit bounds for the sealed MOSI publication profiles, not arbitrary model archives.
MAX_SCOPE_BYTES=64*1024*1024
MAX_INPUT_BYTES=16*1024*1024
MAX_METADATA_BYTES=1024*1024
MAX_CODE_BYTES=64*1024
MAX_INPUT_FILES=1024
ARCHIVE_HELPER_SHA='be141f99e01d06eaee8febbf215cc13646f0de893f474816bf55cc4abe5c54a2'
FRESH_DRIVER_SHA='e7537324fb45f9bfbde4dc0078265442dd46d41e72a87eee5bdcaa12ba9fe0cd'
FRESH_VERIFIER_SHA='bdbb45e0ad4227ef2750bb7d35ca4d2035b1c9fd8257d2c4e2c7ed7fa76b17af'


def safe_relative(name):
    if (not isinstance(name,str) or not name or Path(name).is_absolute()
            or '..' in Path(name).parts or '/'.join(Path(name).parts)!=name
            or any(c in name for c in '\\\x00\n\r\t')):
        raise PublicationIncomplete('incomplete publication: unsafe object path')
    return name


def file_identity(item):
    return (item.st_dev,item.st_ino,item.st_mode,item.st_nlink,item.st_size,item.st_mtime_ns,item.st_ctime_ns)


def regular_bytes(root,name,limit,private=False,expected=None):
    """Bounded descriptor-relative reads; source hardlinks are valid, symlinks are not."""
    if type(limit) is not int or not 0<=limit<=MAX_INPUT_BYTES:
        raise PublicationIncomplete('incomplete publication: invalid input byte limit')
    parts=Path(safe_relative(name)).parts
    flags=os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW
    directory=os.open(root,flags|os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            following=os.open(part,flags|os.O_DIRECTORY,dir_fd=directory)
            os.close(directory);directory=following
        descriptor=os.open(parts[-1],flags|os.O_NONBLOCK,dir_fd=directory)
        with os.fdopen(descriptor,'rb') as stream:
            before=os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_size>limit
                    or (private and before.st_nlink!=1)):
                raise PublicationIncomplete('incomplete publication: nonregular, linked private, or oversized input '+name)
            if expected is not None and file_identity(before)!=expected:
                raise PublicationIncomplete('incomplete publication: private input identity changed '+name)
            chunks=[];count=0
            while chunk:=stream.read(min(1024*1024,limit-count+1)):
                count+=len(chunk)
                if count>limit:raise PublicationIncomplete('incomplete publication: input byte limit '+name)
                chunks.append(chunk)
            after=os.fstat(stream.fileno())
            if count!=before.st_size or file_identity(before)!=file_identity(after):
                raise PublicationIncomplete('incomplete publication: input changed during capture '+name)
            return b''.join(chunks)
    finally:os.close(directory)


def metadata_bytes(data):
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('duplicate metadata key '+key)
            value[key]=item
        return value
    def constant(value):raise ValueError('nonfinite metadata '+value)
    value=json.loads(data,object_pairs_hook=unique,parse_constant=constant)
    if not isinstance(value,dict):raise ValueError('metadata object required')
    return value


def capture_inputs(task,kind):
    """Capture metadata once, then derive every remaining path from those exact bytes."""
    captured={};total=0
    def take(name,limit=MAX_INPUT_BYTES):
        nonlocal total
        name=safe_relative(name)
        if name not in captured:
            if len(captured)>=MAX_INPUT_FILES:
                raise PublicationIncomplete('incomplete publication: input count limit')
            payload=regular_bytes(task,name,min(limit,MAX_SCOPE_BYTES-total))
            total+=len(payload);captured[name]=payload
        elif len(captured[name])>limit:
            raise PublicationIncomplete('incomplete publication: repeated input exceeds tighter byte limit '+name)
        return captured[name]
    if kind=='mosi_recovery_raw':
        take('source/SEAL.json',MAX_METADATA_BYTES)
        record=metadata_bytes(take('candidate_replay/reconstruction_result.json',MAX_METADATA_BYTES))
        take('candidate_replay/candidate_hash_seal.json',MAX_METADATA_BYTES)
        for name in ('input_recovery.json','source_transfer.json'):
            take(name,MAX_METADATA_BYTES)
        try:take('original_custody_audit.json',MAX_METADATA_BYTES)
        except FileNotFoundError:pass
        enrolled=record['authenticated_cold_results']
        if not isinstance(enrolled,dict) or len(enrolled)>MAX_INPUT_FILES:
            raise PublicationIncomplete('incomplete publication: recovery enrollment')
        for key in enrolled:
            safe_relative(key)
            take('candidate_replay/'+key+'.cold.npz')
            take('candidate_replay/fits/'+key)
    elif kind=='mosi_fresh_raw':
        take('fresh/FRESH_SEAL.json',MAX_METADATA_BYTES)
        terminal=metadata_bytes(take('fresh/terminal_manifest.json',MAX_METADATA_BYTES))
        for name in ('reconstructed/data.json','fresh/av_train_inputs/manifest.json','input_recovery.json'):
            take(name,MAX_METADATA_BYTES)
        for name in ('fresh_study.py','source/verify.py','PROSPECTIVE_REPLICATION.md'):
            take(name,MAX_CODE_BYTES)
        enrolled=terminal['files']
        if not isinstance(enrolled,dict) or len(enrolled)>MAX_INPUT_FILES:
            raise PublicationIncomplete('incomplete publication: fresh enrollment')
        required={'data.json','FRESH_SEAL.json','terminal_manifest.json','AV_input_provenance.json',
                  'PROSPECTIVE_REPLICATION.md','fresh_study.py','input_recovery.json'}
        for name in enrolled:
            safe_relative(name)
            if name in required:raise PublicationIncomplete('incomplete publication: fresh object overlaps required input '+name)
            take('fresh/'+name)
    else:raise PublicationIncomplete('incomplete publication: unknown input scope')
    return captured


def module_bytes(name,payload,path,imports=None):
    """Execute the bytes already pinned by the caller; never reread or reuse a task module."""
    module=ModuleType(name);module.__file__=str(path)
    if imports:
        namespace=dict(vars(builtins));original=namespace['__import__']
        def import_bound(name,globals=None,locals=None,fromlist=(),level=0):
            if level==0 and name in imports:return imports[name]
            return original(name,globals,locals,fromlist,level)
        namespace['__import__']=import_bound;module.__dict__['__builtins__']=namespace
    exec(compile(payload,str(path),'exec',dont_inherit=True,optimize=0),module.__dict__)
    return module


def publisher_module():
    helper=Path(SHARED);payload=regular_bytes(helper.parent,helper.name,MAX_CODE_BYTES)
    dependency=regular_bytes(helper.parent,'archive.py',MAX_CODE_BYTES)
    if hashlib.sha256(payload).hexdigest()!=HELPER_SHA:raise ValueError('publisher digest')
    if hashlib.sha256(dependency).hexdigest()!=ARCHIVE_HELPER_SHA:raise ValueError('publisher archive dependency digest')
    archive=module_bytes('_mosi_verified_archive',dependency,helper.parent/'archive.py')
    pub=module_bytes('_mosi_verified_publisher',payload,helper,{'archive':archive})
    pub.PREFIX=PREFIX
    if pub.BRANCH!=BRANCH:raise ValueError('unexpected branch')
    return pub


@dataclass(frozen=True,repr=False)
class FrozenFile:
    """The original publisher's two-method file protocol, backed only by immutable bytes."""
    directory:Path
    name:str
    data:bytes

    def __post_init__(self):
        safe_relative(self.name)
        if type(self.data) is not bytes:raise PublicationIncomplete('incomplete publication: nonimmutable frozen data')

    def relative_to(self,directory):
        if Path(directory)!=self.directory:raise PublicationIncomplete('incomplete publication: frozen destination mismatch')
        return Path(self.name)

    def read_bytes(self):return self.data


@dataclass(frozen=True,repr=False)
class FrozenPublication:
    payloads:tuple
    manifest:bytes
    objects:object

    def files(self,root,kind):
        directory=root/kind
        return [FrozenFile(directory,name,data) for name,data in self.payloads]+[
            FrozenFile(directory,'verified_objects.json',self.manifest)]


def freeze_publication(task,root,kind,mapper):
    """Validate private ordinary files, then publish only their original captured byte values."""
    try:
        captured=capture_inputs(task,kind)
        with tempfile.TemporaryDirectory(prefix=kind+'-verify-',dir=root) as temporary:
            private=Path(temporary);identities={}
            for name,payload in captured.items():
                path=private/name;path.parent.mkdir(parents=True,exist_ok=True)
                descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o400)
                with os.fdopen(descriptor,'wb') as output:
                    output.write(payload);output.flush()
                    identities[name]=file_identity(os.fstat(output.fileno()))
            def unchanged():
                for name,payload in captured.items():
                    if regular_bytes(private,name,len(payload),private=True,expected=identities[name])!=payload:
                        raise PublicationIncomplete('incomplete publication: private verification input changed '+name)
            unchanged()
            selected=mapper(private)
            unchanged()
            payloads={}
            for name,path in selected.items():
                safe_relative(name)
                if name=='verified_objects.json':raise PublicationIncomplete('incomplete publication: reserved manifest name')
                relative=safe_relative(str(Path(path).relative_to(private)))
                if relative not in captured:
                    raise PublicationIncomplete('incomplete publication: mapper returned uncaptured input '+name)
                payloads[name]=captured[relative]
            data,objects=publication_snapshot(payloads)
        # No upload operation retains a path to either the producer or the private validator copy.
        return FrozenPublication(tuple(sorted(payloads.items())),data,MappingProxyType(objects))
    except (OSError,ValueError,KeyError,ImportError,AssertionError) as error:
        raise PublicationIncomplete('incomplete publication: frozen input verification failed: '+str(error)) from error


def object_id(value, length=40):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{'+str(length)+'}',value) is not None and value!='0'*length


def validate_receipt(doc,kind):
    fields={'kind','commit','branch','repo_prefix','file_count','route','manifest_sha256','manifest_blob','utc_unix'}
    if not isinstance(doc,dict) or set(doc)!=fields:
        raise PublicationIncomplete('incomplete publication: receipt schema')
    if (doc['kind']!=kind or doc['branch']!=BRANCH or doc['repo_prefix']!=PREFIX+kind+'/'
            or doc['route'] not in ('GitHub Git Data API','native Git fast-forward')):
        raise PublicationIncomplete('incomplete publication: receipt destination')
    if not all(object_id(doc[k],n) for k,n in [('commit',40),('manifest_blob',40),('manifest_sha256',64)]):
        raise PublicationIncomplete('incomplete publication: receipt object identity')
    if type(doc['file_count']) is not int or doc['file_count']<2:
        raise PublicationIncomplete('incomplete publication: receipt file count')
    if type(doc['utc_unix']) not in (int,float) or not 0<doc['utc_unix']<float('inf'):
        raise PublicationIncomplete('incomplete publication: receipt timestamp')
    return doc


def receipt_from(path,kind):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate key '+key)
            result[key]=value
        return result
    def constant(value):
        raise ValueError('nonfinite JSON '+value)
    try:
        if path.stat().st_size>65536:raise ValueError('receipt size')
        doc=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique,parse_constant=constant)
        return validate_receipt(doc,kind)
    except (OSError,UnicodeError,ValueError) as error:
        raise PublicationIncomplete('incomplete publication: invalid receipt '+str(path)+': '+str(error)) from error


def publication_snapshot(files):
    """Bind a canonical manifest and Git IDs to immutable, already validated payload bytes."""
    report={};objects={}
    for name,payload in sorted(files.items()):
        safe_relative(name)
        if name=='verified_objects.json' or type(payload) is not bytes:
            raise PublicationIncomplete('incomplete publication: immutable payload bytes required')
        report[name]={'sha256':hashlib.sha256(payload).hexdigest(),'size':len(payload)}
        objects[name]=hashlib.sha1(f'blob {len(payload)}\0'.encode()+payload).hexdigest()
    if not report:raise PublicationIncomplete('incomplete publication: empty input set')
    data=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode()
    objects['verified_objects.json']=hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
    return data,objects

def api_objects(pub,commit,prefix):
    status=pub.gh('GET',API+'/commits/'+commit)
    if not isinstance(status,dict) or status.get('sha')!=commit:
        raise PublicationIncomplete('incomplete publication: remote commit identity')
    tree=status.get('tree')
    tree=tree.get('sha') if isinstance(tree,dict) else None
    if not object_id(tree):raise PublicationIncomplete('incomplete publication: remote commit tree')
    # Walk only this scope, avoiding truncation of the large repository's root tree.
    for part in [*prefix.rstrip('/').split('/'),None]:
        result=pub.gh('GET',API+'/trees/'+tree+('?recursive=1' if part is None else ''))
        if (not isinstance(result,dict) or result.get('sha')!=tree or result.get('truncated') is not False
                or not isinstance(result.get('tree'),list)):
            raise PublicationIncomplete('incomplete publication: incomplete remote tree')
        entries={}
        for entry in result['tree']:
            if not isinstance(entry,dict) or not isinstance(entry.get('path'),str) or entry['path'] in entries:
                raise PublicationIncomplete('incomplete publication: malformed remote tree')
            entries[entry['path']]=entry
        if part is None:return entries
        selected=entries.get(part,{})
        if selected.get('type')!='tree' or selected.get('mode')!='040000' or not object_id(selected.get('sha')):
            raise PublicationIncomplete('incomplete publication: missing remote scope '+part)
        tree=selected['sha']


def native_objects(root,kind,commit,prefix):
    """Read the exact remote commit; this cache never updates a remote ref."""
    repo=root/(kind+'-readback.git')
    if not repo.exists():
        git(root,['init','--bare',str(repo)])
        git(repo,['remote','add','origin',REPO])
    if git(repo,['remote','get-url','origin'])!=REPO:
        raise PublicationIncomplete('incomplete publication: unexpected readback target')
    git(repo,['fetch','--depth=1','--filter=blob:none','origin',commit])
    if git(repo,['rev-parse','FETCH_HEAD^{commit}'])!=commit:
        raise PublicationIncomplete('incomplete publication: fetched commit identity')
    result={}
    for record in git(repo,['ls-tree','-rz','--full-tree',commit,'--',prefix]).split('\0'):
        if not record:continue
        metadata,path=record.split('\t',1);mode,kind_,oid=metadata.split(' ')
        if not path.startswith(prefix) or path[len(prefix):] in result:
            raise PublicationIncomplete('incomplete publication: malformed native tree')
        result[path[len(prefix):]]={'mode':mode,'type':kind_,'sha':oid}
    return result


def verify_publication(pub,root,kind,receipt,data,objects):
    validate_receipt(receipt,kind)
    if (receipt['file_count']!=len(objects) or receipt['manifest_sha256']!=hashlib.sha256(data).hexdigest()
            or receipt['manifest_blob']!=objects['verified_objects.json']):
        raise PublicationIncomplete('incomplete publication: receipt does not bind current verified inputs')
    try:
        actual=api_objects(pub,receipt['commit'],receipt['repo_prefix']);route='GitHub immutable commit tree'
    except (RuntimeError,subprocess.TimeoutExpired,ConnectionError,OSError):
        try:
            actual=native_objects(root,kind,receipt['commit'],receipt['repo_prefix']);route='native immutable commit tree'
        except (RuntimeError,subprocess.TimeoutExpired,ConnectionError,OSError) as error:
            raise PublicationIncomplete('incomplete publication: cannot read fixed remote commit') from error
    # Other independently appended scopes may coexist; none can replace this manifest's files.
    for path,oid in objects.items():
        entry=actual.get(path,{})
        if entry.get('type')!='blob' or entry.get('mode')!='100644' or entry.get('sha')!=oid:
            raise PublicationIncomplete('incomplete publication: remote object mismatch '+path)
    return route


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(path):return json.loads(path.read_text())
def save(path,doc):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(doc,indent=2,allow_nan=False)+'\n');tmp.replace(path)
def git(cwd,args,data=None,env=None):
    p=subprocess.run(['git',*args],input=data,capture_output=True,cwd=cwd,timeout=600,
                     env={**os.environ,'GIT_TERMINAL_PROMPT':'0',**(env or {})})
    if p.returncode:raise RuntimeError(f"git {args[0]} error {p.returncode}: {p.stderr.decode(errors='replace')[-280:]}")
    return p.stdout.decode().strip()


def native(root,kind,files):
    repo=root/(kind+'.git')
    if not repo.exists():
        git(root,['init','--bare',str(repo)])
        git(repo,['remote','add','origin',REPO])
    if git(repo,['remote','get-url','origin'])!=REPO:raise ValueError('unexpected native target')
    for attempt in range(6):
        git(repo,['fetch','--depth=1','--filter=blob:none','origin','refs/heads/'+BRANCH])
        head=git(repo,['rev-parse','FETCH_HEAD'])
        # A tree derived from the actual live branch prevents replacing unrelated outputs.
        git(repo,['read-tree',head])
        entries=[]
        for f in files:
            oid=git(repo,['hash-object','-w','--stdin'],f.read_bytes());path=f'{PREFIX}{kind}/{f.relative_to(root/kind)}'
            entries.append(f'100644 blob {oid}\t{path}\0'.encode())
        git(repo,['update-index','-z','--index-info'],b''.join(entries))
        tree=git(repo,['write-tree','--missing-ok'])
        if tree==git(repo,['rev-parse',head+'^{tree}']):return head
        commit=git(repo,['-c','user.name=HCSN Research Runner','-c','user.email=hcsn-research@users.noreply.github.com',
                         'commit-tree',tree,'-p',head],('Archive independently verified '+kind+'\n').encode())
        try:git(repo,['push','origin',commit+':refs/heads/'+BRANCH])
        except RuntimeError:
            latest=git(repo,['ls-remote','--heads','origin','refs/heads/'+BRANCH]).split()[0]
            if latest==commit:return commit
            if latest==head:raise
            continue
        if git(repo,['ls-remote','--heads','origin','refs/heads/'+BRANCH]).split()[0]==commit:return commit
    raise RuntimeError('native results branch advanced repeatedly')


def recovery_map(task):
    import numpy as np
    old=task/'candidate_replay';historical=read(task/'source/SEAL.json');rec=read(old/'reconstruction_result.json')
    if rec['original_seal_sha256']!=digest(task/'source/SEAL.json') or rec['hash_comparison_seal_sha256']!=digest(old/'candidate_hash_seal.json'):
        raise ValueError('historical recovery chain')
    result={'input_recovery.json':task/'input_recovery.json','source_transfer.json':task/'source_transfer.json',
            'candidate_hash_seal.json':old/'candidate_hash_seal.json','reconstruction_result.json':old/'reconstruction_result.json',
            'historical_SEAL.json':task/'source/SEAL.json'}
    audit=task/'original_custody_audit.json'
    if audit.is_file():result['original_custody_audit.json']=audit
    for key,v in rec['authenticated_cold_results'].items():
        f=old/(key+'.cold.npz'); w=old/'fits'/key
        if digest(f)!=v['score_sha256'] or digest(w)!=historical['weights'].get(key):
            raise ValueError('historical candidate mismatch')
        with np.load(f,allow_pickle=False) as z:
            if len(z['y'])!=686 or len(np.unique(z['video']))!=31:raise ValueError('historical external ids')
            d=np.abs(z['intact']-z['y'])
            m=np.array([d[z['video']==video].mean() for video in np.unique(z['video'])]).mean()
            if abs(m-v['intact']['video_mae'])>1e-8:raise ValueError('independent historical score')
        result['selected/'+key]=w;result['cold/'+f.name]=f
    if len(rec['authenticated_cold_results'])!=rec['eligible_objects']:raise ValueError('historical count')
    return result


def fresh_map(task):
    base=task/'fresh';terminal=read(base/'terminal_manifest.json');seal=read(base/'FRESH_SEAL.json')
    if terminal['actual_groups']!=36 or terminal['score_archives']!=36 or digest(base/'FRESH_SEAL.json')!=terminal['seal_sha256']:
        raise ValueError('incomplete fresh panel')
    if terminal['summary_sha256']!=digest(base/'result/SUMMARY.json'):raise ValueError('summary mismatch')
    data_manifest=task/'reconstructed/data.json'
    if digest(data_manifest)!=seal['data_manifest_sha256']:raise ValueError('fresh data manifest hash')
    driver_bytes=regular_bytes(task,'fresh_study.py',MAX_CODE_BYTES)
    verifier_bytes=regular_bytes(task,'source/verify.py',MAX_CODE_BYTES)
    if hashlib.sha256(driver_bytes).hexdigest()!=FRESH_DRIVER_SHA or seal['fresh_driver_sha256']!=FRESH_DRIVER_SHA:
        raise ValueError('fresh driver identity')
    if hashlib.sha256(verifier_bytes).hexdigest()!=FRESH_VERIFIER_SHA or seal['code']['verify.py']!=FRESH_VERIFIER_SHA:
        raise ValueError('fresh verifier identity')
    if digest(task/'PROSPECTIVE_REPLICATION.md')!=seal['fresh_protocol_sha256']:
        raise ValueError('fresh protocol identity')
    if digest(base/'av_train_inputs/manifest.json')!=seal['AV_input_provenance_sha256']:
        raise ValueError('fresh AV provenance identity')
    driver=module_bytes('_mosi_verified_fresh_driver',driver_bytes,task/'fresh_study.py')
    replay=module_bytes('_mosi_verified_fresh_verifier',verifier_bytes,task/'source/verify.py')
    replay.DESIGNS=driver.DESIGNS;replay.SHARED=('fp_h','fp_r','random_h','bp_h','transformer','fp_h_av')
    with tempfile.TemporaryDirectory(dir=task) as temp:
        saved=sys.argv[:]
        try:
            sys.argv=['verify.py',str(base/'models'),str(base/'cold'),str(data_manifest),
                      str(base/'FRESH_SEAL.json'),temp]
            replay.main()
        finally:sys.argv=saved
        for n in ('SUMMARY.json','all_intact_models.json'):
            if digest(Path(temp)/n)!=digest(base/'result'/n):raise ValueError('independent metric replay mismatch')
    result={'data.json':data_manifest,'FRESH_SEAL.json':base/'FRESH_SEAL.json','terminal_manifest.json':base/'terminal_manifest.json',
            'AV_input_provenance.json':base/'av_train_inputs/manifest.json','PROSPECTIVE_REPLICATION.md':task/'PROSPECTIVE_REPLICATION.md',
            'fresh_study.py':task/'fresh_study.py','input_recovery.json':task/'input_recovery.json'}
    for rel,h in terminal['files'].items():
        if Path(rel).is_absolute() or '..' in Path(rel).parts or '\n' in rel:raise ValueError('path')
        if rel in result:raise ValueError('fresh object overlaps required input '+rel)
        p=base/rel
        if digest(p)!=h:raise ValueError('fresh object hash '+rel)
        result[rel]=p
    return result


def run(task):
    if not __debug__:raise PublicationIncomplete('incomplete publication: original verification requires Python assertions; -O/-OO are unsupported')
    pub=publisher_module()
    root=task/'publication';root.mkdir(exist_ok=True)
    with (root/'relay.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for kind,ready,fn in [('mosi_recovery_raw',task/'candidate_replay/reconstruction_result.json',recovery_map),
                              ('mosi_fresh_raw',task/'fresh/terminal_manifest.json',fresh_map)]:
            done=root/(kind+'-receipt.json')
            if done.exists() or done.is_symlink():
                receipt=receipt_from(done,kind)
                if not ready.is_file():raise PublicationIncomplete('incomplete publication: missing local terminal '+str(ready))
                frozen=freeze_publication(task,root,kind,fn)
                route=verify_publication(pub,root,kind,receipt,frozen.manifest,frozen.objects)
                print('resumed verified publication',kind,receipt['commit'],route,flush=True)
                continue
            while not ready.is_file():time.sleep(20)
            frozen=freeze_publication(task,root,kind,fn)
            data,objects=frozen.manifest,frozen.objects
            paths=frozen.files(root,kind)
            while True:
                try:
                    try:commit=pub.push(kind,paths,root);route='GitHub Git Data API'
                    except (RuntimeError,subprocess.TimeoutExpired):
                        commit=native(root,kind,paths);route='native Git fast-forward'
                    receipt={'kind':kind,'commit':commit,'branch':BRANCH,'repo_prefix':PREFIX+kind+'/',
                             'file_count':len(paths),'route':route,'manifest_sha256':hashlib.sha256(data).hexdigest(),
                             'manifest_blob':objects['verified_objects.json'],'utc_unix':time.time()}
                    verify_publication(pub,root,kind,receipt,data,objects)
                    save(done,receipt)
                    print('published',done.read_text(),flush=True);break
                except (RuntimeError,subprocess.TimeoutExpired,ConnectionError) as e:
                    print('retained verified outputs; retrying original destination',str(e)[:400],flush=True);time.sleep(55)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('task',type=Path);run(ap.parse_args().task.resolve())

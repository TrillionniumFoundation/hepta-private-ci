"""Verify the two MOSI evidence scopes locally, then publish to distinct private result directories."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
    """Bind one canonical manifest and Git blob IDs to the currently verified inputs."""
    report={};objects={}
    for name,source in sorted(files.items()):
        if (not isinstance(name,str) or not name or name=='verified_objects.json'
                or Path(name).is_absolute() or '..' in Path(name).parts
                or '/'.join(Path(name).parts)!=name or any(c in name for c in '\\\x00\n\r\t')):
            raise PublicationIncomplete('incomplete publication: unsafe object path')
        size=source.stat().st_size;sha=hashlib.sha256();blob=hashlib.sha1(f'blob {size}\0'.encode());count=0
        with source.open('rb') as stream:
            while chunk:=stream.read(1024*1024):
                sha.update(chunk);blob.update(chunk);count+=len(chunk)
        if count!=size:raise PublicationIncomplete('incomplete publication: input changed while hashing '+name)
        report[name]={'sha256':sha.hexdigest(),'size':size};objects[name]=blob.hexdigest()
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
            oid=git(repo,['hash-object','-w',str(f)]);path=f'{PREFIX}{kind}/{f.relative_to(root/kind)}'
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
    import numpy as np
    from fresh_study import DESIGNS
    base=task/'fresh';terminal=read(base/'terminal_manifest.json');seal=read(base/'FRESH_SEAL.json')
    if terminal['actual_groups']!=36 or terminal['score_archives']!=36 or digest(base/'FRESH_SEAL.json')!=terminal['seal_sha256']:
        raise ValueError('incomplete fresh panel')
    if terminal['summary_sha256']!=digest(base/'result/SUMMARY.json'):raise ValueError('summary mismatch')
    data_manifest=task/'reconstructed/data.json'
    if digest(data_manifest)!=seal['data_manifest_sha256']:raise ValueError('fresh data manifest hash')
    sys.path.insert(0,str(task/'source'))
    import verify as replay
    replay.DESIGNS=DESIGNS;replay.SHARED=('fp_h','fp_r','random_h','bp_h','transformer','fp_h_av')
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
    helper=Path(SHARED)
    if digest(helper)!=HELPER_SHA:raise ValueError('publisher digest')
    sys.path.insert(0,str(helper.parent));spec=importlib.util.spec_from_file_location('results_helper',helper)
    pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub);pub.PREFIX=PREFIX
    if pub.BRANCH!=BRANCH:raise ValueError('unexpected branch')
    root=task/'publication';root.mkdir(exist_ok=True)
    with (root/'relay.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for kind,ready,fn in [('mosi_recovery_raw',task/'candidate_replay/reconstruction_result.json',recovery_map),
                              ('mosi_fresh_raw',task/'fresh/terminal_manifest.json',fresh_map)]:
            done=root/(kind+'-receipt.json')
            if done.exists() or done.is_symlink():
                receipt=receipt_from(done,kind)
                if not ready.is_file():raise PublicationIncomplete('incomplete publication: missing local terminal '+str(ready))
                try:data,objects=publication_snapshot(fn(task))
                except (OSError,ValueError,KeyError,ImportError,AssertionError) as error:
                    raise PublicationIncomplete('incomplete publication: current input verification failed: '+str(error)) from error
                route=verify_publication(pub,root,kind,receipt,data,objects)
                print('resumed verified publication',kind,receipt['commit'],route,flush=True)
                continue
            while not ready.is_file():time.sleep(20)
            files=fn(task);data,objects=publication_snapshot(files);dest=root/kind;dest.mkdir(exist_ok=True)
            for name,src in files.items():
                path=dest/name;path.parent.mkdir(exist_ok=True,parents=True)
                if not path.exists():os.link(src,path)
                if digest(path)!=digest(src):raise ValueError('staging mismatch')
            idx=dest/'verified_objects.json';save(idx,json.loads(data))
            paths=[dest/n for n in sorted(files)]+[idx]
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

"""Verify the two MOSI evidence scopes locally, then publish to distinct private result directories."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
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
    sys.path.insert(0,str(task/'source'))
    import verify as replay
    replay.DESIGNS=DESIGNS;replay.SHARED=('fp_h','fp_r','random_h','bp_h','transformer','fp_h_av')
    with tempfile.TemporaryDirectory(dir=task) as temp:
        saved=sys.argv[:]
        try:
            sys.argv=['verify.py',str(base/'models'),str(base/'cold'),str(task/'reconstructed/data.json'),
                      str(base/'FRESH_SEAL.json'),temp]
            replay.main()
        finally:sys.argv=saved
        for n in ('SUMMARY.json','all_intact_models.json'):
            if digest(Path(temp)/n)!=digest(base/'result'/n):raise ValueError('independent metric replay mismatch')
    result={'FRESH_SEAL.json':base/'FRESH_SEAL.json','terminal_manifest.json':base/'terminal_manifest.json',
            'AV_input_provenance.json':base/'av_train_inputs/manifest.json','PROSPECTIVE_REPLICATION.md':task/'PROSPECTIVE_REPLICATION.md',
            'fresh_study.py':task/'fresh_study.py','input_recovery.json':task/'input_recovery.json'}
    for rel,h in terminal['files'].items():
        if Path(rel).is_absolute() or '..' in Path(rel).parts or '\n' in rel:raise ValueError('path')
        p=base/rel
        if digest(p)!=h:raise ValueError('fresh object hash '+rel)
        result[rel]=p
    return result


def run(task):
    helper=Path(SHARED)
    if digest(helper)!=HELPER_SHA:raise ValueError('publisher digest')
    sys.path.insert(0,str(helper.parent));spec=importlib.util.spec_from_file_location('results_helper',helper)
    pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub);pub.PREFIX=PREFIX
    if pub.BRANCH!=BRANCH:raise ValueError('unexpected branch')
    root=task/'publication';root.mkdir(exist_ok=True)
    lock=(root/'relay.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for kind,ready,fn in [('mosi_recovery_raw',task/'candidate_replay/reconstruction_result.json',recovery_map),
                          ('mosi_fresh_raw',task/'fresh/terminal_manifest.json',fresh_map)]:
        done=root/(kind+'-receipt.json')
        if done.exists():continue
        while not ready.is_file():time.sleep(20)
        files=fn(task);dest=root/kind;dest.mkdir(exist_ok=True)
        for name,src in files.items():
            path=dest/name;path.parent.mkdir(exist_ok=True,parents=True)
            if not path.exists():os.link(src,path)
            if digest(path)!=digest(src):raise ValueError('staging mismatch')
        report={n:{'sha256':digest(v),'size':v.stat().st_size} for n,v in sorted(files.items())}
        idx=dest/'verified_objects.json';save(idx,report)
        paths=[dest/n for n in sorted(files)]+[idx]
        while True:
            try:
                try:commit=pub.push(kind,paths,root);route='GitHub Git Data API'
                except (RuntimeError,subprocess.TimeoutExpired):
                    commit=native(root,kind,paths);route='native Git fast-forward'
                path=PREFIX+kind+'/verified_objects.json';data=idx.read_bytes()
                oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
                if route=='native Git fast-forward':
                    if git(root/(kind+'.git'),['rev-parse',commit+':'+path])!=oid:raise ValueError('native published tree')
                else:
                    status=pub.gh('GET','repos/TrillionniumFoundation/hepta-private-ci/contents/'+path+'?ref='+commit)
                    if status['sha']!=oid:raise ValueError('remote directory attestation')
                save(done,{'kind':kind,'commit':commit,'branch':BRANCH,'repo_prefix':PREFIX+kind+'/',
                           'file_count':len(paths),'route':route,'manifest_sha256':digest(idx),
                           'manifest_blob':oid,'utc_unix':time.time()})
                print('published',done.read_text(),flush=True);break
            except (RuntimeError,subprocess.TimeoutExpired,ConnectionError) as e:
                print('retained verified outputs; retrying original destination',str(e)[:400],flush=True);time.sleep(55)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('task',type=Path);run(ap.parse_args().task.resolve())

"""Restore the immutable deposit into a fresh object database and reproduce the numerical report."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

PREFIX='qualification/hcsn_cross_corpus_8559'


def run(remote,commit,target):
    t=time.perf_counter();target.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target) as tmp:
        git=Path(tmp)/'objects.git'
        env={**os.environ,'GIT_TERMINAL_PROMPT':'0'}
        def call(args,stdin=None):
            return subprocess.run(args,capture_output=True,input=stdin,env=env,check=True).stdout
        call(['git','init','--bare','--quiet',str(git)])
        g=['git','--git-dir='+str(git)]
        call([*g,'remote','add','origin',remote])
        fetch=[*g,'-c','fetch.negotiationAlgorithm=noop','-c','gc.auto=0','fetch','--filter=blob:none','--no-tags','--no-recurse-submodules']
        call([*fetch,'--depth=1','origin',commit])
        digest=call([*g,'show',commit+':'+PREFIX+'/EVIDENCE.json']);m=json.loads(digest)
        actual=call([*g,'ls-tree',commit+':'+PREFIX+'/evidence']).decode().splitlines()
        if [r.split()[2:] for r in actual]!=[[v['git_blob'],v['name']] for v in m['chunks']]:raise ValueError('remote tree mismatch')
        need=[v['git_blob'] for v in m['chunks']]
        call([*fetch,'--no-write-fetch-head','--stdin','origin'],('\n'.join(need)+'\n').encode())
        archive=target/'evidence.tar.zst';h=hashlib.sha256()
        with archive.open('wb') as out:
            for f in m['chunks']:
                data=call([*g,'cat-file','blob',f['git_blob']])
                assert len(data)==f['bytes'] and hashlib.sha256(data).hexdigest()==f['sha256']
                assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==f['git_blob']
                h.update(data);out.write(data)
        assert h.hexdigest()==m['sha256'] and archive.stat().st_size==m['bytes']
        work=target/'restored';work.mkdir(exist_ok=True)
        subprocess.run(['tar','--zstd','-xf',str(archive.resolve()),'-C',str(work)],check=True)
        report=target/'recount.py';report.write_bytes(call([*g,'show',commit+':'+PREFIX+'/report.py']))
        expected=call([*g,'show',commit+':'+PREFIX+'/RESULTS.json'])
        subprocess.run([os.sys.executable,str(report),str(work)],check=True,stdout=subprocess.DEVNULL)
        replay=(work/'results.json').read_bytes();assert replay==expected
        desc={'commit':commit,'remote':remote,'chunks':len(m['chunks']),'archive_bytes':m['bytes'],'archive_sha256':h.hexdigest(),'frozen_checkpoints':len(list((work/'fits').glob('*/*.pt'))),'cold_evidence_files':len(list((work/'cold').glob('*.npz'))),'replayed_results_sha256':hashlib.sha256(replay).hexdigest(),'elapsed_s':time.perf_counter()-t,'extraction_root':'.'}
        (target/'RESTORE_VERIFICATION.json').write_text(json.dumps(desc,indent=2)+'\n')
        print(desc,flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('remote');ap.add_argument('commit');ap.add_argument('target',type=Path);a=ap.parse_args();run(a.remote,a.commit,a.target)

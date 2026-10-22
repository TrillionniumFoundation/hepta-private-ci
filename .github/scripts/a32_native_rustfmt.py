#!/usr/bin/env python3
"""Proposed native Rust 1.95 formatting-only collector. Not executed on Rust here.

Run only in a disposable exact committed checkout after root review. Output must
be outside checkout. Does not generate locks, commit, publish, or renew controls.
"""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import stat
import time
import tempfile
import subprocess
import sys


def blob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def git(repo,*args):
    return subprocess.check_output(['git','--no-replace-objects',*args],cwd=repo)


def inventory(repo, expected_sha, expected_tree):
    assert git(repo,'rev-parse','HEAD').decode().strip()==expected_sha
    assert git(repo,'rev-parse','HEAD^{tree}').decode().strip()==expected_tree
    rows=git(repo,'ls-tree','-rz','--full-tree','HEAD').split(b'\0')
    result={}
    for row in rows:
        if not row:continue
        left,path=row.split(b'\t',1)
        mode,kind,digest=left.decode().split()
        assert kind=='blob' and mode in ('100644','100755','120000'),(mode,kind,path)
        result[os.fsdecode(path)]={'mode':mode,'blob':digest}
    return result


def snapshot(repo, entries):
    result={}
    for path,entry in entries.items():
        p=repo/path
        assert not any(parent.is_symlink() for parent in p.parents if parent!=repo and repo in parent.parents),f'symlink ancestor: {path}'
        if entry['mode']=='120000':
            assert p.is_symlink(),path
            data=os.fsencode(os.readlink(p)); mode='120000'
        else:
            assert p.is_file() and not p.is_symlink(),path
            data=p.read_bytes();mode='100755' if p.stat().st_mode&stat.S_IXUSR else '100644'
        result[path]={'mode':mode,'blob':blob(data),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    return result


def tree_hash(entries):
    root={}
    for path,item in entries.items():
        node=root;parts=path.split('/')
        for part in parts[:-1]:node=node.setdefault(part,{})
        node[parts[-1]]=(item['mode'],item['blob'])
    def visit(node):
        values=[]
        for name,value in node.items():
            mode,digest=('40000',visit(value)) if isinstance(value,dict) else value
            values.append((name.encode()+(b'/' if mode=='40000' else b''),mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(digest)))
        data=b''.join(v for _,v in sorted(values))
        return hashlib.sha1(b'tree '+str(len(data)).encode()+b'\0'+data).hexdigest()
    return visit(root)

def verify_reviewed_input(repo,entries,source_sha,manifest_path):
    raw=git(repo,'show',f'{source_sha}:{manifest_path}')
    m=json.loads(raw)
    assert m['schema']=='a32.rustfmt-source.v1' and m['status']=='frozen','source manifest not frozen'
    assert os.environ.get('GITHUB_REF_NAME')==m['branch'],'wrong diagnostic branch'
    assert git(repo,'rev-list','--parents','-n','1',source_sha).decode().split()==[source_sha,m['base']],'wrong parent'
    assert git(repo,'rev-parse',m['base']+'^{tree}').decode().strip()==m['base_tree'],'wrong base tree'
    files={f['path']:f for f in m['files']};aux=set(m['auxiliary_paths'])
    assert len(files)==len(m['files']) and len(aux)==len(m['auxiliary_paths']) and not aux.intersection(files),'duplicate or overlapping source paths'
    assert manifest_path in aux
    changed={os.fsdecode(p) for p in git(repo,'diff','--name-only','--no-renames','-z',m['base'],source_sha).split(b'\0') if p}
    assert changed==set(files)|aux,'input changed-path allowlist mismatch'
    for path,f in files.items():
        original=git(repo,'ls-tree',m['base'],'--',path).decode().split()
        assert (original[2] if original else None)==f['base_blob'],f'wrong preimage {path}'
        assert entries[path]['blob']==f['candidate_blob'] and entries[path]['mode']==f.get('mode','100644'),f'wrong postimage {path}'
        data=git(repo,'show',f'{source_sha}:{path}')
        assert hashlib.sha256(data).hexdigest()==f['candidate_sha256'],f'wrong digest {path}'
    for path in aux:
        assert not git(repo,'ls-tree',m['base'],'--',path),f'auxiliary overwrites base {path}'
        assert entries[path]['mode']=='100644'
    product={p:v for p,v in entries.items() if p not in aux}
    assert tree_hash(product)==m['product_tree'],'wrong complete product tree'
    allowed=set(m['allowed_formatted_paths'])
    assert len(allowed)==len(m['allowed_formatted_paths'])
    assert allowed=={p for p in files if p.startswith('codex-rs/') and p.endswith('.rs')},'format allowlist must equal reviewed changed Rust paths'
    return m,raw,allowed

def boundary(repo,sha,tree,entries):
    assert inventory(repo,sha,tree)==entries,'HEAD/tree changed'
    stage={}
    for row in git(repo,'ls-files','--stage','-z').split(b'\0'):
        if not row:continue
        left,path=row.split(b'\t',1);mode,digest,number=left.decode().split();path=os.fsdecode(path)
        assert number=='0' and path not in stage,'non-stage-0 or duplicate index entry'
        stage[path]={'mode':mode,'blob':digest}
    assert stage==entries,'index path/mode/blob inventory differs from HEAD'
    assert not git(repo,'diff','--cached','--name-only'),'index changed'
    assert not git(repo,'ls-files','--others','-z'),'untracked checkout additions'
    # Direct byte checks never trust an apparently clean hidden index.
    flags=git(repo,'ls-files','-v','-f','-z').split(b'\0')
    assert all(not r or (r[:1]==b'H') for r in flags),'hidden/unmerged index flags'


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--source-sha',required=True)
    p.add_argument('--source-tree',required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--artifact-root',type=Path,help='Entire uploaded directory; live logs are always outside it')
    p.add_argument('--command-timeout-seconds',type=float,default=300,help='Optional stricter deadline; cannot exceed 300 seconds')
    p.add_argument('--verify-only',action='store_true',help='Validate committed input without invoking Rust')
    p.add_argument('--source-manifest',default='.github/fixtures/a32-native-rustfmt/source-manifest.json')
    args=p.parse_args()
    if not 0<args.command_timeout_seconds<=300:
        raise RuntimeError('command deadline must be positive and at most 300 seconds')
    if not __debug__:
        raise RuntimeError('optimized Python disables guards; invoke python3 -I without -O')
    repo=args.repo.resolve();out=args.out.resolve()
    assert repo!=out and repo not in out.parents,'output must be outside checkout'
    assert not out.exists(),'refuse to reuse an evidence directory'
    artifact_root=args.artifact_root.resolve() if args.artifact_root else out
    assert artifact_root==out or artifact_root in out.parents,'output must be within artifact root'
    assert repo!=artifact_root and repo not in artifact_root.parents,'artifact root must be outside checkout'
    out.mkdir(parents=True)
    receipt={'schema':'a32.rustfmt-diagnostic.v1','source_sha':args.source_sha,'source_tree':args.source_tree,'toolchain':'1.95.0','native_compile_or_test':False,'lock_generation':False,'publication':False,'source_control_refresh':False,'complete':False,'generated_artifacts_accepted':False,'commands':[],'guards':[],'preflight_only':args.verify_only,'writer_unsettled':False,'abort_latched':False,'signals_sent':False,'artifact_root':str(artifact_root)}
    receipt['host']={k:os.environ.get(k) for k in ('RUNNER_OS','RUNNER_ARCH','ImageOS','ImageVersion','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_JOB')}
    receipt['host'].update(actual_machine=platform.machine(),actual_system=platform.system(),python_version=platform.python_version())
    env=os.environ.copy();env.update(RUSTUP_TOOLCHAIN='1.95.0',CARGO_NET_OFFLINE='true',CARGO_TERM_COLOR='never')
    live_dir=None
    def command(name,argv,cwd=repo):
        nonlocal live_dir
        assert not receipt['abort_latched'],'unsettled writer: no subsequent Rust command is allowed'
        deadline=min(args.command_timeout_seconds,30 if name in ('rustc','cargo','rustfmt') else 300)
        log=out/(name+'.log');started=time.monotonic();timed_out=False;spawn_error=None;actual_exit=None
        if live_dir is None:
            live_dir=Path(tempfile.mkdtemp(prefix=artifact_root.name+'-live-',dir=artifact_root.parent))
            assert live_dir!=artifact_root and artifact_root not in live_dir.parents
            receipt['live_log_directory_not_uploaded']=str(live_dir)
        live=live_dir/(name+'.log')
        # Live stdout must never target uploaded evidence. On timeout it may keep
        # growing; preserve only an immutable bounded prefix and do not signal Rust.
        with live.open('wb') as stream:
            try:
                proc=subprocess.Popen(argv,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    proc.wait(timeout=deadline)
                except subprocess.TimeoutExpired:
                    timed_out=True
                    receipt.update(writer_unsettled=True,abort_latched=True,generated_artifacts_accepted=False,evidence_consistency='partial observations only; live invocation may continue; no coherent final checkout claimed',timeout_policy='observation only; no signals; runner-owned teardown is the external boundary')
                actual_exit=proc.poll()
            except OSError as exc:
                spawn_error=str(exc);stream.write(('COMMAND START FAILED: '+spawn_error+'\n').encode())
            stream.flush();os.fsync(stream.fileno())
        with live.open('rb') as observed:
            prefix_bytes=os.fstat(observed.fileno()).st_size
            data=observed.read(prefix_bytes)
        log.write_bytes(data)
        rc=124 if timed_out else (127 if spawn_error is not None else actual_exit)
        receipt['commands'].append({'name':name,'argv':argv,'cwd':str(cwd),'exit_code':rc,'process_exit_code':actual_exit,'timed_out':timed_out,'timeout_seconds':deadline,'elapsed_seconds':round(time.monotonic()-started,3),'spawn_error':spawn_error,'log_sha256':hashlib.sha256(data).hexdigest(),'log_bytes':len(data),'log_is_partial':timed_out,'live_log_not_uploaded':str(live),'writer_settled':not timed_out,'signals_sent':False})
        return rc,data
    entries={}
    try:
        entries=inventory(repo,args.source_sha,args.source_tree)
        frozen,frozen_bytes,allowed=verify_reviewed_input(repo,entries,args.source_sha,args.source_manifest)
        (out/'source-manifest.json').write_bytes(frozen_bytes)
        receipt['source_manifest_sha256']=hashlib.sha256(frozen_bytes).hexdigest()
        receipt['product_tree']=frozen['product_tree']
        receipt['allowed_formatted_paths']=sorted(allowed)
        boundary(repo,args.source_sha,args.source_tree,entries)
        before=snapshot(repo,entries)
        assert all(before[k]['blob']==v['blob'] and before[k]['mode']==v['mode'] for k,v in entries.items()),'checkout bytes differ from commit'
        index=git(repo,'ls-files','--stage','-z')
        (out/'input-index-entries.bin').write_bytes(index)
        (out/'input-index-flags.bin').write_bytes(git(repo,'ls-files','-v','-f','-z'))
        def guard(name,expected,permitted=()):
            boundary(repo,args.source_sha,args.source_tree,entries)
            assert git(repo,'ls-files','--stage','-z')==index,'index entries changed'
            current=snapshot(repo,entries)
            unexpected=[p for p in entries if current[p]!=expected[p] and p not in permitted]
            assert not unexpected,f'worktree bytes changed outside allowlist: {unexpected}'
            receipt['guards'].append({'stage':name,'pass':None if receipt['writer_unsettled'] else True,'status':'partial_instantaneous_observation' if receipt['writer_unsettled'] else 'settled_command_boundary','consistent_at_observation':True,'tracked_files':len(entries),'permitted_changes':sorted(permitted)})
            return current
        (out/'input-files.json').write_text(json.dumps(before,sort_keys=True)+'\n')
        if args.verify_only:
            receipt.update(complete=True,input_verified=True)
            return 0
        for name,argv,prefix in [('rustc',['rustc','--version','--verbose'],b'rustc 1.95.0 '),('cargo',['cargo','--version'],b'cargo 1.95.0 '),('rustfmt',['rustfmt','--version'],b'rustfmt ')]:
            guard(name+'-before',before)
            rc,data=command(name,argv)
            guard(name+'-after',before)
            assert rc==0 and data.startswith(prefix),(name,rc)
        check=['cargo','fmt','--','--config','imports_granularity=Item','--check']
        guard('input-check-before',before)
        rc_before,_=command('input-format-check',check,repo/'codex-rs')
        boundary(repo,args.source_sha,args.source_tree,entries)
        assert snapshot(repo,entries)==before,'format check modified checkout'
        guard('input-check-after',before)
        assert rc_before!=124,'input format check timed out; partial log retained'
        guard('format-before',before)
        rc_format,_=command('generate-format-only',['cargo','fmt','--','--config','imports_granularity=Item'],repo/'codex-rs')
        boundary(repo,args.source_sha,args.source_tree,entries)
        after=snapshot(repo,entries)
        changes=[k for k in entries if before[k]!=after[k]]
        receipt['changed_files']=[{'path':k,'before':before[k],'after':after[k]} for k in changes]
        if rc_format==124:
            guard('format-after',before,allowed)
            raise RuntimeError('format generation timed out; partial rejected observations only; writer unsettled')
        (out/'rustfmt.patch').write_bytes(git(repo,'diff','--binary','--full-index','--no-ext-diff','--no-textconv',args.source_sha,'--'))
        for k in changes:
            dest=out/'postimages'/k;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(os.fsencode(os.readlink(repo/k)) if (repo/k).is_symlink() else (repo/k).read_bytes())
        # Preserve all generated bytes before rejecting unexpected paths/modes.
        assert all(k.endswith('.rs') and before[k]['mode']==after[k]['mode'] for k in changes),'non-Rust or file-mode changes'
        assert set(changes)<=allowed,'formatter changed Rust outside reviewed allowlist'
        guard('format-after',before,allowed)
        guard('generated-check-before',after)
        rc_after,_=command('generated-format-check',check,repo/'codex-rs')
        boundary(repo,args.source_sha,args.source_tree,entries)
        assert snapshot(repo,entries)==after,'final format check modified checkout'
        guard('generated-check-after',after)
        assert rc_after!=124,'generated format check timed out; partial log retained'
        (out/'final-files.json').write_text(json.dumps(after,sort_keys=True)+'\n')
        (out/'final-index-entries.bin').write_bytes(git(repo,'ls-files','--stage','-z'))
        (out/'final-index-flags.bin').write_bytes(git(repo,'ls-files','-v','-f','-z'))
        receipt.update(complete=True,generated_artifacts_accepted=(rc_format==rc_after==0),input_format_check_exit=rc_before,generation_exit=rc_format,generated_format_check_exit=rc_after,locks_unchanged=True,generated_patch_sha256=hashlib.sha256((out/'rustfmt.patch').read_bytes()).hexdigest(),postimages_require_review=True)
        return 0 if (rc_before==rc_format==rc_after==0) else 1
    except Exception as exc:
        receipt['error']=f'{type(exc).__name__}: {exc}'
        if receipt['writer_unsettled']:
            receipt['rejected_observations_are_partial']=True
        # Preserve rejected output as evidence, never as an accepted format patch.
        try:
            rejected=git(repo,'diff','--binary','--full-index','--no-ext-diff','--no-textconv',args.source_sha,'--')
            (out/'rejected-worktree.patch').write_bytes(rejected)
            receipt['rejected_worktree_patch_sha256']=hashlib.sha256(rejected).hexdigest()
        except Exception as evidence_error:
            receipt['evidence_error']=str(evidence_error)
        try:
            observations=[]
            for path,original in entries.items():
                p=repo/path
                # Never follow a formatter-created symlink outside the checkout.
                if any(parent.is_symlink() for parent in p.parents if parent!=repo and repo in parent.parents):
                    observations.append({'path':path,'state':'symlink-ancestor-not-read'});continue
                try:mode=p.lstat().st_mode
                except FileNotFoundError:
                    observations.append({'path':path,'state':'missing'});continue
                if stat.S_ISLNK(mode):data=os.fsencode(os.readlink(p));git_mode='120000'
                elif stat.S_ISREG(mode):data=p.read_bytes();git_mode='100755' if mode&stat.S_IXUSR else '100644'
                else:
                    observations.append({'path':path,'state':'nonregular-not-read'});continue
                if blob(data)!=original['blob'] or git_mode!=original['mode']:
                    item={'path':path,'state':'changed','mode':git_mode,'blob':blob(data),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
                    dest=out/'rejected-postimages'/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
                    observations.append(item)
            receipt['rejected_observations']=observations
            receipt['observed_head']=git(repo,'rev-parse','HEAD').decode().strip()
            (out/'rejected-index-entries.bin').write_bytes(git(repo,'ls-files','--stage','-z'))
            (out/'rejected-index-flags.bin').write_bytes(git(repo,'ls-files','-v','-f','-z'))
            (out/'rejected-untracked-paths.bin').write_bytes(git(repo,'ls-files','--others','-z'))
        except Exception as capture_error:
            receipt['capture_error']=str(capture_error)
        return 2
    finally:
        receipt['artifact_files']={p.relative_to(out).as_posix():{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(out.rglob('*')) if p.is_file() and p!=out/'manifest.json'}
        (out/'manifest.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')

if __name__=='__main__':sys.exit(main())

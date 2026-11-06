#!/usr/bin/env python3
"""Validate exact transport, original artifacts, and their bounded source/result claims."""
from pathlib import Path, PurePosixPath
import argparse, base64, collections, hashlib, io, json, re, tarfile, zipfile

def ident(b):
    return dict(bytes=len(b),git_blob=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),sha256=hashlib.sha256(b).hexdigest())

def equal(b,row):
    assert ident(b)=={k:row[k] for k in ('bytes','git_blob','sha256')}

def safe(path):
    p=PurePosixPath(path)
    assert path and not p.is_absolute() and '..' not in p.parts and '\\' not in path

def tree(rows):
    dirs={'':{}}
    for path,mode,sha in rows:
        safe(path);bits=path.split('/');parent=''
        for bit in bits[:-1]:
            child=(parent+'/' if parent else '')+bit
            dirs.setdefault(child,{})
            prior=dirs[parent].setdefault(bit,('40000',child));assert prior==('40000',child)
            parent=child
        assert bits[-1] not in dirs[parent];dirs[parent][bits[-1]]=(mode,sha)
    def walk(p):
        out=[]
        for name,(mode,obj) in sorted(dirs[p].items(),key=lambda kv:(kv[0]+('/' if kv[1][0]=='40000' else '')).encode()):
            sha=walk(obj) if mode=='40000' else obj
            out.append(mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha))
        b=b''.join(out)
        return hashlib.sha1(b'tree '+str(len(b)).encode()+b'\0'+b).hexdigest()
    return walk(''),len(dirs)

def leaves(b):
    rows=[]
    for line in b.split(b'\0'):
        if not line:continue
        head,path=line.split(b'\t',1);mode,kind,sha=head.decode().split()
        assert kind=='blob'
        rows.append((path.decode(),mode,sha))
    assert len({r[0] for r in rows})==len(rows)
    return rows

def api(data):
    wrapper=json.loads(data)
    p=wrapper.get('structuredContent')
    if p is None:p=json.loads(next(x['text'] for x in wrapper['content'] if x['type']=='text'))
    return json.loads(p['content']) if isinstance(p.get('content'),str) else p

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--extract',type=Path);a=ap.parse_args()
    root=Path(__file__).resolve().parent
    descriptor=json.loads((root/'archive.json').read_bytes())
    chunks=[]
    for row in descriptor['parts']:
        safe(row['path']);b=(root/row['path']).read_bytes();equal(b,row);chunks.append(b)
    raw=base64.b64decode(b''.join(chunks),validate=True);equal(raw,descriptor['archive'])
    manifest_bytes=(root/'manifest.json').read_bytes();equal(manifest_bytes,descriptor['payload_manifest'])
    manifest=json.loads(manifest_bytes)
    payload={}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(set(z.namelist()))==len(manifest['files'])
        assert set(z.namelist())=={x['path'] for x in manifest['files']}
        for row in manifest['files']:
            safe(row['path']);b=z.read(row['path']);equal(b,row);payload[row['path']]=b
    nested=json.loads(payload['nested-original-zip-manifest.json'])['archives']
    zip_payload={}
    for row in nested:
        b=payload[row['path']];equal(b,row);members={}
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            assert z.testzip() is None
            assert len(z.namelist())==len(set(z.namelist()))==len(row['members'])
            assert set(z.namelist())=={x['path'] for x in row['members']}
            for m in row['members']:
                safe(m['path']);v=z.read(m['path']);equal(v,m);assert z.getinfo(m['path']).CRC==m['crc32'];members[m['path']]=v
        zip_payload[row['path']]=members
    metas=api(payload['b21.artifacts.tool-return.original.json'])['artifacts']+api(payload['b23.artifacts.tool-return.original.json'])['artifacts']
    expected=[('b21.original.zip',13475799648,1017),('b23.original.zip',13476180428,21),('b23_compact.original.zip',13475294944,10)]
    artifacts=[]
    for name,aid,count in expected:
        meta=next(x for x in metas if x['id']==aid);b=payload[name]
        assert len(b)==meta['size_in_bytes'] and 'sha256:'+ident(b)['sha256']==meta['digest']
        assert len(zip_payload[name])==count
        artifacts.append(dict(id=aid,path=name,**ident(b),members=count,official_digest_matches=True))
    scopes=[]
    for name,prefix,expected_exit,expected_errors,event_count,jobid in [
        ('b21','b21-original-intel-full-context/',3,{'duplicate_event_id':1,'attempt_reference_unavailable':131},7394,127685180579),
        ('b23','',0,{'duplicate_event_id':2,'attempt_reference_unavailable':8},1924,127687422035)]:
        z=zip_payload[name+'.original.zip']
        def read(p):return z[prefix+p]
        m=json.loads(read('attempt-retention-manifest.json'))
        assert m['complete'] is False and m['original_bazel_exit']==expected_exit and m['console_copy_exit']==0
        errors=dict(collections.Counter(x['kind'] for x in m['errors']));assert errors==expected_errors
        assert read('original-bazel-exit-code.txt')==f'{expected_exit}\n'.encode()
        assert read('console-copy-exit-code.txt')==b'0\n'
        events=[json.loads(x) for x in read('build-events.sanitized.jsonl').splitlines()];assert len(events)==event_count
        repeated=[]
        for e in m['errors']:
            if e['kind']=='duplicate_event_id':
                eid=events[e['event']]['id'];assert 'fetch' in eid
                prior=[i for i in range(e['event']) if events[i]['id']==eid];assert prior
                repeated.append(dict(event=e['event'],prior=prior,id=eid))
            else:
                output=events[e['event']]['testResult']['testActionOutput'][e['output']]
                assert output['name']=='test.xml'
        for f in m['files']:
            b=read(f['archive_path']);assert len(b)==f['bytes'] and hashlib.sha256(b).hexdigest()==f['sha256']
        jobs=api(payload[name+'_jobs.tool-return.original.json'])['jobs'];job,=jobs
        assert job['id']==jobid and job['conclusion']=='failure'
        privacy=json.loads(read('artifact-privacy-gate.json'));assert privacy['safe_for_upload'] is True
        redaction=json.loads(read('bep-redaction-receipt.json'))
        assert redaction['raw_bep_retained_in_artifacts'] is False and redaction['event_count']==event_count
        scopes.append(dict(name=name,job_id=jobid,original_bazel_exit=expected_exit,job_conclusion='failure',collector_complete=False,collector_errors=errors,derived_bep_events=event_count,duplicate_fetch_ids=repeated,retained_log_xml_files=len(m['files'])))
    z=zip_payload['b21.original.zip'];prefix='b21-original-intel-full-context/'
    rows=leaves(z[prefix+'source-leaves.nul']);assert len(rows)==10583
    rootsha,dirs=tree(rows);assert rootsha=='46fca3e684217066c260dc10d0dc319a33e0a93c'
    product=[r for r in rows if r[0]!='.github/workflows/b21-intel-original-pty.yml']
    assert len(product)==10582 and tree(product)[0]=='3982ba56dc5a3f1da0c1de7ea57992f88125c359'
    assert z[prefix+'source-status-before.txt']==z[prefix+'source-status-after.txt']==b''
    assert z[prefix+'source-final-head-tree.txt']==b'ebd31e2b3e38ff72cedaa7b57bee60c1c102da27\n46fca3e684217066c260dc10d0dc319a33e0a93c\n'
    archive=z[prefix+'source-head.tar.gz'];official=json.loads(z[prefix+'source-archive-verification.json'])
    assert len(archive)==official['bytes'] and ident(archive)['sha256']==official['sha256']
    actual={}
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as tar:
        for member in tar:
            safe(member.name)
            if member.isdir():continue
            assert member.name.startswith('source/')
            path=member.name[len('source/'):];assert path not in actual
            if member.issym():b=member.linkname.encode();mode='120000'
            else:
                assert member.isfile();b=tar.extractfile(member).read();mode='100755' if member.mode&0o111 else '100644'
            actual[path]=(mode,ident(b)['git_blob'])
    assert actual=={path:(mode,sha) for path,mode,sha in rows}
    pty=z[prefix+'all-testlogs/codex-rs/utils/pty/pty-unit-tests/test.log'].decode()
    assert re.search(r'test result: FAILED\. 30 passed; 1 failed; 0 ignored;',pty)
    assert 'pty_dropped_output_receiver_keeps_draining_child' in pty and 'backend=portable' in pty
    assert 'wait_elapsed=2.01948407s outcome=deadline_elapsed' in pty and 'read_bytes=1827840 discarded_bytes=1827840' in pty
    scopes[0]['pty']={'passed':30,'failed':1,'ignored':0,'observed_failing_backend':'portable','wait_seconds':'2.01948407','read_and_discarded_bytes':1827840,'preserved_fds_failure_claim':False}
    scopes[0]['source_archive']={'all_leaf_bytes_and_modes_equal':True,'leaves':len(actual),'tree':rootsha,'directories':dirs,'product_tree':tree(product)[0]}
    b23=zip_payload['b23.original.zip'];counts=[0,0,0];names=[]
    for shard in range(1,9):
        text=b23[f'all-testlogs/codex-rs/app-server/app-server-unit-tests/shard_{shard}_of_8/test.log'].decode()
        matches=re.findall(r'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;',text,re.M);assert len(matches)==1
        counts=[a+int(b) for a,b in zip(counts,matches[0])]
        names.extend(re.findall(r'^test (.+) \.\.\. (ok|ignored(?:,.*)?)$',text,re.M))
    assert counts==[307,0,1] and len(names)==308 and len({x[0] for x in names})==308
    expected_names=['shutdown_signals::tests::first_sigterm_survives_cancelled_receive','shutdown_signals::tests::first_sighup_survives_cancelled_receive','shutdown_signals::tests::first_sigint_survives_cancelled_receive','drain_handle_tests::requesting_drain_does_not_acknowledge_outstanding_turns','drain_handle_tests::repeated_drain_requests_preserve_the_real_completion_acknowledgement']
    assert all((name,'ok') in names for name in expected_names)
    scopes[1]['target_cases']={'passed':307,'failed':0,'ignored':1,'five_original_cases_passed':expected_names}
    if a.extract:
        a.extract.mkdir(parents=True,exist_ok=True)
        for name,b in payload.items():
            target=a.extract/name;assert not target.exists();target.write_bytes(b)
    result={'schema':'diagnostic-terminal-root-offline-verification-v1','archive':ident(raw),'payload_members':len(payload),'official_artifacts':artifacts,'original_zip_members':sum(len(x) for x in zip_payload.values()),'scopes':scopes,'limits':['No product execution or CI dispatch/rerun.','Offline verification success does not change original job conclusions.','B23 original-scope closure is decided in its separate independent review.','Raw BEP was not retained; derived sanitization and opaque omission metadata is preserved.','Main API subset is not a complete standalone 92-job census.']}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

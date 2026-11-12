import os, sys, json, stat, hashlib, io, tarfile, xml.etree.ElementTree as ET
C=json.loads(sys.argv[1])
def digest(data): return hashlib.sha256(data).hexdigest()
def git_blob(data): return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def require(ok, msg):
    if not ok: raise AssertionError(msg)
result={'schema':'hepta.immutable-archive-independent-reparse.v1','read_only':True,'archives':[],'new_test_execution':False,'result_inheritance':False,'ordinary_complete_chains':0,'positive_adoption_chains':0,'ordinary_no_update_rollback_chains':0}
for spec in C['archives']:
    require(spec['path'].startswith('/home/qq/af52-learning-local-decision-20261111/'),'unexpected root')
    require(spec['path'].endswith('/original-records.tar.xz'),'unexpected archive')
    fd=os.open(spec['path'],os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1,'archive must be original regular single-link file')
        require(before.st_size==spec['bytes'] and before.st_size<=8*1024*1024,'archive size')
        blocks=[]
        while True:
            block=os.read(fd,65536)
            if not block: break
            blocks.append(block)
        data=b''.join(blocks)
        after=os.fstat(fd)
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'archive changed during read')
    finally:
        os.close(fd)
    require(len(data)==spec['bytes'] and digest(data)==spec['sha256'] and git_blob(data)==spec['git_blob'],'whole archive identities')
    payload={}
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:xz') as archive:
        members=archive.getmembers()
        require(len(members)==spec['members'],'member count')
        total=0
        for member in members:
            require(member.isfile() and not member.name.startswith('/') and '..' not in member.name.split('/'),'unsafe or nonregular member')
            require(member.name not in payload and 0<=member.size<=32*1024*1024,'duplicate or oversized member')
            total+=member.size
            require(total<=128*1024*1024,'payload bound')
            source=archive.extractfile(member)
            require(source is not None,'missing member body')
            body=source.read()
            require(len(body)==member.size,'member size')
            payload[member.name]=body
    raw=payload['MANIFEST.json']
    require(digest(raw)==spec['manifest_sha256'],'manifest digest')
    manifest=json.loads(raw)
    require(manifest['status']=='verified-original-record-export','original export status')
    rows=manifest['files']
    require(len(rows)==spec['payload_files'] and len({row['path'] for row in rows})==len(rows),'manifest count/uniqueness')
    require(set(payload)=={'MANIFEST.json'}|{row['path'] for row in rows},'manifest/tar inventory')
    for row in rows:
        body=payload[row['path']]
        require(len(body)==row['bytes'] and digest(body)==row['sha256'] and git_blob(body)==row['git_blob'],'payload digest '+row['path'])
    verified_runs=[]
    for expected in spec['expected_runs']:
        prefix=expected['prefix']+'/'
        def read_json(name): return json.loads(payload[prefix+name])
        execution=read_json('root.execution.json')
        counts=read_json('root.counts.json')
        uid=read_json('root.uid.json')
        summary=read_json('root.junit.summary.json')
        final=read_json('final-source-identity.json')
        progress=read_json('progress.json')
        xml_raw=payload[prefix+'root.junit.xml']
        xml=ET.fromstring(xml_raw)
        cases=xml.findall('.//testcase')
        actual_failed=sum(case.find('failure') is not None or case.find('error') is not None for case in cases)
        actual_skipped=sum(case.find('skipped') is not None for case in cases)
        actual_passed=len(cases)-actual_failed-actual_skipped
        require((len(cases),actual_passed,actual_failed,actual_skipped)==(expected['tests'],expected['passed'],expected['failed'],0),'JUnit counts')
        require({case.attrib['name'] for case in cases}==set(C['expected_root_parents']) and len(cases)==len(C['expected_root_parents']),'original selected roster')
        require(counts['executed']==len(cases) and counts['passed']==actual_passed and counts['failed']==actual_failed and counts['skipped']==0,'retained counts')
        require(uid['uid']==uid['euid']==uid['gid']==0 and uid['pid']>0,'actual UID0 record')
        require(execution['source_sha']==execution['tested_sha']==expected['source'],'execution source')
        require(execution['before']==execution['after'] and execution['before']['commit']==expected['source'] and execution['before']['tree']==expected['tree'] and execution['before']['dirty'] is False,'equal clean source')
        require(execution['status']=='failed' and execution['command_exit_code']!=0 and not execution['timed_out'] and not execution['output_limit_exceeded'],'original failure classification')
        require(final=={'head':expected['source'],'tree':expected['tree'],'status':''},'final source')
        require(progress['source_sha']==expected['source'] and progress['source_tree']==expected['tree'] and progress['status']=='root-component-diagnostic-failed','original terminal progress')
        log=payload[prefix+execution['log_file']]
        require(len(log)==execution['log_bytes'] and digest(log)==execution['log_sha256'],'original execution log')
        require(summary['execution_sha256']==digest(payload[prefix+'root.execution.json']) and summary['junit_sha256']==digest(xml_raw),'original JUnit collector digests')
        require(summary['status']=='retained-failed' and summary['source_sha']==expected['source'] and summary['source_tree']==expected['tree'],'original collector source')
        verified_runs.append({'source':expected['source'],'tree':expected['tree'],'tests':len(cases),'passed':actual_passed,'failed':actual_failed,'skipped':actual_skipped,'uid_record':uid,'junit_sha256':digest(xml_raw),'execution_sha256':digest(payload[prefix+'root.execution.json']),'raw_log_sha256':digest(log),'original_status':'failed','timed_out':False,'output_limit_exceeded':False})
    result['archives'].append({'version':spec['version'],'path':spec['path'],'bytes':len(data),'sha256':digest(data),'git_blob':git_blob(data),'members_verified':len(payload),'payload_files_verified':len(rows),'manifest_sha256':digest(raw),'archive_stat_unchanged':True,'runs':verified_runs})
result['status']='verified-original-failed-runs-without-new-execution'
print(json.dumps(result,sort_keys=True),flush=True)

from pathlib import Path
import base64, gzip, hashlib, json, re

ROOT = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1')

def pin(data):
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}

def put(name,data):
    path=ROOT/name
    if path.exists(): assert path.read_bytes()==data,name
    else:
        with path.open('xb') as f: f.write(data)
    return {'name':name,'path':str(path),**pin(data)}

def check(data,expected):
    p=pin(data)
    assert all(p[k]==expected[k] for k in p),(p,expected)

artifacts=json.loads((ROOT/'ARTIFACTS.json').read_bytes())
index={x['name']:x for x in artifacts['files']}
names=[('fix.after.postimages.json.gz.part-001.b64','RECOVERY_01'),('INPUT_IDENTITIES.json','RECOVERY_01'),('SOURCE_ENTRY.AGENTS.md',''),('SOURCE_ENTRY.justfile',''),('fix.after.git-state.json',''),('final.git-state.json','')]
decoded=[]
for name,suffix in names:
    sdkname='RUN_'+re.sub(r'[^A-Za-z0-9]','_',name)+'_READ_000000'+('_'+suffix if suffix else '')+'.original.json'
    raw=(ROOT/sdkname).read_bytes(); sdk=json.loads(raw)
    assert sdk['isError'] is False,(sdkname,sdk)
    v=sdk.get('structuredContent') or json.loads(sdk['content'][0]['text'])
    body=base64.b64decode(v['data_base64'],validate=True)
    assert v['offset']==0 and v['eof'] is True and v['size']==v['next_offset']==len(body)
    assert v['chunk_sha256']==pin(body)['sha256']
    check(body,index[name])
    row={'sdk_name':sdkname,'sdk_identity':pin(raw),'original_path':v['path'],'version':v['version'],**put(name,body)}
    if name.endswith('.gz.part-001.b64'):
        gzipname=name[:-len('.part-001.b64')]
        gz=base64.b64decode(body.strip(),validate=True); check(gz,index[gzipname])
        rawdata=gzip.decompress(gz); check(rawdata,{k:index[gzipname]['raw_'+k] for k in ['bytes','sha256','git_blob']})
        row['gzip']=put(gzipname,gz); row['decoded_raw']=put(gzipname[:-3],rawdata)
    decoded.append(row)
before=(ROOT/'SOURCE_GIT_STATE.before.json').read_bytes()
assert before==(ROOT/'fix.after.git-state.json').read_bytes()==(ROOT/'final.git-state.json').read_bytes()
assert (ROOT/'SOURCE_GIT_METADATA.before.json').read_bytes()==(ROOT/'SOURCE_GIT_METADATA.after.json').read_bytes()
report={'format':'hepta-failed-maintenance-additional-original-readback-v1','job_id':'1a1d3eccd3a-392-231','actual_full_reads':decoded,'git_state_three_raw_originals_equal':True,'git_metadata_two_raw_originals_equal':True,'native_processes_started_by_this_script':0,'failed_first_reads_preserved':['RUN_fix_after_postimages_json_gz_part_001_b64_READ_000000.original.json','RUN_INPUT_IDENTITIES_json_READ_000000.original.json'],'failed_first_reads_had_no_version':True,'recovery_is_same_original_path_full_read':True}
rp=put('ADDITIONAL_ORIGINAL_READBACK_REVIEW.v1.json',(json.dumps(report,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'review':rp,'decoded':decoded},ensure_ascii=False))

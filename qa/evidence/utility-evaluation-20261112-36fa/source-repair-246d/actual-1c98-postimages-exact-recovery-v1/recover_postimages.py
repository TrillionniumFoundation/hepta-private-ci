"""Pure exact-byte recovery of actual job 1c98's three transition records.

No H, Git process, source/control module execution, formatter, tests, refs, or
source mutation. Outputs are retained as exact only after all independently
observed raw/gzip/part identities match. The complete inventories remain in
their already-archived packages; this package does not duplicate them.
"""
from pathlib import Path
import ast
import base64
import gzip
import hashlib
import json
import sys
import zlib

OUT=Path(__file__).resolve().parent
ACTUAL=Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1')
PROPOSAL=Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')
BEFORE=Path('/tmp/hepta-36fa-final-source-preparation-v2/CANONICAL_CLEAN_INVENTORY.expected.json')
AFTER=PROPOSAL/'actual-finalfmt-exact-recovery/final.inventory.exact-recovered.json'
V5=Path('/tmp/hepta-36fa-final-nonrust-fmt-v1/MAINTENANCE_V5.original.py')

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
      'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def exact(raw, expected, label):
    actual=pin(raw)
    assert all(actual[k]==expected[k] for k in actual),(label,actual,expected)
    return actual

def read(path):
    a=path.stat();raw=path.read_bytes();b=path.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns),str(path)
    return raw

def save(name,raw):
    path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==raw,('create-only path differs',name)
    else:
        with path.open('xb') as f:f.write(raw)
    return {'local':str(path),**pin(raw)}

def jbytes(value):
    # Exact original V5 expression; archived control code is never imported.
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')

result_raw=read(ACTUAL/'RESULT.original.json')
artifacts_raw=read(ACTUAL/'ARTIFACTS.original.json')
normal_raw=read(ACTUAL/'STATUS_01.original.json')
exact(result_raw,{'bytes':7097,'sha256':'f0a8fd1bb8b6b3b4aa71cf5e9a0683cb4d4e0d7b532cc0cde43bedff4244544f','git_blob':'6cb1b8d6af25907ca0fea5d9bd0f787062dbef94'},'actual RESULT')
exact(artifacts_raw,{'bytes':62965,'sha256':'9a05c5017ac52da29e78b954da246f3d8d719edc548461e9bedf551179a3cf80','git_blob':'ea898b88fbb0e4a83a94b01d7b9fbfbe56dde7bf'},'actual ARTIFACTS')
exact(normal_raw,{'bytes':955,'sha256':'c7e92ac3e26262c0bcc0707ae138ed873c2b2221d98a4c6c5f7889fd5ff923eb','git_blob':'b20a78f43e34fa72937df40d09d782f792a2f873'},'actual supervisor')
result=json.loads(result_raw);normal=json.loads(json.loads(normal_raw)['content'][0]['text'])
assert normal['job_id']=='1a1d2107dce-2564-1c98'
assert normal['state']=='succeeded' and normal['exit_code']==0
assert normal['output_complete'] and normal['output_durable'] and normal['terminal_publication_confirmed']
assert not normal['timed_out'] and not normal['automatic_retry'] and not normal['cancelled']
assert result['source_commit']=='246d8cb614770252ee42029a5c014f2a4904176a'
assert result['source_tree']=='d5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
assert result['status']=='APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
assert result['attempted_commands']==['fmt'] and result['not_run_commands']==[]
assert result['formatter_changed_paths']==[] and result['format_source_stable'] is True
assert not result['fix_dispatched'] and result['test_commands_dispatched']==0
assert result['previous_source_gate_status']=='failed' and result['failed_source_result_retained_without_reclassification'] is True
assert len(result['final_audits'])==3 and all(a['status']=='verified' for a in result['final_audits'])
artifacts={row['name']:row for row in json.loads(artifacts_raw)['files']}
assert len(artifacts)==len(json.loads(artifacts_raw)['files'])

before_raw=read(BEFORE);after_raw=read(AFTER)
exact(before_raw,result['baseline_inventory'],'actual before complete inventory')
exact(after_raw,result['actual_final_source']['inventory'],'actual after complete inventory')
before=json.loads(before_raw);after=json.loads(after_raw)
assert before['tracked_entries']==after['tracked_entries']==15188
assert before['filesystem_entries']==after['filesystem_entries']==15188
assert before['source']['head']==after['source']['head']==result['source_commit']
assert before['source']['tree']==after['source']['tree']==result['source_tree']
bmap={r['path']:r for r in before['files']};amap={r['path']:r for r in after['files']}
assert len(bmap)==len(amap)==15188 and set(bmap)==set(amap)
packet_raw=read(PROPOSAL/'REPAIR_PACKET.json')
exact(packet_raw,{'bytes':2209325,'sha256':'c18566ac882c18008ea03a0926a8734187466b1987abc969eda5042a13c24c88','git_blob':'bade35cfabded0a0db3451d758e8316034cabec6'},'reviewed five-file packet')
prepared=json.loads(packet_raw)
paths=sorted(path for path in bmap if bmap[path]!=amap[path])
assert paths==result['applied_paths']==[r['path'] for r in prepared['changes']]
assert len(paths)==5
changes=[];source_bytes=[]
for row in prepared['changes']:
    path=row['path'];old=read(PROPOSAL/'source-before'/path)
    new=base64.b64decode(row['after_base64'],validate=True)
    assert new==read(PROPOSAL/'proposal-after'/path)
    for raw,meta,inv in ((old,row['before'],bmap[path]),(new,row['after'],amap[path])):
        exact(raw,meta,path+' source pin')
        exact(raw,{'bytes':inv['bytes'],'sha256':inv['sha256'],'git_blob':inv['working_blob']},path+' actual inventory pin')
        assert inv['kind']=='file' and inv['stable'] is True
    changes.append({'path':path,'before':bmap[path],'after':amap[path],
      'before_raw_base64':base64.b64encode(old).decode('ascii'),
      'after_raw_base64':base64.b64encode(new).decode('ascii')})
    source_bytes.append({'path':path,'before':pin(old),'after':pin(new)})

v5_raw=read(V5);exact(v5_raw,artifacts['MAINTENANCE_V5.original.py'],'original V5')
source=v5_raw.decode();parsed=ast.parse(source)
functions={n.name:ast.get_source_segment(source,n) for n in parsed.body if isinstance(n,ast.FunctionDef)}
serializer_names=['jbytes','gzrecord','archive_transition','capture_source']
serializers={n:pin(functions[n].encode()) for n in serializer_names}
save('ORIGINAL_SERIALIZERS.txt',('\n\n'.join(functions[n] for n in serializer_names)+'\n').encode())
outputs=[]

def retain(name,raw):
    expected=artifacts[name]
    exact(raw,{'bytes':expected['raw_bytes'],'sha256':expected['raw_sha256'],'git_blob':expected['raw_git_blob']},name+' whole raw')
    packed=gzip.compress(raw,mtime=0)
    exact(packed,expected,name+' whole gzip')
    assert gzip.decompress(packed)==raw
    save('recovered/'+name.removesuffix('.gz'),raw)
    save('recovered/'+name,packed)
    parts=[]
    for i,offset in enumerate(range(0,len(packed),262144)):
        chunk=packed[offset:offset+262144];encoded=base64.b64encode(chunk)+b'\n'
        part=expected['parts'][i]
        exact(encoded,part,part['name'])
        assert part['decoded_offset']==offset and part['decoded_bytes']==len(chunk)
        assert part['decoded_sha256']==hashlib.sha256(chunk).hexdigest()
        parts.append({'original_name':part['name'],'decoded_offset':offset,
           'decoded_bytes':len(chunk),'decoded_sha256':hashlib.sha256(chunk).hexdigest(),
           **save('recovered/'+part['name'],encoded)})
    assert len(parts)==len(expected['parts'])
    assert b''.join(base64.b64decode(Path(p['local']).read_bytes()[:-1],validate=True) for p in parts)==packed
    outputs.append({'original_name':name,'raw':pin(raw),'gzip':pin(packed),'parts':parts,
        'all_original_raw_gzip_encoded_decoded_part_pins_equal':True})

for stage,previous,selected in [('apply.after',before_raw,changes),('fmt.after',after_raw,[]),('final',before_raw,changes)]:
    value={'format':'hepta-maintenance-actual-source-transition-v1','stage':stage,
      'source_commit_unchanged':result['source_commit'],
      'base_inventory_sha256':hashlib.sha256(previous).hexdigest(),
      'after_inventory_sha256':hashlib.sha256(after_raw).hexdigest(),'changes':selected,
      'all_physical_changes_including_untracked_or_ignored_are_recorded':True,'qualification':False}
    retain(stage+'.postimages.json.gz',jbytes(value))

# This one small original gzip was actually read completely from native.
# Its matching bytes validate the same constructor without implying large reads.
anchor_path=ACTUAL/'fmt.after.postimages.json.gz.READ_01.original.json'
anchor_raw=read(anchor_path)
exact(anchor_raw,{'bytes':869,'sha256':'3b40e9d1ca1c61a0156c7c04a8ae59554f0d61047fc7da3ff69f5831fa3e826f','git_blob':'13045447c1b10b5e4b6bff58bdf893d8b95fc22a'},'actual small gzip read')
sdk=json.loads(anchor_raw);assert sdk['isError'] is False
chunk=json.loads(sdk['content'][0]['text'])
small=base64.b64decode(chunk['data_base64'],validate=True)
assert chunk['offset']==0 and chunk['next_offset']==chunk['size']==276 and chunk['eof'] is True
assert hashlib.sha256(small).hexdigest()==chunk['chunk_sha256']
assert small==read(OUT/'recovered/fmt.after.postimages.json.gz')
assert read(ACTUAL/'fmt.after.postimages.json')==read(OUT/'recovered/fmt.after.postimages.json')

summaries=[]
for stage,value in [('apply.after',result['application']['postimages']),
                    ('fmt.after',result['stages'][0]['retention']['postimages']),
                    ('final',result['actual_final_source']['postimages'])]:
    name=stage+'.postimages-summary.json';raw=jbytes(value)
    exact(raw,artifacts[name],name)
    summaries.append({'original_name':name,**save('recovered/'+name,raw)})

unique={}
for record in outputs:
    for part in record['parts']:
        unique.setdefault(part['git_blob'],{'representative':part,'aliases':[]})['aliases'].append(part['original_name'])
assert len(unique)==6  # five unique large-record parts, plus the actual empty-fmt part
review={'format':'hepta-1c98-postimages-exact-recovery-v1',
 'status':'EXACT_RECOVERY_ALL_ORIGINAL_RAW_GZIP_PART_IDENTITIES_MATCH',
 'actual_job':normal['job_id'],'actual_source_commit':result['source_commit'],
 'actual_source_index_tree':result['source_tree'],
 'actual_physical_tree':result['actual_final_source']['postimages']['all_actual_physical_tree'],
 'actual_apply_paths':paths,'applied_change_count':5,'actual_formatter_change_count':0,
 'other_inventory_rows_unchanged':15183,'complete_inventory_count':15188,
 'inputs':{'actual_RESULT':{'path':str(ACTUAL/'RESULT.original.json'),**pin(result_raw)},
   'actual_ARTIFACTS':{'path':str(ACTUAL/'ARTIFACTS.original.json'),**pin(artifacts_raw)},
   'actual_supervisor':{'path':str(ACTUAL/'STATUS_01.original.json'),**pin(normal_raw)},
   'original_before_inventory':{'path':str(BEFORE),**pin(before_raw)},
   'ordinary_after_inventory_exact_recovery':{'path':str(AFTER),**pin(after_raw)},
   'reviewed_source_packet':{'path':str(PROPOSAL/'REPAIR_PACKET.json'),**pin(packet_raw)},
   'original_V5':{'path':str(V5),**pin(v5_raw)}},
 'source_byte_pins':source_bytes,'original_serializer_functions':serializers,
 'records':outputs,'unique_parts':list(unique.values()),'recovered_original_summaries':summaries,
 'actual_small_gzip_read_anchor':{'path':str(anchor_path),**pin(anchor_raw),
   'native_version':chunk['version'],'actual_gzip':pin(small),'all_bytes_equal':True},
 'provenance':'Exact lossless reconstruction from already-held source bytes and complete inventories, validated against independently observed actual ARTIFACTS. Not a second native full read.',
 'ordinary_inventory_and_canonical30_package_duplicated':False,
 'large_raw_and_gzip_remote_blob_existence_not_claimed':True,
 'no_new_H_or_source_observation':True,'source_module_or_main_executed':False,
 'no_source_ref_or_control_changes':True,'tests_or_gates_repeated':False,
 'original_source_gate_failure_retained':True,'qualification':False,
 '3033_cutoff_package_changed':False,'python':sys.version,'zlib':zlib.ZLIB_VERSION}
save('RECOVERY_REVIEW.json',(json.dumps(review,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'status':review['status'],'applied':5,'formatter_changes':0,
 'unique_large_parts':5,'empty_fmt_anchor':True,'records':[{k:r[k] for k in ['original_name','raw','gzip']} for r in outputs],
 'review':pin(read(OUT/'RECOVERY_REVIEW.json'))},indent=2))

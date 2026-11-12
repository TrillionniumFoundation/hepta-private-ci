import base64,copy,gzip,hashlib,json
from pathlib import Path

BASE=Path('/tmp/hepta-36fa-checkpoint1867-recovery/RECOVERED_PEER_EXPECTED_AFTER_INVENTORY.json')
NATIVE=Path('/tmp/hepta-36fa-maintenance-v5-launch')
OUT=Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1')

def git_oid(kind,raw):
    return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':git_oid('blob',raw)}

def physical_merkle(rows):
    root={}
    for row in rows:
        assert row['kind'] in ('file','symlink') and row['stable']
        mode='120000' if row['kind']=='symlink' else ('100755' if row['permissions']&0o111 else '100644')
        node=root;parts=row['path'].split('/')
        for part in parts[:-1]:node=node.setdefault(part,{})
        assert parts[-1] not in node
        node[parts[-1]]=(mode,row['working_blob'])
    def walk(node):
        entries=[]
        for name,item in node.items():
            if isinstance(item,dict):mode,sha='40000',walk(item)
            else:mode,sha=item
            key=name.encode()+(b'/' if mode=='40000' else b'')
            entries.append((key,mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)))
        return git_oid('tree',b''.join(raw for _,raw in sorted(entries)))
    return walk(root)

base_raw=BASE.read_bytes();base=json.loads(base_raw)
packet_raw=(NATIVE/'fmt.after.postimages.json').read_bytes();packet=json.loads(packet_raw)
artifacts=json.loads((NATIVE/'ARTIFACTS.json').read_text())['files']
artifacts={x['name']:x for x in artifacts}
expected=artifacts['fmt.after.inventory.json.gz']
packet_pin=artifacts['fmt.after.postimages.json.gz']
assert pin(packet_raw)=={'bytes':packet_pin['raw_bytes'],'sha256':packet_pin['raw_sha256'],'git_blob':packet_pin['raw_git_blob']}
assert packet['format']=='hepta-maintenance-actual-source-transition-v1' and packet['stage']=='fmt.after'
assert packet['source_commit_unchanged']=='9c4a11f61d30e9cc352bf44d56c98909d202a55d'
assert packet['qualification'] is False and packet['all_physical_changes_including_untracked_or_ignored_are_recorded'] is True
assert hashlib.sha256(base_raw).hexdigest()==packet['base_inventory_sha256']=='c006da7852740c7c24961a4748744eb1270f25c8d8fe95c2fc873d4dc279d79d'
assert len(packet['changes'])==len({x['path'] for x in packet['changes']})==43
original_rows={x['path']:x for x in base['files']};mapping=copy.deepcopy(original_rows)
assert len(mapping)==15188 and physical_merkle(base['files'])=='ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'
for change in packet['changes']:
    assert mapping[change['path']]==change['before']
    after=change['after'];before=change['before']
    assert after['kind']=='file' and after['stable'] and after['path']==change['path']
    assert after['matches_index'] is False
    for key in ('index_blob','index_mode','permissions'):assert after[key]==before[key]
    for side in ('before','after'):
        raw=base64.b64decode(change[side+'_raw_base64'],validate=True);row=change[side]
        assert len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'] and git_oid('blob',raw)==row['working_blob']
    mapping[change['path']]=after

# The original 511818 serializer uses sorted full rows and json compact sorted
# keys. Its identity helper strips the complete porcelain-v1 status string.
# This one candidate uses only recorded modified paths; no guess/search loop.
base['files']=[mapping[k] for k in sorted(mapping)]
base['source']['status']=''.join(' M '+x['path']+'\n' for x in sorted(packet['changes'],key=lambda x:x['path'])).strip()
raw=(json.dumps(base,sort_keys=True,separators=(',',':'))+'\n').encode()
raw_pin=pin(raw)
assert raw_pin=={'bytes':expected['raw_bytes'],'sha256':expected['raw_sha256'],'git_blob':expected['raw_git_blob']}
assert raw_pin['bytes']==5614211 and raw_pin['sha256']==packet['after_inventory_sha256']=='3f28f2ea4b78a0b3faa41024bd1664c2201ad21cb3c3f3465cb40192b034f58f'
assert raw_pin['git_blob']=='1563de8825fc183d345d10d03e68d79b2d9211ca'
actual_tree=physical_merkle(base['files'])
assert actual_tree=='65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
gz=gzip.compress(raw,mtime=0);gz_pin=pin(gz)
assert all(gz_pin[k]==expected[k] for k in gz_pin)
assert gzip.decompress(gz)==raw
parts=[]
for i,e in enumerate(expected['parts'],1):
    data=gz[e['decoded_offset']:e['decoded_offset']+e['decoded_bytes']]
    encoded=base64.b64encode(data)+b'\n'
    assert hashlib.sha256(data).hexdigest()==e['decoded_sha256']
    assert pin(encoded)=={k:e[k] for k in ('bytes','sha256','git_blob')}
    parts.append((f'final.inventory.json.gz.part-{i:03d}.b64',encoded,e))
OUT.mkdir(exist_ok=True)
(OUT/'final.inventory.recovered.json').write_bytes(raw)
(OUT/'final.inventory.recovered.json.gz').write_bytes(gz)
for name,encoded,_ in parts:(OUT/name).write_bytes(encoded)
report={'format':'hepta-exact-postformat-inventory-recovery-v1','status':'ONE_CANDIDATE_MATCHED_ALL_ORIGINAL_RAW_GZIP_AND_PART_PINS','qualification':False,'source_unchanged_by_this_analysis':True,'method':'Complete retained c006 pre-format inventory plus all 43 actual original before/after rows and raw bytes, unchanged remaining rows, and the exact original 511818 compact serializer and porcelain status convention. One candidate only.','base':pin(base_raw),'actual_postimages':pin(packet_raw),'raw':raw_pin,'gzip':gz_pin,'all_original_encoded_parts_matched':len(parts),'parts':[{'recovered_file':name,'original':e} for name,_,e in parts],'physical_tree':actual_tree,'head_tree_preserved':base['source']['tree'],'head_preserved':base['source']['head'],'physical_rows':len(mapping),'changed_rows':43,'unchanged_rows':len(mapping)-43,'source_status_preserved':base['source']['status'],'limits':'Exact recovery of previously observed native output, not a new native full-inventory download or independent task-utility evaluation. The separate SH collector must still read actual current 73 files and verify complete source stability before/final source use.'}
(OUT/'RECOVERY_REVIEW.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('parts','source_status_preserved')},indent=2))

"""Exact registry union data proof. Does not run the repository scanner or gates."""
from pathlib import Path
import copy,hashlib,json,re,tomllib,gzip,base64
OUT=Path('/tmp/hepta-36fa-root-registration-union-seed-v1')
E2=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/registration-components-frozen-v2')
E3=Path('/tmp/hepta-36fa-root-product-e3-proposal-v1/registration-proposal-v1')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
base_raw=Path('/tmp/hepta-36fa-e1-source-candidate-v1/after/CALLERS.toml').read_bytes()
assert pin(base_raw)['git_blob']=='8875892749c45665abdce90310a7a47d90308b9b'
base=tomllib.loads(base_raw.decode())
p=json.loads((E3/'SOURCE_PACKET.json').read_text());entry=next(e for e in p['entries'] if e['path']=='CALLERS.toml')
assert entry['before']==pin(base_raw) and entry['before_utf8'].encode()==base_raw
e3_raw=entry['after_utf8'].encode();assert pin(e3_raw)==entry['after']
assert entry['after']['git_blob']=='b5e0e965c59dfe784d29ff09e4806127c3079474'
e3=tomllib.loads(e3_raw.decode())
e2b_raw=(E2/'BOUNDARY_ROWS.json').read_bytes();assert pin(e2b_raw)['git_blob']=='d86174866a649ddcdf2595cb47bb332dbaf9f6df'
e2p_raw=(E2/'PROTECTED_ROWS.json').read_bytes();assert pin(e2p_raw)['git_blob']=='fc37b43f2499cc71ef39011a1f360082992650cd'
sp_raw=(E2/'EXACT_REGISTRATION_SPLICES.json').read_bytes();assert pin(sp_raw)['git_blob']=='9064d31a63f9ccdd4bae5523946ca4201ac8795c'
b=json.loads(e2b_raw);guards=json.loads(e2p_raw);splices=json.loads(sp_raw)['splices']
expected=copy.deepcopy(e3)
assert len(base['boundary'])==650 and len(base['protected_file'])==451
assert e3['protected_file'][:451]==base['protected_file']
overlap=[];old_changes={}
for c in b['old_row_changes']:
 i=c['index'];assert c['before']==base['boundary'][i]
 assert {k:v for k,v in c['after'].items() if k!='product_callers'}=={k:v for k,v in c['before'].items() if k!='product_callers'}
 current=expected['boundary'][i]
 assert {k:v for k,v in current.items() if k!='product_callers'}=={k:v for k,v in c['before'].items() if k!='product_callers'}
 if current!=c['before']:overlap.append(i)
 for caller in c['added_callers']:
  assert caller not in c['before']['product_callers']
  if caller not in current['product_callers']:current['product_callers'].append(caller)
 old_changes[c['id']]=copy.deepcopy(current)
for c in guards['old_required_rebindings']:
 i=c['index'];assert expected['protected_file'][i]==c['before']==base['protected_file'][i]
 assert {k:v for k,v in c['before'].items() if k!='required'}=={k:v for k,v in c['after'].items() if k!='required'}
 expected['protected_file'][i]=c['after']
expected['boundary'].extend(b['new_rows'])
expected['protected_file'].extend(guards['append_protected_rows'])
required=expected['privileged_inventory']['required_boundary_ids']
for name in b['required_boundary_ids_append']:
 assert name not in required;required.append(name)
text=e3_raw.decode();applied=[]
for edit in splices:
 label=edit['label'];old=edit['before_utf8'];new=edit['after_utf8']
 assert pin(old.encode())==edit['before'] and pin(new.encode())==edit['after']
 if label.startswith('boundary '):
  name=label.removeprefix('boundary ')
  if text.count(old)!=1:
   marker='[[boundary]]\nid = '+json.dumps(name)+'\n'
   assert text.count(marker)==1
   start=text.index(marker);match=re.search(r'(?m)^\[',text[start+1:])
   end=start+1+match.start() if match else len(text)
   old=text[start:end]
   parsed=tomllib.loads(old)['boundary'];assert len(parsed)==1 and parsed[0]['id']==name
   target=old_changes[name]
   pattern=r'(?m)^product_callers = .*?$'
   assert len(re.findall(pattern,old))==1
   new=re.sub(pattern,'product_callers = '+json.dumps(target['product_callers']),old,count=1)
   assert tomllib.loads(new)['boundary'][0]==target
 elif label=='append only original required_boundary_ids':
  matches=list(re.finditer(r'(?m)^required_boundary_ids = .*?$',text));assert len(matches)==1
  old=matches[0].group(0);new='required_boundary_ids = '+json.dumps(required)
 assert text.count(old)==1,('nonunique edit',label)
 text=text.replace(old,new,1);applied.append((label,old,new))
actual=tomllib.loads(text);assert actual==expected
inverse=text
for label,old,new in reversed(applied):
 assert inverse.count(new)==1,('nonunique inverse',label)
 inverse=inverse.replace(new,old,1)
assert inverse.encode()==e3_raw
assert len(actual['boundary'])==757 and len(actual['protected_file'])==531
assert len({x['id'] for x in actual['boundary']})==757
assert actual['boundary'][650:666]==e3['boundary'][650:666]
assert actual['boundary'][666:757]==b['new_rows']
assert actual['protected_file'][451:470]==e3['protected_file'][451:470]
assert actual['protected_file'][470:531]==guards['append_protected_rows']
for i in range(650):
 before=base['boundary'][i];after=actual['boundary'][i]
 assert {k:v for k,v in before.items() if k!='product_callers'}=={k:v for k,v in after.items() if k!='product_callers'}
 assert after['product_callers'][:len(before['product_callers'])]==before['product_callers']
for i in range(451):
 before=base['protected_file'][i];after=actual['protected_file'][i]
 assert {k:v for k,v in before.items() if k!='required'}=={k:v for k,v in after.items() if k!='required'}
for key in base:
 if key not in ('boundary','protected_file','privileged_inventory'):assert actual[key]==base[key]
for key in base['privileged_inventory']:
 if key!='required_boundary_ids':assert actual['privileged_inventory'][key]==base['privileged_inventory'][key]
out=text.encode()
OUT.mkdir(exist_ok=False)
(OUT/'CALLERS_E1_E3_E2_SEED.toml').write_bytes(out)
compressed=gzip.compress(out,mtime=0);parts=[]
for index,offset in enumerate(range(0,len(compressed),196608),1):
 chunk=compressed[offset:offset+196608];encoded=base64.b64encode(chunk)+b'\n';name=f'part-{index:03d}.b64'
 (OUT/name).write_bytes(encoded);parts.append({'path':name,'offset':offset,'encoded':pin(encoded),'decoded':pin(chunk)})
report={'format':'hepta-root-e1-e3-e2-registration-union-seed-v1','state':'PARTIAL_REGISTRATION_SEED_NOT_FINAL_SOURCE_GATE',
 'base':pin(base_raw),'E3_projection':pin(e3_raw),'E2_boundaries':pin(e2b_raw),'E2_guards':pin(e2p_raw),'E2_exact_splices':pin(sp_raw),
 'complete_union':pin(out),'gzip':pin(compressed),'parts':parts,'all_19_edits_inverse_to_full_E3_raw':True,
 'old_caller_overlap_indices':overlap,'boundary_count':757,'protected_count':531,'base_noncaller_and_nonrequired_fields_preserved':True,
 'all_other_top_level_and_inventory_fields_preserved':True,'old_forbidden_and_authority_fields_preserved':True,
 'new_boundary_slices':{'E3':[650,666],'E2':[666,757]},'new_guard_slices':{'E3':[451,470],'E2':[470,531]},
 'edits':[{'label':label,'before':pin(old.encode()),'after':pin(new.encode())} for label,old,new in applied],
 'remaining':['loader and pre-freeze actual callers/new boundaries','rebind shared full source guards to final composed bytes',
 'Material3 terminal-brace successor exact test pin','full source contracts/QA hashes/inventory and Root-parent workflow union',
 'unchanged original collector/QA/Rust/source/native gates'],
 'collector_executed':False,'QA_executed':False,'H_calls':0,'source_ref_mutation':False,'qualification':False}
raw=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
(OUT/'UNION_REVIEW.json').write_bytes(raw)
print(json.dumps({'review':pin(raw),'complete_union':pin(out),'boundaries':757,'protections':531,'old_overlap':overlap,'parts':len(parts),'qualification':False}))

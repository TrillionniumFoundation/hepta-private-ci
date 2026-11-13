from pathlib import Path
import ast, hashlib, json, re, tomllib
OUT=Path('/tmp/hepta-36fa-root-loader-registration-obligations-v1')
BASE=Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1')
HELPER=Path('/tmp/hepta-36fa-e2-registration-independent-review-v1/review_bytes_v2.py')
SEED=Path('/tmp/hepta-36fa-root-registration-union-seed-v1/CALLERS_E1_E3_E2_SEED.toml')
def pin(b): return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def put(name,obj):
 b=(json.dumps(obj,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode()
 with (OUT/name).open('xb') as f:f.write(b)
 return {'path':str(OUT/name),**pin(b)}
def checked(b,p):
 q=pin(b);assert q=={k:p[k] for k in q},(q,p);return q
helper_text=HELPER.read_text(); tree=ast.parse(helper_text)
selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['rust_code','balanced','declarations']]
assert len(selected)==3
namespace={'re':re}
exec(compile(ast.Module(body=selected,type_ignores=[]),str(HELPER)+'[three reviewer-owned pure lexical functions]','exec'),namespace)
decl=namespace['declarations'];mask=namespace['rust_code']
all_before={};composed={};layers=[];new=[];files=[]
for layer,expected in [('inputs-layer-v1','e78f0413a20e306c1064c51eb8e53e76d597fd93'),('task-inputs-layer-v1','77b05d5ec3f8d3b10a4024b63103e97e8f3fe996')]:
 p=BASE/layer/'SOURCE_PACKET.json';raw=p.read_bytes();assert pin(raw)['git_blob']==expected
 packet=json.loads(raw);layers.append({'layer':layer,'path':str(p),**pin(raw)})
 for row in packet['entries']:
  path=row['path'];before=row['before_utf8'];after=row['after_utf8']
  if before is not None:checked(before.encode(),row['before'])
  checked(after.encode(),row['after'])
  if path in composed:assert composed[path]==before,(layer,path)
  else:all_before[path]=before
  composed[path]=after
  old={(x['impl_header'],x['name'],x['visibility']):x for x in decl(before or '')}
  fresh=decl(after)
  for x in fresh:
   key=(x['impl_header'],x['name'],x['visibility'])
   if key in old:
    assert x['body']==old[key]['body'],(layer,path,key)
   else:
    body=x['body'];x=dict(x);x.update({'layer':layer,'path':path,'source_pin':row['after'],'body_pin':pin(body.encode()),'start_line':after.count('\n',0,x['start'])+1,'end_line':after.count('\n',0,x['end'])+1,'signature':body[:mask(body).index('{')].strip()})
    new.append(x)
  files.append({'layer':layer,'path':path,'before':row['before'],'after':row['after'],'old_function_bodies_exact':True})
assert len(composed)==17,len(composed)
raw=SEED.read_bytes();assert pin(raw)['git_blob']=='1b55bc0cc5be4d47b7273f3c451f2eeff02fc542'
reg=tomllib.loads(raw.decode());assert len(reg['boundary'])==757
candidates=[]
for d in new:
 code=mask(d['body'])
 for index,row in enumerate(reg['boundary']):
  name=row['symbol'].rsplit('::',1)[-1]
  matches=list(re.finditer(r'(?<!\w)'+re.escape(name)+r'\s*(?:(?:<[^;{}]*?>)?\s*\()',code))
  if matches:
   candidates.append({'caller_path':d['path'],'caller_impl':d['impl_header'],'caller_method':d['name'],'boundary_index':index,'id':row['id'],'symbol':row['symbol'],'receiver_type':row.get('receiver_type'),'definition_path':row.get('definition_path'),'already_registered_path':d['path'] in row.get('product_callers',[]),'lexical_occurrences':[{'line':d['start_line']+d['body'].count('\n',0,m.start()),'text':d['body'].splitlines()[d['body'].count('\n',0,m.start())]} for m in matches],'status':'LEXICAL_CANDIDATE_ONLY_REQUIRES_TYPED_MANUAL_DISAMBIGUATION'})
proof=put('DECLARATION_EXTRACTION.preparation.json',{'format':'hepta-loader-registration-declaration-preparation-v1','state':'PREPARATION_NOT_FINAL_REGISTRATION_REVIEW','scope':'Only complete frozen e78f and 77b05, excluding future third/fourth loader or prefreeze layers','layers':layers,'seed':{'path':str(SEED),**pin(raw)},'lexical_helper':{'path':str(HELPER),**pin(HELPER.read_bytes()),'only_pure_functions_extracted':['rust_code','balanced','declarations']},'files':files,'composed_paths':len(composed),'new_declarations':new,'old_boundary_lexical_candidates':candidates,'collector_executed':False,'H_calls':0,'source_modified':False})
print(json.dumps({'preparation':proof,'new_declarations':len(new),'lexical_candidate_pairs':len(candidates)},indent=2))

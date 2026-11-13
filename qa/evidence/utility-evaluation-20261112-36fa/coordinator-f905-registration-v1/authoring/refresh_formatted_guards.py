#!/usr/bin/env python3
"""Re-extract exact guarded spans from actual formatter bytes; no QA/gate call."""
from pathlib import Path
import ast, copy, difflib, hashlib, importlib.util, json, re, sys, tomllib
sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('original_guard_lexical',R/'before/scripts/verify_hepta_callers.py')
P=importlib.util.module_from_spec(spec);sys.modules[spec.name]=P;spec.loader.exec_module(P)
manifest=tomllib.loads((R/'before/CALLERS.toml').read_text())
candidate=copy.deepcopy(manifest)
errors=[];changes=[];maps={}
TOK=re.compile(r'[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]')

def pin(raw):
 return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def active(source):return P._strip_cfg_test_items(P._strip_rust_non_code(source))

def mapping(before,after):
 key=(hashlib.sha256(before.encode()).hexdigest(),hashlib.sha256(after.encode()).hexdigest())
 if key not in maps:
  a=list(TOK.finditer(before));b=list(TOK.finditer(after));m={}
  matcher=difflib.SequenceMatcher(None,[x.group() for x in a],[x.group() for x in b],autojunk=False)
  for block in matcher.get_matching_blocks():
   for n in range(block.size):m[block.a+n]=block.b+n
  maps[key]=(a,b,m)
 return maps[key]

def remap(marker,before,after,where):
 if marker in after:return marker
 positions=[m.start() for m in re.finditer(re.escape(marker),before)]
 if len(positions)!=1:
  raise ValueError(f'{where}: old marker occurrences={len(positions)}: {marker[:100]!r}')
 start=positions[0];end=start+len(marker)
 a,b,index=mapping(before,after)
 tokens=[i for i,t in enumerate(a) if start<=t.start() and t.end()<=end]
 if not tokens:raise ValueError(f'{where}: marker contains no complete token')
 first,last=tokens[0],tokens[-1]
 if first not in index or last not in index:raise ValueError(f'{where}: formatted endpoint token unavailable')
 if index[first]>index[last]:raise ValueError(f'{where}: formatter moved span endpoints across one another')
 # A marker may begin/end inside a token only if that original edge is unchanged.
 if a[first].start()<start or a[last].end()>end:raise ValueError(f'{where}: partial token edge')
 new_start=b[index[first]].start();new_end=b[index[last]].end()
 translated=after[new_start:new_end]
 if not translated or translated not in after:raise ValueError(f'{where}: empty/unlocatable translated span')
 # Preserve supplied whitespace at each edge only when it was required. Leading
 # or trailing layout inside a larger scope is not used to find another scope.
 leading=before[start:a[first].start()];trailing=before[a[last].end():end]
 if leading and not leading.isspace():raise ValueError(f'{where}: non-whitespace omitted prefix')
 if trailing and not trailing.isspace():raise ValueError(f'{where}: non-whitespace omitted suffix')
 return translated

def function(code,marker):
 if code.count(marker)!=1:raise ValueError(f'non-unique original function {marker}: {code.count(marker)}')
 start=code.index(marker);end=P._rust_item_end(code,start)
 if end is None or code[end]!='}':raise ValueError('incomplete function '+marker)
 return code[start:end+1],start,end+1

def locate_sequence(sequence,code,label):
 offset=0
 for marker in sequence:
  found=code.find(marker,offset)
  if found<0:raise ValueError(f'{label}: target marker/order absent {marker[:80]!r}')
  offset=found+len(marker)

for i,row in enumerate(candidate['protected_file']):
 path=row['path'];oldpath=R/'pre-format'/path
 if not oldpath.exists():continue
 before_raw=oldpath.read_text();after_raw=(R/'before'/path).read_text()
 before,after=active(before_raw),active(after_raw)
 old=copy.deepcopy(row)
 replacements=[]
 try:
  for j,marker in enumerate(row['required']):
   new=remap(marker,before_raw,after_raw,f'row{i}.required[{j}]')
   if new!=marker:replacements.append({'field':f'required[{j}]','before':marker,'after':new})
   row['required'][j]=new
  for j,seq in enumerate(row.get('required_order',[])):
   for k,marker in enumerate(seq):
    new=remap(marker,before,after,f'row{i}.required_order[{j}][{k}]')
    if new!=marker:replacements.append({'field':f'required_order[{j}][{k}]','before':marker,'after':new})
    seq[k]=new
   locate_sequence(seq,after,f'row{i}.required_order[{j}]')
  for j,guard in enumerate(row.get('required_function_order',[])):
   oldbody,start,end=function(before,guard['function']);newbody,ns,ne=function(after,guard['function'])
   for key in ('sequence','top_level','literal_calls'):
    if key not in guard:continue
    for k,marker in enumerate(guard[key]):
     left,right=(before_raw[start:end],after_raw[ns:ne]) if key=='literal_calls' or marker in guard.get('literal_calls',[]) else (oldbody,newbody)
     new=remap(marker,left,right,f'row{i}.function[{j}].{key}[{k}]')
     if new!=marker:replacements.append({'field':f'required_function_order[{j}].{key}[{k}]','before':marker,'after':new})
     guard[key][k]=new
   # Literal markers are checked against raw function bytes at their exact code
   # positions in the unchanged verifier. This preparation only locates them.
   seq=[x for x in guard['sequence'] if x not in guard.get('literal_calls',[])]
   locate_sequence(seq,newbody,f'row{i}.function[{j}]')
   for marker in guard.get('top_level',[]):
    if newbody.count(marker)!=1:raise ValueError(f'row{i} top_level uniqueness')
    prefix=newbody[:newbody.index(marker)]
    if prefix.count('{')-prefix.count('}')!=1:raise ValueError(f'row{i} top_level depth')
  assert row['forbidden']==old['forbidden']
  if row!=old:changes.append({'index':i,'path':path,'before_source':pin(before_raw.encode()),'after_source':pin(after_raw.encode()),
                            'replacements':replacements,'old_forbidden_equal':True,'before':old,'after':copy.deepcopy(row)})
 except (ValueError,AssertionError) as exc:
  candidate['protected_file'][i]=old
  errors.append({'index':i,'path':path,'error':str(exc)})

result={'status':'STATIC_EXACT_SPAN_PREPARATION_ONLY','changed_rows':len(changes),'errors':errors,
        'no_verifier_gate_or_QA_method_called':True,'changes':changes,
        'all_original_forbidden_equal':all(a['forbidden']==b['forbidden'] for a,b in zip(manifest['protected_file'],candidate['protected_file'])),
        'row411_equal':manifest['protected_file'][411]==candidate['protected_file'][411]}
(R/'FORMATTED_GUARD_REFRESH.draft.json').write_text(json.dumps(result,indent=2)+'\n')
(R/'CALLERS_FORMAT_REFRESH.draft.json').write_text(json.dumps(candidate,indent=2)+'\n')
print(json.dumps({'changed_rows':len(changes),'errors':errors,'marker_changes':sum(len(x['replacements']) for x in changes),'row411_equal':result['row411_equal']},indent=2))

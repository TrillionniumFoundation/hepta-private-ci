"""Read fixed contract data and source syntax only; no QA/collector execution."""
import ast
import base64
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=Path('/tmp/hepta-36fa-coordinator-f905-registration-v1')
QA=BASE/'before/qa/b4-no-bypass'
sys.path.insert(0,'/tmp/hepta-36fa-provider-0c59-fmt62-semantic-peer-v1')
from inspect_fmt_tokens import lex, ident
from classify_fmt_items import groups

def source(path,side):
 file=BASE/('pre-format' if side=='before' else 'view')/path
 if not file.exists():file=BASE/'before'/path
 return file.read_text()

def mask(s):
 ts,comments=lex(s); chars=list(s)
 for t in ts+comments:
  if t[0]=='literal' or 'comment' in t[0]:
   for i in range(t[2],t[3]):
    if chars[i]!='\n':chars[i]=' '
 return ''.join(chars)

def function_span(s,name):
 ts,_=lex(s);pairs,_=groups(ts);found=[]
 for i,t in enumerate(ts[:-1]):
  if t[1]!='fn' or ts[i+1][1]!=name:continue
  j=i+2
  while j<len(ts):
   v=ts[j][1]
   if v in ('(', '['):j=pairs[j]+1;continue
   if v==';':break
   if v=='{':found.append((t[2],ts[pairs[j]][3]));break
   j+=1
 assert len(found)==1,(name,len(found))
 return found[0]

def main():
 contract_raw=(QA/'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json').read_bytes();contract=json.loads(contract_raw)
 tree=ast.parse((QA/'test_evaluated_published_read_source_closure.py').read_text());constants={}
 for n in tree.body:
  if isinstance(n,ast.Assign):
   for target in n.targets:
    if isinstance(target,ast.Name) and target.id in ['ORDINARY_SCOPE_GUARDS','ORDINARY_LITERAL_SPECS','ORDINARY_MODULE_MOUNTS','ORDINARY_NEW_BOUNDARIES']:
     constants[target.id]=ast.literal_eval(n.value)
 actual=json.loads(Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1/fmt.after.postimages.json').read_bytes())
 changed={x['path'] for x in actual['changes']}; attacks=[];missing=[]
 for group,cases in contract['attacks'].items():
  for index,case in enumerate(cases):
   counts={};spans={};matched={}
   for side in ('before','after'):
    s=source(case['path'],side);code=mask(s);start,end=function_span(s,case['function'])
    marker=case['marker'];pattern=r'\s*'.join(re.escape(token) for token in re.findall(r'\w+|[^\w\s]',marker))
    if marker[0].isalnum() or marker[0]=='_':pattern=r'(?<!\w)'+pattern
    if marker[-1].isalnum() or marker[-1]=='_':pattern+=r'(?!\w)'
    values=list(re.finditer(pattern,code[start:end]));counts[side]=len(values)
    spans[side]=[start,end]
    matched[side]=[{'start':start+m.start(),'end':start+m.end(),'raw':s[start+m.start():start+m.end()]} for m in values]
   row={'group':group,'index':index,**case,'original_whitespace_token_pattern_counts':counts,'function_spans':spans,'matched_original_source':matched}
   attacks.append(row)
   if counts['before']!=counts['after'] or not counts['after']:missing.append(row)
 def overlap(mapping):
  return [{'path':path,'entries':len(values)} for path,values in mapping.items() if path in changed]
 ordinary=overlap(constants['ORDINARY_SCOPE_GUARDS']);provider=overlap(contract['scopes'])
 literal_changes=[x for x in constants['ORDINARY_LITERAL_SPECS'] if x['path'] in changed]
 assert not literal_changes
 mounts=[x for x in constants['ORDINARY_MODULE_MOUNTS'] if x['parent'] in changed]
 out={'format':'hepta-fixed-provider-attack-anchors-after-actual-fmt-v1','scope':'Pure lexical inspection in unique original functions; no imported QA/collector or verifier invocation and no mutation execution. This independently checks marker occurrence stability, not rejection verdicts.',
 'contract':ident(contract_raw),'attack_cases':len(attacks),'attack_rows':attacks,'changed_or_missing_marker_occurrences':missing,
 'provider_scope_files_total':len(contract['scopes']),'provider_scopes_total':sum(map(len,contract['scopes'].values())),
 'provider_scope_files_affected_by_actual_fmt':provider,'provider_scope_count_in_changed_files':sum(x['entries'] for x in provider),
 'ordinary_scope_files_total':len(constants['ORDINARY_SCOPE_GUARDS']),'ordinary_scopes_total':sum(map(len,constants['ORDINARY_SCOPE_GUARDS'].values())),
 'ordinary_scope_files_affected_by_actual_fmt':ordinary,'ordinary_scope_count_in_changed_files':sum(x['entries'] for x in ordinary),
 'ordinary_17_literal_source_paths_changed':literal_changes,'ordinary_mounts_with_changed_parent_bytes':mounts,
 'refresh_scope':'All affected code/literal scope hashes and module-shape descriptions must be recomputed from actual formatted source by the sole registry writer. No selector/forbidden/assertion/ignore relaxation follows from these diagnostics.'}
 raw=(json.dumps(out,sort_keys=True,indent=2)+'\n').encode()
 with (HERE/'FIXED_CONTRACT_ANCHOR_REVIEW.json').open('xb') as f:f.write(raw)
 print(json.dumps({'identity':ident(raw),'attacks':len(attacks),'mismatches':len(missing),'provider_affected_files':len(provider),'provider_affected_scopes':sum(x['entries'] for x in provider),'ordinary_affected':ordinary,'ordinary_literal_paths_changed':literal_changes,'mount_parents':mounts},indent=2))
 for x in missing:print(json.dumps(x))

if __name__=='__main__':main()

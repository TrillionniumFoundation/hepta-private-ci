"""Parse frozen QA syntax and search actual bytes; do not import or execute QA."""
import ast
import base64
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
QA=Path('/tmp/hepta-36fa-coordinator-f905-registration-v1/before/qa/b4-no-bypass')
PACKET=Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1/fmt.after.postimages.json')
INV=Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1/final.inventory.exact_recovered.json')

def pin(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

class Strings(ast.NodeVisitor):
 def __init__(self,path,text):self.path=path;self.text=text;self.scope=[];self.stack=[];self.rows=[]
 def visit(self,node):
  self.stack.append(node)
  super().visit(node)
  self.stack.pop()
 def visit_FunctionDef(self,node):
  self.scope.append(node.name);self.generic_visit(node);self.scope.pop()
 visit_AsyncFunctionDef=visit_FunctionDef
 def visit_ClassDef(self,node):
  self.scope.append(node.name);self.generic_visit(node);self.scope.pop()
 def visit_Constant(self,node):
  if not isinstance(node.value,str) or len(node.value)<5:return
  call=next((x for x in reversed(self.stack[:-1]) if isinstance(x,ast.Call)),None)
  parent=self.stack[-2] if len(self.stack)>1 else None
  self.rows.append({'qa_path':self.path,'line':node.lineno,'column':node.col_offset,
    'scope':'.'.join(self.scope),'value':node.value,'parent':type(parent).__name__,
    'call_function':ast.unparse(call.func) if call else None,
    'call_text':ast.get_source_segment(self.text,call) if call else None,
    'is_fstring_segment':isinstance(parent,ast.JoinedStr)})

def main():
 raw=PACKET.read_bytes();assert pin(raw)['git_blob']=='43f7dd7eaa1578a4d6d570252939084f80181685'
 changes=json.loads(raw)['changes'];sources={}
 for row in changes:
  sides=[]
  for side in ['before','after']:
   b=base64.b64decode(row[side+'_raw_base64'],validate=True);p=pin(b)
   assert p['git_blob']==row[side]['working_blob'] and p['sha256']==row[side]['sha256'] and p['bytes']==row[side]['bytes']
   sides.append(b.decode())
  sources[row['path']]=sides
 invraw=INV.read_bytes();assert pin(invraw)['git_blob']=='e1e48f35bb6cf5a3dd86c59472da77df87154b6a'
 rows={x['path']:x for x in json.loads(invraw)['files']}
 strings=[];inputs=[]
 for path in sorted(QA.glob('*.py')):
  b=path.read_bytes();name='qa/b4-no-bypass/'+path.name;p=pin(b);r=rows[name]
  assert p=={'bytes':r['bytes'],'sha256':r['sha256'],'git_blob':r['working_blob']}
  t=b.decode();s=Strings(name,t);s.visit(ast.parse(t));strings+=s.rows;inputs.append({'path':name,**p})
 assert len(inputs)==64
 values={x['value'] for x in strings}
 matches={}
 for value in values:
  found=[]
  for path,(before,after) in sources.items():
   old=before.count(value)
   if old:
    new=after.count(value)
    if new<old:found.append({'source_path':path,'before_count':old,'after_count':new})
  if found:matches[value]=found
 result=[{**x,'actual_source_occurrence_losses':matches[x['value']]} for x in strings if x['value'] in matches]
 out={'format':'hepta-actual-fmt-static-qa-string-occurrence-diagnostic-v1','qa_inputs':inputs,
  'actual_fmt_packet':pin(raw),'actual_full_inventory':pin(invraw),'qa_files':64,
  'literal_occurrences_considered':len(strings),'unique_literal_values_considered':len(values),
  'unique_values_with_actual_occurrence_loss':len(matches),'rows':result,
  'scope':'All AST Constant strings of length at least five are searched in all 62 exact actual pre/post source bodies. No QA or imported repo function is invoked. A hit is a diagnostic; negative attack output strings and unrelated same-text occurrences require manual classification. Regexes, runtime-built strings and full-test outcomes are not inferred.'}
 encoded=(json.dumps(out,sort_keys=True,indent=2)+'\n').encode()
 with (HERE/'LITERAL_OCCURRENCE_DIAGNOSTIC.json').open('xb') as f:f.write(encoded)
 print(json.dumps({'identity':pin(encoded),'qa_files':len(inputs),'strings':len(strings),'unique':len(values),'loss_values':len(matches),'occurrences':len(result)}))
 for i,x in enumerate(result):print(json.dumps({'i':i,'qa':Path(x['qa_path']).name,'line':x['line'],'scope':x['scope'],'call':x['call_function'],'value':x['value'],'losses':x['actual_source_occurrence_losses']}))

if __name__=='__main__':main()

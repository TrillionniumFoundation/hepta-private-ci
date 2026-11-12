from pathlib import Path
import json
r=Path('/workspace/scratch/037c0371c195/candidate-evaluated-command-guards-a96-v1')
plan=json.loads((r/'CALLERS_DELTA_PLAN.json').read_text())
values=json.loads((r/'reviewed_contract_constants.json').read_text())
values['EXPECTED']={x['id']:x['after']['product_callers'] for x in plan['boundary_changes']}
values['GUARDED']={p:v for p,v in json.loads((r/'GUARDED_FUNCTIONS.json').read_text()).items() if not p.endswith('learning_iteration_evidence_client.rs')}
def value(v):
 if isinstance(v,str):
  prefix='codex-rs/hepta-agentd/src/'
  return ('AGENT + '+repr(v.removeprefix(prefix))) if v.startswith(prefix) else repr(v)
 if isinstance(v,list):return '('+', '.join(value(x) for x in v)+(',' if len(v)==1 else '')+')'
 return repr(v)
parts=[]
for key,data in values.items():
 if isinstance(data,dict):parts.append(key+' = {\n'+''.join('    '+value(k)+': '+value(v)+',\n' for k,v in data.items())+'}')
 else:parts.append(key+' = '+value(data))
s=(r/'source_qa.template.py').read_text().replace('__REVIEWED_CONSTANTS__','\n\n'.join(parts))
p=r/'overlay/qa/b4-no-bypass/test_evaluated_retention_command_source_closure.py';p.write_text(s)
(r/'reviewed_contract_constants.json').write_text(json.dumps(values,indent=2)+'\n')
print('source QA lines',s.count('\n'))


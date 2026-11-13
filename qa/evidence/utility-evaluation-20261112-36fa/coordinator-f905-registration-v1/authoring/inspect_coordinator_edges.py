#!/usr/bin/env python3
"""Partial changed-source caller inventory using the unchanged lexical engine."""
import copy, importlib.util, json, re, sys, tomllib
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('coordinator_original_predicates',R/'before/scripts/verify_hepta_callers.py')
P=importlib.util.module_from_spec(s);sys.modules[s.name]=P;s.loader.exec_module(P)
old=tomllib.loads((R/'before/CALLERS.toml').read_text())
ignored=tuple(old['ignored_path_fragments'])
index={p.relative_to(R/'view').as_posix():P._strip_cfg_test_items(P._strip_rust_non_code(p.read_text())) for p in (R/'view').rglob('*.rs') if not P._is_ignored(p.relative_to(R/'view').as_posix(),ignored)}
AGENT='codex-rs/hepta-agentd/src/'
definitions=[
 ('OriginalRootInitialGenerationCustodyV1','neuron_generation_initial_root_custody.rs',['from_original_prepared','original_final_use_binding','original_intent_digest','read_original_operation','publish','recover_original']),
 ('OriginalRootInitialGenerationCustodyV1','neuron_generation_initial_root_task.rs',['into_q24_task']),
 ('OriginalRootInitialGenerationCustodyV1','neuron_generation_initial_root_cold.rs',['recover_from_original_current']),
 ('OriginalRootCircuitTaskCustodyV1','neuron_generation_initial_root_task.rs',['read_original_operation','drain_completed_task']),
 ('OriginalRootInitialInstallationErrorV1','neuron_generation_initial_root_task.rs',['original_error','read_original_operation']),
]
new=[];uncertainties=[];fields={}
for owner,file,methods in definitions:
 for method in methods:
  path=AGENT+file
  marker='fn '+method+('<' if method=='into_q24_task' else '(')
  assert marker in index[path]
  if owner not in fields:fields[owner]=P.authority_fields(index,owner)
  observed=[]
  for p,code in sorted(index.items()):
   if p==path:continue
   try:
    if P.has_authority_call(code,owner,method,fields[owner]):observed.append(p)
   except P.UnresolvedTypedReceiver as exc:uncertainties.append({'symbol':owner+'::'+method,'path':p,'error':str(exc)})
  identifier='root_initial_custody_'+re.sub(r'(?<!^)(?=[A-Z])','_',owner).lower()+'_'+method
  new.append({'id':identifier,'symbol':owner+'::'+method,'definition_path':path,'definition_markers':[marker],
              'product_callers':observed,'caller_markers':[],'receiver_type':owner})
coord=json.loads(Path('/tmp/hepta-36fa-coordinator-f905-preparation-v1/SOURCE_PACKET.json').read_text())
changed=[x['path'] for x in coord['source_changes'] if not P._is_ignored(x['path'],ignored)]
old_changes=[]
for row in old['boundary']:
 owner=row.get('receiver_type')
 if owner and owner not in fields:fields[owner]=P.authority_fields(index,owner)
 added=[]
 for path in changed:
  if path==row['definition_path']:continue
  code=index[path]
  try:
   if owner:
    matched=any(P.has_authority_call(code,owner,m,fields[owner]) for m in row.get('receiver_methods',[row['symbol'].split('::')[-1]]))
   else:matched=bool(re.search(row.get('call_pattern',re.escape(row['symbol'])+r'\s*\('),code))
   if matched and path not in row['product_callers']:added.append(path)
  except P.UnresolvedTypedReceiver as exc:uncertainties.append({'symbol':row['symbol'],'path':path,'error':str(exc)})
 if added:old_changes.append({'id':row['id'],'append':added})
result={'format':'hepta-partial-coordinator-boundary-inspection-v1','full_source_scanned':False,'product_view_paths':len(index),
        'changed_product_paths':changed,'new_boundaries':new,'old_boundary_additions':old_changes,'uncertainties':uncertainties,
        'original_scanner_unchanged':True,'ignored_path_fragments':list(ignored),'gate_or_qa_called':False}
(R/'COORDINATOR_BOUNDARIES.draft.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'new_boundaries':len(new),'old_additions':old_changes,'uncertainties':uncertainties},indent=2))

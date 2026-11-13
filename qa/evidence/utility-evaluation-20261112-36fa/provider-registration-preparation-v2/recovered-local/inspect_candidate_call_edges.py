"""Inspect only the frozen changed-file overlay; never claim a full collector run."""
from pathlib import Path
import importlib.util, json, re, sys, tomllib

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('original_hepta_callers', ROOT/'before/scripts/verify_hepta_callers.py')
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)
manifest = tomllib.loads((ROOT/'before/CALLERS.toml').read_text())
boundaries = proof._boundary_rows(manifest)
ignored = tuple(manifest['ignored_path_fragments'])
source_root = ROOT/'candidate'
sources = {str(p.relative_to(source_root)):p.read_text() for p in source_root.rglob('*.rs')}
index = {p:proof._strip_cfg_test_items(proof._strip_rust_non_code(s)) for p,s in sources.items()
         if not proof._is_ignored(p,ignored)}
typed = {}
uncertain, edits = [], []

def observed(symbol,receiver,path,pattern=None,methods=()):
    if receiver:
        if receiver not in typed:
            typed[receiver]=proof.authority_fields(index,receiver)
        fields=typed[receiver]
    result=[]
    for name,code in index.items():
        if name==path:
            continue
        try:
            if receiver:
                match=any(proof.has_authority_call(code,receiver,m,fields)
                          for m in (methods or (symbol.rsplit('::',1)[-1],)))
            else:
                match=bool(re.search(pattern or re.escape(symbol)+r'\s*\(',code))
            if match:
                result.append(name)
        except proof.UnresolvedTypedReceiver as error:
            uncertain.append({'symbol':symbol,'path':name,'error':str(error)})
    return sorted(result)

for b in boundaries:
    actual=observed(b.symbol,b.receiver_type,b.definition_path,b.call_pattern,b.receiver_methods)
    old_touched=sorted(p for p in b.product_callers if p in index)
    if actual!=old_touched:
        edits.append({'id':b.identifier,'symbol':b.symbol,'definition_path':b.definition_path,
                      'old_all_product_callers':list(b.product_callers),
                      'old_touched_product_callers':old_touched,'observed_overlay_callers':actual,
                      'candidate_all_product_callers':sorted((set(b.product_callers)-set(index))|set(actual))})

root_proposal=json.loads((ROOT/'before/ROOT_V1_BOUNDARY_PROPOSAL.json').read_text())
new=[]
for row in root_proposal['new_boundary_candidates']:
    new.append({'id':row['suggested_id'],'symbol':row['symbol'],
                'receiver_type':row['receiver_type'],'definition_path':row['definition_path']})
prefix='codex-rs/hepta-agentd/src/'
for id_,filename,receiver,name in [
 ('learning_original_training_completed_readback_seal','cell_q24_training_shared_readback.rs','OriginalCellQ24TrainingCommandClientV1','seal_original_completed_readback'),
 ('learning_original_evaluation_completed_readback_seal','neuron_cell_evaluation_shared_readback.rs','OriginalCellEvaluationCommandClientV1','seal_original_completed_readback'),
 ('learning_evaluated_retention_readback_owners_seal','circuit_evaluated_retention_context.rs','OriginalCircuitEvaluatedRetentionContextV1','seal_original_readback_owners'),
 ('learning_evaluated_selection_shared_command_create','circuit_evaluated_selection_command_service.rs','OriginalCircuitSelectionCommandOwnerV1','from_original_evaluated_shared_receipt_owner'),
 ('learning_evaluated_selection_shared_command_adapter','circuit_evaluated_selection_command_owner_adapter.rs','OriginalCircuitSelectionReceiptOwnerV1','into_evaluated_shared_command_owner'),
 ('learning_evaluated_next_use_shared_command_create','circuit_evaluated_next_use_command_service.rs','OriginalCircuitNextUseCommandOwnerV1','from_original_evaluated_shared_receipt_owner'),
 ('learning_evaluated_next_use_shared_command_adapter','circuit_evaluated_next_use_remote.rs','OriginalCircuitNextUseReceiptOwnerV1','into_evaluated_shared_command_owner'),
 ('learning_published_shared_original_predecessors_read','circuit_retained_version_shared_readback.rs','OriginalCircuitPublishedEvidenceReadbackV1','read_original_predecessors'),
 ('learning_published_shared_original_context_require','circuit_retained_version_shared_readback.rs','OriginalCircuitPublishedEvidenceReadbackV1','require_original_context'),
 ('learning_published_shared_original_clients_borrow','circuit_retained_version_shared_readback.rs','OriginalCircuitPublishedEvidenceReadbackV1','original_clients'),
 ('learning_version_published_original_readbacks_share','circuit_retained_version_shared_readback.rs','OriginalCircuitRetainedVersionHostV1','share_original_evaluated_readbacks'),
]:
    new.append({'id':id_,'symbol':receiver+'::'+name,'receiver_type':receiver,'definition_path':prefix+filename})
for row in new:
    row['observed_overlay_callers']=observed(row['symbol'],row['receiver_type'],row['definition_path'])
report={'format':'hepta-changed-overlay-caller-inspection-v1','status':'PREPARATION_ONLY_NOT_FULL_COLLECTOR',
        'source_paths':len(sources),'product_paths_in_overlay':len(index),
        'original_boundary_count':len(boundaries),'new_explicit_boundary_candidates':new,
        'existing_edge_candidates':edits,'uncertainties':uncertain,
        'full_source_collector_executed':False,'source_qualification':False,
        'scope':'Only changed-file product source was scanned with the unchanged original scanner. Unchanged caller sets are inherited candidates, not globally reverified observations.'}
(ROOT/'OVERLAY_CALL_EDGE_INSPECTION.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps(report,indent=2,sort_keys=True))

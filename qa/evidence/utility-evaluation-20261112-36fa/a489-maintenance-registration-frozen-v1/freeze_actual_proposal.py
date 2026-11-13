#!/usr/bin/env python3
"""Freeze a bounded, exact four-write proposal against actual c026 source."""
import base64
import copy
import difflib
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tomllib

SOURCE = Path('/tmp/hepta-36fa-a489-maintenance-registration-refresh-v1')
ACTUAL = Path('/tmp/hepta-36fa-a489-actual-maintenance-source-review-v1')
HERE = Path(__file__).resolve().parent
PREFIX = 'a489-maintenance-registration-frozen-v1/'


def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def dump(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def put(name,raw):
    path=HERE/name;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==raw,str(path)
    else:
        with path.open('xb') as f:f.write(raw)
    return {'name':name,'path':PREFIX+name,'local_path':str(path),'chars':len(raw.decode()) if isinstance(raw,bytes) and not name.endswith('.gz') else None,**pin(raw)}


def bundle(name,raw):
    put(name,raw);gz=gzip.compress(raw,mtime=0);put(name+'.gz',gz)
    assert gzip.decompress(gz)==raw
    parts=[]
    for i,offset in enumerate(range(0,len(gz),307200),1):
        block=gz[offset:offset+307200];encoded=base64.b64encode(block)+b'\n'
        row=put(name+'.gz.part-%03d.b64'%i,encoded)
        row.update(decoded_offset=offset,decoded=pin(block));parts.append(row)
    assert all(row['bytes']<=512000 for row in parts)
    assert b''.join(base64.b64decode(Path(row['local_path']).read_bytes().strip(),validate=True)for row in parts)==gz
    return {'raw':pin(raw),'gzip':pin(gz),'parts':parts,'encoding':'gzip.compress(raw,mtime=0), level9; 307200 decoded gzip bytes per canonical base64 plus LF leaf'}


def main():
    bindings=json.loads((SOURCE/'FENCE_PATHS.json').read_bytes())
    assert len(bindings)==7
    inventory_raw=(ACTUAL/'final.inventory.exact_recovered.json').read_bytes()
    assert pin(inventory_raw)=={'bytes':5633323,'sha256':'981e5971d3e8afc2694bcb1951b0261d24f0238675187005ec8e9bb386a07bf1','git_blob':'4a77b645fd76a980ef746997efbd09fcd8f233ba'}
    inventory=json.loads(inventory_raw);rows={r['path']:r for r in inventory['files']}
    spec=importlib.util.spec_from_file_location('freeze_original_pure_merkle',ACTUAL/'inspect_actual_transitions.py')
    pure=importlib.util.module_from_spec(spec);spec.loader.exec_module(pure)
    assert pure.merkle(rows.values())=='c026a8d7e93c958b39a36c666debecb3dba4be14'
    after_rows=copy.deepcopy(rows);changes=[];fullimages=[]
    for binding in bindings:
        path=binding['path'];before=(SOURCE/'before'/path).read_bytes();after=(SOURCE/'after'/path).read_bytes()
        assert pin(before)==binding['before'] and pin(after)==binding['after']
        assert {k:rows[path][k]for k in ('bytes','sha256')}=={k:pin(before)[k]for k in ('bytes','sha256')}
        assert rows[path]['working_blob']==pin(before)['git_blob'] and rows[path]['index_mode']=='100644'
        put('before/'+path,before);put('after/'+path,after)
        fullimages.append({**binding,'before_raw_base64':base64.b64encode(before).decode(),'after_raw_base64':base64.b64encode(after).decode()})
        if before==after:
            assert binding['operation']=='unchanged'
            continue
        assert binding['operation']=='modify' and not path.endswith('.rs')
        new=copy.deepcopy(rows[path]);new.update(bytes=len(after),sha256=pin(after)['sha256'],working_blob=pin(after)['git_blob'])
        new['matches_index']=new['index_blob']==new['working_blob']
        after_rows[path]=new
        changes.append({'path':path,'before':rows[path],'after':new,
                        'before_raw_base64':base64.b64encode(before).decode(),
                        'after_raw_base64':base64.b64encode(after).decode()})
    assert len(changes)==4
    after_tree=pure.merkle(after_rows.values())
    proposed_inventory=pure.exact_inventory(inventory,after_rows)
    assert len(after_rows)==15243
    put('EXPECTED_AFTER_INVENTORY.json',proposed_inventory)
    packet={
        'format':'hepta-reviewed-nonrust-fence-refresh-proposal-v1',
        'status':'HOLD_REVIEWABLE_PROPOSAL_NOT_EXECUTED',
        'source_identity':inventory['source'],
        'base_inventory':pin(inventory_raw),
        'base_physical_tree':'c026a8d7e93c958b39a36c666debecb3dba4be14',
        'expected_after_leaf_count':15243,'expected_after_physical_tree':after_tree,
        'expected_after_inventory':pin(proposed_inventory),
        'actual_maintenance_result':'b87aed7647ac34e3db0e381110bf685438aee0ee',
        'actual_artifacts':'222eb4e2913d62cdd308e2ce26edf7c320ebe47f',
        'actual_transition_packet_raws':{'fix':'1cb4a10f1ca57b4487c4eb03e239d643bf93c0d7','fmt':'fd45c00bc5956ed4de6f666f0c1d509de86f0ac0','final':'88b9299120113937610da4a84b344eda76011674'},
        'all_seven_fence_bindings':bindings,'changes':changes,
        'canonical_source_deletions':[],'source_paths_written_by_preparation':0,
        'Rust_source_changes':0,'qa_or_project_gate_executions':0,'H_calls':0,
        'qualification':False,'execution_approval':False,
        'protocol_note':'Data-only review proposal. A native apply/fmt driver must be separately bound and approved; this file is not a dispatch or an execution approval.'
    }
    packet_bundle=bundle('SOURCE_PACKET.json',dump(packet))
    images_bundle=bundle('ALL_SEVEN_FENCE_IMAGES.json',dump({'format':'hepta-complete-fence-preimages-postimages-v1','files':fullimages}))
    # Exact before/after images for all seven fences are losslessly present above;
    # the actual mutation set contains only four paths.
    reg= json.loads((SOURCE/'REGISTRATION_REFRESH_REVIEW.json').read_bytes())
    a=tomllib.loads((SOURCE/'before/CALLERS.toml').read_text());b=tomllib.loads((SOURCE/'after/CALLERS.toml').read_text())
    extras=[]
    for index,(old,new)in enumerate(zip(a['protected_file'],b['protected_file'])):
        for j,(x,y)in enumerate(zip(old.get('required_function_order',[]),new.get('required_function_order',[]))):
            for key in ('top_level','literal_calls'):
                if x.get(key)!=y.get(key):extras.append([index,j,key])
    assert not extras and a['boundary']==b['boundary']
    fix_rationales={
      'cell_q24_training_shared_readback_support_tests.rs':'The poisoned Mutex error closure is replaced by the identical PoisonError::into_inner method item; release/notify and poison recovery behavior are retained.',
      'circuit_evaluated_same_host_sc_connections_tests.rs':'Removes an identity anyhow::Error::from conversion before the same context operation. The dataset is still dropped and the same original peer cleanup is attempted before returning the original error.',
      'circuit_evaluated_same_host_sc_support_tests.rs':'Two nested take/finish error conditions become left-to-right short-circuit let chains. Each Option is still consumed once, each held resource is finished once, all recorded errors remain collected.',
      'circuit_evaluated_version_local_readback_tests.rs':'The same task.take and !consumed_join condition become a let chain. Abort, awaiting the original handle, cancelled JoinError handling and the subsequent original-terminal observation are unchanged.',
      'circuit_evaluated_version_next_use_readback_tests.rs':'Equivalent fixture take/finish let chain and Boolean observed == !already_expired to observed != already_expired. The two Boolean truth values, original deadline assertions and cell/source observations are preserved.',
      'circuit_evaluated_version_shared_export_tests.rs':'Equivalent fixture take/finish let chain; all held peer cleanup results remain aggregated and the original refusal/current assertions are retained.',
      'circuit_evaluated_version_shared_readback_tests.rs':'Two Option::map closures become the identical consuming JoinHandle::join method item; both original handles are still taken and joined before collecting errors.',
      'circuit_learning_local_read.rs':'Only a cfg(test) pause hook combines response.is_ok and the same Some(terminal) condition. The original production exchange, 128 counter, absolute end, slot ownership and actual response authentication remain unchanged.',
      'circuit_resident_candidate_first_material_tests.rs':'Two last-use JSON/byte Vec clones become ownership moves. Negative payload construction and every rejection check remain; no owner, FD, opaque grant or Source capability is cloned or created.',
      'circuit_resident_candidate_provider_material_control_tests.rs':'Two last-use JSON/byte Vec clones become ownership moves. Original changed-freeze-payload, trailing-byte and oversize negative inputs and all assertions remain.',
      'circuit_resident_candidate_provider_publication_support_tests.rs':'Equivalent stages.take/finish let chain; original staged peer cleanup still occurs once before retained home handles are dropped and aggregated errors are returned.',
      'circuit_resident_candidate_provider_stage_support_tests.rs':'Three equivalent panel/training-peer/original take+finish let chains. The original consumer close, held-client drops, server joins and remaining cleanup ordering are preserved.'
    }
    lexical=json.loads((ACTUAL/'ACTUAL_BYTE_AND_LEXICAL_REVIEW.json').read_bytes())
    fix=next(x for x in lexical['transitions']if x['stage']=='fix.after')
    fmt=next(x for x in lexical['transitions']if x['stage']=='fmt.after')
    assert len(fix_rationales)==len(fix['rows'])==12
    assert all(r['literal_sequences_equal'] and r['comments_exact_equal']for stage in lexical['transitions']for r in stage['rows'])
    semantic={
        'format':'hepta-actual-a489-scoped-fix-format-author-semantic-review-v1',
        'status':'NO_CONCRETE_SEMANTIC_BLOCKER_IDENTIFIED_IN_ACTUAL_DIFF',
        'actual_result':'b87aed7647ac34e3db0e381110bf685438aee0ee',
        'byte_and_lexical_report':pin((ACTUAL/'ACTUAL_BYTE_AND_LEXICAL_REVIEW.json').read_bytes()),
        'fix_files':[{'path':r['path'],'before':r['before'],'after':r['after'],'reason':fix_rationales[Path(r['path']).name]}for r in fix['rows']],
        'format_files':14,'format_files_with_exact_tokens':sum(r['tokens_exact_equal']for r in fmt['rows']),
        'format_remaining_changes':{
            'optional_trailing_comma_hunks':23,
            'import_order_only_files':['neuron_generation_initial_root_cold_tests.rs','neuron_generation_initial_root_custody_support_tests.rs'],
            'three_tail_expression_closure_blocks':'The same OpenOptions::open, FileAnchorWitnessStore::open and anyhow error expressions are wrapped as block tail expressions; no added statement, async boundary, operation, capture, value or error mapping.',
            'comma_contexts':'Only original function/method argument and parameter lists, struct/variant expressions and pattern fields, and an array literal. No singleton tuple meaning or custom macro token grammar is changed.'
        },
        'all_literal_and_comment_sequences_equal':True,
        'all_17_actual_paths_read_and_chained':True,
        'qualification':False,'tests_or_source_gates_run_by_review':0,'H_calls':0,
        'limits':['Static source review is separate from the actual two maintenance return codes; no Rust tests or full source qualification have run on these final bytes.',
                  'Existing timeout/cancellation and lack of ordinary Root startup integration limits are preserved. This refresh supplies no real A/B/C task chain.',
                  'The original fix101 failure in the earlier source attempt is retained; this new single scoped fix success does not rewrite that historical result.']
    }
    semantic_row=put('SEMANTIC_REVIEW.json',dump(semantic))
    summary={
        'format':'hepta-actual-c026-nonrust-fence-author-review-v1',
        'status':'FROZEN_REVIEWABLE_PROPOSAL_PENDING_INDEPENDENT_REVIEW_AND_EXECUTION_APPROVAL',
        'base_physical_tree':packet['base_physical_tree'],'expected_after_physical_tree':after_tree,
        'base_inventory':pin(inventory_raw),'expected_after_inventory':pin(proposed_inventory),
        'actual_rust_sources_preserved':True,'all_non_update_graph_entries_preserved':True,'complete_graph_entries':15243,'unchanged_non_update_entries':15239,
        'seven_fences':bindings,'modified_path_count':4,'unchanged_fence_count':3,
        'changed_protected_rows':[r['row']for r in reg['guard_changes']],
        'changed_marker_values':sum(len(r['replacements'])for r in reg['guard_changes']),
        'all_633_boundaries_and_required_ids_unchanged':True,
        'all_442_forbidden_arrays_and_extra_top_level_literal_constraints_unchanged':True,
        'duplicate_protection_paths_and_row_order_preserved':True,'no_path_deduplication':True,
        'provider_paths':45,'provider_scopes':288,'changed_provider_scope_digests':len(reg['provider_scope_updates']),
        'provider_module_shape_changes':len(reg['module_shape_updates']),
        'ordinary_scopes':34,'ordinary_literals':17,'ordinary_scope_changes':len(reg['ordinary_scope_updates']),
        'all_107_original_attacks_same_target_counts':True,
        'qa_files':64,'qa_methods':607,'all_method_bodies_byte_equal':True,
        'root_parents':48,'workflow_and_root_QA_bytes_unchanged':True,
        'source_roots_ignored_paths_authority_budgets_filters_unchanged':True,
        'source_packet':packet_bundle['raw'],'all_seven_images':images_bundle['raw'],
        'semantic_review':{k:semantic_row[k]for k in ('bytes','sha256','git_blob')},
        'native_maintenance_and_gates':'Await separately approved exact four-write apply plus original fmt900. No fix replay, no test/gate claim.',
        'source_or_ref_mutations':0,'H_calls':0,'qualification':False
    }
    core=put('REVIEW.json',dump(summary))
    copied=[]
    for name in ['REGISTRATION_REFRESH_REVIEW.json','FENCE_PATHS.json','SOURCE_DELTA.patch','BASELINE_COMPLETE_BINDINGS.json','refresh_actual_fences.py','prepare_baseline.py']:
        copied.append(put(name,(SOURCE/name).read_bytes()))
    lexical_bundle=bundle('ACTUAL_BYTE_AND_LEXICAL_REVIEW.json',(ACTUAL/'ACTUAL_BYTE_AND_LEXICAL_REVIEW.json').read_bytes())
    inspect=put('inspect_actual_transitions.py',(ACTUAL/'inspect_actual_transitions.py').read_bytes())
    serializer_note=put('LOCAL_SERIALIZER_ATTEMPT_01.json',(ACTUAL/'LOCAL_SERIALIZER_ATTEMPT_01.json').read_bytes())
    manifest={
        'format':'hepta-bounded-actual-maintenance-fence-proposal-manifest-v1',
        'status':'HOLD_NOT_EXECUTED','prefix':PREFIX,
        'base_physical_tree':packet['base_physical_tree'],'expected_after_physical_tree':after_tree,
        'leaf_count':15243,'source_packet':packet_bundle,'all_seven_fence_images':images_bundle,
        'actual_byte_and_lexical_evidence':lexical_bundle,'fence_bindings':bindings,
        'review':{k:core[k]for k in ('bytes','sha256','git_blob')},
        'unchanged_reference_controls':{'workflow':bindings[1]['after'],'root_QA':bindings[-1]['after'],'ordinary_QA':bindings[-3]['after']},
        'readme_status':'All Rust bytes here are the actual native postimages. Four nonRust edits are a new unexecuted proposal; original complete qualification remains required.',
        'source_or_ref_mutations':0,'H_calls':0,'qualification':False,
        'leaf_limit':512000
    }
    manifest_row=put('MANIFEST.json',dump(manifest))
    payloads=[core,semantic_row,manifest_row,inspect,serializer_note]
    payloads.extend(r for r in copied if r['bytes']<=512000)
    for data in [packet_bundle,images_bundle,lexical_bundle]:payloads.extend(data['parts'])
    # Actual final inventory is independently recoverable with original format
    # parts in the source-review directory, and is not recast as another native read.
    payloads.append(put('ACTUAL_INVENTORY_RECOVERY_REFERENCE.json',dump({
        'actual_artifacts':'222eb4e2913d62cdd308e2ce26edf7c320ebe47f',
        'actual_inventory':pin(inventory_raw),'not_a_second_native_read':True,
        'local_exact_raw':str(ACTUAL/'final.inventory.exact_recovered.json'),
        'original_parts_directory':str(ACTUAL/'final-inventory-parts'),
        'actual_alias_proof':lexical['inventory_artifact_aliases']})))
    payloads.append(put('freeze_actual_proposal.py',Path(__file__).read_bytes()))
    assert len({r['path']for r in payloads})==len(payloads)
    assert all(r['bytes']<=512000 for r in payloads)
    index=put('ARCHIVE_INPUT_INDEX.json',dump({'format':'hepta-bounded-proposal-archive-index-v1','count':len(payloads),'entries':payloads}))
    print(json.dumps({'review':core,'manifest':manifest_row,'source_packet':packet_bundle['raw'],'parts':packet_bundle['parts'],
                      'all_images':images_bundle['raw'],'expected_after_tree':after_tree,
                      'expected_after_inventory':pin(proposed_inventory),'archive_payloads':len(payloads),'archive_index':index},indent=2))


if __name__=='__main__':
    main()

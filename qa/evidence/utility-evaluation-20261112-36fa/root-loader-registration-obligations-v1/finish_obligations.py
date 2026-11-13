"""Pure reviewer metadata; no project collector, Rust, author code, H or edits."""
from pathlib import Path
import ast
import collections
import hashlib
import json
import re
import tomllib

OUT = Path('/tmp/hepta-36fa-root-loader-registration-obligations-v1')
ROOT = Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1')
SEED = Path('/tmp/hepta-36fa-root-registration-union-seed-v1/CALLERS_E1_E3_E2_SEED.toml')
LEX = Path('/tmp/hepta-36fa-e2-registration-independent-review-v1/review_bytes_v2.py')


def pin(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                git_blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())


def check(raw, expected):
    actual = pin(raw)
    assert actual == {key: expected[key] for key in actual}
    return actual


def strict(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_bytes(), object_pairs_hook=strict)


def save(name, value):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2)+'\n').encode()
    path = OUT / name
    with path.open('xb') as stream:
        stream.write(raw)
    assert path.read_bytes() == raw and len(raw) <= 512000
    return dict(path=str(path), **pin(raw))


def main():
    original = read(OUT / 'DECLARATION_EXTRACTION.preparation.json')
    assert pin((OUT / 'DECLARATION_EXTRACTION.preparation.json').read_bytes())['git_blob'] == 'a2ca14fd16af6338013ea555e66e8c9f14556109'
    functions = original['new_declarations']
    assert len(functions) == 45
    files = {}
    for layer in original['layers']:
        path = Path(layer['path'])
        check(path.read_bytes(), layer)
        packet = read(path)
        for entry in packet.get('entries', packet.get('images')):
            after = entry.get('after_utf8', entry.get('after'))
            assert isinstance(after, str)
            if isinstance(entry.get('after'), dict):
                check(after.encode(), entry['after'])
            files[entry['path']] = after
    assert len(files) == 17
    own_ast = ast.parse(LEX.read_text())
    selected = [n for n in own_ast.body if isinstance(n, ast.FunctionDef)
                and n.name in {'rust_code', 'balanced', 'declarations'}]
    namespace = {'re': re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(LEX), 'exec'), namespace)
    declarations, mask = namespace['declarations'], namespace['rust_code']
    for f in functions:
        body = files[f['path']]
        check(body.encode(), f['source_pin'])
        check(f['body'].encode(), f['body_pin'])
        found = [d for d in declarations(body) if d['impl_header'] == f['impl_header']
                 and d['name'] == f['name'] and d['visibility'] == f['visibility']]
        assert len(found) == 1 and found[0]['body'] == f['body']

    # Each relation is manually resolved from the exact imported receiver/field
    # type, not merely a shared method name. Needles are checked in that caller.
    incoming = {
        0:[(6,'files::require_descriptors(')],
        1:[(6,'files::require_artifact_directory(')],
        2:[(6,'files::require_existing_consumer(')],
        3:[(1,'require_private_child('),(2,'require_private_child(')],
        4:[(1,'open_private('),(2,'open_private(')],
        5:[(0,'require_private_file('),(1,'require_private_file('),(2,'require_private_file('),(4,'require_private_file(')],
        6:[(16,'HostAuthorityService::load_original_initial_generation_inputs('),(17,'HostAuthorityService::load_original_initial_generation_inputs(')],
        7:[(6,'require_before(')],
        8:[(9,'map(SignerFile::original)')],
        9:[(6,'value.artifacts.trust.original()')],
        10:[(6,'value.artifacts.writer_lease.original()')],
        11:[(6,'value.artifacts.required_current_head.original()')],
        12:[(6,'value.artifacts.withdrawal_snapshot.original()')],
        13:[(6,'value.selection.trust.original()')],
        14:[(6,'value.selection.signed.original()')],
        15:[(10,'signature(self.signature)'),(11,'signature(self.signature)'),(14,'signature(self.signature)')],
        16:[],17:[],
        18:[(25,'OriginalTaskClockStatus::new(end)')],
        19:[(25,'callback_status.record_original_error(error)')],
        20:[(25,'callback_status.record_overflow()')],
        21:[(19,'self.record(code)'),(20,'self.record(4)'),(22,'self.record(5)')],
        22:[(25,'callback_status.require_healthy()'),(25,'clock_status.require_healthy()'),(40,'self.clock_status.require_healthy()'),(41,'self.clock_status.require_healthy()')],
        23:[(25,'files::require_descriptors(')],
        24:[(23,'require_one(')],
        25:[(44,'HostAuthorityService::load_original_root_q24_task_inputs(')],
        26:[(25,'require_before(')],
        27:[(25,'fenced_time()')],
        28:[(25,'value.source_witness.scope()'),(25,'value.cell_witness.scope()')],
        29:[(25,'value.source_witness.generation()'),(25,'value.cell_witness.generation()')],
        30:[(25,'value.source.into_original()')],
        31:[(25,'value.fence.into_original()')],
        32:[(25,'map(types::Route::into_original)')],
        33:[(25,'value.bundle.into_original()')],
        34:[(25,'value.definition.into_original()')],
        35:[(34,'map(Candidate::into_original)')],
        36:[(34,'self.runtime.into_original()')],
        37:[(36,'self.calibration.into_original()')],
        38:[(36,'self.resource_envelope.into_original()')],
        39:[(34,'self.native.into_original()')],
        40:[],41:[(40,'self.require_original_result(result)')],
        42:[],43:[],
        44:[(42,'self.load_original_task_files('),(43,'self.load_original_task_files(')],
    }
    assert set(incoming) == set(range(45))
    public = {16,17,40,42,43}
    service = {6,25}
    assembly = {44}
    file_guards = set(range(6)) | {23,24}
    clock_guards = set(range(18,23)) | {27,41}
    time_guards = {7,26}
    pure = set(range(45)) - public - service - assembly - file_guards - clock_guards - time_guards
    assert len(pure) == 20
    classifications = [
        (public,'PUBLIC_PRIVILEGED_ENTRY_BOUNDARY'),
        (service,'CRATE_PRIVILEGED_ORIGINAL_OWNER_LOADER_BOUNDARY'),
        (assembly,'PRIVATE_READY_PHASE_ASSEMBLY_BOUNDARY_OR_EXACT_SCOPE_GUARD'),
        (file_guards,'PRIVATE_PROTECTED_INPUT_IO_GUARD'),
        (clock_guards,'PRIVATE_PERMANENT_CLOCK_FENCE_GUARD'),
        (time_guards,'PRIVATE_ABSOLUTE_DEADLINE_GUARD'),
        (pure,'DATA_ONLY_CONVERSION_EXACT_MODULE_GUARD'),
    ]
    table=[]
    for index, f in enumerate(functions):
        callers=[]
        for source_index, needle in incoming[index]:
            caller = functions[source_index]
            assert needle in caller['body'], (index, source_index, needle)
            locations=[]
            at=0
            while True:
                at=caller['body'].find(needle,at)
                if at<0: break
                absolute=caller['start']+at
                locations.append(dict(line=files[caller['path']][:absolute].count('\n')+1,
                                      utf8_byte_offset=len(files[caller['path']][:absolute].encode())))
                at+=len(needle)
            callers.append(dict(declaration_index=source_index,path=caller['path'],
                                method=caller['name'],receiver=caller['impl_header'],
                                exact_expression=needle,locations=locations,
                                source_pin=caller['source_pin']))
        item={k:v for k,v in f.items() if k not in ['body','start','end']}
        item.update(declaration_index=index, receiver=f['impl_header'],
                    classification=next(label for indices,label in classifications if index in indices),
                    incoming_exact_layer_relations=callers,
                    relation_status='MANUALLY_TYPED_WITH_EXACT_EXPRESSION_AND_SOURCE_PIN',
                    root_registry_edited=False)
        if index in public:
            # Neither layer has its eventual third-layer CLI call. Do not
            # silently invent it or combine an unfrozen integration view.
            occurrences=[]
            for path,body in files.items():
                for match in re.finditer(r'\b'+re.escape(f['name'])+r'\s*\(',mask(body)):
                    occurrences.append(dict(path=path,line=body[:match.start()].count('\n')+1))
            assert len(occurrences)==1 and occurrences[0]['path']==f['path']
            item['product_callers_within_fixed_two_layers']=[]
            item['future_cli_caller']='OUT_OF_SCOPE_NOT_FROZEN_IN_THESE_TWO_PACKETS'
        table.append(item)

    seed_raw=SEED.read_bytes()
    assert pin(seed_raw)['git_blob']=='1b55bc0cc5be4d47b7273f3c451f2eeff02fc542'
    seed=tomllib.loads(seed_raw.decode())
    rows=seed['boundary']
    assert len(rows)==757
    wanted={
        (634,'prepare_original_initial_generation_from_files'),
        (635,'recover_original_initial_generation_from_files'),
        (666,'read_loaded_original_root_task_generation'),
        (624,'load_original_task_files'),
        (640,'load_original_task_files'),
        (669,'load_original_task_files'),
    }
    confirmed=[];rejected=[]
    for candidate in original['old_boundary_lexical_candidates']:
        key=(candidate['boundary_index'],candidate['caller_method'])
        if key in wanted:
            assert all(candidate['symbol'] in x['text'] for x in candidate['lexical_occurrences'])
            assert candidate['already_registered_path'] is False
            record=dict(candidate)
            record['status']='CONFIRMED_EXPLICIT_RECEIVER_NEW_CALLER_IN_FIXED_TWO_LAYERS'
            record['original_boundary_row']=rows[candidate['boundary_index']]
            record['required_change']='Append this exact product caller path/markers; preserve every existing row field and caller.'
            confirmed.append(record)
        else:
            assert not any(candidate['symbol'] in x['text'] for x in candidate['lexical_occurrences'])
            item=dict(candidate)
            item['status']='REJECTED_SAME_METHOD_NAME_WITH_DIFFERENT_EXPLICIT_RECEIVER_OR_NEW_DECLARATION'
            rejected.append(item)
    assert len(confirmed)==6 and len(rejected)==367
    assert sum(len(c['lexical_occurrences']) for c in confirmed)==8
    external = []
    # These true original APIs are not entries in the frozen 757-row boundary
    # table. They are listed for Root's classification rather than adding
    # misleading callers to a similarly named low-level receiver.
    calls = {
      6:['read_root_json(deployment)', 'ArtifactSelectionVerifierV1::new(',
         'read_dataset_withdrawal_snapshot(', 'LearningArtifactOwnerService::open(',
         'AgentdSelectedGenerationV1::load(', 'self.clock.now_unix_ms()',
         'self.issuer.trust_key()', 'self.issuer.revocations()',
         'HostAuthorityFrontierStore::<FinalUseFrontier>::open(', 'frontier.load(&owner_id)',
         'FinalUseAuthority::open_state_dir_with_trust(',
         'FinalUseAuthority::open_state_dir_with_issuer_keys(',
         'final_use.current_external_frontier()', 'final_use.revocation_head()',
         'CellGenerationOwnerBindingV1::new(', 'FileAnchorWitnessStore::open('],
      25:['read_root_json(deployment)', 'self.clock.now_unix_ms()',
          'LoadedCellQ24ModelV1::open_files(model)', 'model.components()',
          'FileAnchorWitnessStore::open(', 'DurableInferenceControl::open_file(',
          'original_clock.now_unix_ms()'],
      16:['require_original_session(&self, end)'],
      17:['require_original_session(&self, end)'],
      44:['require_original_session(&self.session, self.end)'],
      1:['RootAuthorityDirectory::open('],
      3:['RootAuthorityDirectory::open('],
      4:['RootAuthorityDirectory::open('],
    }
    for idx, needles in calls.items():
        f=functions[idx]
        for needle in needles:
            assert needle in f['body']
            positions=[m.start() for m in re.finditer(re.escape(needle),f['body'])]
            external.append(dict(caller_declaration_index=idx,caller_path=f['path'],caller_method=f['name'],
                                 receiver=f['impl_header'],exact_expression=needle,
                                 lines=[files[f['path']][:f['start']+p].count('\n')+1 for p in positions],
                                 source_pin=f['source_pin'],
                                 classification='EXISTING_ORIGINAL_API_CALL_FOR_ROOT_REVIEW_NOT_A_NEW_757_ROW_EDGE'))
    evidence=dict(format='hepta-first-two-loader-registration-obligations-v1',
                  scope='Only exact e78f0413 and 77b05d5e, composed 17 complete paths; excludes later CLI, Material and prefreeze layers.',
                  not_a_collector_result=True, H_calls=0,project_execution=False,
                  source_registry_ref_writes=False,
                  source_packets=original['layers'],seed=dict(path=str(SEED),**pin(seed_raw)),
                  declarations=table,classification_counts={label:len(ids) for ids,label in classifications},
                  old_boundary_additions=confirmed,old_edge_count=6,old_callsite_count=8,
                  rejected_same_name_candidate_count=len(rejected),
                  rejected_same_name_candidates=rejected,
                  other_original_api_calls=external,
                  private_module_guards=[dict(path=path,**pin(body.encode())) for path,body in files.items()
                    if any(f['path']==path for f in functions)],
                  required_module_shape='Protect all ten new modules including declarations, fields, imports, visibility and tail; whole-body substring guards alone do not exclude extra impl/getter or clock escape.',
                  original_757_rows_not_modified=True,
                  type_resolution_limit='Manual receiver resolution plus frozen imports/struct fields; no rustc, compiler typecheck or project caller collector ran.')
    print(json.dumps(save('REGISTRATION_OBLIGATIONS.json',evidence)))


if __name__=='__main__':
    main()

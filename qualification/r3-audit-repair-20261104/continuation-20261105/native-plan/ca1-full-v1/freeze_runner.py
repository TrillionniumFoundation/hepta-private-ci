"""Cloud-only deterministic derivation; it does not execute the native runner."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / 'ai395-c1-after-memory-stop-v1/c1-resume-candidate-v1/run_c1_resume.py'
old = PARENT.read_text()
new = old


def replace(before, after):
    global new
    assert new.count(before) == 1, before[:120]
    new = new.replace(before, after)


replace('"""Resume only the original seven helper build on unchanged ai395 e78.\n\nC0 and its memory-gate failure are immutable parents. No source mutation,\nmetadata, catalog, tests, hygiene, B-driver access, or automatic C2 launch.\n"""',
'''"""Continue prepared Core source to the published candidate, then the original full gate.

Only the reviewed12-file e78-to-ca1 transition, seven helpers and default full
metadata/catalog/just-test recipe run. No hygiene, qualification feature scope,
old B-driver access, source reset, resource relaxation or automatic retry.
"""''')
replace("OUT = ROOT / 'c1-resume-e78-v1'", "OUT = ROOT / 'candidate-default-full-v1'")
new = new.replace('CANDIDATE_TREE', 'INITIAL_TREE')
replace("INITIAL_TREE = 'e78c819b8b1f435f8b37bea17b4ffdc724961aa2'",
        "INITIAL_TREE = 'e78c819b8b1f435f8b37bea17b4ffdc724961aa2'\nFINAL_TREE = 'ca1c4671ef6b2773280d01b5d76c6166252f5856'\nPUBLICATION_COMMIT = 'eed4d6bb61b789b19f60facc79f9e031765fa4c9'")
replace('def main(request, raw_request):', (HERE / 'new_stage_functions.py.txt').read_text() + 'def main(request, raw_request):')
replace("terminal = {'schema': 'ai395-core-C1-only-resume-terminal-v1'", "terminal = {'schema': 'ai395-core-candidate-default-full-terminal-v1'")
replace("'scope': 'Only the original seven normal helpers on unchanged e78; no C0 replay or C2 continuation.'}",
        "'scope': 'Reviewed source transition, original seven helpers and default complete workspace gate only.',\n                'full_gate': 'NOT_STARTED', 'hygiene': 'NOT_STARTED',\n                'qualification_feature_scope': 'NOT_STARTED_SEPARATE_REVIEW_REQUIRED'}")
replace("need(request['stage'] == 'C1_ONLY_UNCHANGED_E78', 'fixed C1-only stage')",
        "need(request['stage'] == 'PUBLISHED_CANDIDATE_C1_DEFAULT_FULL', 'fixed candidate/full stage')")
replace("need(request['idempotency_key'] == 'hepta-ai395-core-c1-resume-e78-20261105-v1', 'fixed new C1 key')",
        "need(request['idempotency_key'] == 'hepta-ai395-core-candidate-ca1-full-20261105-v1', 'fixed new candidate key')")
anchor="        parent_request_raw = pinned(PARENT_OUT / 'execution-request.json', request['parent_request'])"
replace(anchor, '''        latest_raw = pinned(ROOT / 'c1-resume-e78-v1/C1-resume-terminal.json', request['latest_C1_terminal'])
        latest = json.loads(latest_raw)
        need(latest['state'] == 'C1_STOPPED_AT_ACTUAL_FAILURE'
             and latest['controller_exit_code'] == 1 and latest['build_commands'] == []
             and 'cold build memory prerequisite' in latest['error']
             and latest['source_expected_at_stop'] == INITIAL_TREE,
             'latest actual C1 memory stop, not a compile failure or retry result')
        latest_guard_raw = pinned(ROOT / 'c1-resume-e78-v1/C1-resume-final-source-guard.json',
                                  request['latest_C1_source_guard'])
        latest_guard = json.loads(latest_guard_raw)
        need(latest_guard == latest['final_source_guard']
             and latest_guard['source_tree'] == INITIAL_TREE
             and latest_guard['ordinary_head'] == PRODUCT_COMMIT
             and latest_guard['ordinary_index'] == parent_guard['ordinary_index']
             and latest_guard['locks'] == parent_guard['locks']
             and latest_guard['unexpected_untracked'] == [], 'latest physical source continuity')
        latest_prerequisites_raw = pinned(ROOT / 'c1-resume-e78-v1/prerequisites-final.json',
                                          latest['final_prerequisites'])
''' + anchor)
new = new.replace("request['current_readonly_observation']", "request['historical_readonly_observation']")
anchor="        environment = os.environ.copy()"
replace(anchor, '''        stage_inputs, stage_raw = decode_stage_inputs(request['candidate_inputs'])
        final_candidate, decoded_changes = bind_candidate(candidate, stage_inputs, tree_hash)
        historical = stage_inputs['historical_graph_reference']
        original_reference = inputs['historical_full_metadata']
        need(historical['source_directory'] == original['plan']['source_directory']
             and historical['raw_metadata_identity']['bytes'] == original_reference['bytes']
             and historical['raw_metadata_identity']['sha256'] == original_reference['sha256']
             and historical['source_tree'] == original_reference['source_tree'],
             'historical raw metadata provenance remains original, not current-host qualification')
        graph_raw = (json.dumps(historical['graph'], sort_keys=True, separators=(',', ':')) + '\\n').encode()
        need(identity(graph_raw) == historical['graph_identity'], 'complete historical graph bytes')
        need(len(historical['graph']['workspace_members']) == 193
             and len(historical['graph']['nodes']) == 1501, 'complete original graph dimensions')
        need(len(inputs['full_roster']) == 19563, 'original complete default workspace roster')
''' + anchor)
replace("        save('one-shot-readonly-observation.original.json', observation_raw)",
'''        save('historical-readonly-observation.original.json', observation_raw)
        save('prior-C1-resource-stop.original.json', latest_raw)
        save('prior-C1-final-source-guard.original.json', latest_guard_raw)
        save('prior-C1-final-prerequisites.original.json', latest_prerequisites_raw)
        save('candidate-stage-inputs.json', stage_raw)
        save('historical-full-graph.json', graph_raw)''')
new = new.replace('class ResumeRunner(Base):', 'class CandidateRunner(Base):')
new = new.replace('runner = ResumeRunner.__new__(ResumeRunner)', 'runner = CandidateRunner.__new__(CandidateRunner)')
replace("        runner.source_guard('C1-resume-entry')", "        runner.source_guard('candidate-stage-entry-e78')")
replace("capacity('C1-resume-entry', PHASE_FREE, memory_required=True)", "capacity('candidate-stage-entry', PHASE_FREE, memory_required=True)")
anchor="        row = runner.command('cold-normal-seven-helpers', original['plan']['phases'][3]['commands'][0])"
replace(anchor, '''        apply_candidate(runner, final_candidate, decoded_changes, tree_hash)
        terminal['published_commit'] = PUBLICATION_COMMIT
        terminal['published_working_tree'] = FINAL_TREE
        terminal['ordinary_checkout_HEAD_retained'] = PRODUCT_COMMIT
''' + anchor)
start=new.index("        final_guard = runner.source_guard('C1-build-complete')")
end=new.index('    except BaseException as error:',start)
new=new[:start]+'''        runner.source_guard('C1-current-candidate-build-complete')
        terminal['C1_helpers'] = file_record(OUT / 'normal-seven-helper-receipt.json')
        fullphase = original['plan']['phases'][5]
        metadata_row = runner.command('candidate-full-metadata', fullphase['commands'][0])
        need(metadata_row['exit_code'] == 0, 'complete metadata command failed')
        metadata = json.loads(Path(metadata_row['stdout']['path']).read_bytes())
        need(metadata['workspace_root'] == str(SOURCE / 'codex-rs'), 'actual metadata workspace path')
        actual_graph = namespace['graph'](metadata)
        need(normalized_graph(actual_graph, str(SOURCE)) ==
             normalized_graph(historical['graph'], historical['source_directory']),
             'whole193/1501 feature/dependency graph differs beyond explicit source-directory IDs')
        need(sorted(metadata['workspace_default_members']) == sorted(metadata['workspace_members']),
             'default members narrow the complete workspace')
        graph_receipt = {'source_tree': runner.expected_tree, 'command': metadata_row,
                         'historical_raw_metadata': historical['raw_metadata_identity'],
                         'historical_source_tree': historical['source_tree'],
                         'historical_graph_identity': historical['graph_identity'],
                         'normalization': {'old_source': historical['source_directory'],
                                           'new_source': str(SOURCE),
                                           'only_fields': ['workspace_members', 'nodes.id', 'nodes.deps.pkg']},
                         'members': len(metadata['workspace_members']), 'nodes': len(metadata['resolve']['nodes']),
                         'full_resolve_projection_equal': True}
        save_json('metadata-binding.json', graph_receipt)
        _, selection = runner.catalog('full-workspace-catalog', fullphase['commands'][1],
                                      artifacts, inputs['full_roster'])
        terminal['full_gate'] = 'RUNNING_ORIGINAL_DEFAULT_WORKSPACE'
        full = runner.nextest('original-full-workspace', fullphase['commands'][2], selection)
        terminal['full_gate'] = 'PASS' if full['suite_passed'] else 'NONPASS'
        terminal['full_result'] = {'review': file_record(OUT / 'original-full-workspace-review.json'),
                                   'counts': full['counts'], 'retries': full['retries'],
                                   'ignored': full['original_ignored_count'],
                                   'observed_early_return_candidates': len(full['raw_early_return_candidates']),
                                   'qualification_limit': 'JUnit/command results are separate from behavior omitted by observed early returns.'}
        terminal['state'] = 'DEFAULT_FULL_TERMINAL_ROOT_REVIEW_REQUIRED'
        code = 0 if full['suite_passed'] else 1
''' + new[end:]
replace("terminal.update({'state': 'C1_STOPPED_AT_ACTUAL_FAILURE'", "terminal.update({'state': 'CANDIDATE_STAGE_STOPPED_AT_ACTUAL_FAILURE'")
replace("            terminal['build_commands'] = runner.commands", '''            terminal['commands'] = runner.commands
            terminal['build_commands'] = [row for row in runner.commands if row['label'] == 'cold-normal-seven-helpers']
            terminal['metadata_executed'] = sum(row['label'] == 'candidate-full-metadata' for row in runner.commands)
            terminal['catalogs_executed'] = sum(row['label'] == 'full-workspace-catalog' for row in runner.commands)
            terminal['tests_executed'] = sum(row['label'] == 'original-full-workspace' for row in runner.commands)
            terminal['source_mutations'] = runner.transitions''')
replace("runner.source_guard('C1-resume-final')", "runner.source_guard('candidate-default-full-final')")
replace("                terminal['final_guard_error'] = repr(error)\n                code = 1", '''                terminal['final_guard_error'] = repr(error)
                terminal['scope_conclusion_before_final_guard_failure'] = terminal['full_gate']
                terminal['full_gate'] = 'OPEN_FINAL_GUARD_FAILURE'
                code = 1''')
replace("capacity('C1-resume-final', PHASE_FREE, memory_required=True)", "capacity('candidate-default-full-final', PHASE_FREE, memory_required=True)")
replace("                terminal['final_input_or_capacity_error'] = repr(error)\n                code = 1", '''                terminal['final_input_or_capacity_error'] = repr(error)
                terminal['scope_conclusion_before_final_input_or_capacity_failure'] = terminal['full_gate']
                terminal['full_gate'] = 'OPEN_FINAL_INPUT_OR_CAPACITY_FAILURE'
                code = 1''')
replace("save_json('C1-resume-terminal.json', terminal)", "save_json('candidate-default-full-terminal.json', terminal)")
replace("print(json.dumps({'C1_resume_terminal': terminal}), flush=True)", "print(json.dumps({'candidate_default_full_terminal': terminal}), flush=True)")

ast.parse(new)
common=['need','now','identity','stat_id','read_stable','pinned','file_record','absent','capacity','verify_prerequisites','save','save_json']
def functions(source):
    return {node.name:ast.get_source_segment(source,node) for node in ast.parse(source).body if isinstance(node,ast.FunctionDef)}
a,b=functions(old),functions(new)
assert all(a[name]==b[name] for name in common)
with (HERE/'run_candidate_default_full.py').open('x') as stream:stream.write(new)
delta=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='reviewed-C1/run_c1_resume.py',tofile='candidate/run_candidate_default_full.py'))
with (HERE/'C1-to-candidate-default-full.delta.patch').open('x') as stream:stream.write(delta)
def pin(path):
    raw=path.read_bytes()
    return {'local_path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
result={'parent':pin(PARENT),'runner':pin(HERE/'run_candidate_default_full.py'),
        'delta':pin(HERE/'C1-to-candidate-default-full.delta.patch'),
        'twelve_common_functions_byte_equal':common,
        'frozen_V3_functions_not_changed':['command','source_guard','preflight_environment','catalog','program_guard','nextest','save','save_bytes'],
        'cloud_checks':['AST parse and source equality only; no native execution or optional tests.']}
with (HERE/'runner-derivation.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps(result))

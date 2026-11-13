"""Pure pinned-data checks only. No admission/live methods, project gate, or H.

The small adapter below reads a fixed local byte map. It exercises proof readers
without opening their native paths. It never represents a canonical admission.
"""
from pathlib import Path
import ast
import copy
import gzip
import hashlib
import json
import os
import types

BASE = Path(__file__).resolve().parent
INPUT = BASE / 'inputs'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def load_json(name):
    return json.loads((INPUT / name).read_bytes())


def main():
    candidate_raw = (BASE / 'qualification-admission.HOLD.py').read_bytes()
    mod = types.ModuleType('isolated_pure_admission_data_review')
    # The generated module has imports/constants/definitions only; no CLI.
    top = ast.parse(candidate_raw)
    assert all(isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                                ast.FunctionDef, ast.ClassDef, ast.Expr)) for node in top.body)
    exec(compile(candidate_raw, '<isolated admission definitions>', 'exec'), mod.__dict__)
    original = (INPUT / 'V5_GUARD_6632.original.py').read_text()
    lines = original.splitlines(keepends=True)
    pure_originals = [node for node in ast.parse(original).body if isinstance(node, ast.FunctionDef)
                      and node.name in ('check', 'nodup', 'parse', 'parse_supervisor')]
    pure_guard = {'json': json, 'PreconditionError': RuntimeError}
    exec(compile(''.join(''.join(lines[node.lineno-1:node.end_lineno]) + '\n\n' for node in pure_originals),
                 '<four exact original pure JSON/supervisor helpers>', 'exec'), pure_guard)
    results = []
    def accepted(name, function, kind='actual pinned data'):
        function()
        results.append({'name': name, 'outcome': 'accepted', 'scope': kind})
    def rejected(name, function, kind='independent mutated data'):
        try:
            function()
        except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as error:
            results.append({'name': name, 'outcome': 'rejected', 'error_type': type(error).__name__,
                            'reason': str(error), 'scope': kind})
        else:
            raise AssertionError('negative boundary was not rejected: ' + name)
    mat, packet = load_json('MATERIALIZATION_3BB_RESULT.json'), load_json('MATERIALIZATION_3BB_PACKET.json')
    records = {key: load_json(name + '.json') for key, name in mod.MATERIALIZATION_RECORDS.items()}
    archive, readback, env = (load_json(name) for name in (
        'ARCHIVE_V3_RESULT.json', 'ARCHIVE_V3_READBACK.json', 'HISTORICAL_ENVIRONMENT_READY.json'))
    maintenance, maintenance_cfg, maintenance_inputs = (load_json(name) for name in (
        'MAINTENANCE_41E_RESULT.json', 'MAINTENANCE_41E_CONFIG.json', 'MAINTENANCE_41E_INPUT_IDENTITIES.json'))
    final, final_cfg = (load_json(name) for name in ('FINAL_FORMAT_50F_RESULT.json', 'FINAL_NONRUST_CONFIG.execution-candidate.json'))
    mat_check = lambda value: mod.Admission._check_materialization(value, packet, records)
    arc_check = lambda value: mod.Admission._check_archive(value, readback, env)
    maintenance_check = lambda value: mod.Admission._check_maintenance(value, mat, maintenance_cfg, maintenance_inputs)
    final_check = lambda value: mod.Admission._check_final_format(value, maintenance, final_cfg)
    accepted('actual materialization schema, donor, objects, four records and exact source start', lambda: mat_check(mat))
    accepted('actual V8 restoration and old ENV five-field projection', lambda: arc_check(archive))
    accepted('actual 3bb to 41e identity, original commands/budgets and retained source', lambda: maintenance_check(maintenance))
    accepted('actual 41e to 50f identity, four paths and original fmt terminal', lambda: final_check(final))
    for name, original_value, checker, changes in [
        ('donor confused with historical runtime', mat, mat_check, [('source_repo', mod.HISTORICAL_REPO)]),
        ('current destination confused with donor', mat, mat_check, [('destination_repo', mod.DONOR_REPO)]),
        ('materialization mistaken for final canonical', mat, mat_check, [('source_commit', mod.FINAL_SUBJECT['commit'])]),
        ('one missing provided object', mat, mat_check, [('new_objects_fully_verified', 16660)]),
        ('materialization unknown cleanup', mat, mat_check, [('cleanup_errors', ['unknown child'])]),
        ('archive repair rewrites environment', archive, arc_check, [('environment_changes', True)]),
        ('archive claims wrong source', archive, arc_check, [('source_repo', mod.CURRENT_REPO)]),
        ('maintenance references a different materialization', maintenance, maintenance_check,
         [('actual_materialization_job', 'different-job')]),
        ('maintenance drops full metadata guard', maintenance, maintenance_check, [('git_metadata_unchanged', False)]),
        ('maintenance retries after completion', maintenance, maintenance_check, [('automatic_retry', True)]),
        ('final fmt uses old schema repo', final, final_check, [('source_repo', mod.HISTORICAL_REPO)]),
        ('final fmt makes extra Rust change', final, final_check, [('formatter_changed_paths', ['src/lib.rs'])]),
        ('final fmt attempts a second fix', final, final_check, [('fix_dispatched', True)]),
    ]:
        mutated = copy.deepcopy(original_value)
        for key, value in changes: mutated[key] = value
        rejected(name, lambda mutated=mutated, checker=checker: checker(mutated))
    for name, mutate in [
        ('fix changes original timeout', lambda value: value['stages'][0].__setitem__('timeout_seconds', 7201)),
        ('fix drops ledger scope', lambda value: value['stages'][0].__setitem__('argv', value['stages'][0]['argv'][:-2])),
        ('fmt output is truncated', lambda value: value['stages'][1]['execution'].__setitem__('output_limit_exceeded', True)),
        ('maintenance initial inventory drifts', lambda value: value['source_initial_inventory'].__setitem__('bytes', 1)),
    ]:
        mutated = copy.deepcopy(maintenance); mutate(mutated)
        rejected(name, lambda mutated=mutated: maintenance_check(mutated))
    for name, mutate in [
        ('final-format wrong before inventory', lambda value: value['baseline_inventory'].__setitem__('bytes', 1)),
        ('final-format wrong fmt budget', lambda value: value['stages'][0].__setitem__('timeout_seconds', 901)),
        ('final-format only 27 original inputs', lambda value: next(row for row in value['final_audits'] if row['check']=='original_inputs').__setitem__('input_count', 27)),
        ('non-Rust application includes Rust', lambda value: value['applied_paths'].append('codex-rs/hepta-agentd/src/lib.rs')),
    ]:
        mutated = copy.deepcopy(final); mutate(mutated)
        rejected(name, lambda mutated=mutated: final_check(mutated))
    mutated = copy.deepcopy(archive); mutated['archive_actual']['stat']['st_ino'] += 1
    rejected('archive full actual inode differs even with same content projection', lambda: arc_check(mutated))
    duplicated = copy.deepcopy(mat); duplicated['final_audits'][2] = duplicated['final_audits'][0]
    rejected('duplicate audit cannot replace a required audit', lambda: mat_check(duplicated))
    for filename in ['MATERIALIZATION_3BB_NORMAL.json', 'MAINTENANCE_41E_NORMAL.json',
                     'FINAL_FORMAT_50F_NORMAL.json', 'ARCHIVE_V3_NORMAL.json', 'HISTORICAL_RUNTIME_NORMAL.json']:
        accepted(filename + ' original complete normal parser',
                 lambda filename=filename: pure_guard['parse_supervisor']((INPUT/filename).read_bytes()))
    normal = load_json('FINAL_FORMAT_50F_NORMAL.json')
    terminal = json.loads(normal['content'][0]['text']); terminal['output_complete'] = False
    normal['content'][0]['text'] = json.dumps(terminal)
    rejected('actual normal parser rejects incomplete output', lambda: pure_guard['parse_supervisor'](json.dumps(normal).encode()))
    for filename, wrapped in [('MATERIALIZATION_3BB_ARTIFACTS.json', False),
                              ('MAINTENANCE_41E_ARTIFACTS.json', True), ('FINAL_FORMAT_50F_ARTIFACTS.json', True)]:
        accepted(filename + ' exact catalog schema/unique paths/full pins',
                 lambda filename=filename, wrapped=wrapped: mod.artifact_catalog(load_json(filename), wrapped))
    catalog = load_json('MATERIALIZATION_3BB_ARTIFACTS.json')
    rejected('duplicate original artifact name', lambda: mod.artifact_catalog(catalog + [catalog[0]], False))
    rejected('maintenance envelope cannot be used as canonical list', lambda: mod.artifact_catalog(load_json('MAINTENANCE_41E_ARTIFACTS.json'), False))

    # Exact old supervisor parser and fixed local blobs stand in for proof file
    # transport only. No native pathname is opened; no canonical data is made up.
    byte_map, local_sources = {}, []
    def add(path, raw, provenance):
        path = str(path)
        assert path not in byte_map or byte_map[path] == raw
        byte_map[path] = raw
        local_sources.append({'native_path_as_data_only': path, 'pin': identity(raw), 'local_provenance': provenance})
    binding_index = json.loads((BASE/'FIXED_INPUT_BINDINGS.json').read_bytes())
    local_by_pin = {identity(path.read_bytes())['git_blob']: path for path in INPUT.iterdir() if path.is_file()}
    for name, spec in mod.FIXED_INPUTS.items():
        path = local_by_pin[spec['pin']['git_blob']]
        add(spec['path'], path.read_bytes(), str(path))
    normal_names = {'materialization': 'MATERIALIZATION_3BB', 'maintenance': 'MAINTENANCE_41E',
                    'archive': 'ARCHIVE_V3', 'runtime': 'HISTORICAL_RUNTIME', 'final_format': 'FINAL_FORMAT_50F'}
    for name, proof in mod.ACTUAL_PROOFS.items():
        for suffix, key in [('RESULT', 'result_path'), ('NORMAL', 'supervisor_path')]:
            local = INPUT/(normal_names[name]+'_'+suffix+'.json')
            add(proof[key], local.read_bytes(), str(local))
    mat_cat = mod.artifact_catalog(load_json('MATERIALIZATION_3BB_ARTIFACTS.json'), False)
    maintenance_cat = mod.artifact_catalog(load_json('MAINTENANCE_41E_ARTIFACTS.json'), True)
    final_cat = mod.artifact_catalog(load_json('FINAL_FORMAT_50F_ARTIFACTS.json'), True)
    def add_artifact(catalog, root, name, path, gzip_raw=False):
        raw = Path(path).read_bytes()
        if gzip_raw:
            row = catalog[name]
            assert identity(raw) == {key: row['raw_'+key] for key in ('bytes','sha256','git_blob')}
            raw = gzip.compress(raw, mtime=0)
        assert identity(raw) == mod.pin_fields(catalog[name])
        add(Path(root)/name, raw, str(path) + ('; exact original gzip re-encoding proved by all three pins' if gzip_raw else ''))
    add_artifact(mat_cat, mod.MATERIALIZATION_CONTROL/'run', 'final.git-metadata.json.gz',
                 INPUT/'MATERIALIZATION_3BB_GIT_METADATA.json', True)
    for name in ['SOURCE_GIT_METADATA.before.json.gz', 'SOURCE_GIT_METADATA.after.json.gz']:
        add_artifact(maintenance_cat, mod.MAINTENANCE_CONTROL/'run', name,
                     INPUT/'MAINTENANCE_41E_GIT_METADATA.json', True)
        add_artifact(final_cat, mod.FINAL_FORMAT_CONTROL/'run', name,
                     INPUT/'MAINTENANCE_41E_GIT_METADATA.json', True)
    for name in ['SOURCE_GIT_STATE.before.json', 'final.git-state.json']:
        add_artifact(maintenance_cat, mod.MAINTENANCE_CONTROL/'run', name, INPUT/'MAINTENANCE_41E_GIT_STATE.json')
    add_artifact(final_cat, mod.FINAL_FORMAT_CONTROL/'run', 'final.git-state.json', INPUT/'MAINTENANCE_41E_GIT_STATE.json')
    recovery = Path('/tmp/hepta-36fa-a489-final-nonrust-exact-recovery-v1/final.inventory.exact_recovered.json')
    add_artifact(final_cat, mod.FINAL_FORMAT_CONTROL/'run', 'final.inventory.json.gz', recovery, True)
    final_runtime = Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-format-runtime-v1')
    add_artifact(final_cat, mod.FINAL_FORMAT_CONTROL/'run', 'fmt.after.postimages.json.gz',
                 final_runtime/'fmt.after.postimages.json.gz')
    add_artifact(final_cat, mod.FINAL_FORMAT_CONTROL/'run', 'INPUT_IDENTITIES.json', final_runtime/'INPUT_IDENTITIES.json')
    class LocalBytesOnly:
        def __init__(self): self.input_pins, self.records = {}, {}
        def read_input(self, path, expected):
            raw = byte_map[str(path)]
            mod.pin(raw, expected, 'offline exact fixed input bytes')
            self.input_pins[str(path)] = mod.pin_fields(expected)
            return raw
        @staticmethod
        def parse(raw): return pure_guard['parse'](raw)
        @staticmethod
        def parse_supervisor(raw): return pure_guard['parse_supervisor'](raw)
        def write(self, name, raw):
            assert name not in self.records
            self.records[name] = raw
        def jwrite(self, name, value): self.write(name, json.dumps(value, sort_keys=True).encode())
    proof_reader = object.__new__(mod.Admission)
    proof_reader.cfg = json.loads((BASE/'QUALIFICATION_CONFIG.HOLD.json').read_bytes())
    proof_reader.m = LocalBytesOnly(); proof_reader._fixed_raw = {}
    proof_reader.materialized = mat
    metadata = proof_reader._artifact(mat_cat, mod.MATERIALIZATION_CONTROL/'run', 'final.git-metadata.json.gz',
                                     'offline materialization metadata', proof_reader.cfg['isolated_materialization']['git_metadata'])
    proof_reader.materialization_metadata = pure_guard['parse'](metadata)
    accepted('actual archive proof reader with original normal parser and fixed map', proof_reader._validate_archive)
    retained_maintenance = proof_reader._validate_maintenance(mat)
    retained_final, final_raw, final_metadata = proof_reader._validate_final_format(retained_maintenance)
    assert retained_final == final and identity(final_raw) == mod.FINAL_FORMAT_PIN
    assert identity(final_metadata) == mod.MAINTENANCE_METADATA_PIN
    results.append({'name': 'complete actual 3bb metadata to 41e to 50f proof-reader chain', 'outcome': 'accepted',
        'scope': 'Pinned local bytes only; no Admission/acquire/live/canonical operation executed',
        'input_files': len(proof_reader.m.input_pins), 'retained_final_inventory': identity(final_raw)})
    # The exact native algorithm is additionally checked against the known actual
    # d256 full/native identities, before any final-canonical identity exists.
    materialized_inventory = Path('/tmp/hepta-36fa-coordinator-a489-actual-inventory-recovery-v1/final.complete.inventory.json.exact_recovered')
    mat_raw = materialized_inventory.read_bytes()
    assert identity(mat_raw) == mod.pin_fields(mat['current_source_after']['inventory'])
    assert identity(mod.native_projection(json.loads(mat_raw))) == mat['current_source_after']['native_inventory']
    results.append({'name': 'original five-field serializer reproduces actual materialized native identity',
                    'outcome': 'accepted', 'scope': 'actual pinned full bytes, pure projection'})

    # Synthetic structural fixtures never stand in for an actual canonical proof.
    def row(path, kind='file'):
        value = {'path':path,'kind':kind,'mode':384 if kind=='file' else 448,'uid':1000,'gid':1000,
                 'device':1,'inode':7,'nlink':1,'mtime_ns':1794565120249826667,'ctime_ns':1794565120249826667}
        if kind=='file':value.update(bytes=0,sha256=hashlib.sha256(b'').hexdigest())
        return value
    synthetic = {'root': mod.CURRENT_REPO+'/.git', 'files': [row('a','directory'),row('a.txt'),row('a/x')]}
    projection = json.loads(mod.canonical_to_v5_projection(synthetic))
    assert [r['path'] for r in projection['files']] == ['a','a/x','a.txt']
    assert synthetic['files'][0]['mtime_ns'] == 1794565120249826667
    results.append({'name':'canonical global path order becomes original per-directory DFS without integer loss',
                    'outcome':'accepted','scope':'synthetic structural fixture only'})
    mutations = [
        ('canonical missing ownership field', lambda v:v['files'][0].pop('uid')),
        ('canonical duplicate path', lambda v:v['files'].append(copy.deepcopy(v['files'][-1]))),
        ('canonical missing parent closure', lambda v:v['files'].pop(0)),
        ('canonical unsafe path', lambda v:v['files'][1].__setitem__('path','../a')),
        ('canonical unknown metadata key', lambda v:v['files'][1].__setitem__('extra',True)),
        ('canonical boolean masquerades as uid', lambda v:v['files'][1].__setitem__('uid',True)),
        ('canonical symlink substituted for regular file', lambda v:v['files'][1].__setitem__('kind','symlink')),
        ('canonical row order differs', lambda v:v['files'].reverse()),
    ]
    for name, mutate in mutations:
        value=copy.deepcopy(synthetic);mutate(value)
        rejected(name,lambda value=value:mod.canonical_to_v5_projection(value),'synthetic structural negative fixture only')
    different_owner=copy.deepcopy(synthetic);different_owner['files'][1]['uid']+=1
    assert mod.canonical_to_v5_projection(different_owner)==mod.canonical_to_v5_projection(synthetic)
    assert different_owner != synthetic
    live_method=next(n for n in ast.walk(top) if isinstance(n,ast.FunctionDef) and n.name=='_require_live_metadata')
    comparison=ast.parse('live != self.initial_metadata',mode='eval').body
    assert any(isinstance(n,ast.Compare) and ast.dump(n,include_attributes=False)==ast.dump(comparison,include_attributes=False)
               for n in ast.walk(live_method))
    results.append({'name':'ownership loss in V5 projection is expressly covered by separate complete live equality',
                    'outcome':'accepted','scope':'synthetic counterexample plus exact production AST assertion; no live check executed'})
    hold = json.loads((BASE/'QUALIFICATION_CONFIG.HOLD.json').read_bytes())
    before_env=dict(os.environ)
    rejected('HOLD configuration stops before module loading, output creation or environment mutation',
             lambda:mod.Admission(hold,BASE/'MUST_NOT_EXIST',True),'HOLD rejection only')
    assert dict(os.environ)==before_env and not (BASE/'MUST_NOT_EXIST').exists()
    premature=copy.deepcopy(hold);premature.update(source=mod.FINAL_SUBJECT['commit'],tree=mod.FINAL_SUBJECT['tree'],parents=mod.FINAL_SUBJECT['parents'])
    rejected('expected b608 alone cannot supply missing actual canonical bindings',
             lambda:mod.Admission._require_complete_bindings(premature),'HOLD structural rejection only')
    assert hold['canonical_alignment']['result'] is None and hold['full_physical_inventory'] is None
    report = {'format':'hepta-admission-successor-pure-data-review-v1','candidate':identity(candidate_raw),
        'config':identity((BASE/'QUALIFICATION_CONFIG.HOLD.json').read_bytes()),
        'actual_known_producer_operations':['3bb','41e','50f','archive-v3','historical-runtime'],
        'actual_canonical_observed':False,'actual_canonical':None,'qualification':False,
        'admission_or_acquire_or_finish_or_live_metadata_called':False,'project_gate_commands_called':[],
        'H_calls':0,'local_map_reads_only':True,'checks':results,
        'accepted':sum(x['outcome']=='accepted' for x in results),
        'rejected':sum(x['outcome']=='rejected' for x in results),
        'source_note':'Runtime original read functions are unchanged. Proof transport here is a fixed local byte map, never a native filesystem or a success simulation.',
        'read_inputs':proof_reader.m.input_pins,'local_sources':local_sources}
    (BASE/'PURE_DATAFLOW_AND_NEGATIVE_BOUNDARIES.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'checks':len(results),'accepted':report['accepted'],'rejected':report['rejected'],
                      'actual_canonical':None,'report':identity((BASE/'PURE_DATAFLOW_AND_NEGATIVE_BOUNDARIES.json').read_bytes())}))


if __name__=='__main__':main()

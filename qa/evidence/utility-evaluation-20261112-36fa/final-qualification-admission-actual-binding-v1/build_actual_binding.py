"""Build an immutable-data late-binding HOLD layer. No native or project calls.

The existing admission module is loaded as definitions only. Its constructor,
acquire, finish, live filesystem checks and executable wrappers are never called.
All nanosecond values remain Python integers from complete original JSON bytes.
"""
from pathlib import Path
import ast
import base64
import copy
import difflib
import gzip
import hashlib
import json
import os
import struct
import types

BASE = Path(__file__).resolve().parent
OLD = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1')
RECOVERY = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1')
NATIVE = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
CANONICAL_INPUTS = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v1'
SOURCE_CLONE = '/home/qian-qi/hepta-utility-36fa-source-gates-b608-v1'
ROOT_RUN = '/run/hepta-utility-36fa-final-b608-v1'
RUN_IDENTITY = 'hepta-utility-36fa-final-b608-v1'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def fields(value, prefix=''):
    return {key: value[prefix + key] for key in ('bytes', 'sha256', 'git_blob')}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def write_same_or_new(name, raw):
    destination = BASE / name
    if destination.exists():
        require(destination.read_bytes() == raw, 'immutable output already differs: ' + name)
    else:
        destination.write_bytes(raw)
    return identity(raw)


def differences(before, after, path=''):
    if isinstance(before, dict) and isinstance(after, dict):
        require(before.keys() == after.keys(), 'no configuration keys added or deleted at ' + path)
        result = []
        for key in sorted(before):
            result.extend(differences(before[key], after[key], path + '/' + key))
        return result
    if before != after:
        return [{'path': path, 'before': before, 'after': after}]
    return []


def decode_original_parts(catalog, name):
    row = catalog[name]
    compressed = bytearray()
    for part in row['parts']:
        raw = (BASE / 'inputs' / part['name']).read_bytes()
        require(identity(raw) == fields(part), 'original part identity: ' + part['name'])
        require(raw.endswith(b'\n') and raw.count(b'\n') == 1, 'canonical original base64 framing')
        decoded = base64.b64decode(raw[:-1], validate=True)
        require(base64.b64encode(decoded) + b'\n' == raw, 'canonical original base64 bytes')
        require(len(compressed) == part['decoded_offset'] and len(decoded) == part['decoded_bytes']
                and hashlib.sha256(decoded).hexdigest() == part['decoded_sha256'], 'original part offset/content')
        compressed.extend(decoded)
    compressed = bytes(compressed)
    require(identity(compressed) == fields(row), 'complete original gzip: ' + name)
    raw = gzip.decompress(compressed)
    require(identity(raw) == fields(row, 'raw_'), 'complete original raw: ' + name)
    return raw


def parse_captured_index(raw):
    """Parse captured DIRC v2 bytes; never lstat a native working file."""
    require(raw[:4] == b'DIRC' and struct.unpack('>I', raw[4:8])[0] == 2, 'original DIRC v2')
    require(hashlib.sha1(raw[:-20]).digest() == raw[-20:], 'complete index checksum')
    count = struct.unpack('>I', raw[8:12])[0]
    offset, entries = 12, []
    for _ in range(count):
        start = offset
        stats = list(struct.unpack('>10I', raw[offset:offset+40]))
        sha = raw[offset+40:offset+60].hex()
        flags = struct.unpack('>H', raw[offset+60:offset+62])[0]
        require(flags & 0xf000 == 0, 'no assume-unchanged/extended/stage flags')
        end = raw.index(b'\0', offset+62)
        path = raw[offset+62:end].decode('utf-8')
        offset = start + ((end + 1 - start + 7) // 8) * 8
        require(raw[end:offset] == bytes(offset-end), 'normal index entry padding')
        entries.append({'path': path, 'mode': format(stats[6], 'o'), 'sha': sha, 'flags': flags,
                        'stat': stats, 'raw_entry_sha256': hashlib.sha256(raw[start:offset]).hexdigest()})
    extensions = []
    while offset < len(raw) - 20:
        extension_start = offset
        name = raw[offset:offset+4].decode('ascii')
        length = struct.unpack('>I', raw[offset+4:offset+8])[0]
        offset += 8
        body = raw[offset:offset+length]
        require(len(body) == length, 'complete original index extension')
        extensions.append({'name': name, 'bytes': length,
                           'sha256': hashlib.sha256(raw[extension_start:offset+length]).hexdigest()})
        offset += length
    require(offset == len(raw)-20, 'exact original index end')
    return entries, extensions


def main():
    before_raw = (OLD/'QUALIFICATION_CONFIG.HOLD.json').read_bytes()
    before_source_raw = (OLD/'SOURCE_GATES_CONFIG.HOLD.json').read_bytes()
    code_raw = (OLD/'qualification-admission.HOLD.py').read_bytes()
    require(identity(before_raw)['git_blob'] == '460139b9ce065184a0809def0823d8d20c45fe41', 'frozen first config')
    require(identity(before_source_raw)['git_blob'] == 'e908def6523ea6bbca2381832297d76ea5178073', 'frozen first source config')
    require(identity(code_raw)['git_blob'] == 'c77e3be6230d3267c08333be582f69f23c016fb9', 'frozen complete code')
    code_ast = ast.parse(code_raw)
    require(all(isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                              ast.FunctionDef, ast.ClassDef, ast.Expr)) for n in code_ast.body), 'definitions-only code')
    module = types.ModuleType('captured_data_only_frozen_c77e')
    exec(compile(code_raw, '<frozen c77e definitions only>', 'exec'), module.__dict__)
    cfg, source_cfg = json.loads(before_raw), json.loads(before_source_raw)
    original_guard = (OLD/'inputs/V5_GUARD_6632.original.py').read_text()
    guard_lines = original_guard.splitlines(keepends=True)
    pure_nodes = [n for n in ast.parse(original_guard).body if isinstance(n, ast.FunctionDef)
                  and n.name in ('check', 'nodup', 'parse', 'parse_supervisor')]
    require(len(pure_nodes) == 4, 'four exact original pure JSON helpers')
    guard = {'json': json, 'PreconditionError': RuntimeError}
    exec(compile(''.join(''.join(guard_lines[n.lineno-1:n.end_lineno])+'\n\n' for n in pure_nodes),
                 '<four original pure helpers>', 'exec'), guard)
    parse = guard['parse']
    input_index = json.loads((BASE/'ACTUAL_INPUT_FULL_GET.json').read_bytes())
    require(len(input_index['entries']) == 22 and all(x['full_GET_equal'] for x in input_index['entries']),
            'all 22 full Git original bodies already compared')
    for row in input_index['entries']:
        require(identity(Path(row['local_path']).read_bytes()) == fields(row), 'fixed input remains exact')
    def read(name): return (BASE/'inputs'/name).read_bytes()
    aligned = parse(read('CANONICAL_RESULT.original.json'))
    artifacts = parse(read('CANONICAL_ARTIFACTS.original.json'))
    catalog = module.artifact_catalog(artifacts, False)
    normal = guard['parse_supervisor'](read('CANONICAL_NORMAL.original.json'))
    require(normal['job_id'] == '1a1d4cbd33e-392-5a9', 'actual canonical job')
    control = parse(read('CANONICAL_APPROVED_CONFIG.original.json'))
    inputs = parse(read('INPUTS.final.json'))
    canonical_root = str(module.CANONICAL_CONTROL)
    packet_path = CANONICAL_INPUTS/'CANONICAL_PACKET.json'
    packet_raw = packet_path.read_bytes()
    packet_pin = identity(packet_raw)
    require(packet_pin == inputs[canonical_root+'/CANONICAL_PACKET.json'], 'complete consumed original canonical packet')
    require(identity(read('CANONICAL_APPROVED_CONFIG.original.json')) == inputs[canonical_root+'/APPROVED_CONFIG.json'],
            'actual consumed canonical configuration')
    require(module.CANONICAL_DRIVER_PIN == inputs[canonical_root+'/driver.py'], 'actual consumed unchanged canonical driver')
    before_inventory_raw = (RECOVERY/'SOURCE.before.inventory.exact_recovered.json').read_bytes()
    clean_raw = (RECOVERY/'SOURCE.final.inventory.exact_recovered.json').read_bytes()
    require(identity(before_inventory_raw) == fields(catalog['SOURCE.before.inventory.json.gz'], 'raw_'), 'actual before inventory')
    require(identity(clean_raw) == fields(catalog['SOURCE.final.inventory.json.gz'], 'raw_'), 'actual final clean inventory')
    clean = parse(clean_raw)
    native_raw = module.native_projection(clean)
    require(native_raw == (RECOVERY/'NATIVE.expected_from_actual_clean_inventory.json').read_bytes(), 'one exact native projection')
    index_raw = decode_original_parts(catalog, 'INDEX.final.raw.gz')
    audit_raw = decode_original_parts(catalog, 'INDEX.final.audit.json.gz')
    audit = parse(audit_raw)
    for name in ['GIT_METADATA.before.json','GIT_METADATA.final.json','INDEX.complete-entry-delta.json']:
        require(identity(read(name)) == fields(catalog[name+'.gz'], 'raw_'), 'actual original raw '+name)
    for name in ['GIT_METADATA.allowed-actual-delta.json','GIT_STATE.before.json','GIT_STATE.final.json',
                 'COMMANDS.json','INPUTS.final.json','MUTATION_PROGRESS.json']:
        require(identity(read(name)) == fields(catalog[name]), 'actual original complete record '+name)
    proof = cfg['canonical_alignment']
    proof.update(job_id=normal['job_id'], result=identity(read('CANONICAL_RESULT.original.json')),
                 supervisor=identity(read('CANONICAL_NORMAL.original.json')),
                 supervisor_path=CONTROL+'/CANONICAL_SUPERVISOR.original.json',
                 artifacts=identity(read('CANONICAL_ARTIFACTS.original.json')),
                 before_git_metadata_raw=identity(read('GIT_METADATA.before.json')),
                 final_git_metadata_raw=identity(read('GIT_METADATA.final.json')),
                 final_git_metadata_gzip=fields(catalog['GIT_METADATA.final.json.gz']),
                 final_index_raw=identity(index_raw), final_index_audit=identity(audit_raw),
                 complete_entry_delta=identity(read('INDEX.complete-entry-delta.json')),
                 allowed_metadata_delta=identity(read('GIT_METADATA.allowed-actual-delta.json')),
                 commands=identity(read('COMMANDS.json')), progress=identity(read('MUTATION_PROGRESS.json')),
                 inputs=identity(read('INPUTS.final.json')),
                 approved_config=identity(read('CANONICAL_APPROVED_CONFIG.original.json')), canonical_packet=packet_pin)
    source_cfg.update(state='HOLD_FOR_EXACT_ROOT_QUALIFICATION_APPROVAL', records=CONTROL+'/source-gates-records',
                      run_identity=RUN_IDENTITY, source_checkout=SOURCE_CLONE,
                      source_sha=module.FINAL_SUBJECT['commit'], source_tree=module.FINAL_SUBJECT['tree'])
    source_raw = json_bytes(source_cfg)
    cfg.update(state='HOLD_FOR_EXACT_ROOT_QUALIFICATION_APPROVAL',
               source=module.FINAL_SUBJECT['commit'], tree=module.FINAL_SUBJECT['tree'],
               parents=module.FINAL_SUBJECT['parents'], full_physical_inventory=identity(clean_raw),
               full_native_inventory=identity(native_raw), expected_inventory_sha256=identity(native_raw)['sha256'],
               current_final_git_state=parse(read('GIT_STATE.final.json')),
               canonical_complete_git_metadata=proof['final_git_metadata_raw'],
               canonical_original_index=proof['final_index_raw'],
               actual_final_format_postimages_reviewed=True, actual_final_fences_reviewed=True,
               source_control_pin_overrides=[copy.deepcopy(module.WORKFLOW_OVERRIDE_READY)],
               admission_path=CONTROL+'/qualification-admission.py',
               plan_path=CONTROL+'/PLAN.original.json', native_driver_path=CONTROL+'/native-driver.original.py',
               records=CONTROL+'/native-records', root_parent=ROOT_RUN, run_identity=RUN_IDENTITY,
               source_gates_config_path=CONTROL+'/SOURCE_GATES_CONFIG.json', source_gates_config_pin=identity(source_raw),
               source_gates_handoff_records=CONTROL+'/source-handoff')
    require(cfg['root_execution_approved'] is False and cfg['not_an_execution_approval'] is True
            and cfg['qualification_execution_dispatched'] is False and cfg['normal_native_and_source_results'] is None,
            'no execution permission or qualification result supplied')
    checks = []
    def accepted(name, function, scope='captured original bytes and pure predicates only'):
        function()
        checks.append({'name': name, 'outcome': 'accepted', 'scope': scope})
    def rejected(name, function):
        try: function()
        except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as error:
            checks.append({'name': name, 'outcome': 'rejected', 'error_type': type(error).__name__, 'reason':str(error),
                           'scope':'independent altered captured-data probe; no native access'})
        else: raise AssertionError('negative captured predicate accepted '+name)
    final_format = parse((OLD/'inputs/FINAL_FORMAT_50F_RESULT.json').read_bytes())
    accepted('all actual binding fields structurally complete while execution remains HOLD',
             lambda: module.Admission._require_complete_bindings(cfg))
    accepted('actual 50f to canonical original schema and budgets',
             lambda: module.Admission._check_canonical(aligned, final_format, cfg, control))
    require(artifacts == aligned['artifacts'] + [dict(proof['result'], name='RESULT.json')], 'actual artifact order and final RESULT')
    accepted('actual canonical normal complete output and terminal', lambda: guard['parse_supervisor'](read('CANONICAL_NORMAL.original.json')))
    before_metadata, after_metadata = parse(read('GIT_METADATA.before.json')), parse(read('GIT_METADATA.final.json'))
    old_v5 = (OLD/'inputs/MAINTENANCE_41E_GIT_METADATA.json').read_bytes()
    require(module.canonical_to_v5_projection(before_metadata) == old_v5, 'full canonical-before to retained actual V5 bytes')
    final_v5 = module.canonical_to_v5_projection(after_metadata)
    require(len(after_metadata['files']) == 70 and all(type(x['uid']) is int and type(x['gid']) is int
            and type(x['mtime_ns']) is int and type(x['ctime_ns']) is int for x in after_metadata['files']),
            'complete actual 70 rows retain ownership and integer nanoseconds')
    old_rows = {r['path']:r for r in before_metadata['files']}; new_rows = {r['path']:r for r in after_metadata['files']}
    changes = [{'path':p,'before':old_rows.get(p),'after':new_rows.get(p)} for p in sorted(set(old_rows)|set(new_rows))
               if old_rows.get(p) != new_rows.get(p)]
    require(changes == parse(read('GIT_METADATA.allowed-actual-delta.json')) == aligned['git_metadata_actual_changes'],
            'complete 61-row actual metadata delta')
    require(module.physical_projection(parse(before_inventory_raw)) == module.physical_projection(clean), 'full physical rows preserved')
    require(clean['source'] == {'head':cfg['source'],'tree':cfg['tree'],'status':''}
            and all(r['matches_index'] for r in clean['files']), 'complete canonical clean source')
    entries, extensions = parse_captured_index(index_raw)
    require(entries == audit['entries'] and extensions == audit['extensions'] and audit['entry_count'] == len(entries) == 15243,
            'all captured original index bytes equal complete original audit')
    rows = {r['path']:r for r in clean['files']}
    require([e['path'] for e in entries] == sorted(rows,key=os.fsencode), 'exact index path sequence')
    for entry in entries:
        row=rows[entry['path']]
        require(entry['sha'] == row['index_blob'] == row['working_blob'] and entry['mode'] == row['index_mode']
                and entry['flags'] == min(len(os.fsencode(entry['path'])),0xfff), 'captured index logical equality')
    require(identity(index_raw)['bytes'] == cfg['current_final_git_state']['index_bytes']
            and identity(index_raw)['sha256'] == cfg['current_final_git_state']['index_sha256'], 'full raw index matches canonical Git state')
    require(parse(read('COMMANDS.json')) == aligned['commands'] and parse(read('MUTATION_PROGRESS.json')) == aligned['mutation_intents'],
            '94 complete original commands and 33 original intents')
    for label, count in [('captured metadata ownership/full delta and original V5 bridge',70),
                         ('captured index checksum/all entries/full stats from original audit',15243),
                         ('captured command/intents preserve independent OBJECT_BATCH terminal schema',94)]:
        checks.append({'name':label,'outcome':'accepted','count':count,
                       'scope':'captured original bytes only; no current native lstat or environment observation'})
    plan = parse((OLD/'inputs/PLAN_3AEF.json').read_bytes())
    originals = plan['unchanged_original_controls']['reviewed_source_pins']['files']
    require(len(originals)==12 and len({r['path'] for r in originals})==12,'all twelve old source pins')
    controls=[]
    for item in originals:
        expected=fields(item)
        override=item['path']==module.WORKFLOW_OVERRIDE_READY['path']
        if override:
            require(expected==module.WORKFLOW_OVERRIDE_READY['original_plan_pin'],'old workflow retained')
            expected=module.WORKFLOW_OVERRIDE_READY['reviewed_current_pin']
        row=rows[item['path']]
        require({k:row[k] for k in ('bytes','sha256')}=={k:expected[k] for k in ('bytes','sha256')}
                and row['working_blob']==row['index_blob']==expected['git_blob'] and row['stable'] is True
                and row['matches_index'] is True,'all original current source controls in complete actual inventory')
        controls.append({'path':item['path'],'original_pin':fields(item),'effective_pin':expected,'explicit_override':override})
    require(sum(r['explicit_override'] for r in controls)==1,'one workflow override only')
    for name, altered in [
        ('canonical source wrongly treated as materialization',('source_repo',module.DONOR_REPO)),
        ('canonical allows source writes',('physical_source_writes_dispatched',1)),
        ('canonical claims test execution',('test_commands_dispatched',1)),
        ('canonical loses stable input audit',('final_audits',aligned['final_audits'][:-1]))]:
        changed=copy.deepcopy(aligned);changed[altered[0]]=altered[1]
        rejected(name,lambda changed=changed:module.Admission._check_canonical(changed,final_format,cfg,control))
    for name, mutate in [
        ('binding substitutes d256 endpoint',lambda v:v.__setitem__('source',module.MATERIALIZED_SUBJECT['commit'])),
        ('binding omits final raw index',lambda v:v['canonical_alignment'].__setitem__('final_index_raw',None)),
        ('binding drops final full metadata identity',lambda v:v.__setitem__('canonical_complete_git_metadata',None)),
        ('binding omits workflow override',lambda v:v.__setitem__('source_control_pin_overrides',[])),
        ('binding adds a second workflow override',lambda v:v['source_control_pin_overrides'].append(copy.deepcopy(v['source_control_pin_overrides'][0]))),
        ('binding changes original target budget',lambda v:v['runtime_guard'].__setitem__('minimum_target_free_bytes',34359738369))]:
        changed=copy.deepcopy(cfg);mutate(changed)
        rejected(name,lambda changed=changed:module.Admission._require_complete_bindings(changed))
    bad_control=copy.deepcopy(control);bad_control['action_seconds']+=1
    rejected('canonical control budget changes',lambda:module.Admission._check_canonical(aligned,final_format,cfg,bad_control))
    for name, mutate in [
        ('metadata missing uid',lambda v:v['files'][0].pop('uid')),
        ('metadata contains duplicate path',lambda v:v['files'].append(copy.deepcopy(v['files'][0]))),
        ('metadata nanoseconds rounded to a float',lambda v:v['files'][0].__setitem__('mtime_ns',float(v['files'][0]['mtime_ns']))),
        ('metadata unsafe path',lambda v:v['files'][0].__setitem__('path','../HEAD'))]:
        changed=copy.deepcopy(after_metadata);mutate(changed)
        rejected(name,lambda changed=changed:module.canonical_to_v5_projection(changed))
    changed=copy.deepcopy(after_metadata);changed['files'][0]['uid']+=1
    require(module.canonical_to_v5_projection(changed)==final_v5 and changed!=after_metadata,
            'projection alone cannot authenticate complete ownership')
    rejected('changed full ownership cannot reuse actual original metadata pin',
             lambda:module.pin((json.dumps(changed,sort_keys=True,separators=(',',':'))+'\n').encode(),
                               proof['final_git_metadata_raw'],'complete original metadata identity'))
    bad_normal=parse(read('CANONICAL_NORMAL.original.json'))
    terminal=json.loads(bad_normal['content'][0]['text']);terminal['output_complete']=False
    bad_normal['content'][0]['text']=json.dumps(terminal)
    rejected('canonical normal missing complete output',lambda:guard['parse_supervisor'](json_bytes(bad_normal)))
    rejected('captured index checksum corruption',lambda:parse_captured_index(index_raw[:-1]+bytes([index_raw[-1]^1])))
    require(cfg['state']!='READY_FOR_FINAL_SOURCE_QUALIFICATION' and cfg['root_execution_approved'] is False
            and source_cfg['state']!='READY_FOR_EXACT_SOURCE_RUN','both frozen entry predicates remain non-executable HOLD')
    output_raw=json_bytes(cfg)
    config_changes=differences(json.loads(before_raw),cfg)
    source_changes=differences(json.loads(before_source_raw),source_cfg)
    diff=''.join(difflib.unified_diff(before_raw.decode().splitlines(keepends=True),output_raw.decode().splitlines(keepends=True),
                                    'frozen-c77e-layer/QUALIFICATION_CONFIG.HOLD.json','actual-5a9-layer/QUALIFICATION_CONFIG.HOLD.json'))
    diff+=''.join(difflib.unified_diff(before_source_raw.decode().splitlines(keepends=True),source_raw.decode().splitlines(keepends=True),
                                     'frozen-c77e-layer/SOURCE_GATES_CONFIG.HOLD.json','actual-5a9-layer/SOURCE_GATES_CONFIG.HOLD.json'))
    write_same_or_new('QUALIFICATION_CONFIG.HOLD.json',output_raw)
    write_same_or_new('SOURCE_GATES_CONFIG.HOLD.json',source_raw)
    write_same_or_new('CONFIG_DELTA.patch',diff.encode())
    write_same_or_new('FIELD_CHANGES.json',json_bytes({'format':'hepta-exact-qualification-config-late-binding-diff-v1',
        'qualification_before':identity(before_raw),'qualification_after':identity(output_raw),
        'source_gates_before':identity(before_source_raw),'source_gates_after':identity(source_raw),
        'qualification_changes':config_changes,'source_gate_changes':source_changes,
        'no_keys_added_or_deleted':True,'frozen_admission_code_unchanged':identity(code_raw),
        'remaining_authorization':'Both configuration states are HOLD; root_execution_approved remains false.'}))
    write_same_or_new('CANONICAL_FINAL_V5_DERIVED.json',final_v5)
    report={'format':'hepta-actual-canonical-captured-predicate-review-v1','actual_job_id':normal['job_id'],
        'frozen_admission':identity(code_raw),'original_config':identity(before_raw),'actual_binding_config':identity(output_raw),
        'source_gates_config':identity(source_raw),'actual_normal':identity(read('CANONICAL_NORMAL.original.json')),
        'actual_result':identity(read('CANONICAL_RESULT.original.json')),'actual_artifacts':identity(read('CANONICAL_ARTIFACTS.original.json')),
        'actual_full_metadata':proof['final_git_metadata_raw'],'derived_v5_projection':identity(final_v5),
        'derived_v5_projection_is_not_a_live_observation':True,'actual_original_index':identity(index_raw),
        'actual_original_index_audit':identity(audit_raw),'all_captured_index_entries_equal_audit_and_complete_source':True,
        'actual_clean_inventory':identity(clean_raw),'expected_only_native_projection':identity(native_raw),
        'source_controls':controls,'qualification_field_change_count':len(config_changes),
        'source_gate_field_change_count':len(source_changes),'checks':checks,
        'accepted':sum(r['outcome']=='accepted' for r in checks),'rejected':sum(r['outcome']=='rejected' for r in checks),
        'new_native_or_H_reads':0,'project_gate_or_test_calls':0,'admission_constructor_acquire_finish_live_calls':0,
        'source_ref_tree_commit_writes':0,'runtime_environment_or_lock_observed':False,
        'planned_paths_not_staged_or_probed':{'control':CONTROL,'source_clone':SOURCE_CLONE,'root_run':ROOT_RUN},
        'deferred_to_exact_authorized_admission':['complete current live metadata and uid/gid equality',
            'all current working-file index stat checks','original lock inode and SH acquisition','original live environment/current process guards',
            'original source and native complete snapshots','actual source gates and native 14-phase/JUnit results'],
        'historical_limitation':'Original finish may report secondary SourceChanged before initial_git exists; that alone does not prove a physical source change.',
        'qualification':False,'real_task_chain_success':0}
    write_same_or_new('PURE_CAPTURED_PREDICATE_REVIEW.json',json_bytes(report))
    originals={'format':'hepta-actual-late-binding-original-reference-manifest-v1','original_code_layer_placement':'c6f2184da06dfb73af1c3fb9d35aac6d14d4775b',
        'original_code_peer_placement':'cbfa9f3a359b5c54371c7922b5a2aa52c84030a6',
        'inventory_recovery_placement':'29bff7138b54ec375b8cd96779edfa090f271e2d',
        'canonical_input_placement':'0b4f421c6cd740dc5b6c4f0275e45ebc6006f960',
        'canonical_packet':{'local_path':str(packet_path),**packet_pin,'actual_consumed_pin':inputs[canonical_root+'/CANONICAL_PACKET.json']},
        'canonical_packet_lossless_representation':next(r for r in json.loads((CANONICAL_INPUTS/'LOSSLESS_REPRESENTATIONS.json').read_bytes())
                                                      if r['name']=='CANONICAL_PACKET.json'),
        'complete_inputs':input_index['entries'],'frozen_original_controls':json.loads((OLD/'FIXED_INPUT_BINDINGS.json').read_bytes()),
        'large_complete_inventory_and_index_raws_not_claimed_as_standalone_Git_uploads':True}
    write_same_or_new('ORIGINAL_REFERENCE_MANIFEST.json',json_bytes(originals))
    print(json.dumps({'configuration':identity(output_raw),'source_gates':identity(source_raw),'report':identity(json_bytes(report)),
                      'field_changes':len(config_changes),'source_field_changes':len(source_changes),
                      'accepted':report['accepted'],'rejected':report['rejected'],'state':cfg['state']},sort_keys=True))


if __name__=='__main__':main()

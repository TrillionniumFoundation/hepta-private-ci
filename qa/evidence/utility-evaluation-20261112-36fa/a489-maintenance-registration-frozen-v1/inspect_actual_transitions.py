#!/usr/bin/env python3
"""Read actual fix/fmt source transitions and reconstruct exact inventories.

Pure offline byte, lexical and mode-aware Merkle inspection. No H, project gate,
compiler, formatter, source-worktree edit or Git tree/commit/ref operation.
"""
import ast
import base64
import collections
import copy
import difflib
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
RUNTIME = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')
BASE = Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json')
REG = Path('/tmp/hepta-36fa-a489-maintenance-registration-refresh-v1')
LEX = Path('/tmp/hepta-36fa-provider-0c59-fmt62-semantic-peer-v1/inspect_fmt_tokens.py')
SOURCE = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
TREE = 'a489b394666b8141840275128a780605b024cde0'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def dump(obj):
    return (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode()


def save(relative, raw):
    path = HERE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as f:
            f.write(raw)
    return {'path': str(path), **pin(raw)}


def merkle(files):
    root = {}
    for row in files:
        pieces = row['path'].split('/')
        node = root
        for piece in pieces[:-1]:
            node = node.setdefault(piece, {})
        assert pieces[-1] not in node
        node[pieces[-1]] = (row['index_mode'], row['working_blob'])
    def tree(node):
        entries = []
        for name, item in node.items():
            if isinstance(item, dict):
                mode, child = '40000', tree(item)
                sort_name = name.encode() + b'/'
            else:
                mode, child = item
                sort_name = name.encode()
            entries.append((sort_name, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(child)))
        return oid('tree', b''.join(raw for _, raw in sorted(entries)))
    return tree(root)


def exact_inventory(initial, rows):
    result = copy.deepcopy(initial)
    result['files'] = [rows[r['path']] for r in initial['files']]
    assert len(result['files']) == 15243
    changed = sorted((r['path'] for r in result['files'] if not r['matches_index']), key=os.fsencode)
    # All actual changes in these receipts are modifications of tracked files
    # with their original mode. This is the unique original porcelain status
    # candidate, after the original source_identity stdout .strip().
    result['source']['status'] = ''.join(' M ' + path + '\n' for path in changed).strip()
    return (json.dumps(result, sort_keys=True, separators=(',', ':')) + '\n').encode()


def main():
    inputs = {}
    def fixed(path, blob):
        raw = path.read_bytes()
        assert pin(raw)['git_blob'] == blob, str(path)
        inputs[str(path)] = pin(raw)
        return raw
    result_raw = fixed(RUNTIME / 'RESULT.json', 'b87aed7647ac34e3db0e381110bf685438aee0ee')
    artifacts_raw = fixed(RUNTIME / 'ARTIFACTS.json', '222eb4e2913d62cdd308e2ce26edf7c320ebe47f')
    base_raw = fixed(BASE, 'f1e2d72f99093581403a2dcc91b55da22a33f905')
    result, artifact_doc, initial = json.loads(result_raw), json.loads(artifacts_raw), json.loads(base_raw)
    assert set(artifact_doc) == {'files', 'terminal_report', 'terminal_report_self_hash_not_included'}
    artifacts = {r['name']: r for r in artifact_doc['files']}
    assert len(artifacts) == len(artifact_doc['files']) == 170
    assert result['status'] == 'MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED'
    assert result['source_commit'] == SOURCE and result['source_tree'] == TREE
    assert result['test_commands_dispatched'] == 0 and result['qualification'] is False
    assert result['attempted_commands'] == ['fix', 'fmt'] and result['not_run_commands'] == []
    assert [r['execution']['returncode'] for r in result['stages']] == [0, 0]
    assert [r['timeout_seconds'] for r in result['stages']] == [7200, 900]
    assert all(not r['execution']['timed_out'] and not r['execution']['output_limit_exceeded'] for r in result['stages'])
    assert initial['source'] == {'head': SOURCE, 'tree': TREE, 'status': ''}
    rows = {r['path']: r for r in initial['files']}
    assert len(rows) == len(initial['files']) == 15243 and merkle(initial['files']) == TREE

    # This standalone prior peer lexical helper only defines functions/constants
    # on import; no main/project code is invoked.
    lex_raw = LEX.read_bytes()
    inputs[str(LEX)] = pin(lex_raw)
    spec = importlib.util.spec_from_file_location('actual_transition_lexical_only', LEX)
    lexer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lexer)
    save('ORIGINAL_LEXICAL_HELPER.py', lex_raw)
    save('inputs/RESULT.original.json', result_raw)
    save('inputs/ARTIFACTS.original.json', artifacts_raw)
    transitions, packets, decoded, inventory_records = [], {}, {}, []
    for stage, expected_count in [('fix.after', 12), ('fmt.after', 14), ('final', 17)]:
        name = stage + '.postimages.json'
        record = artifacts[name + '.gz']
        raw = fixed(RUNTIME / name, record['raw_git_blob'])
        assert pin(raw) == {'bytes': record['raw_bytes'], 'sha256': record['raw_sha256'], 'git_blob': record['raw_git_blob']}
        compressed = gzip.compress(raw, mtime=0)
        assert pin(compressed) == {k: record[k] for k in ('bytes', 'sha256', 'git_blob')}
        parts = []
        for n, offset in enumerate(range(0, len(compressed), 262144), 1):
            block = compressed[offset:offset + 262144]
            encoded = base64.b64encode(block) + b'\n'
            part_name = name + '.gz.part-%03d.b64' % n
            part = record['parts'][n - 1]
            assert part == artifacts[part_name]
            assert pin(encoded) == {k: part[k] for k in ('bytes', 'sha256', 'git_blob')}
            assert part['decoded_offset'] == offset and part['decoded_bytes'] == len(block)
            assert part['decoded_sha256'] == hashlib.sha256(block).hexdigest()
            parts.append(save('inputs/' + part_name, encoded))
        packet = json.loads(raw)
        assert packet['format'] == 'hepta-maintenance-actual-source-transition-v1'
        assert packet['stage'] == stage and len(packet['changes']) == expected_count
        assert packet['source_commit_unchanged'] == SOURCE and packet['qualification'] is False
        assert packet['all_physical_changes_including_untracked_or_ignored_are_recorded'] is True
        assert len({r['path'] for r in packet['changes']}) == expected_count
        packets[stage] = packet
        decoded[stage] = {}
        stage_rows, stage_diff = [], []
        for row in packet['changes']:
            relative = row['path']
            pair = {}
            for side in ('before', 'after'):
                data = base64.b64decode(row[side + '_raw_base64'], validate=True)
                assert base64.b64encode(data).decode() == row[side + '_raw_base64']
                wanted = row[side]
                assert wanted['path'] == relative
                assert pin(data) == {'bytes': wanted['bytes'], 'sha256': wanted['sha256'], 'git_blob': wanted['working_blob']}
                assert wanted['index_mode'] == '100644' and wanted['permissions'] == 420 and wanted['stable'] is True and wanted['kind'] == 'file'
                assert wanted['matches_index'] == (wanted['index_blob'] == wanted['working_blob'])
                pair[side] = data
                save(stage + '/' + side + '/' + relative, data)
                if stage == 'final':
                    save(side + '/' + relative, data)
            decoded[stage][relative] = pair
            before, after = pair['before'].decode(), pair['after'].decode()
            a, ac = lexer.lex(before); b, bc = lexer.lex(after)
            token_changes = lexer.changed_sequences(a, b)
            comment_changes = lexer.changed_sequences(ac, bc)
            diff = ''.join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                              fromfile='before/' + relative, tofile='after/' + relative))
            diff_pin = save('diffs/' + stage + '/' + Path(relative).name + '.diff', diff.encode())
            stage_diff.append(diff)
            stage_rows.append({
                'path': relative, 'before': pin(pair['before']), 'after': pin(pair['after']),
                'raw_before': row['before'], 'raw_after': row['after'],
                'token_count_before': len(a), 'token_count_after': len(b),
                'tokens_exact_equal': not token_changes, 'comments_exact_equal': not comment_changes,
                'literal_sequences_equal': [x[1] for x in a if x[0] == 'literal'] == [x[1] for x in b if x[0] == 'literal'],
                'token_changes': token_changes, 'comment_changes': comment_changes,
                'diff': diff_pin,
            })
        transitions.append({'stage': stage, 'packet': pin(raw), 'gzip': {k: record[k] for k in ('bytes','sha256','git_blob')},
                            'parts': parts, 'rows': stage_rows,
                            'combined_diff': save(stage + '.SOURCE_DELTA.patch', ''.join(stage_diff).encode())})
        if stage != 'final':
            assert packet['base_inventory_sha256'] == hashlib.sha256(base_raw).hexdigest()
            for row in packet['changes']:
                assert rows[row['path']] == row['before'], (stage, row['path'])
                assert row['after']['index_blob'] == row['before']['index_blob']
                assert row['after']['index_mode'] == row['before']['index_mode']
                rows[row['path']] = row['after']
            base_raw = exact_inventory(initial, rows)
            phase = next(r for r in result['stages'] if r['name'] == stage.split('.')[0])
            assert pin(base_raw) == phase['retention']['inventory'], stage
            assert hashlib.sha256(base_raw).hexdigest() == packet['after_inventory_sha256']
            expected_tree = phase['retention']['postimages']['all_actual_physical_tree']
            assert merkle(rows.values()) == expected_tree
            assert sorted(r['path'] for r in packet['changes']) == phase['retention']['postimages']['paths']
            inventory_records.append({'stage': stage, 'recovery': save(stage + '.inventory.exact_recovered.json', base_raw),
                                      'physical_tree': expected_tree, 'not_a_second_native_full_read': True})

    original_rows = {r['path']: r for r in initial['files']}
    final = packets['final']
    assert final['base_inventory_sha256'] == pin(BASE.read_bytes())['sha256']
    assert final['after_inventory_sha256'] == pin(base_raw)['sha256']
    changed = sorted(p for p in rows if rows[p] != original_rows[p])
    assert changed == sorted(r['path'] for r in final['changes'])
    for row in final['changes']:
        path = row['path']
        assert row['before'] == original_rows[path] and row['after'] == rows[path]
        for stage in ('fix.after', 'fmt.after'):
            if path in decoded[stage]:
                if stage == 'fix.after':
                    assert decoded['final'][path]['before'] == decoded[stage][path]['before']
                if stage == 'fmt.after' or path not in decoded['fmt.after']:
                    assert decoded['final'][path]['after'] == decoded[stage][path]['after']
        if path in decoded['fix.after'] and path in decoded['fmt.after']:
            assert decoded['fix.after'][path]['after'] == decoded['fmt.after'][path]['before']
        if path not in decoded['fix.after']:
            assert decoded['final'][path]['before'] == decoded['fmt.after'][path]['before']
    assert pin(base_raw) == result['actual_final_source']['inventory']
    assert changed == result['actual_final_source']['postimages']['paths']
    final_tree = merkle(rows.values())
    assert final_tree == result['actual_final_source']['postimages']['all_actual_physical_tree'] == 'c026a8d7e93c958b39a36c666debecb3dba4be14'
    save('final.inventory.exact_recovered.json', base_raw)
    # Every actual original inventory alias and original format part is checked.
    alias_proofs = []
    inventory_by_sha = {pin(BASE.read_bytes())['sha256']: BASE.read_bytes()}
    for item in inventory_records:
        raw = Path(item['recovery']['path']).read_bytes()
        inventory_by_sha[pin(raw)['sha256']] = raw
    for record in artifact_doc['files']:
        if record.get('raw_sha256') not in inventory_by_sha:
            continue
        raw = inventory_by_sha[record['raw_sha256']]
        assert pin(raw) == {'bytes':record['raw_bytes'],'sha256':record['raw_sha256'],'git_blob':record['raw_git_blob']}
        gz = gzip.compress(raw,mtime=0)
        assert pin(gz)=={k:record[k]for k in ('bytes','sha256','git_blob')}
        actual_parts = []
        for i, offset in enumerate(range(0,len(gz),262144),1):
            block=gz[offset:offset+262144]; encoded=base64.b64encode(block)+b'\n';part=record['parts'][i-1]
            assert part==artifacts[part['name']]
            assert pin(encoded)=={k:part[k]for k in ('bytes','sha256','git_blob')}
            assert (part['decoded_offset'],part['decoded_bytes'],part['decoded_sha256'])==(offset,len(block),hashlib.sha256(block).hexdigest())
            actual_parts.append({'name':part['name'],**pin(encoded)})
            if record['name'].startswith('final.'):
                save('final-inventory-parts/'+part['name'],encoded)
        alias_proofs.append({'artifact_name':record['name'],'raw':pin(raw),'gzip':pin(gz),'parts':actual_parts,'full_match':True})
    log = fixed(RUNTIME / 'fix.raw.log.exact_extracted.txt','3fd1317daf9db7c84fe0956cbf75c8571cc7e80e')
    assert pin(log)=={k:artifacts['fix.raw.log'][k]for k in ('bytes','sha256','git_blob')}
    save('inputs/fix.raw.log.exact_extracted.txt',log)
    for path, wanted in inputs.items():
        assert pin(Path(path).read_bytes()) == wanted
    report = {
        'format':'hepta-a489-actual-maintenance-source-byte-lexical-review-v1',
        'status':'ACTUAL_BYTE_CHAIN_VERIFIED_SEMANTIC_REVIEW_PENDING',
        'source_commit':SOURCE,'initial_tree':TREE,'final_physical_tree':final_tree,
        'input_files':[{'path':path,**value}for path,value in inputs.items()],
        'actual_stage_counts':{'fix':12,'fmt':14,'union':17},
        'all_initial_to_fix_to_fmt_to_final_rows_and_raw_bytes_equal':True,
        'all_other_source_rows_equal':True,'leaf_count':15243,
        'exact_inventory_recoveries':inventory_records,'inventory_artifact_aliases':alias_proofs,
        'source_status_provenance':'Unique original porcelain tracked-modification candidate with original stdout.strip; accepted only on complete actual raw/gzip/all-part identity equality, not claimed a new native status read.',
        'not_a_rust_parser_or_execution_test':True,
        'transitions':transitions,
        'raw_log_provenance':'Actual supervisor stdout unique 862..118383 slice, exactly matching original ARTIFACTS raw log identity; not a second native logfile read.',
        'tests_executed_by_this_review':0,'H_calls':0,'source_worktree_or_ref_writes':0,
        'qualification':False
    }
    data=dump(report);save('ACTUAL_BYTE_AND_LEXICAL_REVIEW.json',data)
    concise=[]
    for stage in transitions:
        concise.append({'stage':stage['stage'],'paths':len(stage['rows']),
          'exact_tokens':sum(r['tokens_exact_equal']for r in stage['rows']),
          'literal_drift':[r['path']for r in stage['rows']if not r['literal_sequences_equal']],
          'token_changes':[{'path':r['path'],'hunks':len(r['token_changes'])}for r in stage['rows']if r['token_changes']],
          'comments_changed':[r['path']for r in stage['rows']if not r['comments_exact_equal']]})
    print(json.dumps({'report':pin(data),'stages':concise,'final_inventory':pin(base_raw),'physical_tree':final_tree,'inventory_aliases':len(alias_proofs)},indent=2))


if __name__ == '__main__':
    main()

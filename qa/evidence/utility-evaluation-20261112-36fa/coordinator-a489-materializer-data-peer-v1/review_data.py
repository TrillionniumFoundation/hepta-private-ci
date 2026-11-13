#!/usr/bin/env python3
"""Independent, read-only data audit. No imports of project code or driver main.

Only JSON, strict base64/gzip, complete source bytes, typed Git identities and a
standalone mode-aware Merkle implementation are used. Outputs go beside this
script with exclusive creation. No Git commands, network, H or subprocesses.
"""
from __future__ import annotations

import base64
import collections
import hashlib
import json
from pathlib import Path, PurePosixPath
import zlib

HERE = Path(__file__).resolve().parent
NATIVE = Path('/tmp/hepta-36fa-coordinator-a489-materializer-hold-v1')
GRAPH = Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1')
OLD = Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1')
ROOT = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
EXPECTED = GRAPH / 'expected-inventory-v1'
HEAD = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
TREE = 'a489b394666b8141840275128a780605b024cde0'
CC57 = 'cc57c7198db6293ccca562253c42fffbe2a04633'
CC57_TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
C0F = 'c0f78493f815780f68b9bf5e390a21314d79311f'
C0F_TREE = '313ee34febc8ccc54c611ab56286e289518c63cb'
PARENT = '246d8cb614770252ee42029a5c014f2a4904176a'
PARENT_TREE = 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
PART_LIMIT = 524288
TYPED_LIMIT = 1048576
REMOTE_PARENT = '/home/qian-qi/hepta-utility-36fa-evidence'
REMOTE_PREFIX = REMOTE_PARENT + '/provider-coordinator-a489-materialization-v1'
inputs = {}
checks = 0


def check(value, label):
    global checks
    checks += 1
    if not value:
        raise AssertionError(label)


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': oid('blob', raw)}


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')) + '\n').encode()


def pairs_unique(pairs):
    result = {}
    for key, value in pairs:
        check(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs_unique)


def read(path, expected_blob=None, expected_pin=None):
    raw = path.read_bytes()
    actual = pin(raw)
    if expected_blob is not None:
        check(actual['git_blob'] == expected_blob, 'fixed reference identity: ' + str(path))
    if expected_pin is not None:
        check(actual == expected_pin, 'complete reference pin: ' + str(path))
    key = str(path)
    check(key not in inputs or inputs[key] == actual, 'input changed during read: ' + key)
    inputs[key] = actual
    return raw


def b64(text):
    check(isinstance(text, str) and text.isascii(), 'base64 text is ASCII')
    raw = base64.b64decode(text, validate=True)
    check(base64.b64encode(raw).decode() == text, 'base64 has canonical complete representation')
    return raw


def gunzip(raw):
    stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
    unpacked = stream.decompress(raw) + stream.flush()
    check(stream.eof and not stream.unused_data and not stream.unconsumed_tail,
          'one complete gzip member, no concatenated member or trailing bytes')
    return unpacked


def project(row):
    return {'path': row['path'], 'mode': row['index_mode'], 'bytes': row['bytes'],
            'sha256': row['sha256'], 'blob': row['working_blob']}


def native_projection(rows):
    return json.dumps(sorted(map(project, rows), key=lambda x: x['path'].encode()),
                      sort_keys=True, separators=(',', ':')).encode()


def unique_by(rows, key, label):
    result = {row[key]: row for row in rows}
    check(len(result) == len(rows), label + ': unique keys')
    return result


def add_object(objects, sha, meta):
    check(sha not in objects or objects[sha] == meta, 'same typed OID has identical metadata')
    objects[sha] = meta


def metadata(kind, raw):
    return {'type': kind, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def checked_objects(rows, label):
    objects, bodies = {}, {}
    for item in rows:
        check(item['type'] in ('blob', 'tree', 'commit'), label + ': allowed object type')
        raw = b64(item['raw_base64'])
        check(oid(item['type'], raw) == item['sha'], label + ': actual typed Git OID')
        meta = metadata(item['type'], raw)
        check(meta == {key: item[key] for key in ('type', 'bytes', 'sha256')}, label + ': full raw identity')
        check(item['sha'] not in objects, label + ': no duplicate object')
        objects[item['sha']], bodies[item['sha']] = meta, raw
    return objects, bodies


def safe_path(path):
    parts = path.split('/')
    check(isinstance(path, str) and path and not path.startswith('/') and
          all(part not in ('', '.', '..') and '\0' not in part for part in parts),
          'canonical relative source path')
    return parts


def merkle(rows):
    """Independent Git tree construction, including executable/symlink modes."""
    directories = {'': {}}
    files = unique_by(rows, 'path', 'complete source graph')
    for path, row in files.items():
        check(row['mode'] in ('100644', '100755', '120000'), 'retained leaf mode')
        parts = safe_path(path)
        current = ''
        for part in parts[:-1]:
            child = '/'.join(filter(None, (current, part)))
            existing = directories[current].get(part)
            check(existing is None or existing == ('tree', child), 'no file/directory collision')
            directories[current][part] = ('tree', child)
            directories.setdefault(child, {})
            current = child
        check(parts[-1] not in directories[current], 'unique tree entry')
        directories[current][parts[-1]] = ('leaf', row)
    result = {}
    for directory in sorted(directories, key=lambda x: (-len(x.split('/')) if x else 0, x.encode())):
        entries = []
        for name, (kind, value) in directories[directory].items():
            if kind == 'tree':
                entries.append((name.encode() + b'/', b'40000', name.encode(), result[value]['sha']))
            else:
                entries.append((name.encode() + b'\0', value['mode'].lstrip('0').encode(), name.encode(), value['blob']))
        raw = b''.join(mode + b' ' + name + b'\0' + bytes.fromhex(sha)
                       for _, mode, name, sha in sorted(entries))
        result[directory] = {'sha': oid('tree', raw), 'raw': raw}
    return result['']['sha'], result


def snapshot(rows, commit_raw, expected_head, expected_tree, parents):
    check(oid('commit', commit_raw) == expected_head, 'snapshot commit typed identity')
    header = commit_raw.split(b'\n\n', 1)[0].split(b'\n')
    check(header[0] == ('tree ' + expected_tree).encode(), 'snapshot root tree in raw commit')
    check([line[7:].decode() for line in header if line.startswith(b'parent ')] == parents,
          'raw commit exact ordered parents')
    leaves = list(map(project, rows))
    root, trees = merkle(leaves)
    check(root == expected_tree, 'independent complete snapshot Merkle root')
    objects = {}
    for row in rows:
        check(row['matches_index'] is True and row['index_blob'] == row['working_blob'], 'clean inventory row')
        check(row['stable'] is True, 'inventory stability flag retained')
        add_object(objects, row['working_blob'], {'type': 'blob', 'bytes': row['bytes'], 'sha256': row['sha256']})
    for tree in trees.values():
        add_object(objects, tree['sha'], metadata('tree', tree['raw']))
    add_object(objects, expected_head, metadata('commit', commit_raw))
    return objects, trees


def counts(objects):
    return dict(sorted(collections.Counter(row['type'] for row in objects.values()).items()))


def identities(objects):
    return [{'sha': sha, **objects[sha]} for sha in sorted(objects)]


def write(name, value):
    raw = encoded(value)
    with (HERE / name).open('xb') as handle:
        handle.write(raw)
    return pin(raw)


def main():
    packet_raw = read(NATIVE / 'MATERIALIZATION_PACKET.HOLD.json', 'b05c78c478bbd55219fea7869b1c7871617509c7')
    packet = parse(packet_raw)
    staging_raw = read(NATIVE / 'STAGING_MANIFEST.HOLD.json', '0b218906e689a212147853f3d2a27f69ccae4788')
    staging = parse(staging_raw)
    check(staging['input_packet'] == pin(packet_raw), 'staging binds exact materialization packet')
    check(packet['qualification'] is False and packet['expected_not_native_observed'] is True,
          'packet remains expected, not execution or qualification')
    check(staging['native_calls_made'] == 0 and staging['status'] == 'HOLD_NO_H_EXECUTION_APPROVAL', 'staging remains HOLD')
    check(staging['file_count'] == 5 and len(staging['files']) == 5, 'exact 2+3 writes')
    check(staging['required_parent'] == REMOTE_PARENT and staging['parent_creation_command'] is None,
          'no parent creation command in staging')
    check(staging['not_process_requests'] is True and staging['separate_materialization_request_approval_still_required'] is True,
          'write requests do not constitute materialization approval')

    staged, packages, transfer = {}, {}, []
    expected_names = []
    stage_by_path = unique_by(staging['files'], 'path', 'staging destination')
    unique_by(staging['files'], 'name', 'staging request file')
    for label, count in [('base', 2), ('candidate', 3)]:
        spec = packet['provided_inputs'][label]
        check(spec['maximum_decoded_part'] == PART_LIMIT and len(spec['parts']) == count, 'original part limit/count')
        cursor, chunks = 0, []
        for number, part in enumerate(spec['parts'], 1):
            name = f'STAGE_{label.upper()}_{number:03d}.REQUEST.HOLD.json'
            expected_names.append(name)
            local_part = NATIVE / f'{label.upper()}.json.gz.part-{number:03d}'
            remote_path = f'{REMOTE_PREFIX}-{label}.json.gz.part-{number:03d}'
            check(part['path'] == remote_path and PurePosixPath(remote_path).parent.as_posix() == REMOTE_PARENT,
                  'fixed unique path directly under existing parent')
            check(part['offset'] == cursor and part['mode'] == 0o600, 'contiguous original part offsets and declared mode')
            record = stage_by_path[remote_path]
            check(record['name'] == name and record['host'] == 'desktop' and
                  record['expected_version'] == 'absent' and record['expected_mode'] == 0o600, 'manifest create-only fields')
            raw_request = read(NATIVE / name, expected_pin=record['request'])
            check(len(raw_request) <= TYPED_LIMIT, 'complete serialized typed request <= 1 MiB')
            request = parse(raw_request)
            check(set(request) == {'data_base64', 'expected_version', 'host', 'path'}, 'exact four typed write fields')
            check(request['host'] == 'desktop' and request['expected_version'] == 'absent' and request['path'] == remote_path,
                  'typed create-only destination')
            decoded = b64(request['data_base64'])
            check(0 < len(decoded) <= PART_LIMIT, 'decoded body <= 524288')
            check(decoded == read(local_part), 'full request decoded body equals fixed local part')
            check(pin(decoded) == {k: part[k] for k in ('bytes', 'sha256', 'git_blob')} == record['decoded'] and
                  len(decoded) == record['decoded_bytes'], 'request/part/manifest full pins all equal')
            check(remote_path not in staged, 'no destination reused')
            staged[remote_path] = pin(decoded)
            cursor += len(decoded)
            chunks.append(decoded)
            transfer.append({'name': name, 'path': remote_path, 'offset': part['offset'], 'mode_expected': part['mode'],
                             'request': pin(raw_request), 'decoded': pin(decoded), 'host': request['host'],
                             'expected_version': request['expected_version']})
        packed = b''.join(chunks)
        check(pin(packed) == spec['gzip'] and cursor == spec['gzip']['bytes'], 'complete gzip concatenation identity')
        raw = gunzip(packed)
        check(pin(raw) == spec['raw'], 'complete decompressed raw identity')
        packages[label] = {'raw': raw, 'gzip': packed, 'value': parse(raw)}
    check([r['name'] for r in staging['files']] == expected_names, 'explicit base001/base002/candidate001/002/003 order')
    check(max(r['request']['bytes'] for r in transfer) == staging['max_actual_typed_bytes'] == 699256 and
          max(r['decoded']['bytes'] for r in transfer) == staging['max_actual_decoded_bytes'] == PART_LIMIT,
          'manifest maxima from complete actual request bodies')
    candidate_raw = read(NATIVE / 'CANDIDATE_OBJECT_INPUT.json', expected_pin=packet['provided_inputs']['candidate']['raw'])
    check(packages['candidate']['raw'] == candidate_raw, 'candidate staging yields exact complete input')
    check(packages['candidate']['gzip'] == read(NATIVE / 'CANDIDATE_OBJECT_INPUT.json.gz'), 'candidate gzip local full bytes')
    check(packages['base']['raw'] == read(OLD / 'BASE_OBJECT_INPUT.json', '26a1d658112e58531b710ab9fb50ed93f50d1afe'),
          'original c0f provided payload is byte unchanged')
    check(packages['base']['gzip'] == read(OLD / 'BASE_OBJECT_INPUT.json.gz', '91b63310e61ac23156731532cba400ce9e7b998e'),
          'original c0f gzip is byte unchanged')
    candidate, base = packages['candidate']['value'], packages['base']['value']
    check(candidate['native_execution'] is False and candidate['qualification'] is False and
          candidate['canonical_source_deletions'] == [], 'candidate remains prepared without canonical deletes')

    overlay_raw = read(GRAPH / 'EXACT_COMPOSED_OVERLAY.json', '9f6949a4b9fd6573f694ae20aa130453bebae00c')
    graph_raw = read(GRAPH / 'CANDIDATE_FILE_GRAPH.json', '097282896b5881614498faf2231e4c8c0da393c3')
    plan_raw = read(GRAPH / 'TREE_OBJECT_PLAN.json', '2a4a3f3330ac032e7e3d09c74e02f4449450dde5')
    overlay, graph, plan = parse(overlay_raw), parse(graph_raw), parse(plan_raw)
    check(candidate['reviewed_overlay'] == packet['overlay']['identity'] == pin(overlay_raw) and
          candidate['complete_leaf_graph'] == pin(graph_raw), 'candidate binds independent frozen overlay/complete graph')
    donor_raw = read(OLD / 'CC57_INVENTORY.json', '7f94788b70546a8b8030dfd2b9182a7d9287c537')
    expected_raw = read(EXPECTED / 'EXPECTED_CLEAN_INVENTORY.json', 'f1e2d72f99093581403a2dcc91b55da22a33f905')
    expected_native = read(EXPECTED / 'EXPECTED_NATIVE_FIVE_FIELD.json', '7647480c5ed06525e1661ac451d0ac0ff2b23ea7')
    donor, expected = parse(donor_raw), parse(expected_raw)
    check(expected_raw == read(NATIVE / 'EXPECTED_CANDIDATE.complete.inventory.json') and
          expected_native == read(NATIVE / 'EXPECTED_CANDIDATE.native-five-field.inventory.json'),
          'both complete expected inventories equal our independently frozen bytes')
    check(pin(expected_raw) == packet['current']['inventory'] and pin(expected_native) == packet['current']['native_inventory'],
          'current inventory full pins')
    check(native_projection(expected['files']) == expected_native and
          pin(native_projection(donor['files'])) == packet['donor']['native_inventory'], 'original five-field serializer reproduced')
    check(expected['source'] == {'head': HEAD, 'tree': TREE, 'status': ''} and
          donor['source'] == {'head': CC57, 'tree': CC57_TREE, 'status': ''}, 'exact clean expected and historical source identities')
    check(expected['filesystem_entries'] == expected['tracked_entries'] == len(expected['files']) == 15243 and
          donor['filesystem_entries'] == donor['tracked_entries'] == len(donor['files']) == 15188, 'complete actual expected row counts')
    before = unique_by(donor['files'], 'path', 'canonical donor')
    after = unique_by(expected['files'], 'path', 'complete candidate')
    check({r['path']: {**project(r), 'kind': r['kind']} for r in expected['files']} ==
          {r['path']: {'path': r['path'], 'mode': r['mode'], 'bytes': r['bytes'], 'sha256': r['sha256'],
                       'blob': r['git_blob'], 'kind': r['kind']} for r in graph['files']}, 'full graph versus expected rows')
    coverage = sorted(overlay['rust_files'] + overlay['non_rust_prepared'], key=lambda x: x['path'].encode())
    check(len(coverage) == len(candidate['covered_paths']) == 119, '119 covered source paths')
    check([r['path'] for r in coverage] == [r['path'] for r in candidate['covered_paths']], 'complete ordered coverage equality')
    unique_by(coverage, 'path', 'reviewed source overlay')
    candidate_objects, candidate_bodies = checked_objects(candidate['objects'], 'candidate provided objects')
    check(len(candidate_objects) == 129 and counts(candidate_objects) == {'blob': 118, 'commit': 1, 'tree': 10},
          'provided objects are exactly 118+10+1')
    required_blobs, coverage_proof = {}, []
    classification = collections.Counter()
    for source, change in zip(coverage, candidate['covered_paths']):
        path = source['path']
        original, final = before.get(path), after[path]
        check(change == {'path': path, 'before': original, 'after': final}, 'full covered before/after exact equality: ' + path)
        check((original['working_blob'] if original else None) == source['original_git_blob'], 'canonical source before OID')
        body = read(GRAPH / 'overlay' / path,
                    expected_pin={key: source[key] for key in ('bytes', 'sha256', 'git_blob')})
        check(pin(body) == {'bytes': final['bytes'], 'sha256': final['sha256'], 'git_blob': final['working_blob']} and
              final['index_mode'] == source['mode'] and final['kind'] == source['kind'], 'full covered source bytes/mode/kind')
        status = 'new' if original is None else 'unchanged' if original == final else 'modified'
        classification[status] += 1
        if status != 'unchanged':
            check(candidate_bodies[final['working_blob']] == body and candidate_objects[final['working_blob']]['type'] == 'blob',
                  'provided changed blob equals complete frozen source raw')
            required_blobs[final['working_blob']] = metadata('blob', body)
        coverage_proof.append({'path': path, 'classification': status, 'before_blob': original['working_blob'] if original else None,
                               'after': pin(body), 'mode': final['index_mode']})
    check(dict(classification) == {'modified': 63, 'new': 55, 'unchanged': 1}, 'exact 119 coverage classifications')
    check(required_blobs == {k: v for k, v in candidate_objects.items() if v['type'] == 'blob'}, 'no missing/extra candidate blob')
    covered = {r['path'] for r in coverage}
    check(set(before) <= set(after) and all(after[path] == before[path] for path in set(before) - covered),
          'all uncovered canonical rows unchanged; no canonical deletion')
    check(set(after) - set(before) == {r['path'] for r in coverage if r['original_git_blob'] is None}, 'exact new path set')
    check(overlay['canonical_source_deletions'] == overlay['materializer_delete_operations'] == plan['canonical_source_deletions'] ==
          packet['overlay']['canonical_source_deletions'] == [], 'no sha:null or nonexistent canonical deletion')
    modes = dict(sorted(collections.Counter(r['index_mode'] for r in after.values()).items()))
    check(modes == {'100644': 15152, '100755': 90, '120000': 1}, 'full mode-aware candidate counts')
    check(all(after[p] == before[p] for p in before if before[p]['index_mode'] in ('100755', '120000')),
          'all 90 executable and one symlink complete rows unchanged')

    original_packet_raw = read(OLD / 'MATERIALIZER_PACKET.original.json', '06503652a2895120daf8b66e42b3a01cefeaf4fb')
    original_packet = parse(original_packet_raw)
    check(packet['parent_snapshot'] == original_packet['parent_snapshot'] and
          packet['seed_raw_commits'] == original_packet['raw_commits'], 'original donor/parent closure sources unchanged')
    check({k: packet['donor'][k] for k in original_packet['current']} == original_packet['current'] and
          pin(donor_raw) == packet['donor']['inventory'], 'original donor complete pins/identity unchanged')
    seed_objects, seed_bodies = checked_objects(packet['seed_raw_commits'], 'original seed commit raw')
    donor_objects, donor_trees = snapshot(donor['files'], seed_bodies[CC57], CC57, CC57_TREE, [PARENT])
    parent_rows = {p: dict(r) for p, r in before.items()}
    for change in original_packet['parent_snapshot']['changes_from_current']:
        row = parent_rows[change['path']]
        check({'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']} == change['current'] and
              row['index_mode'] == change['mode'], 'original parent delta full preimage')
        row.update(bytes=change['parent']['bytes'], sha256=change['parent']['sha256'],
                   index_blob=change['parent']['git_blob'], working_blob=change['parent']['git_blob'])
    parent_objects, parent_trees = snapshot(list(parent_rows.values()), seed_bodies[PARENT], PARENT, PARENT_TREE,
                                           ['9c4a11f61d30e9cc352bf44d56c98909d202a55d'])
    donor_union = dict(donor_objects)
    for sha, meta in parent_objects.items():
        add_object(donor_union, sha, meta)
    check(len(donor_union) == 16449 and counts(donor_union) == {'blob': 14615, 'commit': 2, 'tree': 1832},
          'complete original donor two-snapshot object union')
    declared_donor_raw = read(NATIVE / 'EXPECTED_DONOR_OBJECT_IDENTITIES.json', '5f8f35dca6e43575f6e801a59f8aa4169faea157')
    check(encoded(identities(donor_union)) == declared_donor_raw, 'all 16449 donor typed identity rows exact')

    commit_raw = read(ROOT / 'CANDIDATE_D2567544_COMMIT.raw', '39f1402eb842b1f005dc69206f1597fc2af0d3f1')
    check(commit_raw == read(NATIVE / 'CANDIDATE_COMMIT.raw.txt') == candidate_bodies[HEAD] and len(commit_raw) == 935,
          'provided commit equals actual Root raw full bytes')
    actual_binding = parse(read(ROOT / 'ROOT_CANDIDATE_D2567544_BINDING.json', '95fc07932d225633d75b7fa93528fe17af8b930d'))
    candidate_snapshot, candidate_trees = snapshot(expected['files'], commit_raw, HEAD, TREE, [CC57])
    changed_tree_raw = {item['sha']: item['raw'] for item in candidate_trees.values()
                        if item['sha'] not in {v['sha'] for v in donor_trees.values()}}
    check(len(changed_tree_raw) == len(plan['trees']) == 10, 'exact ten changed complete directory trees')
    for item in plan['trees']:
        raw = b64(item['raw_base64'])
        check(raw == changed_tree_raw[item['sha']] == candidate_bodies[item['sha']] and pin(raw) == item['raw'],
              'planned/provided/independently rebuilt complete typed tree raw')
    check({k for k, v in candidate_objects.items() if v['type'] == 'tree'} == set(changed_tree_raw), 'no extra or missing candidate tree')
    check(candidate['candidate_commit'] == packet['current']['commit'] == HEAD and
          candidate['candidate_tree'] == packet['current']['tree'] == TREE and
          candidate['candidate_parents'] == packet['current']['parents'] == [CC57] and
          candidate['donor_commit'] == CC57, 'candidate current identity exactly bound')

    c0f_raw = read(OLD / 'C0F_INVENTORY.json', '5ed18452e2e967281ac368f934b9e4358627b9d3')
    c0f = parse(c0f_raw)
    closure_raw = read(OLD / 'C0F_CLOSURE_IDENTITIES.json', 'b4a90055e3dc64d24dcc17ba96695ba0c9ce25ac')
    closure = parse(closure_raw)
    check(pin(closure_raw) == base['complete_closure_identity_manifest'] and pin(c0f_raw) == base['base']['inventory'],
          'original full format-base closure/inventory fixed pins')
    base_objects, base_bodies = checked_objects(base['objects'], 'provided original c0f base')
    c0f_parents = ['e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd', 'b29869e856d08db1bfb066116a9c443376ccc57d']
    c0f_objects, c0f_trees = snapshot(c0f['files'], base_bodies[C0F], C0F, C0F_TREE, c0f_parents)
    check(len(c0f['files']) == 14851 and len(c0f_objects) == 16094 and
          counts(c0f_objects) == {'blob': 14315, 'commit': 1, 'tree': 1778}, 'complete original format-base snapshot')
    check(unique_by([{k: r[k] for k in ('sha', 'type', 'bytes', 'sha256')} for r in closure['objects']], 'sha', 'legacy c0f closure') ==
          unique_by(identities(c0f_objects), 'sha', 'recomputed c0f closure'), 'all original c0f closure identities independently recomputed')
    check(set(c0f_objects) - set(donor_union) == set(base_objects) and len(base_objects) == 83 and
          len(set(c0f_objects) & set(donor_union)) == 16011 and base['provided_count'] == 83 and base['required_existing_count'] == 16011,
          'unchanged 83 provided plus 16011 reused base closure')
    check(all(c0f_objects[key] == meta for key, meta in base_objects.items()), 'all provided c0f objects belong to complete original snapshot')
    check(packet['format_base']['inventory'] == pin(c0f_raw) and
          packet['format_base']['leaf_projection'] == pin(native_projection(c0f['files'])) and
          packet['format_base']['commit'] == C0F and packet['format_base']['tree'] == C0F_TREE and
          packet['format_base']['parents'] == c0f_parents and packet['format_base']['counts'] == counts(c0f_objects),
          'format-base full packet projection and snapshot identity')
    union = dict(donor_union)
    for objects in (c0f_objects, candidate_snapshot):
        for sha, meta in objects.items():
            add_object(union, sha, meta)
    supplied_union = dict(donor_union)
    for objects in (base_objects, candidate_objects):
        for sha, meta in objects.items():
            add_object(supplied_union, sha, meta)
    check(union == supplied_union and len(union) == 16661 and counts(union) == {'blob': 14805, 'commit': 4, 'tree': 1852},
          'four complete snapshots equal exactly all reused and supplied objects')
    check(not (set(candidate_objects) & (set(base_objects) | set(donor_union))) and not (set(base_objects) & set(donor_union)),
          'provided base/candidate and reused donor are disjoint')
    union_raw = read(NATIVE / 'EXPECTED_OBJECT_IDENTITIES.json', '1a6ed5b28442d83b061019957fee98780fafb569')
    check(encoded(identities(union)) == union_raw, 'all 16661 union identity rows exact')
    check(packet['object_scope'] == {
        'format': 'four-complete-snapshots-not-full-ancestry',
        'complete_snapshot_commits': [HEAD, CC57, PARENT, C0F], 'reused_donor_objects': 16449,
        'provided_base_objects': 83, 'provided_candidate_objects': 129, 'provided_base_candidate_overlap': [],
        'union_objects': 16661, 'counts': {'blob': 14805, 'commit': 4, 'tree': 1852},
        'unmaterialized_parent_boundaries': ['9c4a11f61d30e9cc352bf44d56c98909d202a55d', *c0f_parents],
        'no_network': True, 'no_fsck': True, 'no_recursive_ancestor_walk': True}, 'exact bounded snapshot graph declaration')
    check(not (set(packet['object_scope']['unmaterialized_parent_boundaries']) & set(union)),
          'three ancestor boundaries remain explicitly unmaterialized')
    for path, original in inputs.items():
        check(pin(Path(path).read_bytes()) == original, 'all read inputs unchanged at audit end')

    proof = {
        'format': 'hepta-independent-materializer-pure-data-reconciliation-v1',
        'status': 'NO_CONCRETE_DATA_OR_STAGING_BLOCKER_FOUND',
        'scope': 'Data objects, complete before/after rows, four snapshot closures and five typed create-only writes only.',
        'packet': pin(packet_raw), 'staging_manifest': pin(staging_raw), 'candidate_input': pin(candidate_raw),
        'expected_inventory': pin(expected_raw), 'expected_native_projection': pin(expected_native),
        'root_actual_commit_raw': pin(commit_raw), 'root_actual_typed_commit': HEAD,
        'coverage': {'total': 119, 'classifications': dict(classification), 'full_rows': coverage_proof},
        'provided_candidate_objects': {'count': len(candidate_objects), 'types': counts(candidate_objects),
                                       'identities': identities(candidate_objects)},
        'snapshot_roots': {'candidate': TREE, 'donor': CC57_TREE, 'parent': PARENT_TREE, 'format_base': C0F_TREE},
        'candidate_mode_counts': modes, 'candidate_leaves': len(after),
        'donor_union': {'count': len(donor_union), 'counts': counts(donor_union), 'complete_identities': pin(declared_donor_raw)},
        'format_base': {'count': len(c0f_objects), 'counts': counts(c0f_objects), 'provided': len(base_objects), 'reused': 16011},
        'union': {'count': len(union), 'counts': counts(union), 'complete_identities': pin(union_raw)},
        'stage_requests': transfer,
        'staged_packages': {label: {'raw': pin(value['raw']), 'gzip': pin(value['gzip'])} for label, value in packages.items()},
        'checks_completed': checks, 'input_files': [{'path': p, **inputs[p]} for p in sorted(inputs)],
        'source_or_control_writes': 0, 'H_calls': 0, 'project_gate_calls': 0, 'Git_tree_commit_ref_operations': 0,
        'runtime_materialization_observed': False, 'qualification': False,
        'limits': [
            'This does not inspect or approve main driver/bootstrap execution or authority guard semantics; those have separate reviewers.',
            'No remote staging path has been probed here. Expected absent/create-only and expected mode0600 are request contracts, not observations of path absence or resulting mode.',
            'Reused donor blob bytes are bound to the original complete inventory and snapshot closure. This is not a fresh native full-object read; runtime must still verify the actual donor and staged payloads.',
            'Complete snapshots include tree/blob closure and their authentic commit bodies, not recursively materialized ancestor history.',
            'Actual source reference is not changed. These expected data do not provide maintenance, tests, source qualification or a real task-chain result.'
        ]
    }
    proof_pin = write('DATA_RECONCILIATION.json', proof)
    print(json.dumps({'status': proof['status'], 'proof': proof_pin, 'checks': checks,
                      'candidate_objects': len(candidate_objects), 'covered': len(coverage), 'union': len(union),
                      'stage_requests': len(transfer), 'maximum_typed': staging['max_actual_typed_bytes']}, sort_keys=True))


if __name__ == '__main__':
    main()

"""Freeze complete handed-off originals and reviews; no H/source/ref operations."""
from pathlib import Path
import base64
import datetime
import gzip
import hashlib
import json

OUT = Path('/tmp/hepta-36fa-post3454-evidence-preparation-v1')
BASE = Path('/tmp/hepta-36fa-post3328-evidence-preparation-v1')
PREFIX = 'qa/evidence/utility-evaluation-20261112-36fa/'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def jb(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def stable(path):
    a = path.stat(); raw = path.read_bytes(); b = path.stat()
    assert all(getattr(a, k) == getattr(b, k) for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')), path
    return raw


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(raw)


def fetched_contents(value):
    if isinstance(value, dict):
        if isinstance(value.get('structuredContent'), dict) and isinstance(value['structuredContent'].get('content'), str):
            yield value['structuredContent']['content']
        for child in value.values():
            yield from fetched_contents(child)
    elif isinstance(value, list):
        for child in value:
            yield from fetched_contents(child)


def main():
    base_raw = stable(BASE / 'FULL_FILEMAP.json')
    assert pin(base_raw)['git_blob'] == '5dd29e2d74cf849728aa0e1ca0fdb6d7eba669c6'
    base = json.loads(base_raw)
    assert len(base) == 3454
    prior = json.loads(stable(Path('/tmp/hepta-36fa-cc57-evidence-publication-v1/PUBLISH_PLAN.json')))['files']
    assert len(prior) == 3328 and all(base.get(k) == v for k, v in prior.items())
    rows = {}; duplicates = []; transports = []

    def add_raw(destination, raw, source, kind, expected=None, readbacks=()):
        destination = destination.removeprefix(PREFIX)
        assert not Path(destination).is_absolute() and '..' not in Path(destination).parts
        ident = pin(raw)
        if expected is not None:
            assert ident == expected, (source, ident, expected)
        if destination in base:
            assert base[destination] == ident['git_blob'], ('attempted old path overwrite', destination)
            duplicates.append({'path': destination, 'origin': str(source), **ident})
            return
        if destination in rows:
            assert rows[destination]['git_blob'] == ident['git_blob']
            return
        if len(raw) >= 500000:
            packed = gzip.compress(raw, compresslevel=9, mtime=0)
            parts = []
            for n, offset in enumerate(range(0, len(packed), 262144), 1):
                part = packed[offset:offset + 262144]
                encoded = base64.b64encode(part) + b'\n'
                name = destination + f'.part-{n:03d}.gz.b64'
                add_raw(name, encoded, source, 'lossless_transport_part')
                parts.append({'path': name, 'offset': offset, 'decoded': pin(part), 'encoded': pin(encoded)})
            assert gzip.decompress(b''.join(base64.b64decode((OUT / 'frozen' / x['path']).read_bytes().strip(), validate=True) for x in parts)) == raw
            manifest = {'format': 'hepta-lossless-large-evidence-transport-v1', 'raw': ident,
                        'gzip': pin(packed), 'parts': parts, 'origin': str(source),
                        'scope': 'Exact local bytes encoded for durable transport. Source and observation scope remains that of the original named file; not a new H read or execution.'}
            add_raw(destination + '.transport-manifest.json', jb(manifest), source, 'lossless_transport_manifest')
            transports.append(manifest)
            return
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            encoded = base64.b64encode(raw) + b'\n'
            add_raw(destination + '.base64.txt', encoded, source, 'exact_binary_transport')
            add_raw(destination + '.binary-manifest.json', jb({'raw': ident, 'encoded': pin(encoded),
                    'origin': str(source), 'encoding': 'strict base64 with one final LF'}), source, 'binary_transport_manifest')
            return
        found = []
        candidates = list(map(Path, readbacks))
        if isinstance(source, Path):
            candidates += list(source.parent.glob(source.name + '*GITHUB*.json'))
            candidates += list(source.parent.glob(source.stem + '.GITHUB*.json'))
        for p in dict.fromkeys(candidates):
            if not p.is_file():
                continue
            try:
                value = json.loads(stable(p))
            except (ValueError, UnicodeDecodeError):
                continue
            if any(x == content for x in fetched_contents(value)):
                found.append(str(p))
        known = ident['git_blob'] in base.values()
        frozen = OUT / 'frozen' / destination
        write(frozen, raw)
        rows[destination] = {'path': destination, 'local': str(source), 'frozen_local': str(frozen),
                             **ident, 'kind': kind, 'verified_original_git_readbacks': found,
                             'same_blob_in_prior_verified_map': known,
                             'full_readback_equal': bool(found) or known}

    def add(path, destination, kind, expected=None, readbacks=()):
        path = Path(path)
        add_raw(destination, stable(path), path, kind, expected, readbacks)

    placements = [
        ('/tmp/hepta-36fa-cc57-closure-log-readonly-capture-v1/COMPLETED_PLACEMENT.json', 'cc57-v2-closure-log-readonly-capture/COMPLETED_PLACEMENT.json'),
        ('/tmp/hepta-36fa-cc57-source-inventory-readonly-capture-v1/COMPLETED_PLACEMENT.json', 'cc57-v2-original-inventory-readonly-capture/COMPLETED_PLACEMENT.json'),
        ('/tmp/hepta-36fa-native-gates-cc57-v1/COMPLETED_PLACEMENT.json', 'native-cc57-v1-failed-precondition/COMPLETED_PLACEMENT.json'),
        ('/tmp/hepta-36fa-native-precondition-snapshot-diagnostic-v1/COMPLETED_PLACEMENT.json', 'native-cc57-precondition-readonly-diagnostic-v1/COMPLETED_PLACEMENT.json'),
        ('/tmp/hepta-36fa-native-after-cc57-source-candidate-peer-v1/PLACEMENT.json', 'native-after-cc57-source-candidate-peer-v1/PLACEMENT.json'),
        ('/tmp/hepta-36fa-c0f-focused-pretriage-cc57-v1/PLACEMENT.json', 'c0f-focused-pretriage-cc57-v1/PLACEMENT.json'),
        ('/tmp/hepta-36fa-native-cc57-preflight-independent-review-v1/PLACEMENT.json', 'native-cc57-preflight-independent-v1/PLACEMENT.json'),
        ('/tmp/hepta-36fa-root-resident-provider-proposal-v1/PLACEMENT.json', 'root-resident-provider-proposal-v1/PLACEMENT.json'),
        ('/tmp/hepta-36fa-root-provider-independent-review-v1/PLACEMENT.json', 'root-provider-independent-peer-v1/PLACEMENT.json'),
    ]
    for path, destination in placements:
        document = json.loads(stable(Path(path)))
        entries = document.get('files', document.get('entries'))
        assert isinstance(entries, list)
        for r in entries:
            original = r.get('local_path', r.get('local'))
            oid = r.get('git_blob', r.get('sha', r.get('blob')))
            assert original and oid
            expected = {'bytes': r['bytes'], 'sha256': r['sha256'], 'git_blob': oid}
            readbacks = r.get('full_readback_records', [])
            readbacks += [r[k] for k in ('github_original', 'original_git_response') if k in r]
            add(original, r['path'], 'frozen_agent_handoff', expected, readbacks)
        add(path, destination, 'frozen_agent_handoff_index')

    for name in ['MANIFEST.json', 'VERIFIED_INCREMENTAL_ENTRIES.json', 'INCREMENTAL_FILEMAP.json', 'FULL_FILEMAP.json', 'PLACEMENT.json']:
        add(BASE / name, 'post3328-preparation/frozen-handoff/' + name, 'previous_frozen_3454_window_handoff')

    source = Path('/tmp/hepta-36fa-source-qualification-cc57-launch-v2')
    for p in sorted(source.rglob('*')):
        if not p.is_file() or 'GITHUB' in p.name or p.name.endswith('.gz'):
            continue
        relative = p.relative_to(source).as_posix()
        progress = {'STATUS_02.original.json', 'STATUS_03.original.json', 'STDOUT_READ_02.original.json', 'STDOUT_READ_03.original.json', 'STDOUT.part-0000000444-0000003600.log'}
        section = 'progress-through-verify-start/' if relative in progress else 'completed-originals/'
        add(p, 'source-qualification-cc57-v2/' + section + relative, 'complete_source_original_or_original_read_record')

    groups = [
        ('/tmp/hepta-36fa-native-after-cc57-source-candidate-v1', 'native-after-cc57-source-candidate-v1', ['NATIVE_BOOTSTRAP.candidate.py', 'NATIVE_STDIN.candidate.json', 'NATIVE_PROCESS_INPUT.candidate.json', 'FROM_HOLD.diff', 'EXACT_CANDIDATE_REVIEW.json', 'MANIFEST.json']),
        ('/tmp/hepta-36fa-cc57-final-source-root-review-v1', 'cc57-final-source-root-review-v1', ['ROOT_COMPLETE_SOURCE_REVIEW.json', 'verify_complete_source.py', 'verify_complete_source.FIRST_ATTEMPT.py', 'FIRST_COMPLETE_VERIFIER_SCHEMA_OBSERVATION.json', 'ROOT_SOURCE_CORE_REVIEW.json', 'ROOT_EXACT_NATIVE_CANDIDATE_STATIC_REVIEW.json', 'ROOT_EXACT_NATIVE_LAUNCH_APPROVAL.json', 'ROOT_PEER_FULL_READBACK.original.json', 'CLONE_INVENTORY_RECONSTRUCTION_PROPOSAL.json']),
        ('/tmp/hepta-36fa-native-cc57-preflight-investigation-v1', 'native-cc57-preflight-root-v1', ['ROOT_PREFLIGHT_REFUSAL_REVIEW.json', 'ORIGINAL_COMPLETE_STDOUT.log', 'ROOT_ACTUAL_SNAPSHOT_DIFFERENCE_REVIEW.json', 'verify_actual_snapshot_difference.py']),
        ('/tmp/hepta-36fa-native-precondition-snapshot-diagnostic-v1', 'native-cc57-precondition-readonly-diagnostic-v1', ['ROOT_EXACT_READONLY_APPROVAL.json', 'source-after.files.EXACT_RECOVERED.json']),
        ('/tmp/hepta-36fa-cc57-closure-log-readonly-capture-v1', 'cc57-v2-closure-log-readonly-capture', ['ROOT_EXACT_READONLY_CAPTURE_APPROVAL.json']),
        ('/tmp/hepta-36fa-cc57-source-inventory-readonly-capture-v1', 'cc57-v2-original-inventory-readonly-capture', ['ROOT_EXACT_READONLY_CAPTURE_APPROVAL.json']),
    ]
    for directory, prefix, names in groups:
        for name in names:
            add(Path(directory) / name, prefix + '/' + name, 'root_review_original_control_or_exact_material')
    clone = Path('/tmp/hepta-36fa-cc57-final-source-root-review-v1/clone-inventory-exact-material')
    for p in sorted(clone.iterdir()):
        if p.is_file() and 'GITHUB' not in p.name:
            add(p, 'cc57-final-source-root-review-v1/clone-inventory-exact-material/' + p.name, 'exact_clone_material_and_observation_binding')

    add(Path(__file__), 'post3454-preparation/prepare_frozen_increment.py', 'collection_script_not_execution')
    report = {'format': 'hepta-post3454-evidence-selection-v1',
              'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'base_count': 3454, 'base_map': pin(base_raw), 'published_base_head': '15673f01e5248efdecd00fcb06a58ae3dd45d2c0',
              'old_paths_changed': [], 'old_readme_unchanged': True, 'new_paths_before_this_report': len(rows),
              'duplicates_already_exactly_preserved': duplicates, 'lossless_large_originals': len(transports),
              'source_gate_status': 'Three original gates passed; complete raw logs, original inventories and full Root review now included.',
              'native_status': '1cd4 failed precondition; zero behavioral stages. Original unknown_missing_before preserved.',
              'diagnostic_status': '1ce4 completed readonly; seven missing tracked qualification archives and 15181 equal rows, no writer attributed.',
              'provider_status': 'Frozen v1 source proposal plus bounded independent review only; not formatted/compiled/gated or activated.',
              'real_qualified_task_chains': 0, 'H_calls': 0, 'source_or_refs_modified': False,
              'later_recovery_and_provider_v2_excluded': True}
    add_raw('post3454-preparation/SELECTION_REVIEW.json', jb(report), 'offline collection metadata', 'collection_metadata_not_execution')
    write(OUT / 'SELECTED_ROWS.json', jb(list(rows.values())))
    write(OUT / 'SELECTION_REVIEW.json', jb(report))
    write(OUT / 'BASE_3454_FILEMAP.json', base_raw)
    pending = [r for r in rows.values() if not r['full_readback_equal']]
    write(OUT / 'PENDING_GIT_READBACK.json', jb(pending))
    print(json.dumps({'new_paths': len(rows), 'previous_paths_preserved': len(base), 'pending_Git_readbacks': len(pending),
                      'pending_unique_blobs': len({r['git_blob'] for r in pending}), 'large_original_transports': len(transports),
                      'maximum_frozen_bytes': max(r['bytes'] for r in rows.values()), 'duplicate_old_paths': len(duplicates)}))


if __name__ == '__main__':
    main()

"""Freeze completed engineering records only; no H, source or remote-ref actions."""
from pathlib import Path
import base64
import datetime
import gzip
import hashlib
import json

OUT = Path('/tmp/hepta-36fa-post3638-evidence-preparation-v1')
BASE_PLAN = Path('/tmp/hepta-36fa-complete-source-native-refusal-publication-v2/PUBLISH_PLAN.json')
PREFIX = 'qa/evidence/utility-evaluation-20261112-36fa/'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def jb(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def stable(path):
    first = path.stat()
    raw = path.read_bytes()
    last = path.stat()
    assert all(getattr(first, k) == getattr(last, k) for k in
               ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')), path
    return raw


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def full_contents(value):
    if isinstance(value, dict):
        structured = value.get('structuredContent')
        if isinstance(structured, dict) and isinstance(structured.get('content'), str):
            yield structured['content']
        for child in value.values():
            yield from full_contents(child)
    elif isinstance(value, list):
        for child in value:
            yield from full_contents(child)


base = json.loads(stable(BASE_PLAN))['files']
assert len(base) == 3638
assert base['README.md'] == 'beaa457aad524b8f16bc71bc7c2029a65c327b99'
rows = {}
duplicates = []
transports = []
normalizations = []


def add_raw(destination, raw, origin, kind, expected=None, readbacks=()):
    original_destination = destination
    destination = destination.removeprefix(PREFIX)
    old_prefix = 'qualification/hepta-utility-36fa-20261112/'
    if destination.startswith(old_prefix):
        destination = destination.removeprefix(old_prefix)
        normalizations.append({'original': original_destination, 'leaf_relative': destination})
    assert not Path(destination).is_absolute() and '..' not in Path(destination).parts
    ident = pin(raw)
    if expected is not None:
        assert ident == expected, (origin, ident, expected)
    if destination in base:
        assert base[destination] == ident['git_blob'], ('old path overwrite', destination)
        duplicates.append({'path': destination, 'origin': str(origin), **ident})
        return
    if destination in rows:
        assert rows[destination]['git_blob'] == ident['git_blob'], destination
        return
    if len(raw) >= 500000:
        packed = gzip.compress(raw, compresslevel=9, mtime=0)
        parts = []
        for n, start in enumerate(range(0, len(packed), 262144), 1):
            part = packed[start:start + 262144]
            encoded = base64.b64encode(part) + b'\n'
            name = destination + f'.part-{n:03d}.gz.b64'
            add_raw(name, encoded, origin, 'lossless_transport_part')
            parts.append({'path': name, 'offset': start, 'decoded': pin(part), 'encoded': pin(encoded)})
        restored = gzip.decompress(b''.join(base64.b64decode(
            (OUT / 'frozen' / item['path']).read_bytes().strip(), validate=True) for item in parts))
        assert restored == raw
        manifest = {'format': 'hepta-lossless-large-evidence-transport-v1', 'raw': ident,
                    'gzip': pin(packed), 'parts': parts, 'origin': str(origin),
                    'scope': 'Exact retained bytes, not a new H read or execution.'}
        transports.append(manifest)
        add_raw(destination + '.transport-manifest.json', jb(manifest), origin, 'lossless_transport_manifest')
        return
    text = raw.decode('utf-8')
    candidates = [Path(p) for p in readbacks]
    if isinstance(origin, Path):
        candidates.extend(origin.parent.glob(origin.name + '*GITHUB*.json'))
        candidates.extend(origin.parent.glob(origin.stem + '.GITHUB*.json'))
    found = []
    for p in dict.fromkeys(candidates):
        if not p.is_file():
            continue
        try:
            value = json.loads(stable(p))
        except (ValueError, UnicodeDecodeError):
            continue
        if any(payload == text for payload in full_contents(value)):
            found.append(str(p))
    prior = ident['git_blob'] in base.values()
    frozen = OUT / 'frozen' / destination
    write(frozen, raw)
    rows[destination] = {'path': destination, 'local': str(origin), 'frozen_local': str(frozen),
                         **ident, 'kind': kind, 'verified_original_git_readbacks': found,
                         'same_blob_in_prior_verified_map': prior,
                         'full_readback_equal': bool(found) or prior}


def add(path, destination, kind, expected=None, readbacks=()):
    path = Path(path)
    add_raw(destination, stable(path), path, kind, expected, readbacks)


placements = [
    ('/tmp/hepta-36fa-object-availability-peer-v1/PLACEMENT.json', 'object-availability-peer-v1/PLACEMENT.json'),
    ('/tmp/hepta-36fa-isolated-source-environment-review-v1/PLACEMENT.json', 'isolated-source-environment-review-v1/PLACEMENT.json'),
    ('/tmp/hepta-36fa-isolated-materializer-peer-v1/PLACEMENT.json', 'isolated-materializer-peer-v1/PLACEMENT.json'),
    ('/tmp/hepta-36fa-fresh-training-b-fixture-proposal-v1/PLACEMENT.json', 'fresh-training-b-fixture-proposal-v1/PLACEMENT.json'),
]
for path, destination in placements:
    document = json.loads(stable(Path(path)))
    entries = document.get('files', document.get('entries'))
    assert isinstance(entries, list), path
    for entry in entries:
        origin = entry.get('local_path', entry.get('local'))
        blob = entry.get('git_blob', entry.get('sha', entry.get('blob')))
        assert origin and blob
        expected = {'bytes': entry['bytes'], 'sha256': entry['sha256'], 'git_blob': blob}
        readbacks = list(entry.get('full_readback_records', []))
        readbacks += [entry[k] for k in ('github_original', 'original_git_response') if k in entry]
        add(origin, entry['path'], 'frozen_agent_component', expected, readbacks)
    add(path, destination, 'frozen_agent_component_index')

groups = [
    ('/tmp/hepta-36fa-cc57-isolated-recovery-plan-v1', 'cc57-isolated-recovery-plan-v1'),
    ('/tmp/hepta-36fa-cc57-isolated-recovery-root-review-v1', 'cc57-isolated-recovery-root-review-v1'),
    ('/tmp/hepta-36fa-cc57-isolated-materializer-v1', 'cc57-isolated-materializer-v1'),
    ('/tmp/hepta-36fa-cc57-isolated-materialization-launch-v1', 'cc57-isolated-materialization-launch-v1'),
    ('/tmp/hepta-36fa-cc57-native-history-scope-review-v1', 'cc57-native-history-scope-review-v1'),
    ('/tmp/hepta-36fa-complete-source-native-refusal-publication-v1', 'checkpoint3638-unpublished-wording-preparation-v1'),
    ('/tmp/hepta-36fa-complete-source-native-refusal-publication-v2', 'checkpoint3638-actual-publication-v2'),
    ('/tmp/hepta-36fa-root-review-corrections-v1', 'root-review-corrections-v1'),
    ('/tmp/hepta-36fa-root-resident-provider-proposal-v2/review-idle-transport-v1', 'root-provider-v2-idle-transport-v1'),
]
for directory, prefix in groups:
    directory = Path(directory)
    for path in sorted(directory.rglob('*')):
        if not path.is_file() or 'GITHUB' in path.name or '__pycache__' in path.parts:
            continue
        add(path, prefix + '/' + path.relative_to(directory).as_posix(), 'retained_original_control_or_frozen_candidate')

add(Path(__file__), 'post3638-preparation/prepare_frozen_increment.py', 'local_collection_code_not_execution')
summary = {
    'format': 'hepta-post3638-completed-evidence-selection-v1',
    'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'base_count': len(base), 'published_base_head': '07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0',
    'old_paths_changed': [], 'old_readme_unchanged': True,
    'new_paths_before_this_report': len(rows), 'duplicates_preserved': duplicates,
    'lossless_large_transports': len(transports), 'path_normalizations': normalizations,
    'actual_availability': '1d0a normal success: 16439 metadata objects and 1836 complete bodies checked in its original observation window; not a later live source check.',
    'materialization': 'One exact request, no job ID. Original launch and independent host-health calls returned tunnel_client_not_seen/404. Admission and actual execution remain Unknown; no fabricated terminal, source inventory or Git baseline.',
    'native': 'Earlier 1cd4 precondition refusal remains zero behavioral stages. No new native result.',
    'provider_components': 'Frozen V2 public-transport/idle tests and Fresh T-to-B component only. Not formatted, compiled, executed, activated or a complete public ten-owner deployment.',
    'later_active_admission_and_full_provider_work_excluded': True,
    'H_calls_by_collection': 0, 'source_or_refs_modified_by_collection': False,
    'real_qualified_task_chains': 0,
}
add_raw('post3638-preparation/SELECTION_REVIEW.json', jb(summary), 'offline selection metadata', 'collection_scope')
write(OUT / 'BASE_3638_FILEMAP.json', jb(base))
write(OUT / 'SELECTED_ROWS.json', jb(list(rows.values())))
write(OUT / 'SELECTION_REVIEW.json', jb(summary))
pending = [row for row in rows.values() if not row['full_readback_equal']]
write(OUT / 'PENDING_GIT_READBACK.json', jb(pending))
print(json.dumps({'new_paths': len(rows), 'old_paths_preserved': len(base),
                  'pending_paths': len(pending), 'pending_unique_blobs': len({r['git_blob'] for r in pending}),
                  'transports': len(transports), 'max_frozen_bytes': max(r['bytes'] for r in rows.values())}))

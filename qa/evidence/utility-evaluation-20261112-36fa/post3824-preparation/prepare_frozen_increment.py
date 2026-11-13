"""Freeze completed follow-up components. No H, source, test or ref operation."""
from pathlib import Path
import ast
import datetime
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-post3824-evidence-preparation-v1')
PREVIOUS = Path('/tmp/hepta-36fa-post3638-evidence-preparation-v1')
base_raw = (PREVIOUS / 'FULL_FILEMAP.json').read_bytes()
assert hashlib.sha1(b'blob ' + str(len(base_raw)).encode() + b'\0' + base_raw).hexdigest() == '2d40c9782d6592fbf92088e98ba39e1f170131a0'
base = json.loads(base_raw)
assert len(base) == 3824
helper = PREVIOUS / 'prepare_frozen_increment.py'
helper_raw = helper.read_bytes()
assert hashlib.sha1(b'blob ' + str(len(helper_raw)).encode() + b'\0' + helper_raw).hexdigest() == base['post3638-preparation/prepare_frozen_increment.py']
tree = ast.parse(helper_raw)
definitions = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
namespace = {'__name__': 'frozen_collector_pure_helpers', '__file__': str(helper)}
exec(compile(ast.Module(body=definitions, type_ignores=[]), str(helper), 'exec'), namespace)
namespace.update(OUT=ROOT, PREFIX='qa/evidence/utility-evaluation-20261112-36fa/',
                 base=base, rows={}, duplicates=[], transports=[], normalizations=[])
add = namespace['add']
add_raw = namespace['add_raw']
write = namespace['write']
jb = namespace['jb']
pin = namespace['pin']
stable = namespace['stable']

for name in ['VERIFIED_INCREMENTAL_ENTRIES.json', 'INCREMENTAL_FILEMAP.json', 'FULL_FILEMAP.json',
             'MANIFEST.json', 'SELECTED_ROWS.json', 'PENDING_GIT_READBACK.json',
             'SELECTION_REVIEW.json', 'finalize_verified_increment.py']:
    add(PREVIOUS / name, 'post3638-preparation/' + name, 'previous_frozen_window_metadata')

placement_path = Path('/tmp/hepta-36fa-provider-registration-proposal-v1/PLACEMENT.json')
placement = json.loads(stable(placement_path))
for row in placement.get('files', placement.get('entries')):
    original = row.get('local_path', row.get('local'))
    blob = row.get('git_blob', row.get('sha', row.get('blob')))
    readbacks = list(row.get('full_readback_records', []))
    readbacks += [row[k] for k in ('github_original', 'original_git_response') if k in row]
    add(original, row['path'], 'frozen_registration_proposal',
        {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': blob}, readbacks)
add(placement_path, 'provider-registration-proposal-v1/PLACEMENT.json', 'frozen_component_index')

groups = [
    ('/tmp/hepta-36fa-isolated-native-admission-v1', 'isolated-native-admission-v1', True),
    ('/tmp/hepta-36fa-isolated-native-admission-peer-v1', 'isolated-native-admission-peer-v1', True),
    ('/tmp/hepta-36fa-training-public-capacity-review-v1', 'training-public-capacity-review-v1', False),
    ('/tmp/hepta-36fa-training-completion-observer-increment-v1', 'training-completion-observer-increment-v1', True),
    ('/tmp/hepta-36fa-fresh-training-b-shared-increment-v1', 'fresh-training-b-shared-increment-v1', True),
]
for directory, prefix, recursive in groups:
    directory = Path(directory)
    paths = directory.rglob('*') if recursive else directory.iterdir()
    for path in sorted(paths):
        if not path.is_file() or 'GITHUB' in path.name or '__pycache__' in path.parts:
            continue
        add(path, prefix + '/' + path.relative_to(directory).as_posix(), 'frozen_followup_component')

launch = Path('/tmp/hepta-36fa-cc57-isolated-materialization-launch-v1')
for name in ['HOST_HEALTH_02.original.json', 'HOST_HEALTH_02_INTENT.json', 'CONNECTION_OBSERVATIONS_ADDENDUM_02.json']:
    if name == 'HOST_HEALTH_02_INTENT.json' and not (launch / name).exists():
        names = [p.name for p in launch.glob('*HEALTH*02*') if p.is_file() and 'GITHUB' not in p.name and 'INTENT' in p.name]
        assert len(names) == 1, names
        name = names[0]
    add(launch / name, 'cc57-isolated-materialization-launch-v1/' + name, 'actual_second_connection_observation')

add(Path(__file__), 'post3824-preparation/prepare_frozen_increment.py', 'local_collection_code_not_execution')
rows = namespace['rows']
scope = {
    'format': 'hepta-post3824-completed-followup-selection-v1',
    'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'published_base_head': '07b7f3ea4daf31b1a466574dfdc8232ad1d88fb0',
    'published_base_files': 3638, 'previous_verified_frozen_window_files': 3824,
    'previous_frozen_map': pin(base_raw),
    'old_paths_changed': [], 'old_readme_unchanged': True,
    'new_paths_before_this_report': len(rows),
    'duplicates_preserved': namespace['duplicates'],
    'path_normalizations': namespace['normalizations'],
    'admission': 'Unexecuted v1 and corrected v2 retained. Two independent original V5 instances; exact future materialization job/result/supervisor remain null and fail closed.',
    'source_gate_registration': 'Frozen V1/idle-only proposal preserves all original 33 Root cases and appends six parent cases; child remains parent-exec-only. Not formatter output or executed gates.',
    'fresh_training_components': 'Actual-completion observer and B shared-readonly-client test-only components are source proposals. No Rust format, compilation or test result.',
    'capacity': 'Source-level seven public Training connections, six after existing B Arc sharing, against original four permits. Not an observed Busy outcome. Minimal published readonly sharing production work is still separate and excluded.',
    'connection': 'Second host-health observation also returned tunnel_client_not_seen/404. Exactly one main launch attempt and two health calls; zero main reconciliation and no job ID. Actual materialization effects remain Unknown.',
    'later_active_shared_readonly_and_full_provider_work_excluded': True,
    'H_calls_by_collection': 0, 'source_or_refs_modified_by_collection': False,
    'real_qualified_task_chains': 0,
}
add_raw('post3824-preparation/SELECTION_REVIEW.json', jb(scope), 'offline selection metadata', 'collection_scope')
write(ROOT / 'BASE_3824_FILEMAP.json', base_raw)
write(ROOT / 'SELECTED_ROWS.json', jb(list(rows.values())))
write(ROOT / 'SELECTION_REVIEW.json', jb(scope))
pending = [row for row in rows.values() if not row['full_readback_equal']]
write(ROOT / 'PENDING_GIT_READBACK.json', jb(pending))
print(json.dumps({'new_paths': len(rows), 'base_frozen_paths': len(base),
                  'pending_paths': len(pending), 'pending_unique_blobs': len({r['git_blob'] for r in pending}),
                  'final_frozen_paths': len(base) + len(rows),
                  'maximum_frozen_bytes': max(r['bytes'] for r in rows.values())}))

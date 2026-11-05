"""Read-only cloud review of frozen H4 archival inputs; no remote execution."""
import ast
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys

WORK = Path('/workspace/scratch/93bfcfe29fc8')
SOURCE = WORK / 'w1/h4-reference-export'
OUTPUT = Path(__file__).resolve().parent / 'actual-plan'
PINS = {
    'H4-reference-export-plan.json': (1236214, 'c917633ed8b22fa7a97455ea06c4a96fecc4a208375899bd3afededebf007619'),
    'H4-reference-export-bootstrap.py': (257707, '5973ff2cd7ecc248b438cec4a66a91e318d013e0f52f7bdf0140159d36f2a0a2'),
    'H4-reference-export-frozen-launch-request.json': (258170, '23aab51a4e4802c75d75712e955f3558d28b187e4243d4e68a88bf3e92a3b452'),
    'H4-reference-export-transport-manifest.json': (1668, '78fff1b9faf93f1c8fcd9659010ede4ef4ad13cadc8416cfcb4d72bff92ae2c2'),
    'transport_payload.py': (1205, '6160a7dc42e570ae51b49ae8c5f44fc59c4eba60b1333577a1c51c0ce4063b84'),
    'build_frozen_transport.py': (6764, 'f20a3d45434bc453b557257a08472d31cede2a69db3781afc6b8223df52d9e2b'),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


for name, (size, expected) in PINS.items():
    raw = (SOURCE / name).read_bytes()
    assert len(raw) == size and sha(raw) == expected, name
plan_raw = (SOURCE / 'H4-reference-export-plan.json').read_bytes()
plan = json.loads(plan_raw)
original_path = WORK / 'model_storage/h4-capture-repair/native/joint-h4-native-attempt-1/h4-actual-image-inventory.json'
original_raw = original_path.read_bytes()
assert sha(original_raw) == 'a1e42612d6a89337144b00335da2fa690dc7f503b46532ff795f0c92198bdd9c'
assert base64.b64decode(plan['source_map']['data_base64'], validate=True) == original_raw
inventory = json.loads(original_raw)
assert plan['source_commit'] == inventory['source_commit'] == '6db78eca53a5acdda0d96873d3f4cd65863426f0'
assert plan['source_tree'] == inventory['source_tree'] == 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
assert plan['source_root'] == '/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf/evidence/joint-h4-native-attempt-1'
assert plan['output_directory'] == '/home/qian-qi/work/hepta-h4-actual-reference-export-20261105-93bfc-01'
assert plan['release_prerequisite'] == {
    'job_id': '1a1ade2970f-fc05-5b5c',
    'path': '/home/qian-qi/work/hepta-joint-h4-owned-release-20261105-93bfc-01.json',
    'sha256': 'dcdd164eb680465a440bf9dc4e11ab68c5598d8cb86a4d99320784d0a5b68107',
}
release_raw = (WORK / 'w1/H4-owned-release-probe/proof.json').read_bytes()
assert sha(release_raw) == plan['release_prerequisite']['sha256']
assert json.loads(release_raw)['owned_processes_clear']
index_raw = (WORK / 'w1/h3-elf-export/H3-actual-export-index.json').read_bytes()
assert len(index_raw) == 294654 and sha(index_raw) == plan['parent']['index_sha256'] == 'b023aca6ab2dccf4324dccab2e5319a00ef9b32773e0dc73127efc9af3caa002'
index = json.loads(index_raw)
assert plan['parent']['archive_path'] == '/home/qian-qi/work/hepta-h3-actual-elf-export-20261105-93bfc-01/H3-actual-retained-elfs.tar.xz'
assert plan['parent']['completion_path'] == '/home/qian-qi/work/hepta-h3-actual-elf-export-20261105-93bfc-01/completion.json'
assert sha((WORK / 'w1/h3-elf-export/H3-export-completion.json').read_bytes()) == plan['parent']['completion_sha256']
exporter_path = WORK / 'w1/h4-content-reference-draft/archive_reference.py'
assert sha(exporter_path.read_bytes()) == 'ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425'
exporter = module('root_h4_exporter_review', exporter_path)
validated, mapping = exporter.validate_plan(plan_raw, {'by_hash': {x['sha256']: x for x in index['files']}})
assert validated == plan and mapping == original_raw
assert len(plan['files']) == 11 and plan['referenced_elf_bytes'] == plan['total_actual_elf_bytes'] == 1674575368
assert plan['embedded_elf_bytes'] == 0 and plan['max_archive_bytes'] == 67108864
assert plan['part_bytes'] == 4194304 and plan['transport_budget_seconds'] == 900 and plan['native_reexecution'] is False
for row, original in zip(plan['files'], inventory['images']):
    assert row['source_path'] == original['retained_aliases'][0]
    assert row['original_observations'] == original['observations']
    assert row['representation'] == 'referenced-complete-image'
assert sum(len(x['original_observations']) for x in plan['files']) == 597
assert sum(len(x['aliases']) for x in plan['files']) == 32
request = json.loads((SOURCE / 'H4-reference-export-frozen-launch-request.json').read_bytes())
bootstrap = (SOURCE / 'H4-reference-export-bootstrap.py').read_bytes()
assert request == {
    'host': 'desktop', 'executable': '/usr/bin/python3', 'args': ['-B', '-'],
    'cwd': '/home/qian-qi/work', 'env': {'PYTHONDONTWRITEBYTECODE': '1'},
    'stdin': bootstrap.decode(), 'timeout_seconds': 900,
    'idempotency_key': '93bfc-hepta-h4-actual-reference-images-export-01',
}
assert bootstrap.startswith((SOURCE / 'transport_payload.py').read_bytes())
tree = ast.parse(bootstrap)
literal = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ('FROZEN_TRANSPORT', 'EXPECTED')}
decoder = module('transport_payload', SOURCE / 'transport_payload.py')
sys.modules['transport_payload'] = decoder
decoded = decoder.decode_exact(*literal['FROZEN_TRANSPORT'])
assert len(decoded) == 1706220 and sha(decoded) == '893712e3955aa2503ffd1336fd25125794c861228ca5973be1e65379adf04cce'
files = json.loads(decoded)['files']
assert len(files) == 2
for row in files:
    raw = base64.b64decode(row['data_base64'], validate=True)
    wanted = exporter_path.read_bytes() if row['name'] == 'archive_reference.py' else plan_raw
    assert raw == wanted
    assert {'bytes': len(raw), 'sha256': sha(raw)} == literal['EXPECTED'][row['name']]
builder = module('root_h4_transport_builder_review', SOURCE / 'build_frozen_transport.py')
generated = {}


def collect(name, raw):
    generated[name] = raw
    return {'path': str(SOURCE / name), 'bytes': len(raw), 'sha256': sha(raw)}


builder.write_fresh = collect
with contextlib.redirect_stdout(io.StringIO()):
    builder.build(SOURCE / 'H4-reference-export-plan.json', PINS['H4-reference-export-plan.json'][1])
for name, raw in generated.items():
    assert raw == (SOURCE / name).read_bytes(), name
OUTPUT.mkdir(parents=True, exist_ok=True)
copied = []
for path in sorted(SOURCE.iterdir()):
    if path.is_file():
        raw = path.read_bytes()
        shutil.copyfile(path, OUTPUT / path.name)
        copied.append({'path': path.name, 'bytes': len(raw), 'sha256': sha(raw)})
report = {
    'schema': 'root-H4-actual-archive-plan-review-v1', 'files': copied,
    'actual_plan_sha256': PINS['H4-reference-export-plan.json'][1],
    'actual_request_sha256': PINS['H4-reference-export-frozen-launch-request.json'][1],
    'exact_bootstrap_rebuilt_in_memory_from_reviewed_builder': True,
    'bounded_transport_decoded_and_two_original_files_verified': True,
    'exact_original_H4_inventory_bytes_preserved': True,
    'individually_bound_original_observations': 597, 'retained_aliases': 32,
    'selected_current_H4_paths': 11, 'other_aliases_not_rehashed': 21,
    'actual_H4_binary_reads_still_required': True, 'actual_parent_archive_read_still_required': True,
    'preserved_H4_native_outcome': 'SUCCEEDED desktop only; H3 failure remains unchanged',
    'native_budget_changed': False, 'postrun_budget_seconds': 900,
    'new_remote_calls': 0, 'new_native_executions': 0,
    'decision': 'Exact inputs accepted; one launch still requires independent review and serialized resource window.',
    'consumer_requirement': 'Authoritative archive success plus exact child/parent completions, whole archives, all original parts and fully hashed member/logical view closure. No parent test credit transfer.',
    'publication_semantics': 'Cross-file publication is not atomic; uncompleted outputs are not accepted.',
}
target = OUTPUT / 'root-actual-plan-review.json'
target.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'path': str(target), 'sha256': sha(target.read_bytes()), 'files': len(copied), 'request_accepted': True, 'launch_authorized': False}))

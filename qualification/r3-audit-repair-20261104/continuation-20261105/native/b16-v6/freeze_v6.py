"""Freeze source-only V6 identities; never bind or execute a native epoch."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'cli-duplicate-flag-v5' / 'v5-candidate'
OUT = ROOT / 'v6-candidate'

def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}

def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')

original_integrity = json.loads((BASE/'runner-integrity.json').read_bytes())
paths = sorted([row['path'] for row in original_integrity['files']] + ['b16_build_only.py', 'test_build_only_guard.py'])
write(OUT/'runner-integrity.json', {
    'schema': 'hepta-b16-runner-integrity-v6-build-only-current-host',
    'files': [{'path': p, **identity((OUT/p).read_bytes())} for p in paths],
    'runtime_scope': 'Existing native/test/oracle/lock/source payload code remains frozen; current-host build cache provenance is separate from historical A qualification.',
})
integrity = identity((OUT/'runner-integrity.json').read_bytes())
for name in ['binding-template-UNBOUND.json', 'foundation-binding-UNBOUND.json']:
    template = json.loads((BASE/name).read_bytes())
    template['approved_runner_integrity_sha256'] = integrity['sha256']
    assert template['execute'] is False and template['approval_reference'] is None
    write(OUT/name, template)

current = json.loads((OUT/'foundation-binding-UNBOUND.json').read_bytes())
current['schema'] = 'hepta-b16-explicit-native-binding-v6-build-only-current-host'
current['target_reuse_mode'] = 'BUILD_ONLY_CURRENT_HOST'
current['current_host_build_only_baseline'] = {'path': None, 'bytes': None, 'sha256': None}
current['build_only_host'] = {'alias': None, 'uname': None, 'uid': None, 'euid': None}
current['build_only_cache_owner'] = None
current['build_only_binding_limit'] = 'Disabled. Populate only from complete actual P4 originals and root approval. Historical A artifacts retain their original source and internal ROG paths. BUILD_ONLY never grants A test qualification.'
write(OUT/'foundation-build-only-binding-UNBOUND.json', current)

changed = []
patch = []
for path in sorted(p.name for p in OUT.iterdir() if p.is_file()):
    before = BASE/path
    after = OUT/path
    old = before.read_bytes() if before.exists() else None
    new = after.read_bytes()
    if old == new: continue
    row = {'path': path, 'mode': '100644', 'before': identity(old) if old is not None else None, 'after': identity(new)}
    changed.append(row)
    patch.append('diff --git a/'+path+' b/'+path+'\n')
    if old is None: patch.append('new file mode 100644\n')
    patch.append('index '+(row['before']['blob'] if old is not None else '0'*40)+'..'+row['after']['blob']+(' 100644\n' if old is not None else '\n'))
    patch.extend(difflib.unified_diff((old or b'').decode().splitlines(True), new.decode().splitlines(True),
                 fromfile='a/'+path if old is not None else '/dev/null', tofile='b/'+path))
(ROOT/'v5-to-v6.delta.patch').write_text(''.join(patch))

unchanged = [{'path': row['path'], **identity((OUT/row['path']).read_bytes())}
             for row in original_integrity['files'] if (BASE/row['path']).read_bytes() == (OUT/row['path']).read_bytes()]
for p in ['b16_native.py', 'b16_oracles.py', 'b16_locks.py', 'payload-manifest.json', 'foundation-output-family.json']:
    assert (BASE/p).read_bytes() == (OUT/p).read_bytes(), p
for p in ['epoch-foundation.json', 'epoch-driver.json', 'epoch-pool.json', 'epoch-checkpoint.json', 'epoch-owning.json']:
    assert (BASE/p).read_bytes() == (OUT/p).read_bytes(), p

def segment(path, symbol):
    text = path.read_text()
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == symbol)
    return ast.get_source_segment(text, node).encode()
protected = []
for path, name in [('b16_runner.py', 'negative_with_finally'), ('b16_runner.py', 'execute_scopes'),
                   ('b16_runner.py', 'export_evidence'), ('b16_guard.py', 'SourceGuard')]:
    old, new = segment(BASE/path, name), segment(OUT/path, name)
    assert old == new, (path,name)
    protected.append({'path': path, 'symbol': name, 'byteequal': True, **identity(new)})
for p in OUT.glob('*.py'): ast.parse(p.read_text())
write(ROOT/'preservation-verification.json', {
    'schema': 'hepta-b16-v6-source-only-preservation-v1',
    'base_integrity': identity((BASE/'runner-integrity.json').read_bytes()), 'new_integrity': integrity,
    'unchanged_existing_inputs': unchanged, 'protected_source_segments': protected,
    'native_started': False, 'source_payload_or_test_changes': False,
    'budget_unchanged': {'foundation_required_bytes': 22000000000, 'per_command_reserve_bytes': 8000000000,
                        'other_epochs_unchanged': True, 'peak_capacity_not_proven': True},
    'templates_disabled': True,
})
write(ROOT/'source-map-v6.json', {'schema': 'hepta-b16-v6-source-map-v1', 'base': str(BASE), 'candidate': str(OUT),
       'files': [{'path': p.name, 'mode': '100644', **identity(p.read_bytes())} for p in sorted(OUT.iterdir()) if p.is_file()],
       'changed_files': changed, 'patch': identity((ROOT/'v5-to-v6.delta.patch').read_bytes())})
print(json.dumps({'candidate_files': len(list(OUT.iterdir())), 'integrity': integrity,
                  'existing_inputs_byte_equal': len(unchanged), 'changed_files': [r['path'] for r in changed],
                  'patch': identity((ROOT/'v5-to-v6.delta.patch').read_bytes())}, indent=2))

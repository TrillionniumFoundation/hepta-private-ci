import hashlib
import json
from pathlib import Path

ROOT = Path.cwd()
OUT = ROOT / 'hepta-audit-fifth'
PREFIX = 'qualification/r3-audit-repair-20261104/continuation-20261105'
entries = {}


def add(local, relative, role, evidence=None):
    path = Path(local).resolve()
    raw = path.read_bytes()
    repo_path = relative if relative.startswith(PREFIX + '/') else PREFIX + '/' + relative
    pin = {
        'repository_path': repo_path,
        'local_file': str(path),
        'mode': '100644',
        'blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
        'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'role': role,
    }
    if evidence:
        for key in ('bytes', 'sha256'):
            assert pin[key] == evidence[key], (path, key)
        assert pin['blob'] == evidence.get('blob', evidence.get('git_blob'))
        pin['prior_object_verification'] = evidence
    if repo_path in entries:
        assert entries[repo_path]['blob'] == pin['blob'], repo_path
    else:
        entries[repo_path] = pin


for name in ('LATEST.zh-CN.md', 'CONTINUATION_PROGRESS_V3.zh-CN.md', 'continuation-blocker-progress-v2.json'):
    add(OUT / name, name, 'human_progress_or_original_blocker_ledger')
for name in ('libcap-sdk-root-review.json', 'libcap-full-originals-root-review.json',
             'p4-v3-originals-root-review.json', 'p4-readonly-completion-static-root-review.json',
             'p4-completion-root-review.json', 'p4-git-augmentation-root-review.json', 'b16-v7-root-review.json'):
    add(OUT / 'inputs' / name, 'reviews/' + name, 'root_independent_scoped_review')
for name in ('verify_libcap_sdk_review.py', 'verify_p4_v3_originals.py', 'verify_p4_completion.py',
             'build_registration_v4.py'):
    add(OUT / name, 'reviews/reproducible/' + name, 'cloud_record_verifier_or_registration_builder')
add(OUT / 'audit-publication-receipt-v3.json', 'reviews/audit-publication-receipt-v3.json', 'prior_actual_ref_publication')

v7 = ROOT / 'architecture-audit/b16-guarded-native-runner-20261105/original-ignored-catalog-v7'
v7_map = json.loads((v7 / 'github-readback-map-v7.json').read_text())
for entry in v7_map['files'] + v7_map['new_records']:
    path = Path(entry['path'])
    add(path, 'b16-runner-v7/' + str(path.relative_to(v7)), 'frozen_V7_runtime_or_complete_verification', entry)
add(v7 / 'github-readback-map-v7.json', 'b16-runner-v7/github-readback-map-v7.json', 'actual_Git_object_readback_map')
add(ROOT / 'research-audit/b16-v7-independent-review-20261105/independent-review.json',
    'reviews/b16-v7-independent-review.json', 'independent_frozen_V7_static_review')
for directory, name in [
    ('b16-libcap-prerequisite-static-20261105', 'libcap-prerequisite-static-review.json'),
    ('b16-p4-libcap-continuation-static-20261105', 'p4-libcap-continuation-static-review.json'),
]:
    add(ROOT / 'architecture-audit' / directory / 'static-review.json', 'reviews/' + name, 'independent_native_plan_static_review')

native = ROOT / 'ci-audit/recovered-20261105/b16-ai395-cold-bootstrap-v1'
for directory in ('p4-libcap-sdk-v1', 'p4-libcap-sdk-continuation-v2', 'p4-libcap-continuation-v3',
                  'p4-readonly-completion-v4'):
    for path in sorted((native / directory).iterdir()):
        if path.is_file() and path.suffix in ('.py', '.json', '.patch'):
            add(path, 'native/b16/' + directory + '/' + path.name, 'native_frozen_plan_or_complete_original_bundle')
for directory, filename in [
    ('p4-libcap-sdk-v1', 'failure-originals/terminal.json'),
    ('p4-libcap-continuation-v3', 'originals/terminal.json'),
    ('p4-readonly-completion-v4', 'originals/new-host-build-only-baseline.json'),
    ('p4-readonly-completion-v4', 'originals/terminal.json'),
]:
    add(native / directory / filename, 'native/b16/' + directory + '/' + filename, 'direct_original_native_record')
export = native / 'p4-v3-catalog-readonly-export-v1'
for path in sorted(export.iterdir()):
    if path.is_file() and path.suffix in ('.py', '.json'):
        add(path, 'native/b16/p4-v3-catalog-readonly-export-v1/' + path.name, 'complete_P4_original_export_manifest_or_verifier')
for path in sorted((export / 'transport').glob('batch-*.json')):
    add(path, 'native/b16/p4-v3-catalog-readonly-export-v1/transport/' + path.name, 'lossless_native_original_base64_transport')
assert len(list((export / 'transport').glob('batch-*.json'))) == 11
augmentation = native / 'p4-git-tool-augmentation-v1'
for name in ('run_readonly_augmentation.py', 'complete-originals.transport.json'):
    add(augmentation / name, 'native/b16/p4-git-tool-augmentation-v1/' + name, 'native_Git_identity_parent_pinned_augmentation')
for path in sorted((augmentation / 'originals').iterdir()):
    if path.is_file():
        add(path, 'native/b16/p4-git-tool-augmentation-v1/originals/' + path.name, 'direct_original_Git_augmentation_record')

ci = ROOT / 'research-audit/published-5b633-ci-20261105/immutable-v4-ci-state'
ci_plan = json.loads((ci / 'registry-plan.json').read_text())
for entry in ci_plan['items']:
    add(entry['local_file'], entry['repository_path'], 'new_head_CI_full_original_or_qualified_projection', entry)
add(ci / 'registry-plan.json', 'generated-evidence/5b633-ci-state-v4/registry-plan.json', 'actual_CI_archive_registration_map')

plan = {
    'schema': 'hepta-continuation-fourth-publication-plan-v1', 'prefix': PREFIX,
    'base_audit_commit': '5eb42c6a1e574d323e4ec0dfc209744674fa1387',
    'base_audit_tree': '4f88b62ab745bc8b997fd112af23de9bc58518f7',
    'code_candidate_commit': '5b6331250ff459033bd44d1a95daec70131277cc',
    'code_candidate_tree': 'b26598d0d97d8d51e723bb5582137315f2174d35',
    'scope': 'Documentation and original evidence only; no product source/ref/base/CI gate change.',
    'entry_count': len(entries), 'items': sorted(entries.values(), key=lambda row: row['repository_path']),
}
target = OUT / 'registration-plan-v4.json'
target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(target), 'entries': len(entries),
                  'file_bytes': sum(entry['bytes'] for entry in entries.values()),
                  'plan_bytes': target.stat().st_size}))

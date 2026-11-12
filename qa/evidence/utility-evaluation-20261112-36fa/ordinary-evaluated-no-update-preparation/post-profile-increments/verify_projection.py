import base64
import hashlib
import json
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path('/tmp')
inputs = json.loads((ROOT / 'hepta-36fa-post-profile-increments-root-input.json').read_text())
inputs.update(json.loads((ROOT / 'hepta-36fa-retained-protocol-ufcs-root-input.json').read_text()))
baseline = json.loads((ROOT / 'hepta-36fa-complete-profile-preformat-leaf-map.json').read_text())

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def identity(data):
    return {'bytes': len(data), 'git_blob': blob(data), 'sha256': hashlib.sha256(data).hexdigest()}

def merkle(entries):
    root = {}
    for entry in entries:
        node = root
        parts = entry['path'].split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = entry
    def walk(node):
        rows = []
        for name, entry in node.items():
            if all(k in entry for k in ('sha', 'mode', 'path')):
                rows.append((name.encode(), entry['mode'], entry['sha']))
            else:
                rows.append((name.encode() + b'/', '40000', walk(entry)))
        raw = b''.join(mode.encode() + b' ' + name.rstrip(b'/') + b'\0' + bytes.fromhex(sha) for name, mode, sha in sorted(rows))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return walk(root)

assert baseline['tree'] == merkle(baseline['entries']) == '8a3e1ad32948453205c2e91507dcbe97752cad19'
assert len(baseline['entries']) == 15188
entries = {e['path']: dict(e) for e in baseline['entries']}
review = []
out = ROOT / 'hepta-36fa-reviewed-post-profile-increments-v1'
out.mkdir(exist_ok=True)
for prefix in ('unsorted_route', 'prepared_publish_ufcs', 'retained_protocol_ufcs'):
    values = {}
    for kind in ('post', 'patch', 'packet', 'manifest'):
        item = inputs[prefix + '_' + kind]
        raw = item['content'].encode()
        assert blob(raw) == item['sha'], (prefix, kind)
        values[kind] = raw
    packet = json.loads(values['packet'])
    manifest = json.loads(values['manifest'])
    assert len(packet['files']) == len(manifest['files']) == 1
    item, facts = packet['files'][0], manifest['files'][0]
    assert all(item[k] == facts[k] for k in ('path', 'mode', 'before', 'after'))
    assert identity(values['packet']) == manifest['packet']
    assert identity(values['patch']) == manifest['patch']
    before = base64.b64decode(item['preimage_base64'], validate=True)
    after = base64.b64decode(item['postimage_base64'], validate=True)
    assert identity(before) == facts['before']
    assert identity(after) == facts['after']
    assert after == values['post']
    path = item['path']
    assert entries[path]['sha'] == facts['before']['git_blob']
    assert entries[path]['mode'] == item['mode'] == '100644'
    with tempfile.TemporaryDirectory(prefix='hepta-36fa-increment-apply-') as directory:
        checkout = pathlib.Path(directory)
        target = checkout / path
        target.parent.mkdir(parents=True)
        target.write_bytes(before)
        patch = checkout / 'increment.patch'
        patch.write_bytes(values['patch'])
        subprocess.run(['git', 'apply', '--check', str(patch)], cwd=checkout, check=True, capture_output=True)
        subprocess.run(['git', 'apply', str(patch)], cwd=checkout, check=True, capture_output=True)
        assert target.read_bytes() == after
    target = out / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(after)
    entries[path]['sha'] = facts['after']['git_blob']
    review.append({'path': path, 'before': facts['before'], 'after': facts['after'], 'manifest_blob': inputs[prefix + '_manifest']['sha'], 'complete_artifact_hashes_and_patch_application': 'verified'})

workflow = '.github/workflows/hepta-daemon-learning-native.yml'
workroot = ROOT / 'hepta-36fa-evaluated-ordinary-nonrust-v1'
before = (workroot / 'baseline' / workflow).read_bytes()
after = (workroot / 'candidate' / workflow).read_bytes()
assert entries[workflow]['sha'] == blob(before) == '72d4b247d90dde972ac592b2d568cd6e470f97ff'
assert blob(after) == '08ffc5c603a4c950cca285ed2b1e479508d8b5ed'
new_lines = [line for line in after.splitlines(keepends=True) if b'evaluated_version_late_b_loss_keeps_published_material_but_cannot_serve_s_or_start_c' in line]
assert len(new_lines) == 1 and len(new_lines[0]) == 322
assert after.replace(new_lines[0], b'', 1) == before
target = out / workflow
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(after)
entries[workflow]['sha'] = blob(after)
review.append({'path': workflow, 'before': identity(before), 'after': identity(after), 'claim': 'One 322-byte explicit original Root FQN registration; removing exactly that line restores complete original workflow bytes. Not executed.'})

final = sorted(entries.values(), key=lambda e: e['path'])
assert len(final) == len(baseline['entries']) == 15188
before_entries = {entry['path']: entry for entry in baseline['entries']}
changed = [entry['path'] for entry in final if entry != before_entries[entry['path']]]
assert set(changed) == {item['path'] for item in review}
tree = merkle(final)
result = {'schema': 'hepta.reviewed-post-profile-increments.v1', 'source_parent': 'c0f78493f815780f68b9bf5e390a21314d79311f', 'fixed_upstream': 'a96d1b821d10ed3d9e99dd06c5141f9f242ae318', 'before_preformat_tree': baseline['tree'], 'after_preformat_tree': tree, 'files': len(final), 'changes': review, 'scope': 'Complete deterministic preformat tree projection with three immutable Rust increments and one explicit Root registration. No native source mutation, formatting, compilation, qualification, source commit, or ref publication. Complete CALLERS/protected/QA synchronization remains pending.'}
(ROOT / 'hepta-36fa-post-profile-increments-preformat-leaf-map.json').write_text(json.dumps({'tree': tree, 'entries': final}, separators=(',', ':')) + '\n')
(ROOT / 'hepta-36fa-post-profile-increments-ROOT_REVIEW.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))

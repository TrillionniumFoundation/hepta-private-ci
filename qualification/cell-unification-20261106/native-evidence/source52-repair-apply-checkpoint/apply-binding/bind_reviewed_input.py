from pathlib import Path, PurePosixPath
import ast
import base64
import copy
import difflib
import hashlib
import json
import tarfile

R = Path('/workspace/scratch/08f5efd48967')
P = R / 'source52-preparation'
O = Path(__file__).parent
TEMPLATE = R / 'source52-apply-preparation/native-source52-apply-template.py'


def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}


def check(b, p):
    actual = pin(b)
    for key in ('bytes', 'sha256', 'git_blob'):
        if key in p:
            assert actual[key] == p[key], (key, actual, p)
    return actual


def save(name, b):
    with (O / name).open('xb') as f:
        f.write(b)


def dump(obj):
    return (json.dumps(obj, indent=2, ensure_ascii=False) + '\n').encode()


bindings_raw = (P / 'ROOT-APPLY-BINDINGS.json').read_bytes()
check(bindings_raw, {'bytes':1190,'sha256':'f3a7460cac3da6f7253fb2a1b573dbeff5d0da6f6829e2f578ebab7fdd7ac6f7'})
bindings = json.loads(bindings_raw)
freeze_raw = (P / 'ROOT-APPLY-INPUT-FREEZE.json').read_bytes()
check(freeze_raw, {'bytes':2271,'sha256':'5220643a8d20eabe4029b7d6084c2316225574685698ef9de136038c22f63a8e'})
freeze = json.loads(freeze_raw)
template = TEMPLATE.read_bytes()
check(template, {'bytes':35669,'sha256':'9510eed8daa3f2e749971bfbd0c33f8e98d5f0524deb36005892766288c9b3a5'})
archive_path = P / 'source52-apply-input.tar.gz'
archive = archive_path.read_bytes()
archive_pin = check(archive, freeze['archive'])
assert len(archive) == bindings['INPUT_BYTES'] and archive_pin['sha256'] == bindings['INPUT_SHA256']
members = {}
member_proofs = []
with tarfile.open(archive_path, 'r:gz') as tf:
    for m in tf.getmembers():
        p = PurePosixPath(m.name)
        assert m.isfile() and not p.is_absolute() and '..' not in p.parts
        assert m.name not in members and m.mode == 0o644
        members[m.name] = tf.extractfile(m).read()
        assert len(members[m.name]) == m.size
assert len(members) == 5
assert set(members) == {p['path'] for p in freeze['members']}
for p in freeze['members']:
    member_proofs.append({'path':p['path'], **check(members[p['path']], p), 'tar_mode':'000644'})

source_raw = (P / 'native-candidate-r28-source.json').read_bytes()
delta_raw = (P / 'source52-actual-delta-manifest.json').read_bytes()
assert source_raw == members['source52-manifest.json']
assert delta_raw == members['delta-manifest.json']
check(source_raw, bindings['SOURCE52_MANIFEST_PIN'])
check(delta_raw, bindings['DELTA_MANIFEST_PIN'])
source = json.loads(source_raw)
delta = json.loads(delta_raw)
prior_raw = (R / 'source51-preparation/native-candidate-r26-source.json').read_bytes()
check(prior_raw, {'bytes':55418,'sha256':'74b7a35a77019ec90e42ec33dc0e81bbdbaca585541a028d57fffbe77c69a41a'})
prior = json.loads(prior_raw)
leaf = 'codex-rs/network-proxy/src/runtime.rs'
old = {x['path']:x for x in prior['changed_files']}
new = {x['path']:x for x in source['changed_files']}
assert len(old) == 194 and len(new) == 195 and len(source['changed_files']) == 195
assert leaf not in old and set(new) - set(old) == {leaf}
assert all(new[path] == row for path, row in old.items())
assert source['source_parent_commit'] == prior['source_commit']
assert source['source_before_tree'] == prior['source_tree']
assert source['source_commit'] == bindings['EXPECTED_COMMIT']
assert source['source_tree'] == bindings['EXPECTED_TREE']
assert bindings['EXPECTED_CHANGED_COUNT'] == 195
assert delta['source_before_commit'] == prior['source_commit']
assert delta['source_before_tree'] == prior['source_tree']
assert delta['source_commit'] == source['source_commit'] and delta['source_tree'] == source['source_tree']
assert delta['schema'] == 'hepta.source52-apply-delta.v1' and len(delta['files']) == 1
assert delta['files'][0] == {'path':leaf, **bindings['CANDIDATE_PINS'][leaf]}
assert new[leaf] == {'path':leaf, **bindings['CANDIDATE_PINS'][leaf]['after']}
assert delta['patch']['path'] == 'candidate.patch'
check(members['candidate.patch'], delta['patch'])
for which in ('before','after'):
    check(members[which + '/' + leaf], bindings['CANDIDATE_PINS'][leaf][which])
for key in ('cargo_lock_sha256','bazel_lock_sha256'):
    assert source[key] == prior[key]
assert source['dependency_inputs_changed'] == source['lock_changes'] == []
assert sum(x['path'].endswith('.rs') for x in new.values()) == 181


def tree_hash(entries):
    def sortkey(e):
        return (e['path'] + ('/' if e['type'] == 'tree' else '')).encode()
    b = b''.join((e['mode'].lstrip('0') + ' ' + e['path']).encode() + b'\0' + bytes.fromhex(e['sha'])
                 for e in sorted(entries, key=sortkey))
    return hashlib.sha1(b'tree ' + str(len(b)).encode() + b'\0' + b).hexdigest()


originals = {}
trees = []
for name in ('root','codex','network','network_src'):
    raw = (P / 'input/original-trees' / (name + '.json')).read_bytes()
    obj = json.loads(raw)
    assert obj.get('truncated') is False and tree_hash(obj['tree']) == obj['sha']
    originals[name] = obj
    trees.append({'name':name, 'original_file':pin(raw),'original_tree':obj['sha']})
assert originals['root']['sha'] == prior['source_tree']
node = next(x for x in originals['network_src']['tree'] if x['path'] == 'runtime.rs')
assert node['sha'] == bindings['CANDIDATE_PINS'][leaf]['before']['git_blob']
assert node['mode'] == '100644' and node['type'] == 'blob'
child = bindings['CANDIDATE_PINS'][leaf]['after']['git_blob']
for name, childpath in [('network_src','runtime.rs'),('network','src'),('codex','network-proxy'),('root','codex-rs')]:
    entries = copy.deepcopy(originals[name]['tree'])
    hit = [e for e in entries if e['path'] == childpath]
    assert len(hit) == 1
    hit[0]['sha'] = child
    child = tree_hash(entries)
    derived = json.loads((P / 'derived-trees' / (name + '.json')).read_bytes())
    assert child == derived['expected_git_tree'] and tree_hash(derived['entries']) == child
    for proof in trees:
        if proof['name'] == name:
            proof['independent_derived_tree'] = child
assert child == bindings['EXPECTED_TREE']
commit_raw = (P / 'CREATED-COMMIT-API-ORIGINAL.json').read_bytes()
commit = json.loads(commit_raw)
check(commit_raw, source['source_identity_bound_from_actual_git_api']['original'])
assert commit['sha'] == source['source_commit'] and commit['tree']['sha'] == child
assert [p['sha'] for p in commit['parents']] == [prior['source_commit']]

text = template.decode()
nodes = {n.targets[0].id:n for n in ast.parse(text).body
         if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
assert {k for k,n in nodes.items() if isinstance(n.value,ast.Constant) and n.value.value is None} == set(bindings)
bound = text
for name, value in bindings.items():
    before = name + ' = None'
    after = name + ' = ' + repr(value)
    assert ast.get_source_segment(text, nodes[name]) == before and bound.count(before) == 1
    bound = bound.replace(before, after, 1)
bound_nodes = {n.targets[0].id:n for n in ast.parse(bound).body
               if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
assert ast.literal_eval(bound_nodes['FROZEN'].value) is False
assert {k:ast.literal_eval(bound_nodes[k].value) for k in bindings} == bindings
reverse = bound
for name in reversed(list(bindings)):
    segment = ast.get_source_segment(bound, bound_nodes[name])
    assert reverse.count(segment) == 1
    reverse = reverse.replace(segment, name + ' = None', 1)
assert reverse.encode() == template
assert bound.count('FROZEN = False') == 1
expected_final = bound.replace('FROZEN = False', 'FROZEN = True', 1)
ast.parse(expected_final)
bound_bytes = bound.encode()
diff = ''.join(difflib.unified_diff(text.splitlines(True),bound.splitlines(True),fromfile='reviewed-template.py',tofile='bound-template.py')).encode()
freeze_diff = ''.join(difflib.unified_diff(bound.splitlines(True),expected_final.splitlines(True),fromfile='bound-template.py',tofile='expected-final.py')).encode()
save('native-source52-apply-bound.py',bound_bytes)
save('template-to-bound.patch',diff)
save('bound-to-expected-final.patch',freeze_diff)
report = {'schema':'hepta.source52-native-apply-bound-review.v1','status':'STATIC_CLEAR_BOUND_REMAINS_INERT',
          'source_commit':source['source_commit'],'source_tree':source['source_tree'],'source_parent_commit':prior['source_commit'],
          'template':pin(template),'root_bindings':pin(bindings_raw),'root_freeze':pin(freeze_raw),
          'archive':archive_pin,'members':member_proofs,'manifest':pin(source_raw),'delta_manifest':pin(delta_raw),
          'prior_manifest':pin(prior_raw),'prior_rows_unchanged':194,'new_existing_repository_leaf':leaf,'changed_file_count':195,
          'rust_file_count':181,'other_file_count':14,'dual_lock_pins_unchanged':True,'dependency_inputs_changed_paths':[],
          'tree_reconstruction':trees,'actual_commit_api':pin(commit_raw),
          'bindings':bindings,'bound':pin(bound_bytes),'template_to_bound_patch':pin(diff),
          'exact_eight_constant_replacements':True,'inverse_whole_file_matches_reviewed_template':True,
          'bound_frozen':False,'expected_final_if_only_frozen_flipped':pin(expected_final.encode()),
          'bound_to_expected_final_patch':pin(freeze_diff),'ast_parse':True,
          'native_upload_performed':False,'native_apply_performed':False,'rust_bazel_fix_fmt_executed':False}
save('BOUND-INDEPENDENT-READBACK.json',dump(report))
print(json.dumps({'bound':report['bound'],'report':pin(dump(report)),'expected_final':report['expected_final_if_only_frozen_flipped'],
                  'archive':archive_pin,'derived_tree':child,'native_applied':False}))

import base64
import gzip
import hashlib
import json
import pathlib

root = pathlib.Path('/tmp')
c0f = json.loads((root / 'hepta-36fa-final-formatted-source/expected-leaf-map.json').read_text())
a96 = json.loads((root / 'hepta-36fa-fixed-a96d1-complete-leaf-map.json').read_text())
delta = json.loads((root / 'hepta-36fa-fixed-a96d1-tree-delta.json').read_text())
inputs = json.loads((root / 'hepta-36fa-next-preparation-root-input.json').read_text())
packet = json.loads(gzip.decompress(base64.b64decode(inputs['eleven_merge_packet']['content'])))
resolved = {x['path']: x for x in packet['changes']}

def digest_tree(entries):
    tree = {}
    for entry in entries:
        node = tree
        parts = entry['path'].split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = entry
    def walk(node):
        values = []
        for name, entry in node.items():
            if 'sha' in entry and 'mode' in entry and 'path' in entry:
                values.append((name.encode(), entry['mode'], entry['sha']))
            else:
                values.append((name.encode() + b'/', '40000', walk(entry)))
        body = b''.join(mode.encode() + b' ' + name.rstrip(b'/') + b'\0' + bytes.fromhex(sha) for name, mode, sha in sorted(values))
        return hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
    return walk(tree)

assert digest_tree(c0f['entries']) == c0f['tree'] == '313ee34febc8ccc54c611ab56286e289518c63cb'
assert digest_tree(a96['entries']) == a96['tree'] == 'f96bebefbc1e7d8187efadb62f88d524cdd18451'
entries = {e['path']: dict(e) for e in c0f['entries']}
applied = []
for change in delta['source_changes'] + delta['evidence_changes']:
    path = change['path']
    current = entries.get(path)
    old, new = change['old'], change['new']
    current_sha = current['sha'] if current else None
    old_sha = old['sha'] if old else None
    new_sha = new['sha'] if new else None
    if path in resolved:
        fix = resolved[path]
        assert current_sha == fix['c0f_blob'] and old_sha == fix['base_b298_blob'] and new_sha == fix['fixed_a96_blob']
        entries[path] = {'path': path, 'mode': fix['mode'], 'type': 'blob', 'sha': fix['candidate_blob']}
        disposition = 'explicit_reviewed_dual_change'
    elif current_sha == new_sha:
        disposition = 'already_identical'
    else:
        assert current_sha == old_sha, (path, current_sha, old_sha, new_sha)
        if new is None:
            entries.pop(path)
        else:
            entries[path] = {'path': path, 'mode': new['mode'], 'type': new['type'], 'sha': new['sha']}
        disposition = 'clean_fixed_upstream'
    applied.append({'path': path, 'disposition': disposition, 'source_sha': entries.get(path, {}).get('sha')})
final = sorted(entries.values(), key=lambda x: x['path'])
tree = digest_tree(final)
result = {'schema': 'hepta.c0f-fixed-a96-baseline-preparation.v1', 'source_parent': 'c0f78493f815780f68b9bf5e390a21314d79311f', 'fixed_upstream': 'a96d1b821d10ed3d9e99dd06c5141f9f242ae318', 'merge_base': 'b29869e856d08db1bfb066116a9c443376ccc57d', 'tree': tree, 'files': len(final), 'source_delta': len(delta['source_changes']), 'qualification_delta': len(delta['evidence_changes']), 'changes': applied, 'scope': 'Complete unformatted baseline before evaluated ordinary-profile overlays; not a published commit and not tested. Final source-marker and CALLERS allowance synchronization remains pending actual formatting.'}
(root / 'hepta-36fa-fixed-a96-integration-baseline-leaf-map.json').write_text(json.dumps({'tree': tree, 'entries': final}, separators=(',', ':')) + '\n')
(root / 'hepta-36fa-fixed-a96-integration-baseline-ROOT_REVIEW.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k:v for k,v in result.items() if k != 'changes'}, indent=2))

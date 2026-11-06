"""Verify actual immutable objects, publication receipts and complete Git trees.

This reads frozen JSON/files only. It does not invoke a product, workflow or host.
"""
from pathlib import Path
import hashlib
import importlib.util
import json

ROOT = Path(__file__).resolve().parent
MAIN = '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
MAIN_TREE = '3982ba56dc5a3f1da0c1de7ea57992f88125c359'
BASE_REF = 'fix/r3-original-product-contracts-20261104'


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
            'sha256': hashlib.sha256(data).hexdigest()}


def unpack(raw):
    value = raw.get('structuredContent')
    if value is None:
        value = json.loads(next(item['text'] for item in raw['content'] if item['type'] == 'text'))
    return json.loads(value['content']) if isinstance(value.get('content'), str) else value


def run():
    spec = importlib.util.spec_from_file_location('frozen_merkle', ROOT / 'verify_postcut_publication.py')
    merkle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(merkle)
    main, main_dirs = merkle.verify_complete_tree(json.loads((ROOT / 'main67-full-tree.json').read_text()), MAIN_TREE)
    assert len(main) == 10582 and len(main_dirs) == 1571
    results = []
    expected = {
        'b21': {'head': 'ebd31e2b3e38ff72cedaa7b57bee60c1c102da27', 'parent': 'cc65856cc0b20d03db506c19495d53d61162102d',
                'tree': '46fca3e684217066c260dc10d0dc319a33e0a93c', 'merge': '01167418c3cf2970b156bc23be911b58ced49691',
                'workflow': '.github/workflows/b21-intel-original-pty.yml', 'blob': 'fb5881fa310d3548cd604d2827fe9c29aa1b3873',
                'bytes': 50740, 'review': 'ecab7af9dc20c8989b9c8c5a4a099f2c91cbf3d0', 'pr': 4902, 'stdout': 7890},
        'b23': {'head': 'e63ed76c5d8ded046f97caffbdbe2883140e6032', 'parent': MAIN,
                'tree': 'a6831e2607e718f1343b788e5b8062a171d50a71', 'merge': 'b3bc3dcf5684568dd03f3667ecd2307b8577a0a6',
                'workflow': '.github/workflows/hepta-b23-linux-app-server-original-gate.yml', 'blob': 'd4b87c924a1dcc795e05aec1dd4e31854dcff687',
                'bytes': 60049, 'review': '8c68dc2cca5bcff0eb99614eca5e39809dd616de', 'pr': 4910, 'stdout': 3472},
    }
    for tag, e in expected.items():
        directory = ROOT / tag
        records = json.loads((directory / 'publication-originals.json').read_text())['original_records']
        full, dirs = merkle.verify_complete_tree(json.loads((directory / 'intended-full-tree.json').read_text()), e['tree'])
        assert len(full) == 10583 and len(dirs) == 1571
        assert all(full[path] == leaf for path, leaf in main.items())
        assert set(full) - set(main) == {e['workflow']}
        w = records['workflowActual']
        wid = identity(w['text'].encode())
        assert wid == w['identity'] and wid['bytes'] == e['bytes'] and wid['git_blob'] == e['blob']
        raww = w['raw'].get('structuredContent')
        if raww is None:
            raww = json.loads(next(x['text'] for x in w['raw']['content'] if x['type'] == 'text'))
        assert raww['content'] == w['text']
        assert full[e['workflow']]['sha'] == e['blob']
        review = records['independentActual']
        assert identity(review['text'].encode()) == review['identity']
        assert review['identity']['git_blob'] == e['review']
        actual_root = unpack(records['treeRootActual']['raw'])
        assert actual_root == records['treeRootActual']['response']
        assert not actual_root['truncated'] and actual_root['sha'] == e['tree']
        intended_root = [{'path': path, 'mode': '040000', 'type': 'tree', 'sha': sha}
                         for path, sha in dirs.items() if path and '/' not in path]
        intended_root += [leaf for path, leaf in full.items() if '/' not in path]
        normalize = lambda rows: sorted(({key: item[key] for key in ('path', 'mode', 'type', 'sha')} for item in rows), key=lambda x: x['path'])
        assert normalize(actual_root['tree']) == normalize(intended_root)
        commit = unpack(records['commitActual']['raw'])
        merge = unpack(records['mergeActual']['raw'])
        assert commit['sha'] == e['head'] and commit['tree']['sha'] == e['tree']
        assert [p['sha'] for p in commit['parents']] == [e['parent']]
        assert merge['sha'] == e['merge'] and merge['tree']['sha'] == e['tree']
        assert [p['sha'] for p in merge['parents']] == [MAIN, e['head']]
        assert unpack(records['refAfter']['raw'])['object']['sha'] == e['head']
        pr = unpack(records['prFinalAfter' if tag == 'b21' else 'prConfirmedAfter']['raw'])
        assert pr['number'] == e['pr'] and pr['draft'] and pr['head']['sha'] == e['head']
        assert pr['base']['sha'] == MAIN and pr['base']['ref'] == BASE_REF and pr['merge_commit_sha'] == e['merge']
        intended = records['prBodyIntended']
        assert pr['body'] == (intended['body'] if tag == 'b21' else intended)
        if tag == 'b21':
            assert pr['body'].endswith(intended['old_body']) and len(intended['old_body']) == 1659
            assert unpack(records['refBefore']['raw'])['object']['sha'] == e['parent']
            old, _ = merkle.verify_complete_tree(json.loads((ROOT / 'cc-v1-full-tree.json').read_text()), 'eaded1870d080eaa55efae6208354729140e784c')
            assert set(old) == set(full)
            assert [p for p in full if full[p] != old[p]] == [e['workflow']]
        else:
            assert records['ref2Before']['response']['error_code'] == 'NOT_FOUND'
        stdout = (directory / 'static-root.stdout.json').read_bytes()
        assert len(stdout) == e['stdout']
        assert (directory / 'static-root.stderr.log').read_bytes() == b''
        results.append({**e, 'all_original_10582_leaves_unchanged': True, 'directory_nodes_recomputed': len(dirs),
                        'actual_root_GET_full_equal': True, 'actual_ref_and_PR_body_GET_equal': True,
                        'actual_merge_same_tree': True, 'root_static_replay_stdout': identity(stdout),
                        'native_result_asserted_by_this_receipt': False, 'blocker_status': 'OPEN'})
    return {'schema': 'hepta-b21-b23-root-publication-verification-v1', 'result': 'PASS',
            'source': MAIN, 'source_tree': MAIN_TREE, 'records': results,
            'B21_root_replay_limit': 'Root replayed the 7,890-byte pre-actual-GET-metadata verifier output. The later 7,937-byte output adds an actual-full-GET count; independent actual addendum2dae covers that increment. These outputs are not asserted byte-equal.',
            'native_or_required_qualification_granted': False, 'all_blockers_closed': False}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))

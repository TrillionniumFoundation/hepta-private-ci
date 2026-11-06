"""Reproduce the complete fixed-window branches inventory from retained API bodies."""
from pathlib import Path
from collections import Counter
import hashlib
import json

ROOT = Path(__file__).resolve().parent


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
            'sha256': hashlib.sha256(data).hexdigest()}


def main():
    raw = (ROOT / 'original-api-bodies.json').read_bytes()
    assert identity(raw) == {'bytes': 1545989, 'git_blob': 'e11589e6d83fef9e8463c50a355d61f410d88dde',
                             'sha256': '59b82e7e899657b89f49105cc8ed7ccef74470a6388a59edc5ede2ad742fe05d'}
    packet = json.loads(raw)
    records = packet['records']
    assert len(records) == 62
    for record in records:
        assert identity(record['original_api_body'].encode()) == record['body_identity']
    pages = {r['page']: r for r in records if r['kind'] == 'page'}
    assert sorted(pages) == list(range(1, 59))
    data = {p: json.loads(r['original_api_body']) for p, r in pages.items()}
    assert all(isinstance(v, list) for v in data.values())
    assert all(len(data[p]) == 100 for p in range(1, 54))
    assert len(data[54]) == 33 and all(data[p] == [] for p in range(55, 59))
    branches = [row for p in range(1, 55) for row in data[p]]
    assert len(branches) == len({row['name'] for row in branches}) == 5333
    for row in branches:
        assert isinstance(row['protected'], bool)
        assert len(row['commit']['sha']) == 40 and set(row['commit']['sha']) <= set('0123456789abcdef')
    anchors = {r['page']: r for r in records if r['kind'] == 'anchor'}
    assert sorted(anchors) == [1, 54, 55]
    for page, record in anchors.items():
        assert json.loads(record['original_api_body']) == data[page]
    current_main = next(row for row in branches if row['name'] == 'main')
    main_commit = json.loads(next(r['original_api_body'] for r in records if r['kind'] == 'actual_main_commit'))
    assert current_main['protected'] and current_main['commit']['sha'] == main_commit['sha'] == '732e934ba496d90fbe042b8d41d479ef901643e5'
    assert main_commit['tree']['sha'] == '75dc1c1f65375c97da259d947c465a04f030461d'
    families = Counter(row['name'].split('/', 1)[0] for row in branches)
    end = max(record['end_utc'] for record in records if 'end_utc' in record)
    output = {
        'schema': 'hepta-full-branch-census-20261106', 'scope': 'Complete branches API traversal in a bounded non-atomic observation window',
        'window_start_utc': packet['window_start'], 'window_end_utc': end,
        'per_page': 100, 'pages_retained': 58, 'full_pages': 53, 'partial_page': {'page': 54, 'count': 33},
        'first_empty_page': 55, 'additional_empty_pages_retained': [56, 57, 58], 'anchor_pages': [1, 54, 55],
        'complete_anchor_bodies_equal': True, 'returned_branches': len(branches), 'unique_branch_names': len(branches),
        'duplicate_names': [], 'protected_count': sum(row['protected'] for row in branches),
        'distinct_commit_shas': len({row['commit']['sha'] for row in branches}),
        'branch_name_prefix_counts': dict(sorted(families.items())),
        'prefix_is_commit_ancestry_claimed': False, 'atomic_snapshot_claimed': False,
        'actual_main': {'commit': main_commit['sha'], 'tree': main_commit['tree']['sha'],
                        'parents': [r['sha'] for r in main_commit['parents']], 'commit_author_date': main_commit['author']['date']},
        'original_bodies': identity(raw),
        'limits': ['All actual page-body bytes are preserved; repeated MCP wrappers and HTTP wire bytes are not claimed.',
                   'Only first/last/empty anchor bodies were rechecked. No claim that every ref was immutable throughout the window.',
                   'Branches created or moved after the bounded window belong to later publication receipts.',
                   'Full metadata/ref coverage is not line-by-line review or acceptance of every branch.'],
        'branches': branches,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

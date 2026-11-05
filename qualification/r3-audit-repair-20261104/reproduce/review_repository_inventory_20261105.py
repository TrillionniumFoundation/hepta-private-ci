import base64
import collections
import datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path('/workspace/scratch/07dd58cc9630')
SOURCE = ROOT / 'research-audit/repository-inventory-20261105'
OUT = ROOT / 'hepta-audit-fourth/deliverables/fourth-repository-inventory-root-review-20261105.json'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def check(raw, expected):
    actual = identity(raw)
    for key in actual:
        if key in expected:
            assert actual[key] == expected[key], (key, actual, expected)
    return actual

manifest_raw = (SOURCE / 'archive-manifest.json').read_bytes()
manifest = json.loads(manifest_raw)
inventory_raw = (SOURCE / 'complete-inventory.json').read_bytes()
inventory = json.loads(inventory_raw)
check(inventory_raw, manifest['inventory'])
part_bytes = []
offset = 0
for number, part in enumerate(manifest['parts']):
    assert part['sequence'] == number and part['offset'] == offset
    raw = (SOURCE / part['path']).read_bytes()
    check(raw, part)
    part_bytes.append(raw)
    offset += len(raw)
assert offset == manifest['base64_bytes']
compressed = base64.b64decode(b''.join(part_bytes), validate=True)
check(compressed, manifest['gzip'])
assert compressed == (SOURCE / 'pagination-originals.tar.gz').read_bytes()
tar_bytes = gzip.decompress(compressed)
check(tar_bytes, manifest['uncompressed_tar'])
expected = {item['path']: item for item in manifest['members']}
assert len(expected) == manifest['member_count']
originals = {}
with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:') as archive:
    members = archive.getmembers()
    assert len(members) == len(expected)
    assert {member.name for member in members} == set(expected)
    for member in members:
        assert member.isfile(), member.name
        raw = archive.extractfile(member).read()
        check(raw, expected[member.name])
        originals[member.name] = raw
assert originals['complete-inventory.json'] == inventory_raw

def page_collection(kind):
    names = sorted(name for name in originals if name.startswith(f'raw/{kind}-page-'))
    pages = [json.loads(originals[name]) for name in names]
    assert all(isinstance(page, list) for page in pages)
    assert names == [f'raw/{kind}-page-{number:03}.json' for number in range(1, len(names) + 1)]
    first_empty = next(number for number, page in enumerate(pages, 1) if not page)
    assert all(not page for page in pages[first_empty - 1:])
    assert all(len(page) == 100 for page in pages[:first_empty - 2])
    return [item for page in pages for item in page], pages, first_empty

prs, pr_pages, pr_empty = page_collection('pulls')
branches, branch_pages, branch_empty = page_collection('branches')
issues, issue_pages, issue_empty = page_collection('issues')
pr_map = {pr['number']: pr for pr in prs}
branch_map = {branch['name']: branch['commit']['sha'] for branch in branches}
assert len(pr_map) == len(prs) and len(branch_map) == len(branches)
assert set(pr_map) == {pr['number'] for pr in inventory['prs']}
assert branch_map == {branch['name']: branch['sha'] for branch in inventory['branches']}
assert {issue['number'] for issue in issues if 'pull_request' in issue} == set(pr_map)
non_pr_issues = [issue for issue in issues if 'pull_request' not in issue]
releases = json.loads(originals['raw/releases.json'])
counts = {'open_prs': len(prs), 'draft': sum(pr['draft'] for pr in prs),
          'non_draft': sum(not pr['draft'] for pr in prs), 'branches': len(branches),
          'base_main': sum(pr['base']['ref'] == 'main' for pr in prs),
          'base_non_main': sum(pr['base']['ref'] != 'main' for pr in prs),
          'open_issues': len(non_pr_issues),
          'published_releases': sum(not release['draft'] for release in releases),
          'all_releases_including_drafts': len(releases)}
for key, value in counts.items():
    assert inventory['counts'][key] == value
assert all(pr['state'] == 'open' for pr in prs)

head_refs = collections.defaultdict(list)
for pr in prs:
    head_refs[pr['head']['ref']].append(pr['number'])
assert not [name for name, numbers in head_refs.items() if len(numbers) > 1]
parents = {pr['number']: head_refs.get(pr['base']['ref'], [None])[0] for pr in prs}
depths = {}
def depth(number, visited=()):
    assert number not in visited, ('cycle', visited, number)
    if number not in depths:
        parent = parents[number]
        depths[number] = 1 if parent is None else 1 + depth(parent, visited + (number,))
    return depths[number]
for number in pr_map:
    depth(number)
assert max(depths.values()) == inventory['stack_graph']['max_depth'] == 211
assert all(depths[pr['number']] == pr['open_stack_depth'] for pr in inventory['prs'])
head_mismatches = [pr['number'] for pr in prs if branch_map.get(pr['head']['ref']) != pr['head']['sha']]
base_mismatches = [pr['number'] for pr in prs if branch_map.get(pr['base']['ref']) != pr['base']['sha']]
assert not head_mismatches
assert len(base_mismatches) == inventory['cross_collection_checks']['base_ref_tip_discrepancy_count'] == 185

def pr_identity(pr):
    return (pr['number'], pr['state'], pr['draft'], pr['head']['ref'], pr['head']['sha'],
            pr['base']['ref'], pr['base']['sha'], pr['updated_at'])
def branch_identity(branch):
    return branch['name'], branch['commit']['sha']
anchors = {}
for name, original, key in [
    ('pulls-first', pr_pages[0], pr_identity),
    ('pulls-last', pr_pages[11], pr_identity),
    ('pulls-empty', pr_pages[12], pr_identity),
    ('branches-first', branch_pages[0], branch_identity),
    ('branches-last', branch_pages[51], branch_identity),
    ('branches-empty', branch_pages[52], branch_identity)]:
    final = json.loads(originals[f'raw/final-{name}.json'])
    anchors[name] = [key(item) for item in original] == [key(item) for item in final]
    assert anchors[name]
latest = json.loads(originals['raw/final-pulls-latest.json'])
anchors['latest100'] = [pr_identity(pr) for pr in sorted(prs, key=lambda pr: (pr['created_at'], pr['number']), reverse=True)[:100]] == [pr_identity(pr) for pr in latest]
assert anchors['latest100']
start_repo = json.loads(originals['raw/repository-start.json'])
end_repo = json.loads(originals['raw/final-repository.json'])
assert start_repo['pushed_at'] == end_repo['pushed_at']
old_raw = (SOURCE / 'old-complete-inventory.json').read_bytes()
check(old_raw, inventory['previous_snapshot'])
old = json.loads(old_raw)
added_prs = sorted(set(pr_map) - {pr['number'] for pr in old['prs']})
removed_prs = sorted({pr['number'] for pr in old['prs']} - set(pr_map))
added_branches = sorted(set(branch_map) - {branch['name'] for branch in old['branches']})
removed_branches = sorted({branch['name'] for branch in old['branches']} - set(branch_map))
assert added_prs == list(range(4809, 4824)) and not removed_prs
assert len(added_branches) == 30 and not removed_branches
candidate = json.loads(originals['raw/final-candidate4797.json'])
assert candidate['draft'] and candidate['state'] == 'open'
assert candidate['head']['sha'] == 'cabcb40d36e116beaa65750e1f674c52035da785'

report = {'schema': 'hepta-complete-repository-inventory-independent-root-review-v1',
          'reviewed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'inventory': identity(inventory_raw), 'archive_manifest': identity(manifest_raw),
          'actual_local_reconstruction': {'strict_base64_parts': len(part_bytes),
              'gzip_crc_checked_by_full_decompression': True, 'full_tar_identity_matches': True,
              'all_members_reopened_and_hashed': len(originals), 'no_extraction_or_execution': True,
              'raw_api_body_count_from_manifest': manifest['raw_api_body_count'],
              'raw_api_bytes_from_manifest': manifest['raw_api_bytes'],
              'scope': 'Independent local reconstruction from exact published-object bytes. Agent Git readback receipt separately records remote availability; this script does not re-fetch Git objects.'},
          'counts_recomputed_from_original_api_pages': counts,
          'pagination': {'pulls': {'pages': len(pr_pages), 'first_empty': pr_empty},
              'branches': {'pages': len(branch_pages), 'first_empty': branch_empty},
              'issues': {'pages': len(issue_pages), 'first_empty': issue_empty}},
          'stack_recomputed': {'maximum_open_ref_chain': max(depths.values()), 'all_1103_depths_equal': True,
              'cycles': [], 'duplicate_head_refs': [], 'head_branch_mismatches': head_mismatches,
              'metadata_base_vs_current_ref_tip_discrepancies': len(base_mismatches),
              'limit': 'Ref-name dependency graph; 185 base metadata discrepancies are not proof of merge conflicts.'},
          'ending_anchor_comparisons': anchors, 'pushed_at_unchanged': start_repo['pushed_at'],
          'reviewer_check_correction': 'The first root check sorted only creation timestamps and reversed two same-second PRs, #4743/#4744. The observed API order uses descending PR number within this tie. Adding that tie-breaker reproduced all 100 original identities; no inventory input or acceptance scope changed.',
          'previous_snapshot_bytes_unchanged': identity(old_raw),
          'delta': {'added_prs': added_prs, 'removed_open_prs': removed_prs,
              'added_branches': len(added_branches), 'removed_branches': removed_branches},
          'candidate_at_observation': {'number': 4797, 'draft': True, 'head': candidate['head']['sha'],
              'base': candidate['base']['sha'], 'merge_commit': candidate['merge_commit_sha']},
          'scope_limits': ['Pagination is not an atomic GitHub transaction. Ending anchors reduce observed drift but do not guarantee unobserved intermediate stability.',
              'Counts describe the stated observation window, not all future repository changes.',
              'No whole blocker, runtime qualification, mergeability, release readiness or scientific efficacy follows from inventory counts.']}
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'report': str(OUT), 'identity': identity(OUT.read_bytes()), 'counts': counts,
                  'members': len(originals), 'all_depths_recomputed': len(depths)}, ensure_ascii=False))

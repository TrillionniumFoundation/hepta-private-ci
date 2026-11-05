from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json

ROOT = Path(__file__).resolve().parent


def ident(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def read(name):
    return json.loads((ROOT / name).read_text())


all_identity_rows = read('raw-identities.json')
for metadata_name in ['final-anchor-acquisition.json', 'donor-acquisition.json']:
    metadata = read(metadata_name)
    rows = metadata['records'] if isinstance(metadata, dict) else metadata
    for row in rows:
        path = ROOT / row['path']
        data = path.read_bytes()
        if len(data) == row['api_raw_bytes'] + 1 and data.endswith(b'\n'):
            data = data[:-1]
            path.write_bytes(data)
        assert len(data) == row['api_raw_bytes'], row['path']
        all_identity_rows.append({**row, **ident(data)})

acquisition = read('page-acquisition.json')['records']
collections = {}
pagination = {}
for kind in ['pulls', 'branches', 'issues']:
    rows = sorted((r for r in acquisition if r['kind'] == kind), key=lambda r: r['page'])
    assert [r['page'] for r in rows] == list(range(1, len(rows) + 1)), kind
    counts = [len(read(r['path'])) for r in rows]
    first_empty = counts.index(0) + 1
    assert all(n == 100 for n in counts[:first_empty - 2]), (kind, counts)
    assert 0 < counts[first_empty - 2] <= 100
    assert all(n == 0 for n in counts[first_empty - 1:])
    data = [x for r in rows for x in read(r['path'])]
    keys = [x['name'] if kind == 'branches' else x['number'] for x in data]
    dup = [k for k, n in Counter(keys).items() if n > 1]
    assert not dup, (kind, dup)
    if kind != 'branches':
        assert all(x['state'] == 'open' for x in data)
        # GitHub promises the requested created timestamp sort, not a secondary
        # PR/issue-number order for equal-second timestamps.
        ordered = [x['created_at'] for x in data]
        assert ordered == sorted(ordered), kind
    collections[kind] = data
    pagination[kind] = {
        'per_page': 100, 'requested_pages': [r['page'] for r in rows],
        'counts': counts, 'first_terminal_empty_page': first_empty,
        'extra_empty_guard_pages': [r['page'] for r in rows if r['page'] > first_empty],
        'started_at_utc': min(r['started_at'] for r in rows),
        'read_finished_at_utc': max(r['completed_at'] for r in rows),
        'unique_count': len(keys), 'duplicate_keys': dup,
        'all_pages_contiguous': True, 'all_data_before_terminal_empty': True,
    }

prs = collections['pulls']
branches = collections['branches']
issues = collections['issues']
old = read('old-complete-inventory.json')
branch_by_name = {x['name']: x['commit']['sha'] for x in branches}
old_branch = {x['name']: x['sha'] for x in old['branches']}


def graph(prs):
    by_number = {p['number']: p for p in prs}
    by_head = defaultdict(list)
    for p in prs:
        by_head[p['head']['ref']].append(p['number'])
    ambiguity = {k: v for k, v in by_head.items() if len(v) > 1}
    parents = {p['number']: by_head[p['base']['ref']][0] for p in prs if len(by_head.get(p['base']['ref'], [])) == 1}
    depths, cycles = {}, []
    def visit(n, trail):
        if n in depths:
            return depths[n]
        if n in trail:
            cycle = trail[trail.index(n):]
            cycles.append(cycle)
            return None
        parent = parents.get(n)
        pd = visit(parent, trail + [n]) if parent is not None else 0
        depth = None if pd is None else pd + 1
        depths[n] = depth
        return depth
    for n in by_number:
        visit(n, [])
    return depths, cycles, ambiguity, parents


old_depth, old_cycles, old_ambiguities, _ = graph(old['prs'])
assert max(old_depth.values()) == old['stack_graph']['max_depth'] == 211
assert old_cycles == old['stack_graph']['cycles'] == []
assert all(old_depth[p['number']] == p['open_stack_depth'] for p in old['prs'])
depths, cycles, ambiguous_heads, parent_edges = graph(prs)

projected = []
for p in sorted(prs, key=lambda p: p['number'], reverse=True):
    projected.append({
        'number': p['number'], 'title': p['title'], 'draft': p['draft'], 'state': p['state'],
        'html_url': p['html_url'], 'created_at': p['created_at'], 'updated_at': p['updated_at'],
        'base': {k: p['base'][k] for k in ['ref', 'sha']},
        'head': {k: p['head'][k] for k in ['ref', 'sha']},
        'base_repository': p['base']['repo']['full_name'] if p['base']['repo'] else None,
        'head_repository': p['head']['repo']['full_name'] if p['head']['repo'] else None,
        'labels': [l['name'] for l in p['labels']], 'open_stack_depth': depths[p['number']],
    })

old_pr = {x['number']: x for x in old['prs']}
new_pr = {x['number']: x for x in projected}
existing_changes = []
for number in sorted(set(old_pr) & set(new_pr)):
    a, b = old_pr[number], new_pr[number]
    changes = {}
    for field in ['title', 'draft', 'state', 'updated_at', 'labels']:
        if a[field] != b[field]:
            changes[field] = {'before': a[field], 'after': b[field]}
    for object_name in ['head', 'base']:
        for field in ['ref', 'sha']:
            if a[object_name][field] != b[object_name][field]:
                changes[object_name + '.' + field] = {'before': a[object_name][field], 'after': b[object_name][field]}
    if changes:
        existing_changes.append({'number': number, 'title': b['title'], 'changes': changes})

head_discrepancies = []
base_discrepancies = []
for p in projected:
    if p['head_repository'] == 'TrillionniumFoundation/hepta-private-ci' and branch_by_name.get(p['head']['ref']) != p['head']['sha']:
        head_discrepancies.append({'number': p['number'], 'ref': p['head']['ref'], 'pr_sha': p['head']['sha'], 'branch_sha': branch_by_name.get(p['head']['ref'])})
    if p['base_repository'] == 'TrillionniumFoundation/hepta-private-ci' and branch_by_name.get(p['base']['ref']) != p['base']['sha']:
        base_discrepancies.append({'number': p['number'], 'ref': p['base']['ref'], 'pr_sha': p['base']['sha'], 'branch_sha': branch_by_name.get(p['base']['ref'])})

non_pr_issues = [i for i in issues if 'pull_request' not in i]
issue_pr_numbers = {i['number'] for i in issues if 'pull_request' in i}
assert issue_pr_numbers == set(new_pr)
releases = read('raw/final-releases.json')
published_releases = [r for r in releases if not r['draft'] and r.get('published_at')]
assert not releases
repo_start = read('raw/repository-start.json')
repo_end = read('raw/final-repository.json')
candidate = read('raw/final-candidate4797.json')
research = read('raw/final-research4798.json')
main = read('raw/final-main.json')
base = read('raw/final-base.json')
assert candidate['head']['sha'] == new_pr[4797]['head']['sha'] == branch_by_name[candidate['head']['ref']]
assert research['head']['sha'] == new_pr[4798]['head']['sha'] == branch_by_name[research['head']['ref']]
assert main['object']['sha'] == branch_by_name['main']
assert base['object']['sha'] == branch_by_name[candidate['base']['ref']]
drift = read('final-anchor-acquisition.json')
assert all(drift['drift_checks'].values())
max_depth = max(d for d in depths.values() if d is not None)

counts = {
    'open_prs': len(prs), 'draft': sum(p['draft'] for p in prs), 'non_draft': sum(not p['draft'] for p in prs),
    'branches': len(branches), 'base_main': sum(p['base']['ref'] == 'main' for p in prs),
    'base_non_main': sum(p['base']['ref'] != 'main' for p in prs),
    'open_issues': len(non_pr_issues), 'published_releases': len(published_releases),
    'all_releases_including_drafts': len(releases),
    'repo_open_issues_including_pr': repo_end['open_issues_count'],
}

inventory = {
    'schema': 'hepta.complete-repository-inventory.v2', 'repository': 'TrillionniumFoundation/hepta-private-ci',
    'created_at_utc': datetime.now(timezone.utc).isoformat(),
    'previous_snapshot': {'blob': '0db12ef5efcb2df620def35407a3076f1af8aa2b', **ident((ROOT / 'old-complete-inventory.json').read_bytes()), 'final_anchor_at_utc': old['pr_observation']['final_anchor_at_utc'], 'counts': old['counts'], 'preserved_unchanged': True},
    'observations': {'pagination': pagination, 'final_anchor_queries': drift['records'], 'drift_checks': drift['drift_checks'], 'repo_pushed_at_before': repo_start['pushed_at'], 'repo_pushed_at_after': repo_end['pushed_at'], 'repo_open_issues_count_is_supplemental_only': True, 'pr_number_set_equal_issue_pr_set': True},
    'counts': counts,
    'stack_graph': {'definition': old['stack_graph']['definition'], 'previous_algorithm_reproduces_all_1088_old_depths': True, 'cycles': cycles, 'ambiguous_head_refs': ambiguous_heads, 'max_depth': max_depth, 'deepest_prs': [{'number': p['number'], 'head': p['head']['ref'], 'depth': depths[p['number']]} for p in projected if depths[p['number']] == max_depth], 'parent_edges': [{'number': n, 'parent_pr': p} for n, p in sorted(parent_edges.items())]},
    'cross_collection_checks': {'head_branch_discrepancies': head_discrepancies, 'base_ref_tip_discrepancies': base_discrepancies, 'base_ref_tip_discrepancy_count': len(base_discrepancies)},
    'current_candidate': {k: candidate[k] for k in ['number', 'title', 'state', 'draft', 'updated_at', 'merge_commit_sha']},
    'current_candidate_refs': {'head': candidate['head']['sha'], 'head_ref': candidate['head']['ref'], 'metadata_base_sha': candidate['base']['sha'], 'base_ref': candidate['base']['ref'], 'current_base_ref_sha': base['object']['sha']},
    'main': {'ref': 'main', 'sha': main['object']['sha'], 'default_branch': repo_end['default_branch']},
    'research_4798': {'state': research['state'], 'draft': research['draft'], 'head': research['head']['sha'], 'head_ref': research['head']['ref'], 'base': research['base']['sha'], 'base_ref': research['base']['ref'], 'merge_commit_sha': research['merge_commit_sha'], 'updated_at': research['updated_at']},
    'delta': {
        'counts': {k: counts[k] - old['counts'][k] for k in old['counts'] if k in counts},
        'added_prs': [new_pr[n] for n in sorted(set(new_pr) - set(old_pr))],
        'removed_from_open_pr_inventory': sorted(set(old_pr) - set(new_pr)),
        'changed_existing_prs': existing_changes,
        'added_branches': [{'name': n, 'sha': branch_by_name[n]} for n in sorted(set(branch_by_name) - set(old_branch))],
        'removed_branches': [{'name': n, 'old_sha': old_branch[n]} for n in sorted(set(old_branch) - set(branch_by_name))],
        'changed_branch_tips': [{'name': n, 'before': old_branch[n], 'after': branch_by_name[n]} for n in sorted(set(branch_by_name) & set(old_branch)) if old_branch[n] != branch_by_name[n]],
    },
    'prs': projected,
    'branches': [{'name': x['name'], 'sha': x['commit']['sha'], 'protected': x['protected']} for x in branches],
    'open_non_pr_issues': non_pr_issues, 'releases': releases,
    'raw_identity_index': 'raw-identities-complete.json',
    'scope_limits': [
        'The API collections were fully paginated during separate recorded intervals. This is not an atomic point-in-time snapshot.',
        'First/last/empty-page and latest100 PR anchors agreed; repository pushed_at was unchanged. These checks do not prove absence of all concurrent metadata changes.',
        'Counts are from enumerated collection rows; repository open_issues_count includes PRs and is only an independently recorded supplemental value.',
        'Ref-name stack depth is not verified commit ancestry, integration compatibility, or mergeability; PR base.sha mismatches are not declared merge conflicts.',
        'The unchanged published PR4797 source is distinct from the unpublished native work tree and from all donor candidates.',
        'No test, ref/PR mutation, external message, release or whole-blocker status change was performed.',
    ],
}
(ROOT / 'complete-inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')
(ROOT / 'raw-identities-complete.json').write_text(json.dumps(all_identity_rows, ensure_ascii=False, indent=2) + '\n')
summary = {k: inventory[k] for k in ['counts', 'stack_graph', 'current_candidate_refs', 'research_4798']}
summary['stack_graph'] = {k: v for k, v in summary['stack_graph'].items() if k != 'parent_edges'}
summary['base_metadata_mismatch_count'] = len(base_discrepancies)
summary['head_branch_discrepancies'] = head_discrepancies
summary['delta_counts'] = inventory['delta']['counts']
summary['branch_delta_counts'] = {k: len(inventory['delta'][k]) for k in ['added_branches', 'removed_branches', 'changed_branch_tips']}
summary['existing_pr_delta'] = existing_changes
summary['inventory_identity'] = ident((ROOT / 'complete-inventory.json').read_bytes())
print(json.dumps(summary, ensure_ascii=False, indent=2))

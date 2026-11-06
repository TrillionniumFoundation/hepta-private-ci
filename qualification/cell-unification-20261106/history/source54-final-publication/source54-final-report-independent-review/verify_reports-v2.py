#!/usr/bin/env python3
"""Independent local data review. Never imports or executes repository programs."""
import argparse
import collections
import gzip
import hashlib
import json
import re
from pathlib import Path

W = Path(__file__).resolve().parent.parent
Q = W / 'hepta-cell/qualification/cell-unification-20261106'
FINAL = Q / 'native-evidence/source53-finalization-checkpoint'
FC = 'b5209cfdf509e990f10922197b32540bf8c353a7'
FT = '42c1dd4e1a751c690c2800dfc3868e771dc9c70b'
TC = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
TT = '440d4a8e09af4009e4d9ea067388826308da8803'
PINKEYS = ('bytes', 'sha256', 'git_blob')
SOURCEKEYS = ('mode',) + PINKEYS


def pin_bytes(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}


def read_json(p):
    return json.loads(p.read_bytes())


def walk(v, pointer=''):
    yield pointer, v
    if isinstance(v, dict):
        for k, x in v.items():
            yield from walk(x, pointer + '/' + str(k).replace('~', '~0').replace('/', '~1'))
    elif isinstance(v, list):
        for k, x in enumerate(v):
            yield from walk(x, pointer + '/' + str(k))


def section(b, number):
    m = re.search(rb'(?m)^## ' + str(number).encode() + rb'\.', b)
    assert m, ('missing README section', number)
    n = re.search(rb'(?m)^## ', b[m.end():])
    return b[m.start(): m.end() + n.start() if n else len(b)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--handoff-sha256', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--allow-tested-label-clarification', action='store_true')
    a = ap.parse_args()
    c = W / a.candidate
    out = W / a.out
    assert not out.exists(), 'create-only output'
    checks, findings, inputs = [], [], {}

    def record_input(p):
        p = Path(p)
        b = p.read_bytes()
        inputs[str(p.relative_to(W))] = pin_bytes(b)
        return b

    def check(name, condition, detail=None):
        checks.append({'check': name, 'pass': bool(condition), 'detail': detail})
        if not condition:
            findings.append({'kind': 'mechanical_mismatch', 'check': name, 'detail': detail})

    def verified_file(p, expected):
        actual = pin_bytes(record_input(p))
        return all(actual[k] == expected[k] for k in PINKEYS if k in expected)

    hraw = record_input(c / 'HANDOFF-MANIFEST.json')
    check('frozen_candidate_handoff', hashlib.sha256(hraw).hexdigest() == a.handoff_sha256)
    h = json.loads(hraw)
    paths = [x['path'] for x in h['files']]
    actual_paths = sorted(str(p.relative_to(c)) for p in c.rglob('*') if p.is_file())
    check('candidate_exact_inventory', len(paths) == len(set(paths)) and sorted(paths + ['HANDOFF-MANIFEST.json']) == actual_paths,
          {'listed': len(paths), 'regular_files': len(actual_paths)})
    for row in h['files']:
        check('candidate_pin:' + row['path'], verified_file(c / row['path'], row))
    source_input_manifest = read_json(c / 'INPUT-PINS.json')
    for row in source_input_manifest['files']:
        check('generation_input_pin:' + row['path'], verified_file(W / row['path'], row))

    bas = c / 'base/r30-closed-candidate-v2'
    baspr = c / 'base/r30-closed-pr-guide'
    current_readme = (c / 'candidates/README.md').read_bytes()
    old_readme = (bas / 'README.md').read_bytes()
    protected_sections = []
    for n in (1, 2, 4):
        before, after = section(old_readme, n), section(current_readme, n)
        normalized = after
        if n == 2 and a.allow_tested_label_clarification:
            normalized = after.replace('源码来源与受测53个登记记录'.encode(), '源码来源与53个登记记录'.encode())
        check('README_protected_section_' + str(n), before == normalized)
        protected_sections.append({'section': n, 'before': pin_bytes(before), 'after': pin_bytes(after),
            'whole_bytes_equal': before == after, 'authorized_label_inverse_equal': before == normalized})
    status = read_json(c / 'candidates/STATUS.json')
    oldstatus = read_json(bas / 'STATUS.json')
    identity = read_json(c / 'candidates/SOURCE_IDENTITY.json')
    oldidentity = read_json(bas / 'SOURCE_IDENTITY.json')
    dynamic = read_json(c / 'pr-guide-candidates/DYNAMIC-STATUS.json')
    groups = read_json(c / 'pr-guide-candidates/PATH-GROUPS.json')
    oldgroups = read_json(baspr / 'PATH-GROUPS.json')
    protected_fields = ['taxonomy', 'source_inputs', 'implementation', 'science', 'historical_assets', 'upstream_ci_history', 'source_compatibility']
    for k in protected_fields:
        check('STATUS_protected_field:' + k, status[k] == oldstatus[k])
    check('historical_gate_key_set', status['validation']['gates'].keys() == oldstatus['validation']['gates'].keys())
    for k, v in oldstatus['validation']['gates'].items():
        if k != 'r31':
            check('historical_gate_exact:' + k, status['validation']['gates'][k] == v)
    check('historical_failure_IDs_exact', status['current_failures']['ids'] == oldstatus['current_failures']['ids'])
    check('old_53_registration_records_exact', identity['created_source_commits'][:-1] == oldidentity['created_source_commits'])
    check('actual_54th_registration', len(identity['created_source_commits']) == 54 and identity['created_source_commits'][-1]['sha'] == FC and identity['created_source_commits'][-1]['tree'] == FT)

    reg = read_json(c / 'new-files/history/source53-final-report/final-code-registration/ROOT-CODE-READBACK.json')
    commitapi = read_json(c / 'new-files/history/source53-final-report/final-code-registration/CREATED-COMMIT-API-ORIGINAL.json')
    check('actual_commit_API', commitapi.get('sha') == FC and commitapi.get('tree', {}).get('sha') == FT and [p['sha'] for p in commitapi['parents']] == [TC])
    check('actual_registration_pin', verified_file(c / 'new-files/history/source53-final-report/final-code-registration/ROOT-CODE-READBACK.json', {'bytes': 3786, 'sha256': '7b9642d8c6a50393dc4f6421b9d1499135efb4faaf3347a1550c678900ca32ac'}))
    check('STATUS_actual_source54', (status['current_source']['stage'], status['current_source']['commit'], status['current_source']['tree']) == (54, FC, FT))
    check('SOURCE_IDENTITY_actual_source54', (identity['current_source_stage'], identity['current_source_commit'], identity['current_source_tree']) == (54, FC, FT))
    check('tested_source53_separate', (identity['tested_source_commit'], identity['tested_source_tree'], identity['last_closed_rust_gate_tree'], identity['last_closed_default_workspace_tree']) == (TC, TT, TT, TT))
    for label, doc in [('dynamic', dynamic), ('path_groups', groups)]:
        check(label + '_two_source_identities', (doc['source_commit'], doc['source_tree'], doc['tested_source_commit'], doc['tested_source_tree']) == (FC, FT, TC, TT))
    for label, doc in [('STATUS', status['final_fix_fmt']), ('SOURCE_IDENTITY', identity), ('DYNAMIC', dynamic)]:
        check(label + '_no_post_format_tests_or_transfer', doc['post_fix_or_format_tests_executed'] is False and doc['qualification_transferred_to_mutated_tree'] is False)
    check('no_branch_PR', status['publication']['branch_created'] is False and status['publication']['pull_request_created'] is False and identity['branch_created'] is False and identity['pull_request_created'] is False and dynamic['pr_sent'] is False)
    check('CI_pending', 'PENDING' in status['publication']['final_github_ci'] and 'PENDING' in dynamic['final_ci'])
    check('science_HOLD_authority_DENY_ALL', status['overall']['scientific_disposition'] == 'HOLD' and status['overall']['authority'] == 'DENY_ALL' and identity['scientific_disposition'] == 'HOLD' and identity['authority'] == 'DENY_ALL' and dynamic['science'] == 'HOLD' and dynamic['authority'] == 'DENY_ALL')
    check('diagnostic_only_no_rootcause_claim', status['current_failures']['diagnostic_only'] is True and status['current_failures']['behavior_repair_claimed'] is False and status['current_failures']['root_cause_proven'] is False)
    expected_counts = {'r30': {'unique_test_results': 1345, 'passed': 1345, 'failed': 0, 'timed_out': 0, 'reported_skipped': 2},
                       'r31': {'unique_test_results': 20228, 'passed': 20228, 'failed': 0, 'timed_out': 0, 'reported_skipped': 130}}
    for k, e in expected_counts.items():
        g = status['validation']['gates'][k]
        check(k + '_separate_original_counts_and_identity', g['counts'] == e and (g['source_commit'], g['source_tree']) == (TC, TT))
        check(k + '_natural_raw_effective_outer_zero', g['tests_raw_exit_code'] == g['tests_effective_exit_code'] == g['original_outer_exit_code'] == 0 and g['natural_outer_durable_complete'] is True)
    check('r31_no_p_original_command', status['validation']['gates']['r31']['original_command'] == ['just', 'test', '--locked', '--retries', '0'])
    check('r31_fresh193', status['validation']['gates']['r31']['actual_workspace_member_count'] == status['validation']['gates']['r31']['actual_workspace_default_member_count'] == 193)
    check('r31_announcement_vs_rows_groups', status['validation']['gates']['r31']['announced_binaries'] == 366 and status['validation']['gates']['r31']['binary_groups_with_executed_rows'] == 323)

    final_manifest = read_json(FINAL / 'original/finalization/final-post-format-source-manifest.json')
    tested_manifest = read_json(FINAL / 'original/finalization/tested-pre-fix-source-manifest.json')
    record_input(FINAL / 'original/finalization/final-post-format-source-manifest.json')
    record_input(FINAL / 'original/finalization/tested-pre-fix-source-manifest.json')
    finalmap = {x['path']: x for x in final_manifest['changed_files']}
    testedmap = {x['path']: x for x in tested_manifest['changed_files']}
    oldpathmap = {x['path']: x for x in oldgroups['paths']}
    check('197_final_tested_pathset', len(finalmap) == len(testedmap) == len(groups['paths']) == 197 and set(finalmap) == set(testedmap) == set(x['path'] for x in groups['paths']))
    check('PR_group_objects_exact', groups['groups'] == oldgroups['groups'])
    change_paths = []
    for row in groups['paths']:
        p = row['path']
        check('final_source_pin:' + p, all(row[k] == finalmap[p][k] for k in SOURCEKEYS))
        check('tested_source_pin:' + p, all(row['tested_source_pin'][k] == testedmap[p][k] for k in SOURCEKEYS))
        check('unchanged_owner_group:' + p, all(row[k] == oldpathmap[p][k] for k in ('review_group', 'owner')))
        check('final_fixed_source_URL:' + p, row['source_url'] == f'https://github.com/TrillionniumFoundation/hepta-private-ci/blob/{FC}/{p}')
        changed = row['sha256'] != testedmap[p]['sha256']
        check('source_change_flag:' + p, row['changed_during_finalization'] == changed)
        if changed:
            change_paths.append(p)
    check('format_56_54Rust_2Python', len(change_paths) == 56 and sum(p.endswith('.rs') for p in change_paths) == 54 and sum(p.endswith('.py') for p in change_paths) == 2)
    check('original_A25_B123_C38_D9_E2_membership', dict(collections.Counter(x['review_group'] for x in groups['paths'])) == {'A': 25, 'B': 123, 'C': 38, 'D': 9, 'E': 2})
    check('197_183Rust_14other_26owner_27CI', groups['counts'] == {'paths': 197, 'rust': 183, 'other': 14, 'rust_owners': 26, 'ci_package_selectors': 27})
    phases = status['final_fix_fmt']['phases']
    check('actual_fix_empty_format56', phases['fix']['changed_paths'] == [] and phases['fix']['before_tree'] == phases['fix']['after_tree'] == TT and set(phases['format']['changed_paths']) == set(change_paths))
    check('original_fix26_defaultfmt', phases['fix']['command'][:3] == ['just', 'fix', '--locked'] and len(phases['fix']['command'][3:]) == 52 and phases['format']['command'] == ['just', 'fmt'])
    check('fix_fmt_receipts_zero', all(phases[k]['exit_code'] == phases[k]['effective_exit_code'] == 0 for k in ('fix', 'format')))
    fixraw = record_input(FINAL / 'original/finalization/fix.log')
    headers = [(n, line) for n, line in enumerate(fixraw.decode().splitlines(), 1) if line.startswith('warning:')]
    diag = [(n, line) for n, line in headers if ' generated ' not in line]
    warnings = phases['fix']['warnings']
    check('three_diagnostic_plus_three_summary_warnings', len(headers) == 6 and len(diag) == 3 and warnings['diagnostic_warning_count'] == 3 and warnings['warning_header_occurrences'] == 6)
    for w in warnings['diagnostic_warnings']:
        raw = fixraw[w['byte_offset']:w['byte_end']]
        check('warning_original_bytes_line_' + str(w['line']), raw.decode() == w['block_text'] and hashlib.sha256(raw).hexdigest() == w['block_sha256'])

    # Resolve candidate relative paths against their future canonical overlay.
    overlay = {str(p.relative_to(c / 'new-files')): p for p in (c / 'new-files').rglob('*') if p.is_file()}
    overlay.update({n: c / 'candidates' / n for n in ('README.md', 'STATUS.json', 'SOURCE_IDENTITY.json')})
    source_map = read_json(FINAL / 'SOURCE-DESTINATION-MAPPING.json')['files']
    by_hash = collections.defaultdict(list)
    for x in source_map:
        by_hash[x['sha256']].append(FINAL / x['destination_path'])
    index = read_json(Q / 'native-evidence/INDEX.json')
    historical_refs = {}
    report_tree_path = W / 'publication-recovery-prep/checkpoint6-plan/ACTUAL-REPORT-TREE-API.json'
    report_tree = json.loads(record_input(report_tree_path))
    check('inherited_actual_report_tree_not_truncated', report_tree['truncated'] is False)
    for row in report_tree['tree']:
        if row['type'] == 'blob':
            historical_refs[row['path']] = {'bytes': row['size'], 'git_blob': row['sha'],
                'source': str(report_tree_path.relative_to(W)), 'tree': report_tree['sha'], 'raw_bytes_reread': False}
    for row in index['artifacts']:
        historical_refs['native-evidence/' + row['path']] = row
    for row in index['additional_inherited_git_paths_not_in_prior_raw_inventory']:
        historical_refs.setdefault('native-evidence/' + row['path'], row)
    refs = []
    def resolve(path, expected=None):
        possible = [overlay.get(path), Q / path, W / 'source53-report-update-preparation/new-files' / path, W / path]
        if path.startswith('native-source53-finalization/'):
            possible.append(FINAL / 'original/finalization' / Path(path).name)
        for x in possible:
            if x is not None and x.is_file():
                if expected and not all(pin_bytes(x.read_bytes())[k] == expected[k] for k in PINKEYS if k in expected):
                    continue
                return {'kind': 'local_exact_bytes', 'target': str(x.relative_to(W)), 'pin': pin_bytes(x.read_bytes())}
        if expected:
            for x in by_hash.get(expected.get('sha256'), []):
                if x.is_file() and all(pin_bytes(x.read_bytes())[k] == expected[k] for k in PINKEYS if k in expected):
                    return {'kind': 'formal_source_mapping_exact_bytes', 'target': str(x.relative_to(W)), 'pin': pin_bytes(x.read_bytes())}
            if path in testedmap and all(testedmap[path].get(k) == expected[k] for k in PINKEYS if k in expected):
                return {'kind': 'tested_source_manifest', 'target': path, 'pin': testedmap[path]}
            if path in finalmap and all(finalmap[path].get(k) == expected[k] for k in PINKEYS if k in expected):
                return {'kind': 'final_source_manifest', 'target': path, 'pin': finalmap[path]}
        if path in historical_refs:
            r = historical_refs[path]
            if not expected or all(r[k] == expected[k] for k in PINKEYS if k in expected and k in r):
                return {'kind': 'inherited_frozen_INDEX_reference_no_fresh_bytes_claim', 'target': path, 'pin': r}
        return None
    docs = ['candidates/STATUS.json', 'candidates/SOURCE_IDENTITY.json', 'pr-guide-candidates/DYNAMIC-STATUS.json']
    for n in docs:
        for ptr, v in walk(read_json(c / n)):
            if isinstance(v, dict) and isinstance(v.get('path'), str) and 'sha256' in v and ('bytes' in v or 'git_blob' in v):
                r = resolve(v['path'], v)
                refs.append({'document': n, 'pointer': ptr, 'requested': v, 'resolution': r})
                check('pinned_reference:' + n + ptr, r is not None, {'path': v['path']})
                if r and v.get('compression') == 'gzip' and 'original_uncompressed' in v and r['kind'] == 'local_exact_bytes':
                    uncompressed = gzip.decompress((W / r['target']).read_bytes())
                    check('compressed_reference_roundtrip:' + n + ptr, all(pin_bytes(uncompressed)[k] == v['original_uncompressed'][k] for k in PINKEYS if k in v['original_uncompressed']))
    mdrefs = []
    markdown_docs = ['candidates/README.md', 'pr-guide-candidates/REVIEW-GUIDE.zh-CN.md', 'pr-guide-candidates/PR-BODY.md', 'pr-guide-candidates/PR-PARAGRAPHS.zh-CN.md']
    for n in markdown_docs:
        s = (c / n).read_text()
        definitions = dict(re.findall(r'(?m)^\[([^\]]+)\]:\s*(\S+)\s*$', s))
        used_refs = re.findall(r'\[[^\]\n]+\]\[([^\]\n]+)\]', s)
        check('markdown_reference_labels:' + n, set(used_refs) <= definitions.keys(), sorted(set(used_refs) - definitions.keys()))
        links = set(definitions.values()) | set(re.findall(r'\[[^\]\n]+\]\(([^)\s]+)\)', s))
        for link in sorted(links):
            if link.startswith('https://github.com/TrillionniumFoundation/hepta-private-ci/blob/'):
                ref, path = link.split('/blob/', 1)[1].split('/', 1)
                # Historical fixed refs are retained rather than relabelled.
                good = bool(re.fullmatch(r'[0-9a-f]{40}', ref)) and path in finalmap
                r = {'kind': 'immutable_source_URL', 'commit': ref, 'path': path, 'current_final': ref == FC, 'known_source_path': path in finalmap}
            elif link.startswith(('https://', 'http://', '#')):
                good, r = True, {'kind': 'external_or_anchor_not_network_fetched'}
            else:
                r = resolve(link.split('#', 1)[0])
                good = r is not None
            mdrefs.append({'document': n, 'link': link, 'resolution': r})
            check('markdown_link:' + n + ':' + link, good)

    guide = (c / 'pr-guide-candidates/REVIEW-GUIDE.zh-CN.md').read_text()
    if '最终 fix/fmt 及最终发布 SHA 验证仍待真实完成。' in guide:
        findings.append({'kind': 'stale_current_status_sentence', 'severity': 'correction_required', 'path': 'pr-guide-candidates/REVIEW-GUIDE.zh-CN.md',
            'text': '最终 fix/fmt 及最终发布 SHA 验证仍待真实完成。', 'reason': 'Actual fix/fmt are complete; only final-SHA CI/publication remain pending.'})
    if '固定 source53 链接' in guide:
        findings.append({'kind': 'stale_source_URL_label', 'severity': 'correction_required', 'path': 'pr-guide-candidates/REVIEW-GUIDE.zh-CN.md',
            'text': '固定 source53 链接', 'reason': 'PATH-GROUPS current URLs are source54, with separate tested_source_pin.'})
    for n in ('PR-BODY.md', 'PR-PARAGRAPHS.zh-CN.md'):
        s = (c / 'pr-guide-candidates' / n).read_text()
        oldurls = re.findall(r'https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e0910becc37383e6d17ecf861ea844fd07d8862/[^)\s]+', s)
        if oldurls:
            findings.append({'kind': 'historical_URLs_in_current_short_PR', 'severity': 'clarification_recommended', 'path': 'pr-guide-candidates/' + n,
                'links': oldurls, 'reason': 'These are valid fixed source52 links but the short final-code PR introduction does not label them as historical; prefer final source54 links or explicit historical scope.'})
    summary = {'schema': 'hepta.source54-final-report-independent-static-review.v1',
        'result': 'CLEAR' if not findings else 'CORRECTIONS_REQUIRED', 'candidate_root': str(c.relative_to(W)), 'handoff_pin': pin_bytes(hraw),
        'candidate_regular_files': len(actual_paths), 'input_pins_checked': len(source_input_manifest['files']),
        'checks': len(checks), 'mechanical_failures': sum(not x['pass'] for x in checks), 'findings': findings,
        'protected_README_sections': protected_sections, 'protected_STATUS_fields': protected_fields,
        'source_identities': {'actual_final': {'commit': FC, 'tree': FT}, 'tested': {'commit': TC, 'tree': TT}},
        'separate_test_counts': expected_counts, 'format_changed_paths': len(change_paths),
        'warnings': {'diagnostic': len(diag), 'summary': len(headers) - len(diag)},
        'pinned_reference_count': len(refs), 'markdown_reference_count': len(mdrefs),
        'boundaries': {'original_reports_modified': False, 'canonical_modified': False, 'native_or_Rust_executed': False,
            'formatter_or_metadata_executed': False, 'network_fetched': False, 'post_format_tests_claimed': False,
            'science': 'HOLD', 'authority': 'DENY_ALL', 'frozen_prior_reader_recomputed': False,
            'this_review': 'Local bytes, JSON values and report semantics only; prior full native/patch/source reviews remain separately pinned.'}}
    out.mkdir(parents=True)
    for name, val in [('INDEPENDENT-REVIEW.json', summary), ('CHECKS.json', checks), ('PINNED-REFERENCE-READBACK.json', refs),
                      ('MARKDOWN-REFERENCE-READBACK.json', mdrefs), ('INPUT-PINS.json', {'files': [{'path': p, **v} for p, v in sorted(inputs.items())]})]:
        with (out / name).open('x') as f:
            json.dump(val, f, ensure_ascii=False, indent=2); f.write('\n')
    print(json.dumps({'result': summary['result'], 'checks': len(checks), 'mechanical_failures': summary['mechanical_failures'], 'findings': findings,
        'report': str((out / 'INDEPENDENT-REVIEW.json').relative_to(W)), **pin_bytes((out / 'INDEPENDENT-REVIEW.json').read_bytes())}, ensure_ascii=False))


if __name__ == '__main__':
    main()

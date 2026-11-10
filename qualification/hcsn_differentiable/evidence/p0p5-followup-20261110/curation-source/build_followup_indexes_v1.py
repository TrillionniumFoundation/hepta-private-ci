"""Build scoped follow-up asset and cost indexes from retained raw receipts."""

import hashlib
import json
from pathlib import Path

ROOT = Path('/workspace/scratch/c385a7439f8e')
BASE = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence'
OUT = BASE / 'p0p5-followup-20261110'


def read(name):
    return json.loads((OUT / name).read_text())


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main():
    observation_path = ROOT / 'hcsn-draft-assets-followup-observation-v1.json'
    observation = json.loads(observation_path.read_text())
    target = OUT / 'publication/hcsn-draft-assets-followup-observation-v1.json'
    if target.exists():
        assert target.read_bytes() == observation_path.read_bytes()
    else:
        target.write_bytes(observation_path.read_bytes())
    old = json.loads((BASE / 'p0p5-20261110/assets.json').read_text())
    review = read('publication/review-profile-assets-v1/RESULT.json')
    fresh = read('original42/receipts-v1/upload-RESULT.json')
    observed = {row['id']: row for row in observation['assets']}
    rows = []
    groups = [('../p0p5-20261110/assets.json', old['verified_assets']),
              ('publication/review-profile-assets-v1/RESULT.json', review['assets']),
              ('original42/receipts-v1/upload-RESULT.json', fresh['assets'])]
    for receipt, entries in groups:
        for row in entries:
            size = row.get('bytes', row.get('size'))
            record = observed[row['asset_id']]
            assert record['state'] == 'uploaded'
            assert record['size'] == size
            assert record['digest'] == 'sha256:' + row['sha256']
            assert (row.get('authenticated_readback_matches') is True
                    or (row.get('readback_verified') is True
                        and row['authenticated_readback_sha256'] == row['sha256']))
            rows.append({'asset_id': row['asset_id'], 'name': row['name'],
                         'bytes': size, 'sha256': row['sha256'], 'receipt': receipt,
                         'authenticated_full_byte_readback_verified': True})
    assert len(rows) == len({row['asset_id'] for row in rows}) == 28
    unmatched = [row for row in observation['assets']
                 if row['id'] not in {r['asset_id'] for r in rows}]
    assert {row['id'] for row in unmatched} == {732265694, 731577229}
    assert observation['release']['draft'] and observation['release']['published_at'] is None
    write('assets.json', {
        'schema': 'hcsn-followup-draft-assets-v1',
        'observation_utc': observation['observed_utc'], 'release_id': 440410488,
        'repository': 'TrillionniumFoundation/hepta-private-ci',
        'repository_visibility': 'public', 'draft': True, 'published': False,
        'verified_payload_count': 28, 'verified_payloads': rows,
        'metadata_only_or_incomplete': [{k: row.get(k) for k in
            ['id', 'name', 'state', 'size', 'digest']} for row in unmatched],
        'metadata_only_receipt': 'publication/hcsn-draft-assets-followup-observation-v1.json',
        'access': 'Large draft assets require authenticated appropriate repository access.',
        'scope': '28 payloads have retained complete byte readback. The preliminary manifest is metadata-only; the official-data starter is not uploaded evidence. No publish, delete or replacement is credited.'})

    costs = []
    for stem in ['final-curation-delta-review-v2', 'current-continuum-scope-closure-v1',
                 'c1-aggregate-originals-addendum-v1', 'final-hcsn-plan-independent-review-v1',
                 'c1-clock-outcomes-independent-review-v1']:
        path = 'review/' + stem + '/EXECUTION.json'
        source = read(path)
        costs.append({'id': stem, 'artifact': path, 'phase': 'Independent retained-evidence review',
                      'whole_waited_process_wall_seconds': source.get(
                          'whole_waited_process_wall_seconds', source.get('whole_waited_child_wall_seconds')),
                      'waited_child_cpu_seconds': source['waited_child_cpu_seconds'],
                      'scope': 'Complete measured review subprocess only; no model/oracle/training. Manual inspection, report writing and later archive construction are outside this timer.'})
    for label, path in [('review-profile-upload', 'publication/review-profile-assets-v1/RESULT.json'),
                        ('original42-upload', 'original42/receipts-v1/upload-RESULT.json')]:
        source = read(path)
        costs.append({'id': label, 'artifact': path, 'phase': 'Authenticated archival upload and full readback',
                      'whole_controller_wall_seconds': source['whole_controller_wall_seconds'],
                      'own_cpu_seconds': source['own_cpu_seconds'],
                      'children_cpu_seconds': source['children_cpu_seconds'],
                      'scope': source['cost_scope']})
    path = 'original42/receipts-v1/archive-original-receipt.json'
    source = read(path)
    costs.append({'id': 'original42-archive', 'artifact': path,
                  **{key: source[key] for key in ['whole_wall_seconds', 'own_cpu_seconds',
                     'full_process_cpu_seconds', 'children_cpu_seconds', 'cost_scope']},
                  'scope_note': 'Retain original report-time samples; not an independent post-exit rusage measurement.'})
    path = 'original42/receipts-v1/launcher-final-original.json'
    source = read(path)
    costs.append({'id': 'original42-whole-launcher', 'artifact': path,
                  'whole_wall_seconds': source['whole_wall_seconds'],
                  'children_cpu_seconds': source['children_cpu_seconds'],
                  'scope': 'Encloses extraction, frozen thirteen-test child, complete campaign controller and its training descendants. Do not add the campaign or fit subscopes to this total.',
                  'nested_commands': source['commands']})
    path = 'original42/terminal-small/campaign-v2/RESULT.json'
    source = read(path)
    costs.append({'id': 'original42-controller', 'artifact': path,
                  **{key: source[key] for key in ['whole_wall_seconds', 'children_cpu_seconds',
                     'controller_cpu_seconds', 'sum_attempt_wall_seconds']},
                  'scope': 'Nested in original42-whole-launcher; includes all42 original fits. Controller wall and sum of overlapping fit durations are different quantities.'})
    path = 'original42/receipts-v1/HCSN-TERMINAL-SUMMARY.json'
    source = read(path)
    costs.append({'id': 'original-six-HCSN', 'artifact': path,
                  'sum_attempt_wall_seconds': source['hcsn_sum_outer_wall_seconds'],
                  'attempts': 6, 'adequate_attempts': 0,
                  'peak_rss_bytes': max(row['peak_rss_bytes'] for row in source['rows']),
                  'scope': 'Subset of original42-controller; six budget-exhausted attempts, all diagnostics passed. Retain partial-epoch work in complete outer costs.'})
    for label in ['evidence-integrity-current-closure-v1-receipt', 'current-protocol-just-fmt-v2']:
        path = 'verification/' + label + '.json'
        source = read(path)
        costs.append({'id': label, 'artifact': path,
                      'whole_process_wall_seconds': source['whole_process_wall_seconds'],
                      'child_cpu_seconds': source['child_cpu_seconds'],
                      'scope': 'Exact described local subprocess; no scientific oracle or training.'})
    costs.append({'id': 'formatter-entry-preflight-failure',
                  'artifact': 'verification/current-protocol-just-fmt-v1.json',
                  'formatter_started': False, 'whole_process_wall_seconds': None,
                  'child_cpu_seconds': None, 'scope': 'Missing executable before formatter start; retained separately from the completed cached entry.'})
    for row in costs:
        assert (OUT / row['artifact']).is_file()
    write('COSTS.json', {'schema': 'hcsn-followup-costs-v1', 'accounting_complete': False,
                        'rows': costs, 'previous_ledger': '../p0p5-20261110/COSTS.json',
                        'rules': ['Never add enclosing and nested timings.',
                                  'Original baseline36+C1 cost subsets and all failed tuning remain in the previous ledger.',
                                  'Archive/upload/review costs are separate from model fitting.',
                                  'Unknown energy, physical-host reservation, human work and provider cost are not zero.'],
                        'total_elapsed_seconds': None, 'total_energy_joules': None,
                        'total_currency_cost': None, 'peak_vram_bytes': None,
                        'scientific_benefit_established': False})
    print(json.dumps({'verified_assets': len(rows), 'cost_rows': len(costs),
                      'builder_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()

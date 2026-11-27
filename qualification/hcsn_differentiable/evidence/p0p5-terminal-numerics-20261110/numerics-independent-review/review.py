"""Independent saved-JSON review; no import of the producer, Torch or an oracle."""
from collections import Counter
from pathlib import Path, PurePosixPath
import hashlib
import json
import math
import re
import zipfile

BASE = Path('/workspace/scratch/c385a7439f8e')
INPUT = BASE / 'terminal-numerics-final-evidence-v1'
OUT = Path(__file__).parent
ERRORS = []
INPUTS = {}


def check(condition, message):
    if not condition:
        ERRORS.append(message)


def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def raw(path):
    value = path.read_bytes()
    INPUTS[str(path)] = ident(value)
    return value


def read(name):
    return json.loads(raw(INPUT / name))


def zip_members(path):
    data = raw(path)
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        check(len(names) == len(set(names)), 'duplicate ZIP names: ' + str(path))
        check(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
                  and '\\' not in n for n in names), 'unsafe ZIP name')
        check(archive.testzip() is None, 'ZIP CRC failure: ' + str(path))
        items = {name: archive.read(name) for name in names}
    if 'MEMBER-MANIFEST.json' in items:
        manifest = json.loads(items['MEMBER-MANIFEST.json'])
        check(set(manifest) == set(items) - {'MEMBER-MANIFEST.json'}, 'ZIP manifest coverage')
        for name, spec in manifest.items():
            check(ident(items[name]) == spec, 'ZIP manifest bytes: ' + name)
    return items


def same_num(a, b, tolerance=1e-15):
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance


def main():
    copy = read('COPY_LIST.json')
    check(INPUTS[str(INPUT / 'COPY_LIST.json')]['sha256'] == '80dc925dc37b12277154171bcc18e363ec41880e8d3db8cc4eee6d5069bb6660', 'frozen input COPY SHA')
    for item in copy['files']:
        check(ident(raw(INPUT / item['relative_path'])) == {k: item[k] for k in ('bytes', 'sha256')}, 'copy-list identity: ' + item['relative_path'])
    index = read('INDEX.json')
    summary = read('postmortem/SUMMARY.json')
    roster = read('STAGE-ROSTER.json')
    members = read('postmortem/ORIGINAL-MANIFEST.json')
    member_map = {item['member']: item for item in members}
    check(len(members) == len(member_map) == 487, 'original member count/uniqueness')
    check(len({item['path'] for item in members}) == 487, 'original path uniqueness')
    collection = read('postmortem/COLLECTION-RECEIPT.json')
    collector_outer = read('collector-launch/receipt.json')
    upload = read('publication/UPLOAD-RESULT.json')
    costs = read('COST-RECORDS.json')
    plan = read('numerical-source/PLAN.json')
    program = zip_members(INPUT / 'numerical-source/PROGRAM.zip')
    check(INPUTS[str(INPUT / 'numerical-source/PROGRAM.zip')]['sha256'] == '51c7c54ed96f40f39c8ebb5b0d04ee0c42f6f462012faf356efe6c3a9446419f', 'numerical source ZIP')
    program_manifest = json.loads(program['MANIFEST.json'])['files']
    check(set(program_manifest) == set(program) - {'MANIFEST.json'}, 'numerical program coverage')
    for name, data in program.items():
        if name != 'MANIFEST.json':
            check(ident(data) == program_manifest[name], 'program self manifest: ' + name)
        spec = member_map['program/' + name]
        check(ident(data) == {k: spec[k] for k in ('bytes', 'sha256')}, 'archived program identity: ' + name)
    check(program['PLAN.json'] == raw(INPUT / 'numerical-source/PLAN.json'), 'plan bytes')
    fullzip = zip_members(INPUT / 'postmortem/FULL-RESULT.zip')
    full_bytes = fullzip['RESULT.json']
    full = json.loads(full_bytes)
    check(ident(full_bytes) == roster['full_report_member_identity'], 'full collector report identity')
    receipts = zip_members(INPUT / 'transport/ORIGINAL-RECEIPTS.zip')
    check(receipts['postmortem/RESULT.json'] == full_bytes, 'full original report byte equality')
    for name, data in receipts.items():
        local = INPUT / name
        if local.is_file():
            check(data == raw(local), 'original receipt byte equality: ' + name)
    check(collector_outer['metadata_returncode'] == 0 and collector_outer['status'] == 'completed_metadata_collection', 'collector outer terminal')
    check(collector_outer['collection_receipt_sha256'] == INPUTS[str(INPUT / 'postmortem/COLLECTION-RECEIPT.json')]['sha256'], 'external collection receipt SHA')
    check(collection['metadata_collection_status'] == 'completed', 'collection finality')
    for field in ['expected_stages', 'expected_finite_fixtures', 'finite_qualified_named_fixture_count', 'observed_stage_cost', 'original_launcher_receipt', 'original_bootstrap_receipt', 'whole_attempt_CPU_completeness']:
        check(collection[field] == full[field] == summary[field], 'summary/full/external field: ' + field)
    check(collection['archive'] == collector_outer['archive'] == index['archive_identity'], 'archive identity chain')
    archive = collection['archive']
    check(archive['sha256'] == 'e96030a4c1a29031e56c406d7cc72cee9d141a0edb4701e3a83d60b5d5e32c52' and archive['bytes'] == 34050599, 'original big archive identity')
    for asset in upload['assets']:
        check(asset['authenticated_full_readback_verified'] and asset['CRC_and_members_verified'], 'recorded asset readback')
        check(asset['authenticated_readback_sha256'] == asset['sha256'], 'recorded asset SHA')
        check(asset['anonymous_asset_API']['HTTP_status'] == asset['anonymous_asset_browser']['HTTP_status'] == '404', 'anonymous visibility')
    check(upload['assets'] == index['authenticated_draft_assets'], 'index asset fields')
    check(upload['assets'][0]['sha256'] == archive['sha256'], 'big archive publisher identity')
    check(upload['assets'][1]['sha256'] == INPUTS[str(INPUT / 'transport/ORIGINAL-RECEIPTS.zip')]['sha256'], 'receipts archive publisher identity')
    check(upload['final_draft_identity'] == {'draft': True, 'id': 440410488, 'tag_name': 'hcsn-research-20261110-c385'}, 'final draft unchanged')
    names = plan['fit_roster']
    stages = ['export-best', 'export-last', 'original-prefix', 'domain-best', 'domain-last', 'logrisk'] + [f'finite-best-{i}' for i in range(9)] + ['finite-last-0']
    expected = [(name, stage) for stage in stages for name in names]
    check(len(expected) == len(set(expected)) == 96, 'declared 96 unique tasks')
    actual = [(row['name'], row['stage']) for row in full['stages']]
    check(actual == expected == [(row['name'], row['stage']) for row in roster['rows']], 'fixed stage order/roster')
    observed = Counter(row['observation_status'] for row in full['stages'])
    check(dict(observed) == roster['counts'] == summary['stage_status_counts'] == index['stage_observations'], 'stage counts')
    check(dict(observed) == {'completed_artifact_chain': 85, 'attempt_artifacts_without_outer_completion': 1, 'not_observed_to_have_started': 10}, 'exact counts')
    closure = full['original_identity_closure']
    check(closure['passed'] and not closure['errors'], 'original closure recorded status')
    for path, record in closure['checks'].items():
        check(record['matches'] and record['expected_sha256'] == record['observed_sha256'], 'original identity mismatch: ' + path)
    for name, sha in plan['source_files'].items():
        matches = [v for p, v in closure['checks'].items() if p.endswith('/run-source-v8/' + name)]
        check(len(matches) == 1 and matches[0]['observed_sha256'] == sha, 'plan source identity: ' + name)
    for episode in plan['fixed_episodes']:
        matches = [v for p, v in closure['checks'].items() if p.endswith('/' + episode['path_in_prepared_data'])]
        check(len(matches) == 1 and matches[0]['observed_sha256'] == episode['sha256'], 'fixed episode identity: ' + episode['id'])
    check(any(p.endswith('/manifest.json') and r['observed_sha256'] == plan['data_manifest_sha256'] for p, r in closure['checks'].items()), 'original data manifest identity')
    replay_path = BASE / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/full-d-replay/SUMMARY.json'
    replay = json.loads(raw(replay_path))
    best_hashes = {r['name']: r['best_checkpoint_sha256'] for r in replay['fits']}
    check(replay['source_capsule_sha256'] == plan['source_capsule_sha256'] and replay['data_manifest_sha256'] == plan['data_manifest_sha256'], 'independent full-D context')
    finite = []
    counted_artifacts = 0
    walls, cpus = [], []
    for row, indexed in zip(full['stages'], roster['rows']):
        name, stage = row['name'], row['stage']
        for label, spec in row['artifacts'].items():
            mapped = indexed['original_artifacts'][label]
            original = member_map[mapped['main_archive_member']]
            check(all(spec[k] == mapped[k] == original[k] for k in ('path', 'bytes', 'sha256')), f'artifact chain {name}/{stage}/{label}')
            counted_artifacts += 1
        if row['observation_status'] != 'completed_artifact_chain':
            check(not row['qualified_named_finite_fixture'], 'incomplete stage gained qualification')
            continue
        outer = row['outer']
        check(outer['returncode'] == 0 and outer['execution_status'] == 'completed' and outer['stop_cause'] is None, 'completed outer: ' + stage)
        check(0 <= outer['whole_process_wall_seconds'] <= outer['whole_stage_wall_ceiling_seconds'] <= 900, 'outer granted wall: ' + stage)
        check(outer['RSS_limit_bytes'] == 2147483648 and all(0 <= outer[k] <= 2147483648 for k in ('sampled_peak_RSS_bytes', 'reported_child_peak_RSS_sample_bytes')), 'fixed RSS limit: ' + stage)
        check(outer['result_sha256'] == row['artifacts']['result']['sha256'], 'outer result SHA: ' + stage)
        for label in ['stdout', 'stderr']:
            check(all(outer[label][k] == row['artifacts'][label][k] for k in ('bytes', 'sha256')), 'outer stream hash')
        check(row['source_and_input_gate_passed'] and row['outer_completion_and_budget_gate_passed'], 'recorded original source/resource flags')
        receipt_sha = outer['argv'][outer['argv'].index('--receipt-sha256') + 1]
        check(receipt_sha == member_map[f'audit/{name}/input-receipt.json']['sha256'], 'input receipt argv SHA')
        walls.append(outer['whole_process_wall_seconds']); cpus.append(outer['waited_child_CPU_seconds'])
        if not stage.startswith('finite-'):
            continue
        value = row['raw_finite_fields']
        fixture = plan['finite_schedule_fixtures_per_primary_checkpoint'][int(stage.rsplit('-', 1)[1])]
        check(value['fixture'] == fixture and fixture['future_observations'] is False, 'fixed finite fixture: ' + stage)
        check(value['checkpoint_sha256'] == best_hashes[name], 'independent best-checkpoint identity')
        check(value['trace_sha256'] == member_map[f"audit/{name}/best-{fixture['episode_id']}.jsonl"]['sha256'], 'finite exported law identity')
        check(value['reference_orders'] == [8, 16] and value['reference_digits'] == 80, 'reference scope')
        check(value['quantities'] == ['value', 'event_count', 'discounted_event_count', 'active_probability'], 'quantity ordering')
        errors = [abs(a - b) for a, b in zip(value['projected'], value['reference'])]
        scaled = [e / max(1, abs(v)) for e, v in zip(errors, value['reference'])]
        relative = [e / abs(v) if v else None for e, v in zip(errors, value['reference'])]
        check(all(same_num(a, b) for a, b in zip(errors, value['absolute_errors'])), 'absolute arithmetic')
        check(all(same_num(a, b) for a, b in zip(scaled, value['scaled_errors'])), 'scaled arithmetic')
        check(all(same_num(a, b) for a, b in zip(relative, value['relative_errors'])), 'relative arithmetic')
        check(value['scaled_error_limit'] == .01 and value['relative_error_gate'] is False and max(scaled) <= .01, 'unchanged scaled gate')
        check(0 <= value['reference_refinement_delta'] <= 2e-8 and abs(value['mass_residual']) <= 5e-11, 'refinement/mass gate')
        check(row['raw_numerical_status'] == 'passed_fixture' and row['qualified_named_finite_fixture'], 'named finite status')
        finite.append({'name': name, 'stage': stage, 'quantities': value['quantities'], 'scaled_errors': scaled,
                       'relative_errors': relative, 'reference': value['reference'], 'projected': value['projected'],
                       'fixture': {k: fixture[k] for k in ('episode_id', 'posterior_after_position', 'intervals')},
                       'result_identity': row['artifacts']['result']})
    check(len(finite) == full['finite_qualified_named_fixture_count'] == index['qualified_named_finite_fixtures'] == 49, '49 named finite fixtures')
    for key, field in [('maximum_scaled_error', 'scaled_errors'), ('maximum_relative_error', 'relative_errors')]:
        maximum = max((v, row['name'], row['stage'], row['quantities'][i]) for row in finite for i, v in enumerate(row[field]))
        advertised = index[key]
        check(maximum == (advertised['value'], advertised['name'], advertised['stage'], advertised['quantity']), key)
    check(same_num(math.fsum(walls), summary['observed_stage_cost']['stage_outer_wall_seconds'], 1e-8), 'stage wall sum')
    check(same_num(math.fsum(cpus), summary['observed_stage_cost']['waited_stage_CPU_seconds'], 1e-8), 'stage CPU sum')
    domains = [r for r in full['stages'] if r['stage'].startswith('domain-')]
    pressure = [dict(p, name=r['name']) for r in domains for p in r['raw_domain_summary']['pressure_sentinels']]
    check(len(domains) == 12 and sum(r['domain_vector_record_count'] for r in domains) == 10752, 'supplement count')
    check(all(r['raw_domain_summary']['state_gradient_checks_passed'] for r in domains), 'held-posterior gradient flags')
    check(len(pressure) == 18 and sum(not p['passed'] for p in pressure) == 12, 'pressure failures retained')
    for p in pressure:
        check(same_num(abs(p['projected'] - p['reference']) / max(1, abs(p['reference'])), p['scaled_error']), 'pressure scalar arithmetic')
    log = [r for r in full['stages'] if r['stage'] == 'logrisk']
    check(len(log) == 6 and all(r['logrisk_primary_passed'] is False for r in log), 'logrisk primary failures')
    check(sum(r['direct_FD_inconclusive_count'] for r in log) == 576 and sum(r['direct_FD_resolved_disagreement_count'] for r in log) == 6, 'ordinary FD unresolved/disagreement')
    prefix = [r['raw_prefix_result'] for r in full['stages'] if r['stage'] == 'original-prefix']
    check(all(r['status'] == 'HOLD' and not r['complete_retained_coverage'] and r['audited_records'] == 16 for r in prefix), 'original prefix scope')
    launcher = read('original-terminal/launch-receipt.json')
    bootstrap = read('original-terminal/bootstrap-receipt.json')
    check(launcher == full['original_launcher_receipt'] and bootstrap == full['original_bootstrap_receipt'], 'outer original bytes/parsed identity')
    check(launcher['returncode'] == -9 and launcher['status'] == 'whole_budget_exhausted' and launcher['hard_whole_wall_seconds'] == 10800, 'original hard stop')
    check(full['whole_attempt_CPU_completeness'] == 'incomplete_waited_processes_only_lower_bound' and full['possible_unreaped_killed_stage_CPU_not_measured'], 'CPU lower bound')
    check(not full['original_controller_aggregate_present'] and not full['original_controller_archive_receipt_present'], 'no fabricated aggregate')
    check(all(full[k] == 'HOLD' for k in ('scientific_admission', 'whole_training_domain_admission')) and not full['training_adequacy_established'], 'no broad qualification')
    gnu = {}
    for filename in ['publication-inventory/GNU-TIME.txt', 'publication/UPLOAD-GNU-TIME.txt']:
        text = raw(INPUT / filename).decode()
        fields = {label: re.search(pattern, text).group(1) for label, pattern in {
            'user': r'User time \(seconds\): ([0-9.]+)', 'system': r'System time \(seconds\): ([0-9.]+)',
            'wall': r'Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([0-9:.]+)',
            'RSS_kib': r'Maximum resident set size \(kbytes\): (\d+)', 'exit': r'Exit status: (\d+)'
        }.items()}
        wall = 0.0
        for part in fields['wall'].split(':'): wall = wall * 60 + float(part)
        check(fields['exit'] == '0', 'GNU terminal status')
        gnu[filename] = {'rounded_whole_wall_seconds': wall, 'rounded_CPU_seconds': float(fields['user']) + float(fields['system']), 'peak_RSS_bytes': int(fields['RSS_kib']) * 1024}
    before = dict(INPUTS)
    check(all(ident(Path(path).read_bytes()) == spec for path, spec in before.items()), 'review inputs changed')
    output = {'schema': 'independent-terminal-numerics-saved-json-review-v1', 'status': 'passed_scoped_metadata_review' if not ERRORS else 'HOLD_review_discrepancies',
              'errors': ERRORS, 'input_identities': before, 'copied_input_items_verified': len(copy['files']),
              'stage_counts': dict(observed), 'artifact_records_bound_to_original_manifest': counted_artifacts,
              'original_manifest_member_count': len(members), 'recorded_original_source_input_checks': len(closure['checks']),
              'finite_count': len(finite), 'finite_rows': finite, 'maximum_scaled_error': index['maximum_scaled_error'],
              'maximum_relative_error': index['maximum_relative_error'], 'uncompleted': index['uncompleted_rows'],
              'source_capsule_sha256': plan['source_capsule_sha256'], 'data_manifest_sha256': plan['data_manifest_sha256'],
              'best_checkpoint_hashes_independently_bound_to_prior_full_D_replay': best_hashes,
              'domain_records': 10752, 'pressure_sentinels': 18, 'pressure_failures': 12,
              'logrisk_primary_false': 6, 'ordinary_FD_inconclusive': 576, 'ordinary_FD_resolved_disagreement': 6,
              'original_prefix_audited_records_per_fit': [r['audited_records'] for r in prefix],
              'costs': {'original_launcher_wall_seconds': launcher['whole_process_wall_seconds'],
                        'original_launcher_waited_CPU_lower_bound_seconds': launcher['waited_controller_and_descendant_CPU_seconds'],
                        'original_bootstrap_wall_seconds': bootstrap['complete_bootstrap_wall_seconds'],
                        'original_bootstrap_waited_CPU_lower_bound_seconds': bootstrap['complete_waited_children_CPU_seconds'],
                        'nested_completed_stage_wall_seconds': math.fsum(walls), 'nested_completed_stage_CPU_seconds': math.fsum(cpus),
                        'hard_cap_enforcement_tail_seconds': launcher['whole_process_wall_seconds'] - 10800,
                        'collector_complete_child_wall_seconds': collector_outer['whole_metadata_child_wall_seconds'],
                        'collector_complete_child_CPU_seconds': collector_outer['metadata_waited_child_CPU_seconds'],
                        'separate_publication_GNU': gnu, 'nested_views_not_added': True,
                        'complete_attempt_CPU_known': False, 'energy_or_billing_known': False},
              'archive_binding': {'original': archive, 'publisher_assets': upload['assets'], 'new_download_by_this_review': False},
              'limitations': ['Review recomputes saved scalar arithmetic and roster/cost sums, not the numerical solver.',
                              'Full stage payloads are bound by original member hashes; the 34MB archive was not downloaded again by this review. Original uploader authenticated full-byte/CRC/member readback receipts are preserved.',
                              'Stage self-RSS/source flags are the original collector result; this review independently checks saved outer budgets/streams and recorded source identities, not a second native file scan.',
                              'The 80-digit order8/16 refinement comparison is not a certified error bound.',
                              '49/60 finite qualification uses max(1,abs(reference)) scaling, not universal 1% relative accuracy.',
                              'Supplemental final-checkpoint laws do not complete byte-capped training trace; original prefix audit is only16 retained records per fit.',
                              'No model, probability array, oracle, training or E access. Original training sufficiency and whole-domain/scientific admission remain HOLD.'],
              'scientific_admission': 'HOLD', 'whole_training_domain_admission': 'HOLD', 'numeric_or_model_executions': 0}
    with (OUT / 'REVIEW.json').open('x') as stream:
        stream.write(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print(json.dumps({'status': output['status'], 'errors': ERRORS, 'finite': len(finite), 'stages': dict(observed), 'bound_artifacts': counted_artifacts, 'inputs': len(before)}))
    return 0 if not ERRORS else 2


if __name__ == '__main__':
    raise SystemExit(main())

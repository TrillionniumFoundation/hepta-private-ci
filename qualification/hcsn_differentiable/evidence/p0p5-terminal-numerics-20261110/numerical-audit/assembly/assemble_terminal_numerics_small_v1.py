"""Package exact terminal originals and a separately labeled metadata index."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'terminal-numerics-collector-receipts-originals-v1'
OUT = ROOT / 'terminal-numerics-final-evidence-v1'
OUT.mkdir(exist_ok=False)
origins = {}


def identity(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def write(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    origins[name] = {'kind': 'derived_metadata_only'}


def copy(source, name, provenance):
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as handle:
        handle.write(source.read_bytes())
    assert identity(target) == identity(source)
    origins[name] = {'kind': 'exact_original_bytes', 'source': str(source), **provenance}


for path in sorted(SOURCE.rglob('*')):
    if path.is_file() and path.relative_to(SOURCE).as_posix() != 'postmortem/RESULT.json':
        name = path.relative_to(SOURCE).as_posix()
        copy(path, name, {'draft_asset_id': 733217675, 'archive_member': name})

full = SOURCE / 'postmortem/RESULT.json'
full_id = identity(full)
full_zip = OUT / 'postmortem/FULL-RESULT.zip'
with zipfile.ZipFile(full_zip, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    archive.write(full, 'RESULT.json')
    archive.writestr('MEMBER-MANIFEST.json', json.dumps({'RESULT.json': full_id}, sort_keys=True) + '\n')
with zipfile.ZipFile(full_zip) as archive:
    assert archive.testzip() is None
    raw = archive.read('RESULT.json')
    assert len(raw) == full_id['bytes'] and hashlib.sha256(raw).hexdigest() == full_id['sha256']
origins['postmortem/FULL-RESULT.zip'] = {'kind': 'archive_of_exact_original_bytes', 'member': 'RESULT.json',
    'member_identity': full_id, 'original_receipts_asset_id': 733217675, 'original_member': 'postmortem/RESULT.json'}

fixed = [
    ('terminal-numerics-postmortem-native-v1/numerics-final-audit-launch-v1__receipt.json', 'original-terminal/launch-receipt.json'),
    ('terminal-numerics-postmortem-native-v1/numerics-final-audit-bootstrap-v1__receipt.json', 'original-terminal/bootstrap-receipt.json'),
    ('terminal-numerics-postmortem-native-v1/ORIGINAL-TERMINAL-READBACK.json', 'transport/ORIGINAL-TERMINAL-READBACK.json'),
    ('terminal-numerics-postmortem-native-v1/COLLECTOR-START-ACK.json', 'transport/COLLECTOR-START-ACK.json'),
    ('terminal-numerics-postmortem-native-v1/COLLECTOR-TERMINAL-PTY.json', 'transport/COLLECTOR-TERMINAL-PTY.json'),
    ('terminal-numerics-postmortem-preparation-v1/NATIVE-REQUEST.json', 'transport/COLLECTOR-EXACT-REQUEST.json'),
    ('terminal-numerics-receipts-recovery-v1/DOWNLOAD-RECEIPT.json', 'transport/RECEIPTS-ZIP-DOWNLOAD.json'),
    ('terminal-numerics-draft-upload-recovered-v1/RESULT.json', 'publication/UPLOAD-RESULT.json'),
    ('terminal-numerics-draft-upload-recovered-v1/GNU-TIME.txt', 'publication/UPLOAD-GNU-TIME.txt'),
    ('final-hcsn-auditor-program-v1.zip', 'numerical-source/PROGRAM.zip'),
    ('final-hcsn-numerical-plan-v1/PLAN.json', 'numerical-source/PLAN.json'),
    ('terminal-numerics-archive-references-v1/REFERENCES.json', 'upstream-trained-artifacts/REFERENCES.json'),
    ('native-fresh42-terminal-receipts-v1/upload-RESULT.json', 'upstream-trained-artifacts/ORIGINAL-UPLOAD-RESULT.json'),
]
for source, target in fixed:
    copy(ROOT / source, target, {})
copy(Path(__file__), 'assembly/assemble_terminal_numerics_small_v1.py', {})

result = json.loads(full.read_bytes())
summary = json.loads((SOURCE / 'postmortem/SUMMARY.json').read_bytes())
receipt = json.loads((SOURCE / 'postmortem/COLLECTION-RECEIPT.json').read_bytes())
launch = json.loads((SOURCE / 'collector-launch/receipt.json').read_bytes())
publication = json.loads((ROOT / 'terminal-numerics-draft-upload-recovered-v1/RESULT.json').read_bytes())
manifest = json.loads((SOURCE / 'postmortem/ORIGINAL-MANIFEST.json').read_bytes())
by_path = {item['path']: item for item in manifest}
assert len(by_path) == len(manifest)
assert receipt['metadata_collection_status'] == 'completed' and receipt['original_identity_closure_passed']
assert launch['status'] == 'completed_metadata_collection' and launch['metadata_returncode'] == 0
assert receipt['archive'] == launch['archive']
assert launch['collection_receipt_sha256'] == identity(SOURCE / 'postmortem/COLLECTION-RECEIPT.json')['sha256']
assert publication['status'] == 'both_assets_authenticated_verified_draft_unchanged'
assert publication['final_draft_identity']['draft'] is True and publication['release_id'] == 440410488
for asset in publication['assets']:
    assert asset['authenticated_full_readback_verified'] and asset['CRC_and_members_verified']
    assert asset['authenticated_readback_sha256'] == asset['sha256']
    assert asset['anonymous_asset_API']['HTTP_status'] == asset['anonymous_asset_browser']['HTTP_status'] == '404'
large_asset = next(a for a in publication['assets'] if a['asset_id'] == 733215514)
assert {k: large_asset[k] for k in ('bytes', 'sha256')} == {k: receipt['archive'][k] for k in ('bytes', 'sha256')}

roster = []
for row in result['stages']:
    saved = {k: row.get(k) for k in ('name', 'stage', 'observation_status', 'qualified_named_finite_fixture',
        'raw_numerical_status', 'source_and_input_gate_passed', 'outer_completion_and_budget_gate_passed',
        'numerical_gate_rechecked_from_original_values')}
    bound_artifacts = {}
    for kind, item in row['artifacts'].items():
        original = by_path[item['path']]
        assert all(item[key] == original[key] for key in ('bytes', 'sha256'))
        bound_artifacts[kind] = {**item, 'main_archive_member': original['member'], 'draft_asset_id': 733215514}
    saved['original_artifacts'] = bound_artifacts
    if 'outer' in row:
        saved['original_outer_cost'] = {k: row['outer'].get(k) for k in ('execution_status', 'returncode',
            'process_started', 'pid', 'started_utc', 'finished_utc', 'whole_process_wall_seconds',
            'waited_child_CPU_seconds', 'sampled_peak_RSS_bytes', 'reported_child_peak_RSS_sample_bytes',
            'whole_stage_wall_ceiling_seconds', 'RSS_limit_bytes', 'stop_cause')}
    if row['stage'] == 'logrisk':
        saved['original_logrisk'] = {k: row.get(k) for k in ('logrisk_primary_passed', 'direct_FD_all_resolved_pass',
            'direct_FD_inconclusive_count', 'direct_FD_resolved_disagreement_count')}
    if row['stage'].startswith('domain-'):
        saved['original_domain'] = row['raw_domain_summary']
        saved['domain_vector_record_count'] = row['domain_vector_record_count']
    roster.append(saved)
assert len(roster) == 96 and len({(r['name'], r['stage']) for r in roster}) == 96
assert Counter(r['observation_status'] for r in roster) == summary['stage_status_counts']
qualified = [r for r in result['stages'] if r.get('qualified_named_finite_fixture')]
assert len(qualified) == receipt['finite_qualified_named_fixture_count'] == 49
write('STAGE-ROSTER.json', {'schema': 'terminal-numerics-96-stage-original-artifact-binding-v1',
    'scope': 'Only original saved scalar values and original artifact identities; no numeric/oracle rerun.',
    'full_report_member_identity': full_id, 'main_archive': large_asset,
    'counts': summary['stage_status_counts'], 'rows': roster})

def largest(field):
    values = []
    for row in qualified:
        raw = row['raw_finite_fields']
        for index, value in enumerate(raw[field]):
            values.append({'value': value, 'name': row['name'], 'stage': row['stage'],
                'quantity': raw['quantities'][index], 'original_result': row['artifacts']['result']})
    return max(values, key=lambda r: r['value'])

domains = [r for r in result['stages'] if r['stage'].startswith('domain-')]
pressures = [{'name': r['name'], **p} for r in domains for p in r['raw_domain_summary']['pressure_sentinels']]
logrisks = [r for r in result['stages'] if r['stage'] == 'logrisk']
write('INDEX.json', {'schema': 'terminal-numerics-frozen-evidence-index-v1',
    'original_attempt_status': receipt['original_launcher_receipt']['status'],
    'original_attempt_returncode': receipt['original_launcher_receipt']['returncode'],
    'original_hard_whole_wall_seconds': 10800, 'original_controller_aggregate_exists': False,
    'planned_stages': 96, 'stage_observations': summary['stage_status_counts'],
    'planned_finite_fixtures': 60, 'qualified_named_finite_fixtures': 49,
    'uncompleted_rows': summary['uncompleted_rows'],
    'finite_scope': 'Recorded best-checkpoint starting laws; specified actual future gaps; future observations disabled. 48 fixtures0-7 across all6 plus s101/.001 fixture8 only.',
    'scaled_error_definition': 'abs(projected-reference)/max(1,abs(reference))', 'scaled_error_limit': .01,
    'relative_error_is_not_the_general_gate': True, 'maximum_scaled_error': largest('scaled_errors'),
    'maximum_relative_error': largest('relative_errors'),
    'refinement_scope': '80-digit computation, orders8/16; order-doubling sensitivity is not a rigorous reference error bound.',
    'supplemental_domain_vector_records': sum(r['domain_vector_record_count'] for r in domains),
    'domain_state_gradient_flags_true': sum(r['raw_domain_summary']['state_gradient_checks_passed'] is True for r in domains),
    'domain_gradient_scope': 'Basis derivatives and each exported posterior held fixed; not end-to-end network-gradient or complete historical-training coverage.',
    'infinite_repeat_sentinels': len(pressures), 'infinite_repeat_failed': sum(p['passed'] is False for p in pressures),
    'pressure_scope': 'Separate hypothetical infinite repetition; different starting laws/horizons from the finite burst fixtures.',
    'logrisk_primary_true_count': sum(r['logrisk_primary_passed'] is True for r in logrisks),
    'logrisk_primary_false_count': sum(r['logrisk_primary_passed'] is False for r in logrisks),
    'direct_FD_inconclusive_total': sum(r['direct_FD_inconclusive_count'] for r in logrisks),
    'direct_FD_resolved_disagreement_total': sum(r['direct_FD_resolved_disagreement_count'] for r in logrisks),
    'logrisk_interpretation': 'OrdinaryFP64 FD confirmation gate failed; original primary=false remains. It does not establish a training AD error.',
    'training_trace_scope': 'Original byte-capped chronological prefixes do not become complete through supplemental final-checkpoint replay.',
    'original_source_input_closure_passed': True, 'original_files_stable_during_collection': True,
    'whole_training_domain_admission': 'HOLD', 'scientific_admission': 'HOLD', 'original_training_adequacy': False,
    'archive_identity': receipt['archive'], 'external_collection_receipt': identity(SOURCE / 'postmortem/COLLECTION-RECEIPT.json'),
    'authenticated_draft_assets': publication['assets'], 'repository_visibility': 'public', 'release_remains_draft': True})

write('COST-RECORDS.json', {'schema': 'terminal-numerics-scope-separated-costs-v1',
    'no_numeric_retries': True, 'energy_joules': None, 'currency_cost': None,
    'rows': [
        {'id': 'original_audit_launcher', 'source': 'original-terminal/launch-receipt.json',
         'wall_seconds': receipt['original_launcher_receipt']['whole_process_wall_seconds'],
         'waited_CPU_seconds': receipt['original_launcher_receipt']['waited_controller_and_descendant_CPU_seconds'],
         'CPU_is_lower_bound': True, 'missing_component': 'Unreaped active s101/.003 finite-best-8 CPU after the process-group kill.',
         'scope': 'Whole original audit controller process group; do not add nested stage totals.'},
        {'id': 'original_bootstrap', 'source': 'original-terminal/bootstrap-receipt.json',
         'recorded_wall_seconds': receipt['original_bootstrap_receipt']['complete_bootstrap_wall_seconds'],
         'waited_children_CPU_seconds': receipt['original_bootstrap_receipt']['complete_waited_children_CPU_seconds'],
         'CPU_is_lower_bound': True, 'scope': 'Includes source fetch, native23tests and original launcher/stages; overlaps original_audit_launcher.'},
        {'id': '85_observed_stage_outers', **receipt['observed_stage_cost']},
        {'id': 'metadata_collection_bootstrap', 'source': 'collector-launch/receipt.json',
         'wall_sample_seconds': launch['bootstrap_wall_sample_seconds'],
         'own_CPU_sample_seconds': launch['bootstrap_own_CPU_sample_seconds'],
         'waited_children_CPU_seconds': launch['bootstrap_waited_children_CPU_seconds'],
         'scope': 'Separate metadata task after original termination. Download and collector child are nested; final serialization after sample is outside this sample.'},
        {'id': 'metadata_collection_child', 'source': 'collector-launch/receipt.json',
         'whole_child_wall_seconds': launch['whole_metadata_child_wall_seconds'],
         'waited_child_CPU_seconds': launch['metadata_waited_child_CPU_seconds'],
         'scope': 'Complete collector child; nested in metadata_collection_bootstrap.'},
        {'id': 'metadata_collection_internal', 'source': 'postmortem/COLLECTION-RECEIPT.json',
         'wall_sample_seconds': receipt['collection_wall_sample_seconds'],
         'CPU_sample_seconds': receipt['collection_CPU_sample_seconds'],
         'scope': 'Collector inner sample before final receipt serialization; nested in collector child.'},
        {'id': 'publication_inventory', 'source': 'publication-inventory/GNU-TIME.txt',
         'scope': 'Read the preserved whole-command GNU record; this separate metadata inventory is outside the numeric/collector attempts.'},
        {'id': 'draft_publication', 'source': 'publication/UPLOAD-GNU-TIME.txt',
         'scope': 'Whole-command GNU record includes upload/readback; uploader RESULT internal clocks are nested. No retry/upload duplication.'},
    ], 'transport_CPU_scope': 'Cloud/native readback control-channel CPU and billing were not measured; do not set them to zero.',
    'concurrency_scope': 'Original audit shared the host with an independent full-D replay and, from21:13:44Z, C2 continuation processes. No idle-host claim.'})

(OUT / 'README.md').write_text('''# Original terminal HCSN numerical audit: bounded results and complete evidence

The original, unique numerical attempt ended under its predeclared 10,800-second process-group cap. Its launcher recorded `whole_budget_exhausted` and return code -9. No numerical stage was restarted or extended. A separately launched, standard-library-only collector ran after all original processes had stopped, verified the original source/model/data identities, and sealed the unchanged originals.

Of 96 planned stages, 85 have complete artifact chains, one has attempt artifacts without an outer completion receipt, and ten have no observed start artifacts. Of 60 planned finite fixtures, 49 pass the original scalar thresholds plus the recorded source, input, wall and RSS checks: fixtures0–7 for all six original trained best checkpoints, and the first model’s255-gap fixture. The remaining11 receive no numerical admission. The detailed original labels are retained rather than relabelled as numerical failures.

The primary finite gate is `abs(projected-reference)/max(1,abs(reference)) <= .01`. It is not a universal one-percent relative-error guarantee. INDEX.json gives maxima with their exact original result identities. The80-digit, order8/16 comparison includes a refinement-sensitivity check, not a rigorous oracle error bound. Six original log-risk `primary=false` results remain, including96 ordinary-FP64 finite-difference inconclusives and one resolved disagreement per model. Agreement of AD with the high-precision checks does not turn the failed ordinary-FD gate into a pass. All12 tiny-gap infinite-repeat pressure failures remain separate from the passed finite burst schedules.

The10,752 supplemental domain vectors and their held-posterior derivative checks do not reconstruct the original truncated training trajectory or prove end-to-end learned-network gradients. Whole-training numerical admission, original training adequacy and scientific admission remain HOLD/false.

`postmortem/SUMMARY.json`, `postmortem/ORIGINAL-MANIFEST.json`, collector sources and launch records are exact recovered bytes. `postmortem/FULL-RESULT.zip` contains the exact750,901-byte RESULT.json with its member manifest, avoiding a giant JSON diff. The collector’s internal SUMMARY and RESULT were provisional when written; finality comes from the external completed COLLECTION-RECEIPT, the exact archive digest, and the authenticated full readback recorded by the publisher. The original controller itself has no completed aggregate report, and this package does not fabricate one.

`STAGE-ROSTER.json` is a new metadata-only index. Every available stage result/outer/stdout/stderr is bound by path, byte count and SHA256 to its member in draft asset733215514. `COST-RECORDS.json` keeps whole-process, bootstrap, nested-stage, collection and publication scopes separate. The killed active child’s CPU is unknown, so the original waited CPU remains a lower bound. Energy and billing remain unknown.

The34,050,599-byte original archive is preserved as asset733215514 (SHA256 e96030a4c1a29031e56c406d7cc72cee9d141a0edb4701e3a83d60b5d5e32c52). The exact254,590-byte receipts archive is asset733217675 (SHA256 e6c01713ed4b962272b937976be2b989208254b1f02c22b8316dfd0ee2887d46). Both have complete authenticated SHA/CRC/member verification. The repository is public; release440410488 remains a draft, and anonymous asset/API checks returned404. This is not public publication.
''')
origins['README.md'] = {'kind': 'derived_metadata_explanation'}
write('PROVENANCE.json', origins)
print(json.dumps({'output': str(OUT), 'qualified_finite': 49, 'status_counts': summary['stage_status_counts'],
                  'roster_bytes': (OUT / 'STAGE-ROSTER.json').stat().st_size,
                  'full_result_zip_bytes': full_zip.stat().st_size}))

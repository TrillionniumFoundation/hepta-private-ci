"""Close a completed evidence snapshot without executing any model or oracle."""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile


ROOT = Path('/workspace/scratch/c385a7439f8e')
DEST = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110'


def identity(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(relative):
    return json.loads((DEST / relative).read_text())


def write(relative, value):
    path = DEST / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def copy(source, relative):
    expected = identity(source)
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(source.read_bytes())
    assert identity(target) == identity(source) == expected
    return {'source': str(source), 'target': relative, **expected}


def main():
    start, cpu = time.perf_counter(), time.process_time()
    assert not (DEST / 'MANIFEST.json').exists(), 'Frozen archive; do not mutate'
    source_identity = identity(Path(__file__))
    copies = []
    trace = ROOT / 'retained-trace-labels-independent-review-v1'
    for path in sorted(trace.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            copies.append(copy(path, 'trace-coverage/independent-review-v1/' + path.relative_to(trace).as_posix()))
    copies.append(copy(ROOT / 'retained-trace-labels-independent-review-v1.zip',
                       'trace-coverage/independent-review-v1.zip'))
    copies.append(copy(Path(__file__), 'curation-source/build_resource_replay_indexes_v1.py'))

    before = {str(p.relative_to(DEST)): identity(p) for p in sorted(DEST.rglob('*')) if p.is_file()}
    t, c = time.perf_counter(), time.process_time()
    parts = [DEST / 'curves-originals' / ('hcsn-original42-c1-curves-20261110-v1.zip.part0' + str(i)) for i in range(2)]
    raw = b''.join(p.read_bytes() for p in parts)
    archive_identity = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    assert archive_identity == {'bytes': 966326, 'sha256': '0ab09b443b102e056849900eb2fcb2d20933a78d6ef321373ae354f98e9b5f1d'}
    expected = read('curves-originals/MEMBER-MANIFEST.json')
    members = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)) == 5 and archive.testzip() is None
        for name in names:
            assert not name.startswith('/') and '..' not in Path(name).parts
            data = archive.read(name)
            record = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            members[name] = record
            if name == 'MEMBER-MANIFEST.json':
                assert json.loads(data) == expected
            else:
                assert record == expected[name]
    assert set(members) == set(expected) | {'MEMBER-MANIFEST.json'}
    write('CURVES-REASSEMBLY.json', {'schema': 'exact-original-curves-reassembly-v1',
          'parts': {p.name: identity(p) for p in parts}, 'archive': archive_identity,
          'members': members, 'all_members_sha_and_CRC_passed': True,
          'recompression': False, 'model_execution': False,
          'main_entry_wall_seconds': time.perf_counter() - t,
          'main_entry_CPU_seconds': time.process_time() - c,
          'scope': 'Byte concatenation, original ZIP CRC and every member hash; no model or resource algorithm rerun.'})

    publication = read('full-d-replay/publication/attempt-v2/RESULT.json')
    science = read('publication-and-science/SUMMARY.json')
    write('assets.json', {'schema': 'resource-replay-assets-v1', 'release_id': 440410488,
          'release_published': False, 'repository_visibility': 'public',
          'previous_index': '../p0p5-followup-20261110/assets.json',
          'known_full_authenticated_payloads_after_this_addition': 29,
          'count_scope': 'Prior 28 independently retained full readbacks plus the one new payload; not a fresh count of all release API entries.',
          'new_payloads': publication['assets'],
          'publication_receipt': {'path': 'full-d-replay/publication/attempt-v2/RESULT.json',
                                  **identity(DEST / 'full-d-replay/publication/attempt-v2/RESULT.json')},
          'publication_failed_attempt': 'full-d-replay/publication/attempt-v1/RESULT.json',
          'original_model_asset_id': 732598130,
          'hosted_science_artifact': {'artifact_id': science['artifact_id'], 'run_id': science['run_id'],
              'attempt': science['attempt'], 'source_head': science['source_head'],
              'tested_merge': science['tested_merge'], 'common_tree': science['common_tree'],
              'archive': science['archives']['science-run-42890048946-attempt1-artifact-13797877354.zip'],
              'local_path': 'publication-and-science/science-run-42890048946-attempt1-artifact-13797877354.zip'}})
    write('STATUS.json', {'schema': 'hcsn-resource-replay-status-v1',
          'curated_utc': datetime.now(timezone.utc).isoformat(), 'status': 'completed_evidence_snapshot',
          'research_position': 'Shared-generator regenerative probability flow and content-memory network',
          'original42_terminal': True, 'original42_adequate': 26, 'original42_attempts': 42,
          'baseline_after_separate_C1_adequate': 33, 'baseline_original_candidates': 36,
          'original_HCSN_attempts': 6, 'original_HCSN_adequate': 0, 'original_HCSN_status': 'budget_exhausted',
          'resource_analysis': {'reports': 49, 'complete_epoch_observations': 2927, 'before_training_observations': 42,
              'independent_review': 'passed', 'plan_was_post_terminal': True,
              'original_prospective_cuts_seconds': [300, 900, 1800], 'original_prospective_target_F1': .30},
          'full_D_replay': {'fits': 6, 'passed': 6, 'events_per_fit': 31952, 'windows_per_fit': 128,
              'max_metric_absolute_difference': 2.220446049250313e-16,
              'confirmation_subject': False, 'training_adequacy_established': False},
          'original_trace_coverage': {'retained_record_slots': 2066, 'valid_sample_position_layer_states': 16492,
              'all_update_indices': [0], 'post_update_record_slots': 0, 'post_update_valid_states': 0,
              'phase_epoch_derived_not_literal': True, 'whole_training_domain': 'HOLD'},
          'current_hosted_science': {'run_id': 42890048946, 'attempt': 1, 'conclusion': 'success',
              'source_head': science['source_head'], 'tested_merge': science['tested_merge'], 'tree': science['common_tree']},
          'repository_overall_CI': 'not_declared_passed; retained observations have separate times and heads',
          'numeric_terminal_audit': 'Separate ongoing run; this archive makes no completed result claim',
          'C2_actual_training': 'Not started at this snapshot; preparation and read-only preflight are separate',
          'scientific_benefit': 'HOLD', 'whole_training_numerical_qualification': 'HOLD',
          'P3_neural_QVI_benefit': 'HOLD', 'P4_multimodal_extension': 'HOLD', 'P5': 'benefit_gated',
          'confirmation_E_access': False, 'main_merged': False, 'release_published': False})

    rows = []
    def row(name, path, scope, measurements=None, fields=()):
        document = read(path) if path.endswith('.json') else None
        if measurements is None:
            measurements = {key: document[key] for key in fields}
        rows.append({'id': name, 'artifact': path, 'artifact_identity': identity(DEST / path),
                     'measurements': measurements, 'scope': scope})

    package = json.loads((DEST / 'curves-originals/native.stdout').read_text().splitlines()[0])
    row('curves-export-and-package', 'curves-originals/native.stdout',
        'Main-entry interval including export and ZIP work; export/package subsets overlap; process CPU is a pre-exit sample, not independent waited CPU.',
        {k: package[k] for k in ['whole_main_wall_seconds', 'full_process_cpu_seconds', 'package_wall_seconds', 'package_cpu_seconds']})
    row('curves-transfer', 'curves-originals/RECOVERY-RECEIPT.json',
        'Sum of overlapping RPC round trips; not model wall, CPU, calendar duration or additive process cost.',
        fields=['sum_rpc_round_trip_wall_seconds_overlapping'])
    for name in ['tests', 'analysis']:
        row('resource-' + name, f'resource-analysis-v1/{name}-EXECUTION.json',
            'Complete isolated subprocess; no model, optimizer or numerical oracle.',
            fields=['whole_child_wall_seconds', 'waited_child_CPU_seconds', 'returncode'])
    row('independent-resource-review', 'independent-resource-review-v1/OUTER-OBSERVATION.json',
        'Only main-entry computation and absolute CPU sample retained; complete spawn-to-exit wall/waited CPU unknown.',
        fields=['main_entry_verification_wall_seconds', 'main_entry_computation_CPU_seconds',
                'absolute_process_CPU_sample_seconds', 'complete_spawn_to_exit_wall_seconds', 'complete_waited_child_CPU_seconds'])
    for folder, name in [('render-attempt-v1', 'first-render'), ('output-v1', 'final-render')]:
        row(name, f'resource-analysis-v1/{folder}/RENDER-RECEIPT.json',
            'Main entry through output, excluding imports and receipt write/exit. First draft source/receipt retained; old draft PNG/SVG not retained.',
            fields=['main_entry_wall_seconds', 'process_CPU_sample_seconds'])
    row('original-trace-JSON-scan', 'trace-coverage/recovery-v1/RESULT.json',
        'Standalone JSON scan pre-serialization samples; no model/oracle. Not a complete post-exit measurement.',
        fields=['wall_sample_seconds', 'CPU_sample_seconds', 'peak_RSS_sample_bytes'])
    row('trace-archive-collection', 'trace-coverage/recovery-v1/COLLECTION.json',
        'Separate archive process samples before receipt serialization; cumulative CPU sample is not interval CPU.',
        fields=['wall_sample_seconds', 'CPU_sample_seconds', 'peak_RSS_sample_bytes'])
    row('trace-local-recovery', 'trace-coverage/recovery-v1/DOWNLOAD.json',
        'Local decode/CRC/hash samples before receipt; transport CPU and full process wall unknown.',
        fields=['local_recovery_wall_sample_seconds', 'local_recovery_CPU_sample_seconds'])
    row('trace-independent-review', 'trace-coverage/independent-review-v1/OUTER.json',
        'Complete independent JSON/order reconstruction child; no probability-array replay, model or oracle.',
        fields=['complete_child_wall_seconds', 'waited_child_CPU_seconds', 'returncode'])
    row('committed-evidence-red-green', 'publication/committed-evidence-recovery-checks-v1/EXECUTION.json',
        'Two distinct historical invocations. Wall includes result-read/setup; original source_unchanged was not independently prehashed. See source-scope addendum.',
        {'receipts': [{k: item[k] for k in ['returncode', 'errors', 'verified_files', 'whole_process_wall_seconds', 'waited_child_cpu_seconds']}
                      for item in read('publication/committed-evidence-recovery-checks-v1/EXECUTION.json')['receipts']]})
    row('CURRENT-committed-closure', 'publication/committed-current-evidence-closure-v2/EXECUTION.json',
        'Complete child interval, explicit source/input pre/post hashes; earlier v1 absent-worktree preflight preserved separately.',
        fields=['whole_child_wall_seconds', 'waited_child_CPU_seconds', 'returncode'])
    row('formatter-preflight-failure', 'publication/resource-analysis-just-fmt-preflight-failure-v1.json',
        'Missing excluded working directory before formatter launch; cost unknown, not zero.',
        fields=['process_started', 'wall_seconds', 'CPU_seconds', 'returncode'])
    row('formatter-success', 'publication/resource-analysis-just-fmt-v2.json',
        'Distinct complete cached formatter subprocess after restoring directory; source unchanged.',
        fields=['whole_child_wall_seconds', 'waited_child_CPU_seconds', 'returncode'])
    row('full-D-validation-replay-archive-publication', 'full-d-replay/COSTS.json',
        'Refer to nested exact ledger. Bootstrap includes native validation and controller; controller includes six fits. Failed v1 and successful v2 publication are distinct; do not add nested terms.',
        {'nested_ledger': 'full-d-replay/COSTS.json', 'complete_experiment_total': None})
    row('publication-originals-and-science-artifact', 'publication-and-science/SUMMARY.json',
        'Complete collection child includes one artifact GET and local ZIP work. Nested stages and text encoding are separate named scopes; previous upload/replay not executed again.',
        {k: science[k] for k in ['native_collection_whole_child_wall_seconds', 'native_collection_waited_child_and_descendant_CPU_seconds',
                                 'own_wrapper_CPU_seconds', 'tool_transport_complete_wall_seconds', 'tool_transport_CPU_seconds']})
    for filename in ['BASE-COPY-RECEIPT.json', 'FULL-D-COPY-RECEIPT.json', 'PUBLICATION-SCIENCE-COPY-RECEIPT.json', 'CURVES-REASSEMBLY.json']:
        row(filename, filename, 'Local main-entry copy/hash/ZIP verification samples; imports/receipt/exit and manual curation are excluded.',
            fields=['main_entry_wall_seconds', 'main_entry_CPU_seconds'])
    write('COSTS.json', {'schema': 'hcsn-resource-replay-costs-v1', 'rows': rows,
          'previous_ledgers': ['../p0p5-20261110/COSTS.json', '../p0p5-followup-20261110/COSTS.json'],
          'accounting_complete': False, 'total_elapsed_seconds': None, 'total_energy_joules': None,
          'total_currency_cost': None, 'peak_vram_bytes': None,
          'rules': ['Never sum enclosing and nested costs.', 'Failed attempts remain charged; unknown is not zero.',
                    'Per-fit process-wall sums are not campaign calendar time, physical energy, or full research cost.',
                    'Index closure sampling is in INDEX-CLOSURE-RECEIPT.json; freezing/verification/publication after this snapshot needs later receipts.'],
          'scientific_benefit_established': False})
    assert all(identity(DEST / name) == value for name, value in before.items())
    assert identity(Path(__file__)) == source_identity
    write('INDEX-CLOSURE-RECEIPT.json', {'schema': 'resource-replay-index-closure-v1',
          'copied_files': copies, 'source_identity': source_identity, 'original_inputs_unchanged': True,
          'main_entry_wall_seconds': time.perf_counter() - start, 'main_entry_CPU_seconds': time.process_time() - cpu,
          'scope': 'Main-entry indexing, exact trace-review copy, reassembly and before/after hashes; excludes imports and receipt/manifest write/exit. Nested reassembly not additional.',
          'new_training_steps': 0, 'new_forward_calls': 0, 'new_oracle_calls': 0})
    files = {str(p.relative_to(DEST)): identity(p) for p in sorted(DEST.rglob('*')) if p.is_file()}
    write('MANIFEST.json', {'schema': 'hcsn-resource-replay-evidence-manifest-v1',
          'files': files, 'scientific_admission': 'HOLD', 'scope': 'All exact snapshot files except this manifest; original nested manifests are preserved unchanged.'})
    print(json.dumps({'files': len(files), 'manifest': identity(DEST / 'MANIFEST.json'), 'cost_rows': len(rows)}))


if __name__ == '__main__':
    main()

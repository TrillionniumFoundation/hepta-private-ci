"""Package preserved execution facts without rerunning or selecting outcomes."""

import argparse
import collections
import json
import math
from pathlib import Path
import tarfile

from .build import sha


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def package(args):
    area = Path(__file__).parent.resolve()
    raw = args.runs / 'fresh-001'
    facts = json.loads((raw / 'results.json').read_text())
    protocol = json.loads((area / 'PROTOCOL.json').read_text())
    if any(sha(path) != digest for path, digest in protocol['frozen_candidate_sha256'].items()):
        raise ValueError('Frozen executed input changed')
    rows = [json.loads(line) for line in (raw / 'rollouts.jsonl').read_text().splitlines()]
    decisions = [json.loads(path.read_text()) for path in sorted(raw.glob('decision-*.json'))]
    candidates = [c for d in decisions for c in d['response']['decision']['candidates']]
    per_view = {}
    for view in protocol['views']:
        selected = [r for r in rows if r['view'] == view]
        emitted = [r for r in selected if r['action'] is not None]
        per_view[view] = {'pairs': len(selected), 'actual_generated': len(emitted),
                          'abstained': len(selected) - len(emitted),
                          'actions': dict(collections.Counter(r['action'] for r in emitted))}
    metrics = {}
    for name in ('owner_micros', 'native_execution_micros', 'owner_peak_bytes', 'native_transient_bytes',
                 'native_checkpoint_bytes', 'native_write_amplification_ppm'):
        values = sorted(c[name] for c in candidates)
        metrics[name] = {'count': len(values), 'p95': values[math.ceil(.95 * len(values)) - 1],
                         'p99': values[math.ceil(.99 * len(values)) - 1], 'maximum': max(values)}
    costs = {p.stem: json.loads(p.read_text()) for p in sorted(args.runs.glob('*.process.json'))}
    builds = {p.parent.name: json.loads(p.read_text()) for p in sorted(args.runs.glob('build-*/build.json'))}
    development = json.loads((args.runs / 'smoke-002/results.json').read_text())
    first = json.loads((args.runs / 'smoke-001/results.json').read_text())
    boundaries = json.loads((args.runs / 'boundaries-001/results.json').read_text())
    archive = area / 'RAW_EVIDENCE.tar.gz'
    contents = {}
    with tarfile.open(archive, 'x:gz', compresslevel=6) as stream:
        for path in sorted(args.runs.rglob('*')):
            if path.is_file():
                relative = str(path.relative_to(args.runs))
                contents[relative] = {'sha256': sha(path), 'bytes': path.stat().st_size}
                stream.add(path, arcname='native/' + relative, recursive=False)
    save(area / 'RAW_MANIFEST.json', {'schema': 'hepta.closure.native-raw-manifest.v1',
                                     'archive_sha256': sha(archive), 'files': contents})
    result = {'schema': 'hepta.closure.native-final.v1', 'protocol_sha256': sha(area / 'PROTOCOL.json'),
              'binary_sha256': protocol['binary_sha256'], 'frozen_inputs_still_exact': True,
              'actual_native_ticks': len(candidates), 'new_source_pairs': len(rows),
              'source_independence_scope': 'Available execution metadata; no attestation of unknown external use',
              'online_results': facts, 'by_view': per_view, 'all_tick_resources': metrics,
              'development72': {'ticks': 144, 'generated': development['actual_output_generations'],
                                'abstained': development['abstained_without_generation'],
                                'negative_cases': len(development['negative_cases']),
                                'rollover_final_sequence': 144},
              'first_smoke12': {'generated': first['actual_output_generations'],
                                'resource_summary_passed': [r['native_resource_summary_passed'] for r in first['process_status']],
                                'observed_failure': 'Second process p95=3847us exceeded unchanged 3000us ceiling; retained, not overwritten'},
              'recovery_and_absent_evidence_probes': boundaries, 'process_costs': costs,
              'build_attempts': builds, 'build_cost_limit': 'Incremental rustc wall only; reused original compiled dependencies, no full daemon build',
              'raw_evidence': {'archive': archive.name, 'sha256': sha(archive),
                               'bytes': archive.stat().st_size, 'files': len(contents)},
              'scope': {'actual_generation_after_native_decision': True, 'original_owner_executed': True,
                        'new_policy_training_steps': 0, 'weights_decodes_per_native_process': 1,
                        'ndu_use': 'Observed utility committed to original NDU store and bound to subsequent tick; no NDU action-value optimization',
                        'selection': protocol['selection'], 'whole_daemon_built_or_deployed': False,
                        'new_calibration_qualification': False, 'global_optimal_control_proved': False,
                        'production_authority': 'deny_all', 'production_dataset_or_signer_credentials_created': False,
                        'production_resolver_invoked_in_this_study': False},
              'pre_source_access_attempts': ['build-001 failed before compilation completed; exact diagnostic retained',
                                            'Old abc_followup process wrapper refused new module before launch; own scoped wrapper added',
                                            'Freeze attempt referenced absent v6/model.py before writing protocol; corrected to actual v7/model.py and v6/neural.py',
                                            '39-file draft protocol extended to41 by pinning emission.py and public feature encoder before any fresh source access']}
    save(area / 'RESULTS.json', result)
    print(json.dumps({'fresh_pairs': len(rows), 'generated': facts['actual_output_generations'],
                      'archive_bytes': archive.stat().st_size, 'archive_sha256': sha(archive)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True)
    package(parser.parse_args())

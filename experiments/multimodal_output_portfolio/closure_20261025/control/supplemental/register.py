"""Freeze added baselines without changing or replacing the primary protocol."""

import argparse
import json
from pathlib import Path
import time

from ....abc_recovery.base_recovery import file_sha, write_json
from ..registry import HERE, BASE


def run(primary, output):
    frozen = json.loads((HERE / 'FRESH_PROTOCOL.json').read_text())
    registered = json.loads((primary / 'registration.json').read_text())
    old = json.loads((BASE / 'abc_followup/control/PROTOCOL-v2.json').read_text())
    files = dict(frozen['frozen_candidate_sha256'])
    files.update({str(p.resolve()): file_sha(p) for p in Path(__file__).parent.glob('*.py')})
    files[str((HERE / 'FRESH_PROTOCOL.json').resolve())] = file_sha(HERE / 'FRESH_PROTOCOL.json')
    if any(file_sha(Path(p)) != expected for p, expected in files.items()):
        raise ValueError('Primary/supplemental identity changed')
    result = {'schema': 'hepta.closure.control-exploratory-supplement.v1', 'study': 'control',
              'source_allocation_sha256': frozen['source_allocation_sha256'], 'frozen_candidate_sha256': files,
              'registered_unix_ns': time.time_ns(), 'primary_started_unix_ns': registered['started_unix_ns'],
              'primary_registration_sha256': file_sha(primary / 'registration.json'),
              'status': 'exploratory_registered_after_primary_collection_started', 'primary_replaced_or_refit': False,
              'source_role': 'closure_control', 'pair_start': 0, 'pair_count': 256, 'seeds': frozen['seeds'],
              'policies': ['strong_nonfeedback', 'fixed_allocation'], 'requests': 40960,
              'evaluation': frozen['evaluation'], 'fixed_allocation_plan': ['refine_image', 'refine_text'],
              'reference': {str(r['seed']): {k: r[k] for k in ('selected_nonfeedback', 'static_plan_index')} for r in old['controllers']},
              'same_public_opportunity': 'ExactFeatureCache.read on every reached decision, including child observations ignored by an already committed fixed/one-shot plan; all actual work charged',
              'initial_and_future_streams': 'Exactly primary namespaces and path-indexed RNG; aliases never enter RNG',
              'quality_scope': 'Exploratory paired source/seed inference; same 256 sources, no extra independent N',
              'cost_scope': 'Actual full requests, policies alternated within supplemental blocks; run separately from primary, no randomized interleaved cost superiority claim',
              'failure_policy': 'Keep every attempt, all costs, no retries or outlier removal; any missing quality blocks inference'}
    if output.exists():
        raise FileExistsError('Supplement registration cannot be overwritten')
    write_json(output, result)
    print(json.dumps({'protocol': str(output), 'sha256': file_sha(output), 'status': result['status']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); run(args.primary, args.output)

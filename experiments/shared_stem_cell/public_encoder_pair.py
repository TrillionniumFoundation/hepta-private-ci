"""Run a second pinned, real public Stem on an existing public smoke cohort.

Research-only. Never manufacture prospective outcomes or alter the first run.
The second model executes in a separate Python process in the hosted workflow.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from experiments.shared_stem_cell.preflight_review import checked_bytes, digest, require
from experiments.shared_stem_cell.wire import canonical, decode, sha, write_once

# Explicit fixed snapshot; do not turn a moving remote 'main' into an experiment arm.
CANDIDATE_ID = 'answerdotai/ModernBERT-base'
CANDIDATE_REVISION = 'fa3113d09d6dacfe5528708803dd92a62240237a'
BASELINE_ID = 'jhu-clsp/mmBERT-small'


def verify_baseline(public_dir: Path) -> tuple[dict, bytes]:
    manifest = decode(checked_bytes(public_dir / 'manifest.json'))
    source = decode(checked_bytes(public_dir / 'model-source.json'))
    require(type(manifest) is dict and manifest.get('schema') == 'hepta.shared-stem-execution.v1',
            'physical baseline manifest missing')
    require(type(source) is dict and source.get('model_id') == BASELINE_ID
            and source.get('revision') == manifest.get('model', {}).get('revision')
            and type(source.get('revision')) is str and len(source['revision']) == 40
            and all(ch in '0123456789abcdef' for ch in source['revision']),
            'baseline model revision is not fixed')
    bound = manifest.get('dataset')
    require(type(bound) is dict and set(bound) == {'path', 'sha256'}
            and bound['path'] == 'dataset.jsonl' and digest(bound['sha256']),
            'baseline dataset identity unavailable')
    dataset_bytes = checked_bytes(public_dir / 'dataset.jsonl', bound['sha256'])
    data = [decode(line) for line in dataset_bytes.splitlines()]
    require(len(data) == 128 and all(type(r) is dict for r in data)
            and {s: sum(row.get('split') == s for row in data) for s in
                 ('train', 'calibration', 'holdout')} ==
            {'train': 64, 'calibration': 32, 'holdout': 32}
            and all(row.get('observed_at') is None for row in data)
            and manifest.get('steps') == 20 and manifest.get('seed') == 20261013
            and manifest.get('cells') == 2 and manifest.get('classes') == 4,
            'unsupported public retrospective cohort/learning budget')
    return manifest, dataset_bytes


def stage_and_execute(public_dir: Path, output: Path) -> dict:
    """Physical run, no synthetic fallback. Output is create-only."""
    baseline, dataset_bytes = verify_baseline(public_dir)
    # Stage is isolated from the producer; network is confined to the explicit
    # public-model acquisition method and the execution loader stays offline.
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'dataset.jsonl').open('xb') as fd:
        fd.write(dataset_bytes)
    from experiments.shared_stem_cell.public_smoke import stage_model
    from experiments.shared_stem_cell.execution import run
    candidate = stage_model(output, CANDIDATE_ID, CANDIDATE_REVISION,
                            kind='masked_lm', allow_conversion=False)
    require(candidate.get('conversion') is None and candidate.get('model_id') == CANDIDATE_ID
            and candidate.get('revision') == CANDIDATE_REVISION,
            'candidate must use signed publisher safetensors without conversion')
    plan = {**baseline, 'model': candidate}
    write_once(output / 'manifest.json', plan)
    # Same train/feature/head/control knobs except pinned model identity, with
    # identical physical dataset bytes. No label source enters the Encoder.
    report = run(output / 'manifest.json', output / 'execution')
    require(report['mode'] == 'local_pretrained' and report['production_accepted'] is False,
            'unexpected producer authority or execution mode')
    write_once(output / 'pair-member.json', {
        'schema': 'hepta.public-two-stem-member.v1',
        'baseline_model_id': BASELINE_ID,
        'baseline_revision': baseline['model']['revision'],
        'candidate_model_id': CANDIDATE_ID,
        'candidate_revision': CANDIDATE_REVISION,
        'dataset_sha256': sha(dataset_bytes),
        'manifest_sha256': sha(canonical(plan)),
        'producer_report_sha256': sha((output / 'execution/report.json').read_bytes()),
        'independent_future_outcomes': False,
        'production_accepted': False,
    })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    stage_and_execute(args.baseline, args.output)


if __name__ == '__main__':
    main()

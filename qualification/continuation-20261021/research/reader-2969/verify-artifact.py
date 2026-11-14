"""Verify retained Reader rows and source bindings without invoking a model."""

import collections
import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('reader_evaluator', ROOT / 'hepta_sngr_reader_eval.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)
corpus = evaluator.load_cases(ROOT / 'hepta_sngr_reader_cases.json')
assert corpus['manifest_sha256'] == evaluator.FROZEN_CASE_SHA256
source_bindings = evaluator.verify_checkout(corpus, ROOT / 'source')
report = json.loads((ROOT / 'extracted/hepta-reader-report.json').read_text())
summary = json.loads((ROOT / 'extracted/hepta-reader-summary.json').read_text())
runtime = json.loads((ROOT / 'extracted/hepta-runtime-receipt.json').read_text())
rows = report['rows']
tasks = {t['id']: t for t in corpus['tasks']}
arms = tuple(evaluator.ARM_NAMES)
expected_keys = set(itertools.product(tasks, arms, [0]))
actual_keys = [(r['task_id'], r['arm'], r['presentation']) for r in rows]
assert len(actual_keys) == len(set(actual_keys)) == 64
assert set(actual_keys) == expected_keys
assert sorted(expected_keys, key=lambda value: (value[0], value[2], value[1])) == actual_keys
assert report['model_calls'] == report['expected_model_calls'] == summary['calls'] == 64
assert report['frozen_manifest_sha256'] == corpus['manifest_sha256']
assert report['repository_base_commit'] == corpus['base_commit']
assert report['model_snapshot_sha256'] == summary['model']
assert summary['status'] == 'evaluated'
assert report['production_selection_authority'] is False
assert runtime['production_selection_authority'] is False
assert report['descriptive_not_statistically_qualified'] is True

for row in rows:
    task = tasks[row['task_id']]
    rotated, shift = evaluator.option_presentation(task, 17, 0, presentations=1)
    state, questions = evaluator.construct_request(corpus, task, row['arm'], choices_override=rotated)
    assert row['option_shift'] == shift
    assert row['canonical_gold'] == task['gold']
    gold = evaluator.CHOICE_LABELS[(evaluator.CHOICE_LABELS.index(task['gold']) + shift) % 4]
    supported = row['arm'] == 'full'
    expected = gold if supported else 'UNKNOWN'
    assert row['gold'] == gold
    assert row['expected_evidence_answer'] == expected
    assert row['prediction'] in ('A', 'B', 'C', 'D', 'UNKNOWN')
    assert row['correct'] == int(row['prediction'] == gold)
    assert row['abstained'] == int(row['prediction'] == 'UNKNOWN')
    assert row['evidence_condition_correct'] == int(row['prediction'] == expected)
    assert row['unsupported_assertion'] == int(row['prediction'] != 'UNKNOWN' and not supported)
    assert row['source_path'] == task['source']['path']
    assert row['source_blob_sha'] == task['source']['blob_sha']
    assert row['input_characters'] == len(json.dumps((state, questions), ensure_ascii=False))
    assert type(row['reported_tokens']) is int and 0 < row['reported_tokens'] < 512
    assert math.isfinite(row['wall_ms']) and row['wall_ms'] > 0
    assert 0 <= row['reported_probability_expected_answer'] <= 1
    assert 0 <= row['multiclass_brier_evidence_target'] <= 2

recomputed = {}
for arm in arms:
    values = [r for r in rows if r['arm'] == arm]
    assert len(values) == 16
    latencies = sorted(r['wall_ms'] for r in values)
    metrics = {
        'top1_gold_fraction': statistics.mean(r['correct'] for r in values),
        'abstention_fraction': statistics.mean(r['abstained'] for r in values),
        'evidence_condition_accuracy': statistics.mean(r['evidence_condition_correct'] for r in values),
        'multiclass_brier_evidence_target': statistics.mean(r['multiclass_brier_evidence_target'] for r in values),
        'mean_reported_probability_expected_answer': statistics.mean(r['reported_probability_expected_answer'] for r in values),
        'unsupported_assertion_fraction': statistics.mean(r['unsupported_assertion'] for r in values),
        'reported_confidence_correctness_mse_diagnostic': statistics.mean((r['confidence'] - r['correct']) ** 2 for r in values),
        'p50_wall_ms': statistics.median(latencies),
        'p95_wall_ms': latencies[math.ceil(0.95 * len(latencies)) - 1],
        'mean_input_characters': statistics.mean(r['input_characters'] for r in values),
        'mean_reported_input_tokens': statistics.mean(r['reported_tokens'] for r in values),
    }
    for name, value in metrics.items():
        assert math.isclose(value, report['summaries'][arm][name], rel_tol=1e-12, abs_tol=1e-12), (arm, name)
        assert math.isclose(value, summary['summary'][arm][name], rel_tol=1e-12, abs_tol=1e-12), (arm, name)
    recomputed[arm] = metrics

log = (ROOT / 'job.log').read_text()
assert 'reader_status=evaluated' in log
assert 'Treat confidence from the affected entries as uncalibrated' in log
result = {
    'schema': 'hepta.reader-artifact-independent-check.v1',
    'workflow_run': 39524743076,
    'job': 118976636455,
    'artifact_id': 12312374935,
    'source_sha': 'ca2768978429a2c9a98641fa2d58a8f587b88874',
    'artifact_sha256': hashlib.sha256((ROOT / 'reader-intake-ca276897.zip').read_bytes()).hexdigest(),
    'verified_new_hosted_predict_calls': 64,
    'unique_registered_cases': len(tasks),
    'rows_per_arm': dict(collections.Counter(r['arm'] for r in rows)),
    'source_files_verified': source_bindings,
    'manifest_sha256': corpus['manifest_sha256'],
    'source_dataset_base': corpus['base_commit'],
    'model_repo': 'convaiinnovations/laya',
    'model_revision': 'c5d78730f3493e4fe16d61507ef4b78eef7318cf',
    'reported_model_snapshot_sha256': report['model_snapshot_sha256'],
    'recomputed_metrics': recomputed,
    'runtime': runtime,
    'posture': {'production_selection_authority': False, 'statistical_qualification': False, 'independent_heldout_calibration': False},
    'limitations': [
        'Registered repository diagnostic cases are not newly independent source families or future-window samples',
        'One answer presentation; position-counterbalanced diagnostics were not run',
        'Hosted runtime emitted an invalid-temperature/clamping warning; confidence is not certified calibrated',
        'Retained rows do not include the complete class probability vector; aggregate Brier values are recomputed from retained per-row scores, not from original vectors',
        'No weights or individual checkpoint-file inventory retained here; the observed fingerprint cannot be independently recomputed from these non-weight artifacts',
        'No FLOPs, energy, full peak memory, complete checkpoint/resource/calibration join, or production acceptance is supplied',
        'These are 64 Laya Reader calls, separate from historical Qwen Memory 40+72',
    ],
    'local_model_calls_by_this_verifier': 0,
}
(ROOT / 'independent-verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k not in ('recomputed_metrics', 'runtime')}, indent=2))

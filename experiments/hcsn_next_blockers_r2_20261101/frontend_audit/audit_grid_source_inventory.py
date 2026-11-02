"""Reconcile the complete registered source QA and HOLD records; no decoding."""
import argparse
import json
from pathlib import Path

import numpy as np

from audit_audio_candidate import read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIMARY = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'
SECONDARY = ROOT / 'experiments/hcsn_grid_temporal_r2_20261101'


def main(role):
    path = PRIMARY / f'{role.upper()}_SOURCE_QA.json'
    qa = read(path)
    rows = [r for r in read(PRIMARY / 'COHORT_SELECTION.json')['entries'] if r['role'] == role]
    ledger_path = PRIMARY / 'inputs' / f'{role.upper()}_ACQUISITION.json'
    ledger = {(r['speaker'], r['member']): r for r in read(ledger_path)['records']}
    actual = {(r['speaker'], r['member']): r for r in qa['records']}
    expected = {(r['speaker'], r['name']): r for r in rows}
    assert len(actual) == len(qa['records']) == len(rows) and set(actual) == set(expected) == set(ledger)
    assert qa['registered_clips'] == len(rows) and qa['raw_bytes'] == sum(r['bytes'] for r in rows)
    assert qa['registered_actors'] == sorted({r['speaker'] for r in rows})
    assert qa['acquisition_sha256'] == sha(ledger_path) and qa['decoder_sha256'] == sha(PRIMARY / 'data_v2.py')
    assert qa['candidate_sha256'] == sha(PRIMARY / 'results/run001/CANDIDATE_FREEZE.json')
    assert not any(qa[k] for k in ('method_changed', 'models_loaded', 'scores_generated', 'valid_subset_adoption'))
    failures = []
    for key, record in actual.items():
        row, acquired = expected[key], ledger[key]
        assert record['role'] == row['role'] == role and record['bytes'] == row['bytes'] == acquired['bytes']
        if record['qualified']:
            detail = record['detail']
            assert detail['raw_sha256'] == acquired['sha256']
            assert record['video_shape'] == [25, 88, 88] and record['audio_shape'] == [16000]
            assert detail['target'] == row['sentence_target'] and detail['accepted_end'] == detail['origin'] + 1
            assert len(detail['selected_timestamps']) == 25
            assert np.all(np.asarray(detail['selected_timestamps']) <= detail['origin'] + np.arange(1, 26) / 25)
        else:
            assert record['raw_sha256'] == acquired['sha256']
            assert record['error_type'] == 'ValueError' and record['error'] == 'Incompleteorderedprefix'
            times = np.asarray(record['video_pts'])
            assert len(times) > 1 and np.all(np.diff(times) > 0)
            start = float(next(s['start_time'] for s in record['stream_starts'] if s['codec_type'] == 'audio'))
            assert times[-1] < max(start, times[0]) + 1
            failures.append(dict(member=row['name'], speaker=row['speaker'], raw_sha256=acquired['sha256'], frames=len(times), last_pts=float(times[-1])))
    valid = sum(r['qualified'] for r in qa['records'])
    assert valid == qa['qualified_source_clips'] and len(failures) == qa['failed_source_clips']
    assert qa['status'] == ('SOURCE_FAILURE_HOLD' if failures else 'SOURCE_QUALIFIED')
    receipt_path = PRIMARY / f'source_qa_{role}.receipt.json'
    receipt = read(receipt_path)
    assert receipt['status'] == 'completed' and receipt['returncode'] == 0
    for log in receipt['logs']:
        assert sha(ROOT / log['path']) == log['sha256']
    holds = []
    for lane in ((PRIMARY, SECONDARY) if failures else ()):
        hold_path = lane / f'{role.upper()}_HOLD.json'
        hold = read(hold_path)
        assert hold['status'] == 'SOURCE_FAILURE_HOLD' and hold['candidate_sha256'] == sha(lane / 'results/run001/CANDIDATE_FREEZE.json')
        assert hold['registered_clips'] == len(rows) and hold['qualified_source_clips'] == valid and hold['failed_source_clips'] == len(failures)
        assert hold['full_registered_source_qa_sha256'] == sha(path)
        assert hold['aggregate_model_scores'] is None and hold['valid_subset_scores'] is None
        assert not any(hold[k] for k in ('source_or_candidate_changed', 'registered_sample_replaced', 'padding_or_short_prefix_exception', 'retained_feature_bank', 'production_activation', 'all_blockers_closed'))
        assert hold['failed_meter_receipt_sha256'] == sha(lane / f'features_{role}.receipt.json')
        holds.append(dict(path=str(hold_path.relative_to(ROOT)), sha256=sha(hold_path)))
    result = dict(schema='hcsn.grid.complete-source-inventory.independent-record-audit.v1', role=role, qa_sha256=sha(path),
        registered_clips=len(rows), qualified_source_clips=valid, failed_source_clips=len(failures), failures=failures, holds=holds,
        source_qa_receipt_sha256=sha(receipt_path), source_qa_cpu_seconds=receipt['total_cpu_seconds'],
        source_inventory_complete=True, valid_subset_qualification=False, quality_accuracy=None, registered_gate_status='HOLD' if failures else 'SOURCE_QUALIFIED_AWAITING_MODEL_METRICS',
        raw_media_opened=False, ffprobe_processes=0, neural_encoder_inference_performed=False, fit_performed=False, all_blockers_closed=False)
    target = HERE / f'REVIEW_GRID_SOURCE_INVENTORY_{role.upper()}.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), role=role, valid=valid, failed=len(failures), status='HOLD' if failures else 'SOURCE_QUALIFIED'), sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['development', 'confirmation'])
    main(parser.parse_args().role)

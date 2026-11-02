"""Independently verify a registered GRID prefix failure with ffprobe only."""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import zlib

import numpy as np

from audit_audio_candidate import read, sha


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIMARY = ROOT / 'experiments/hcsn_grid_frontend_r2_20261101'
SECONDARY = ROOT / 'experiments/hcsn_grid_temporal_r2_20261101'


def main(role):
    qa_path = PRIMARY / f'FAILURE_{role.upper()}_PREFIX_QA.json'
    qa = read(qa_path)
    failures = [r for r in qa['records'] if not r['full_one_second']]
    assert failures
    culprit = failures[0]
    rows = [r for r in read(PRIMARY / 'COHORT_SELECTION.json')['entries'] if r['role'] == role]
    ordinal = next(i for i, r in enumerate(rows) if r['speaker'] == culprit['speaker'] and r['name'] == culprit['member'])
    row = rows[ordinal]
    assert ordinal == culprit['ordinal']
    ledger_path = PRIMARY / 'inputs' / f'{role.upper()}_ACQUISITION.json'
    ledger = read(ledger_path)
    assert ledger['protocol_sha256'] == sha(PRIMARY / 'PROTOCOL.json')
    assert ledger['cohort_sha256'] == sha(PRIMARY / 'COHORT_SELECTION.json')
    assert ledger['role'] == role and len(ledger['records']) == len(rows)
    expected = {(r['speaker'], r['name']) for r in rows}
    records = {(r['speaker'], r['member']): r for r in ledger['records']}
    assert len(records) == len(ledger['records']) and set(records) == expected
    record = records[row['speaker'], row['name']]
    media = ROOT.parent / 'grid_raw_r2_media' / f"s{row['speaker']}" / Path(row['name']).name
    data = media.read_bytes()
    assert len(data) == row['bytes'] == record['bytes']
    assert f'{zlib.crc32(data) & 0xffffffff:08x}' == row['crc32']
    digest = sha(media)
    assert digest == record['sha256'] == culprit['raw_sha256']
    command = ['ffprobe', '-v', 'error', '-show_streams', '-show_frames', '-show_entries',
               'stream=codec_type,start_time,width,height,sample_rate:frame=media_type,best_effort_timestamp_time', '-of', 'json', str(media)]
    completed = subprocess.run(command, capture_output=True, check=False)
    assert completed.returncode == 0
    probe = json.loads(completed.stdout)
    times = np.array([float(f['best_effort_timestamp_time']) for f in probe['frames'] if f.get('media_type') == 'video'])
    audio = next(r for r in probe['streams'] if r['codec_type'] == 'audio')
    origin = max(float(audio.get('start_time', 0)), float(times[0]))
    assert np.all(np.diff(times) > 0)
    assert len(times) == culprit['video_frames'] and times[0] == culprit['first_pts'] and times[-1] == culprit['last_pts']
    assert times[-1] < origin + 1 and not culprit['full_one_second']
    if 'pts' in culprit:
        assert times.tolist() == culprit['pts']
    # Evaluate the actual frozen guard predicate on independently probed
    # timestamps, without invoking a feature extractor or neural encoder.
    code = (PRIMARY / 'data_v2.py').read_text()
    tree = ast.parse(code)
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.If) and any(isinstance(child, ast.Constant) and child.value == 'Incompleteorderedprefix' for child in ast.walk(n))]
    assert len(guards) == 1
    predicate = ast.Expression(guards[0].test)
    rejects = bool(eval(compile(ast.fix_missing_locations(predicate), 'frozen-prefix-guard', 'eval'), {'np': np, 'times': times, 'origin': origin}))
    assert rejects
    receipts = []
    for lane in (PRIMARY, SECONDARY):
        frozen_name = 'MODEL_SOURCE_FREEZE.json' if lane == PRIMARY else 'SOURCE_FREEZE.json'
        frozen = read(lane / frozen_name)
        for name, expected_digest in frozen['files'].items():
            assert sha(lane / name) == expected_digest
        for name, expected_digest in frozen.get('dependencies', {}).items():
            assert sha(ROOT / name) == expected_digest
        candidate_path = lane / 'results/run001/CANDIDATE_FREEZE.json'
        for name, expected_digest in read(candidate_path)['files'].items():
            assert sha(candidate_path.parent / name) == expected_digest
        receipt_path = lane / f'features_{role}.receipt.json'
        receipt = read(receipt_path)
        assert receipt['status'] == 'completed' and receipt['returncode'] == 1
        for log in receipt['logs']:
            assert sha(ROOT / log['path']) == log['sha256']
        assert 'Incompleteorderedprefix' in (ROOT / receipt['stderr_path']).read_text()
        assert not (lane / 'features' / role / 'FEATURES.npz').exists()
        assert not (lane / 'features' / role / 'IDENTITY.json').exists()
        assert not (lane / 'results/run001' / f'{role}_OUTPUTS.npz').exists()
        assert not (lane / 'results/run001' / f'{role}_RESULT.json').exists()
        assert not (lane / 'results/run001' / f'{role}_FAMILY_RESULT.json').exists()
        receipts.append(dict(path=str(receipt_path.relative_to(ROOT)), sha256=sha(receipt_path), total_cpu_seconds=receipt['total_cpu_seconds'], returncode=1,
                             candidate_sha256=sha(candidate_path), no_feature_bank=True, no_quality_outputs=True))
    result = dict(schema='hcsn.grid-source-failure.independent-probe-audit.v1', role=role, qa_sha256=sha(qa_path),
        acquisition_sha256=sha(ledger_path), ordinal=ordinal, member=row['name'], speaker=row['speaker'], raw_bytes=len(data), raw_sha256=digest,
        original_crc32=row['crc32'], video_frames=len(times), timestamps=times.tolist(), audio_start=float(audio.get('start_time', 0)), origin=origin,
        accepted_end=origin + 1, ordered=True, complete_registered_prefix=False, actual_frozen_guard_rejects=True,
        attempts=receipts, ffprobe_command=command, ffprobe_stderr=completed.stderr.decode('utf-8'),
        quality_accuracy=None, registered_gate_status='HOLD', valid_subset_qualification=False, replacement_or_padding_performed=False,
        raw_media_opened=True, ffprobe_processes=1, neural_encoder_inference_performed=False, fit_performed=False,
        scope='Registered original bytes independently match CRC/length/acquisition SHA. Probe-only verification; both frozen methods correctly reject insufficient prefix. No subset quality, replacement or protocol repair.', all_blockers_closed=False)
    target = HERE / f'REVIEW_GRID_SOURCE_FAILURE_{role.upper()}.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), role=role, frames=len(times), last_pts=float(times[-1]), guard_rejects=True, gate='HOLD'), sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role', choices=['development', 'confirmation'])
    main(parser.parse_args().role)

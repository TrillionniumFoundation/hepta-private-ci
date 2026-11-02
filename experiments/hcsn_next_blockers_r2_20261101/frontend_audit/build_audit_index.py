"""Finalize this independent frontend audit snapshot without overwriting it."""
import ast
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def main():
    scripts = sorted(HERE.glob('*.py'))
    for path in scripts:
        ast.parse(path.read_text(), filename=str(path))
    reports = sorted(HERE.glob('REVIEW_*.json'))
    for path in reports:
        read(path)
    receipts = []
    for path in sorted(HERE.glob('*.receipt.json')):
        record = read(path)
        assert record['status'] == 'completed' and record['returncode'] == 0 and record['meter_source_unchanged']
        for row in record['logs'] + record['artifacts']:
            assert row['is_file'] and sha(ROOT / row['path']) == row['sha256']
        receipts.append(dict(path=path.name, sha256=sha(path), total_cpu_seconds=record['total_cpu_seconds'], wall_seconds=record['wall_seconds'],
                             cpu_scope='Independent direct-child envelopes; these do not contain scientific fit/feature envelopes.'))
    primary = read(HERE / 'REVIEW_GRID_CONFIRMATION.json')
    family = read(HERE / 'REVIEW_GRID_FAMILY_CONFIRMATION.json')
    assert not primary['registered_gate_recomputed'] and not family['any_candidate_family_gate']
    assert read(HERE / 'REVIEW_GRID_SOURCE_INVENTORY_DEVELOPMENT.json')['registered_gate_status'] == 'HOLD'
    assert read(HERE / 'REVIEW_GRID_SOURCE_INVENTORY_CONFIRMATION.json')['qualified_source_clips'] == 128
    entries = []
    for path in sorted(HERE.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.name != 'AUDIT_INDEX.json':
            entries.append(dict(path=str(path.relative_to(HERE)), bytes=path.stat().st_size, sha256=sha(path)))
    result = dict(schema='hcsn.frontend.independent-audit-index.v1', artifacts=entries, artifact_count=len(entries), report_count=len(reports),
        python_files_AST_checked=len(scripts), audit_consistency_checks_completed=True, all_blockers_closed=False,
        quality_summary=dict(CREMA_raw_video=28/72, CREMA_pretrained_video=39/72, CREMA_pretrained_audio=69/72,
            CREMA_joint_gate=False, GRID_development_source='61/64 eligible; both whole-role HOLD; model metrics absent',
            GRID_confirmation_source='128/128 eligible, same four registered actors', GRID_primary_confirmation_gate=False,
            GRID_temporal_family_confirmation_gate=False, GRID_primary_video=80/128, GRID_temporal_video=76/128),
        review_resolution_chain=dict(original_no_B_frame_profile='Archived original failure; REVIEW_REPAIR explicitly qualifies offline presentation-prefix only.',
            GRID_prefix_entrypoint='REVIEW_GRID_V2:41 synthetic guards; qualified data_v2 checks source/member/role/acquisition SHA before decoding.',
            GRID_outer_fold_retention='Historical REVIEW_GRID_JOINT_SOURCE issue closed by REVIEW_GRID_RETENTION; all nine checkpoints retained before fit.',
            GRID_stale_V2_payload_count='Original source freeze preserved; primary PROVENANCE_ADDENDUM records unknown count at V2 freeze.',
            CREMA_inference_field='REVIEW_TERMINOLOGY_ADDENDUM: no neural encoder rerun; frozen classifier/relation heads were recomputed.'),
        measured_review_receipts=receipts, measured_review_cpu_sum_seconds=sum(row['total_cpu_seconds'] for row in receipts),
        total_review_cpu_seconds=None, total_review_cpu_reason='Earlier independent checks and audit-tool development were not under complete-child meters; recorded envelopes are not the full review cost.',
        scope='Audit consistency does not imply quality-gate success. Scientific source/checkpoints were not changed; no fitting or new neural-encoder execution was performed by this reviewer. Initial training and one failed-development raw metadata probe used ffprobe; all quality recomputation used cached data.')
    target = HERE / 'AUDIT_INDEX.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), artifacts=len(entries), reports=len(reports), scripts=len(scripts),
                          measured_review_cpu_sum_seconds=result['measured_review_cpu_sum_seconds']), sort_keys=True))


if __name__ == '__main__':
    main()

"""Verify the visual training-only decoder amendment and preserved failure."""
import ast
import difflib
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VISUAL = ROOT / 'experiments/hcsn_video_pretrained_feasibility_r2_20261101'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def main():
    retired = VISUAL / 'retired_no_bframe_profile'
    before, after = (retired / 'encoder.py').read_text(), (VISUAL / 'encoder.py').read_text()
    a, b = ast.parse(before), ast.parse(after)
    # Feature encoding and descriptor math must be exactly unchanged.
    for name in ('load', 'encode', 'descriptor'):
        first = next(n for n in a.body if isinstance(n, ast.FunctionDef) and n.name == name)
        second = next(n for n in b.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert ast.dump(first) == ast.dump(second)
    oldfreeze, newfreeze = read(retired / 'SOURCE_FREEZE.json'), read(VISUAL / 'SOURCE_FREEZE.json')
    for name in ('encoder.py', 'register.py'):
        assert sha(retired / name) == oldfreeze['identity']['source_sha256'][name]
        assert sha(VISUAL / name) == newfreeze['identity']['source_sha256'][name]
    assert sha(retired / 'PROTOCOL.json') == oldfreeze['identity']['protocol_sha256']
    assert sha(VISUAL / 'PROTOCOL.json') == newfreeze['identity']['protocol_sha256']
    assert sha(VISUAL / 'study.py') == oldfreeze['identity']['source_sha256']['study.py'] == newfreeze['identity']['source_sha256']['study.py']
    for name in ('dependencies', 'checkpoint_receipt_sha256', 'source_identity_sha256', 'cohort_sha256', 'inherited_source_sha256'):
        assert oldfreeze['identity'][name] == newfreeze['identity'][name]
    for freeze in (oldfreeze, newfreeze):
        assert not freeze['newheadfit_started'] and not freeze['validation_loaded']
    failed = read(VISUAL / 'extract_train001.receipt.json')
    assert failed['status'] == 'completed' and failed['returncode'] == 1
    assert failed['total_cpu_seconds'] == 68.709255
    assert failed['wall_seconds'] == 68.89999178900325
    assert 'Future-reordered frames are outside this registered prefix profile' in (VISUAL / 'extract_train001.stderr.log').read_text()
    assert 'encoded": 144' in (VISUAL / 'extract_train001.stdout.log').read_text()
    for row in failed['logs']:
        assert sha(ROOT / row['path']) == row['sha256']
    protocol = read(VISUAL / 'PROTOCOL.json')
    assert 'offline' in protocol['observations'].lower() and 'live' in protocol['observations'].lower()
    assert 'not bounded or instrumented' in after
    result = dict(schema='hcsn.visual.decoder-amendment.independent-review.v1',
        checks=dict(retired_source_hashes=True, current_source_hashes=True, same_checkpoint=True, same_descriptor_and_encoder_math=True,
            unchanged_study=True, same_inherited_audio_text=True, failed_attempt_receipt_and_logs_preserved=True, no_fit_or_heldout_at_registration=True),
        source_freeze_sha256=sha(VISUAL / 'SOURCE_FREEZE.json'), protocol_sha256=sha(VISUAL / 'PROTOCOL.json'),
        failed_attempt=dict(total_cpu_seconds=failed['total_cpu_seconds'], wall_seconds=failed['wall_seconds'], returncode=1),
        repair_diff=''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile='retired/encoder.py', tofile='encoder.py')),
        qualification='Offline presentation-prefix only; compressed-reference lookahead is uninstrumented and live causal 1s remains unqualified.',
        fit_performed=False, held_media_decoded=False, all_blockers_closed=False)
    target = HERE / 'REVIEW_REPAIR.json'
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps(dict(path=str(target.relative_to(ROOT)), sha256=sha(target), checks=result['checks']), sort_keys=True))


if __name__ == '__main__':
    main()

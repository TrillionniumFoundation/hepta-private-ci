"""Adversarial checks against an ACTUALLY executed E2 budget sweep.

Unlike the ordinary unit tests, these need real physical producer/cell inputs.
Do not count them as passed if the artifacts are unavailable.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from safetensors.numpy import load, save

from experiments.shared_stem_cell.e2_budget_review import review_sweep
from experiments.shared_stem_cell.preflight_review import PreflightError
from experiments.shared_stem_cell.wire import canonical, sha


def expect_reject(fn, expected):
    try:
        fn()
    except (PreflightError, ValueError, KeyError) as exc:
        if expected not in str(exc):
            raise AssertionError(f'wrong rejection: {type(exc).__name__}: {exc}') from exc
    else:
        raise AssertionError(f'false success: {expected}')


def exercise(manifest: Path, producer: Path, report_sha256: str, sweep: Path) -> dict:
    base = review_sweep(manifest, producer, report_sha256, sweep)
    if base['physical_head_checkpoint_count'] != 60 or base['independently_replayed_prediction_vectors'] != 1920:
        raise AssertionError('full real execution is required for integrity tests')
    passes = 0
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / 'sweep'
        shutil.copytree(sweep, target, symlinks=False)
        def rerun():
            return review_sweep(manifest, producer, report_sha256, target)
        path = target / 'predictions.json'
        receipt = target / 'run.json'
        observed = json.loads(path.read_bytes())
        record = observed['predictions'].pop()
        path.write_bytes(canonical(observed))
        data = json.loads(receipt.read_bytes())
        original_receipt = json.loads((sweep / 'run.json').read_bytes())
        data['predictions_sha256'] = sha(path.read_bytes())
        receipt.write_bytes(canonical(data))
        expect_reject(rerun, 'E2 case pairing drift')
        passes += 1
        observed['predictions'].append(record)
        path.write_bytes(canonical(observed))
        data['predictions_sha256'] = sha(path.read_bytes())
        receipt.write_bytes(canonical(data))
        # Redirection cannot be smuggled through valid looking hashes.
        data['artifacts'][0]['checkpoints']['trained']['path'] = '../../unexpected.safetensors'
        receipt.write_bytes(canonical(data))
        expect_reject(rerun, 'path cannot redirect')
        passes += 1
        data['artifacts'][0]['checkpoints']['trained']['path'] = 'heads/seed-11/budget-2048/cell-0/trained.safetensors'
        # Mutation of optimizer weights with hashes repaired must fail independent arithmetic.
        target_rel = data['artifacts'][0]['checkpoints']['trained']['path']
        weights_path = target / target_rel
        tensors = load(weights_path.read_bytes())
        tensors['up.bias'] = tensors['up.bias'].copy()
        tensors['up.bias'][:] = [100., 0., 0., -100.]
        raw = save(tensors)
        weights_path.write_bytes(raw)
        data['artifacts'][0]['checkpoints']['trained']['sha256'] = sha(raw)
        data['artifacts'][0]['checkpoints']['trained']['file_bytes'] = len(raw)
        receipt.write_bytes(canonical(data))
        expect_reject(rerun, 'Head checkpoint/prediction inconsistency')
        passes += 1
        # Restore genuine checkpoint and its bound SHA for the next distinct test.
        shutil.copyfile(sweep / target_rel, weights_path)
        data['artifacts'][0]['checkpoints']['trained'] = original_receipt['artifacts'][0]['checkpoints']['trained'].copy()
        receipt.write_bytes(canonical(data))
        data['artifacts'][0]['minibatch_sha256'] = 'f'*64
        receipt.write_bytes(canonical(data))
        expect_reject(rerun, 'unequal training sample streams')
        passes += 1
        data['artifacts'][0]['minibatch_sha256'] = original_receipt['artifacts'][0]['minibatch_sha256']
        data['production_accepted'] = True
        receipt.write_bytes(canonical(data))
        expect_reject(rerun, 'E2 evidence identity or authority drift')
        passes += 1
    return {'actual_source_e2_checkpoints': 60, 'reviewed_vector_count': 1920,
            'adversarial_negative_checks': passes, 'production_accepted': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest',type=Path,required=True)
    ap.add_argument('--producer',type=Path,required=True)
    ap.add_argument('--report-sha256',required=True)
    ap.add_argument('--sweep',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    q=ap.parse_args()
    from experiments.shared_stem_cell.wire import write_once
    write_once(q.output,exercise(q.manifest,q.producer,q.report_sha256,q.sweep))


if __name__=='__main__':main()

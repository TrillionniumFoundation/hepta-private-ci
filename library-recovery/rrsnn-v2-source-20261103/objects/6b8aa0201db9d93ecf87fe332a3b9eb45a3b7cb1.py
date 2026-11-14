"""Run an offline Hepta V1 input and candidate latent conversion check.

Example (the supplied tick may be a reconstructed upstream unit fixture):
  python contract_check.py --tick-input tick.json --latent latent.npy \
      --candidate-artifact candidate.pt --output-prefix candidate_shadow

This command never invokes a Hepta owner, signs a receipt, or publishes state.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from shadow_contract import Q24, decode_tick_input, make_shadow_proposal


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_latent(path, row_index):
    path = Path(path)
    if path.suffix == '.npy':
        values = np.load(path, allow_pickle=False)
    else:
        values = np.asarray(json.loads(path.read_text()))
    if values.ndim == 2:
        if row_index is None:
            raise ValueError('two-dimensional latent requires explicit --row-index')
        if not 0 <= row_index < values.shape[0]:
            raise ValueError('row index out of bounds')
        values = values[row_index]
    elif row_index is not None:
        raise ValueError('--row-index applies only to a two-dimensional latent')
    if values.ndim != 1:
        raise ValueError('latent must be a vector, or a matrix with a selected row')
    if values.dtype.kind not in 'fiu':
        raise ValueError('latent must contain real numerical values')
    return values.astype(np.float64)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tick-input', required=True, type=Path)
    parser.add_argument('--latent', required=True, type=Path)
    parser.add_argument('--row-index', type=int)
    parser.add_argument('--candidate-artifact', required=True, type=Path)
    parser.add_argument('--output-prefix', required=True, type=Path)
    args = parser.parse_args()

    tick = decode_tick_input(args.tick_input.read_bytes())
    latent = load_latent(args.latent, args.row_index)
    artifact_sha = sha256_file(args.candidate_artifact)
    proposal = make_shadow_proposal(
        tick, latent, artifact_sha, output_width=int(latent.size),
    )
    restored = np.asarray(proposal['candidateValuesQ24'], dtype=np.float64) / Q24
    error = np.abs(restored - latent)
    report = {
        'schema': 'rrsnn.offline-contract-check.v1',
        'sourceCommit': proposal['sourceCommit'],
        'tickInputSha256': sha256_file(args.tick_input),
        'latentInputSha256': sha256_file(args.latent),
        'candidateArtifactSha256': artifact_sha,
        'candidateArtifactRole': 'caller-supplied bytes; model identity not authenticated',
        'rowIndex': args.row_index,
        'width': int(latent.size),
        'maximumAbsoluteConversionError': float(error.max()),
        'meanAbsoluteConversionError': float(error.mean()),
        'halfQuantum': 0.5 / Q24,
        'withinHalfQuantum': bool(np.all(error <= 0.5 / Q24)),
        'latentMinimum': float(latent.min()),
        'latentMaximum': float(latent.max()),
        'clippingPerformed': False,
        'officialOwnerExecuted': False,
        'realEncoderForwardVerified': False,
        'officialRuntimeReceiptIssued': False,
        'checkpointPublished': False,
        'productionActivationAllowed': False,
        'interpretation': 'Numerical and JSON input compatibility only; not runtime integration.',
    }
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    proposal_path = Path(str(args.output_prefix) + '_proposal.json')
    report_path = Path(str(args.output_prefix) + '_report.json')
    proposal_path.write_text(json.dumps(proposal, indent=2) + '\n')
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'proposal': str(proposal_path), 'report': str(report_path), **report}, indent=2))


if __name__ == '__main__':
    main()

"""Acquire the one declared follow-up model with the existing metered downloader."""
import argparse
import json
from pathlib import Path

from ..ndu_frozen_lm_pilot_20261106.acquire import download, measured, sha

ROOT = Path(__file__).resolve().parent


def acquire(destination, ledger):
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'model_manifest.json').read_text())
    directory = destination / 'model'
    directory.mkdir(exist_ok=True)
    files = []
    for row in manifest['files']:
        files.append(measured(ledger, 'download-' + row['name'],
                     lambda r=row: download(manifest, r, directory)))
    with (destination / 'materialized-model.json').open('x') as stream:
        json.dump({'model_id': manifest['model_id'], 'revision': manifest['revision'],
                   'files': files, 'manifest_sha256': sha(ROOT / 'model_manifest.json')},
                  stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    args = parser.parse_args()
    acquire(args.destination, args.ledger)

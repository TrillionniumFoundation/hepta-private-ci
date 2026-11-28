"""Verify the three intentional large checkpoints against exact registered digests."""
import argparse
import hashlib
from pathlib import Path

ENTRIES = {
    'results/hx-137-best.pt': (4625574, '01aa522dd32ed89a21c63b67eee115cdaa3cfed03b30e702d76d7f9e1b71b86b'),
    'curved/results/hxcurve-137-best.pt': (4627047, '1f8143d38d59637a587c55a0f56d16e57cc00e18c32f653ae3156d3a55eb068b'),
    'direct/direct-137-init71.pt': (4626828, '01ccd521cb10d2a2d3a3354315bcb5730bb425957e2970404ae7e3da6938de83')
}


def verify(root):
    for name,(expected_size,expected_sha) in ENTRIES.items():
        path=root/name
        with path.open('rb') as fp:
            digest=hashlib.sha256()
            for chunk in iter(lambda: fp.read(1024*1024), b''):
                digest.update(chunk)
            sha=digest.hexdigest()
        if path.stat().st_size!=expected_size or sha!=expected_sha:
            raise ValueError(f'Endpoint identity mismatch: {name}')
        print(f'{sha}  {name}')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',nargs='?',type=Path,default=Path(__file__).resolve().parents[1])
    verify(p.parse_args().root)

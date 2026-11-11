"""Explicit *prospective* C2 program manifest freezer, not a run authorization.

Freeze only present source/config bytes. Never synthesize missing policies,
contracts, parents, a decision, checkpoints or experiment outcomes. The
original C2 job and outputs are never read or modified by this utility.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from c2_boundary import Ineligible, require

# CLI execution does not first import c2_io (unlike the test/runner process).
# Locate only the intended sibling durable implementation, not an ambient name.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'recovery_v1'))
from c2_durable import EvidenceError, identity as durable_identity, publish_once

REQUIRED_FILES = (
    'c2_runner.py', 'c2_io.py', 'c2_recording.py',
    'c2_boundary.py', 'c2_controller.py', 'POSTERIOR-POLICY.json',
    'OPTIMIZATION-POSTERIOR-POLICY-v2.json', 'CONTRACT.json',
)
DURABLE_DEPENDENCY = 'recovery_v1/c2_durable.py'


def _regular_identity(path: Path):
    require(path.is_file() and not path.is_symlink() and not path.parent.is_symlink(),
            'source is absent or an unsafe symlink: ' + str(path))
    try:
        before = durable_identity(path)
        require(durable_identity(path) == before,
                'source changed while freezing: ' + str(path))
        return before
    except EvidenceError as exc:
        raise Ineligible('unqualified source: ' + str(path)) from exc


def collect_manifest(root: Path) -> dict:
    """Read-only, identity-only preflight. Absence remains a failed preflight."""
    root = Path(root)
    require(root.is_dir() and not root.is_symlink()
            and not root.parent.is_symlink(),
            'unsafe or missing prospective C2 source directory')
    files = {name: _regular_identity(root / name) for name in REQUIRED_FILES}
    sibling = root.parent / 'recovery_v1'
    require(sibling.is_dir() and not sibling.is_symlink(),
            'durable publisher sibling directory is absent or symlinked')
    dep = _regular_identity(sibling / 'c2_durable.py')
    return {
        'schema': 'hcsn-c2-successor-source-manifest-v1',
        'scientific_admission': 'HOLD_NO_GO',
        'execution_authorized': False,
        'files': files,
        'dependencies': {DURABLE_DEPENDENCY: dep},
    }


def publish_manifest(root: Path) -> tuple[dict, dict]:
    """Explicit create-once candidate file. Never replace any published bytes."""
    root = Path(root)
    manifest = collect_manifest(root)
    raw = (json.dumps(manifest, sort_keys=True, indent=2,
                      ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')

    def write(stream):
        stream.write(raw)

    receipt = publish_once(root / 'PROGRAM-MANIFEST.json', write,
                           lambda path: path.read_bytes() == raw,
                           max_bytes=65536)
    return manifest, receipt


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-dir', type=Path, default=Path(__file__).resolve().parent)
    p.add_argument('--write', action='store_true',
                   help='explicitly create PROGRAM-MANIFEST.json once; no training')
    a = p.parse_args()
    try:
        if a.write:
            manifest, receipt = publish_manifest(a.candidate_dir)
            print(json.dumps({'manifest': manifest, 'receipt': receipt}, sort_keys=True))
        else:
            print(json.dumps(collect_manifest(a.candidate_dir), sort_keys=True))
        return 0
    except (Ineligible, EvidenceError, FileExistsError, OSError) as e:
        print(json.dumps({'status': 'HOLD_NO_GO', 'manifest_published': False,
                          'error_type': type(e).__name__, 'detail': str(e)}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

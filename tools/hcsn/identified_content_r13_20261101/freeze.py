"""Freeze actual source, selected fits, corpus and native library before confirmation."""

import hashlib
import json
from pathlib import Path

from launch import ROOT, identity


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(folder):
    folder = Path(folder)
    protocol = json.loads((ROOT/'PROTOCOL.json').read_text())
    current = identity()
    choices, fits, receipts = {}, {}, {}
    for seed in protocol['seeds']:
        losses = []
        for core in protocol['cores']:
            path = folder/'fits'/f'{seed}_{core}.json'
            receipt_path = folder/'receipts'/f'{seed}_{core}.json'
            fit, receipt = json.loads(path.read_text()), json.loads(receipt_path.read_text())
            if receipt['returncode'] or not receipt['source_unchanged'] or receipt['source_before'] != current:
                raise ValueError(f'Fit/source identity mismatch: {path}')
            if fit['frontend_sha256'] != digest(folder/'frontend.json'):
                raise ValueError('Frontend changed during fits')
            fits[str(path.relative_to(folder))] = digest(path)
            receipts[str(receipt_path.relative_to(folder))] = digest(receipt_path)
            if core != 'hx_distribution':
                losses.append((fit['selected_validation']['posterior_ce'], core))
        choices[str(seed)] = min(losses)[1]
    sources = [ROOT.parent/name for name in current]
    sources += sorted(ROOT.glob('*.py'))
    sources += [ROOT/'IMPLEMENTATION.md', ROOT/'data/sms_spam_collection.zip']
    sources += sorted((ROOT/'native').glob('*.rs'))
    sources += sorted((ROOT/'native').glob('*.py'))
    payload = {'schema': 'hcsn-r13-before-confirmation-v1',
        'protocol_commit': '168ed5ea20c98a9f313d2e1b5b41bd26d284c958',
        'source_sha256': {str(p.relative_to(ROOT.parent)): digest(p) for p in sorted(set(sources))},
        'fit_sha256': {**fits, **receipts, 'frontend.json': digest(folder/'frontend.json'),
                       'frontend_receipt.json': digest(folder/'frontend_receipt.json')},
        'native_library_sha256': digest(ROOT/'native/evidence/build/libhcsn_prepared.so'),
        'ordinary_choices': choices, 'confirmation_encoded_or_scored': False,
        'scope': 'Confirmation raw corpus already loaded for deterministic partitioning; no heldout text evidence, outcomes or frequency estimates used in fitting.'}
    target = folder/'FREEZE.json'
    if target.exists():
        raise FileExistsError('Never overwrite a freeze')
    target.write_text(json.dumps(payload, indent=2)+'\n')
    return target


if __name__ == '__main__':
    print(freeze(ROOT/'evidence'))

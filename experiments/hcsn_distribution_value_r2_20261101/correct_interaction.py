"""Record-only correction: use the registered paired interaction parentheses.

Preserves frozen scientific source and original SUMMARY. No model or test rerun.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results/run002'


def main():
    original_path = OUT / 'SUMMARY.json'
    summary = json.loads(original_path.read_text())
    original_interaction = summary['main_2x2']['(D-C)-(B-A)']
    values = np.zeros((3, 6, 8, 4, 64))
    fits = json.loads((OUT / 'ALL_CANDIDATES.json').read_text())['fits']
    files = 0
    for si, fit in enumerate(fits):
        for ci in range(6):
            for cue in range(8):
                for price in range(4):
                    with np.load(OUT / 'confirmation' / f"fit{fit['seed']}_context{ci}_cue{cue}_price{price}.npz", allow_pickle=False) as raw:
                        # These equalities are measured on saved actual outcomes.
                        assert np.array_equal(raw['utility'][0], raw['utility'][2])
                        assert np.array_equal(raw['utility'][1], raw['utility'][3])
                        assert np.array_equal(raw['actions'][0], raw['actions'][2])
                        assert np.array_equal(raw['actions'][1], raw['actions'][3])
                        values[si, ci, cue, price] = (raw['utility'][3] - raw['utility'][2]) - (raw['utility'][1] - raw['utility'][0])
                    files += 1
    assert np.all(values == 0)
    corrected = dict(mean=0., per_fit=values.mean(axis=(1, 2, 3, 4)).tolist(), per_context=values.mean(axis=(0, 2, 3, 4)).tolist(), conditional_context_interval=[0., 0.], strictly_positive_gate=False)
    summary['main_2x2']['(D-C)-(B-A)'] = corrected
    receipt = dict(schema='hcsn-r2-paired-arithmetic-correction.v1', source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        original_summary_sha256=hashlib.sha256(original_path.read_bytes()).hexdigest(), original_interaction=original_interaction,
        corrected_interaction=corrected, paired_files_checked=files, exact_zero_interaction=True,
        reason='Frozen analyzer evaluated D-C-B+A sequentially. Registered (D-C)-(B-A) must subtract paired differences; ordinary/analytic saved outcomes and actions are exactly equal. The spurious positive ~5e-19 flag is invalid.',
        scope='No source/protocol/model/action/raw test record changed. This is deterministic reanalysis of the same paired outcomes, not a new confirmation. Main D-B and association gates unchanged.')
    summary['interaction_arithmetic_correction'] = receipt
    with (OUT / 'CORRECTED_SUMMARY.json').open('x') as stream:
        json.dump(summary, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    with (OUT / 'INTERACTION_CORRECTION.json').open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()

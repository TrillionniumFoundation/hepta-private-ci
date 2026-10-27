"""Prespecified source-cluster comparisons after actual transcript readback."""

import numpy as np


NAMES = ("conditional_nll", "posterior_nll", "accuracy")


def grouped(metrics, rows):
    speakers = sorted({row['speaker'] for row in rows})
    by_speaker = np.array([metrics[[row['speaker'] == speaker for row in rows]].mean(0)
                           for speaker in speakers])
    return {'by_speaker': {speaker: dict(zip(NAMES, values.tolist()))
                           for speaker, values in zip(speakers, by_speaker)},
            'means': dict(zip(NAMES, by_speaker.mean(0).tolist())),
            'source_count': len(speakers), 'derived_rows': len(rows)}


def difference(left, right):
    if set(left['by_speaker']) != set(right['by_speaker']):
        raise ValueError('Source-paired comparison requires the same speakers')
    delta = np.array([[left['by_speaker'][s][name]-right['by_speaker'][s][name]
                       for name in NAMES] for s in sorted(left['by_speaker'])])
    choices = np.random.default_rng(272033).integers(len(delta), size=(20000, len(delta)))
    samples = delta[choices].mean(1)
    result = {name: {'difference': float(delta[:, index].mean()),
                     'ci97_5': np.percentile(samples[:, index], [1.25, 98.75]).tolist()}
              for index, name in enumerate(NAMES)}
    result['conditional_likelihood_gain'] = result['conditional_nll']['ci97_5'][1] < 0
    result['actual_output_gain'] = result['accuracy']['ci97_5'][0] > 0
    result['both_gates_passed'] = result['conditional_likelihood_gain'] and result['actual_output_gain']
    return result

"""Report sensitivity to omitting each whole production from the fixed third cohort."""
import json
from pathlib import Path
from statistics import fmean
from zipfile import ZipFile


def evaluate(scores):
    cells = scores['audio_guitar_gallery_piano_low_margin']['by_source']
    qvi = scores['three_seed_comparisons']['bp']
    comparisons = [qvi['qvi_minus_fixed']['by_source'], qvi['qvi_minus_learned']['by_source']]
    assert len(cells) == 12 and all(set(values) == set(cells) for values in comparisons)
    immediate = scores['immediate_comparators']['svd']
    waits = scores['wait_hindsight']['by_source']
    cases = {}
    for omit in sorted(cells):
        kept = [key for key in cells if key != omit]
        purchases = sum(cells[key]['windows'] for key in kept)
        rescues = sum(cells[key]['rescues'] for key in kept)
        harms = sum(cells[key]['harms'] for key in kept)
        net = (rescues - harms) / purchases - 0.30
        cases[omit] = {
            'recordings': len(kept),
            'qvi_minus_fixed_learned': [fmean(d[key] for key in kept) for d in comparisons],
            'mean_waiting_opportunity': fmean(waits[key] for key in kept),
            'subgroup_purchases': purchases,
            'subgroup_rescued': rescues,
            'subgroup_harmed': harms,
            'subgroup_net_per_buy': net,
            'svd_gain_vs_free': fmean(immediate['minus_free']['by_source'][key] for key in kept),
            'svd_gain_vs_paid': fmean(immediate['minus_paid']['by_source'][key] for key in kept),
            'svd_worst_vs_free': min(immediate['minus_free']['by_source'][key] for key in kept),
        }
    return cases


if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    with ZipFile(here / 'independent-scores.zip') as archive:
        scores = json.loads(archive.read('scores.json'))
    print(json.dumps(evaluate(scores), indent=2, sort_keys=True))

"""Fit only historical sources and seal all choices before qualification."""

import json
from pathlib import Path
import shutil
import time

import numpy as np

from .data import ROOT, SOURCE, CHECKPOINT, digest, make_capture_registry, write
from .models import STRENGTHS, fit_pair, fit_prior, fit_rank, pair_cases, rank_views, score


AREA = Path(__file__).parent
OLD = Path('/workspace/scratch/95988d8d3ab1/ndu-continuation-evidence/study-002')
RUN = ROOT/'qualification-001'


def select():
    RUN.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    registry_path = make_capture_registry()
    sources = {path.name: digest(path) for path in AREA.glob('*.py')}
    sources['PROTOCOL.json'] = digest(AREA/'PROTOCOL.json')
    snapshot = RUN/'executed_source'
    snapshot.mkdir()
    for name in sources:
        shutil.copyfile(AREA/name, snapshot/name)
    shutil.copyfile(AREA/'PROTOCOL.json', RUN/'PROTOCOL.json')
    input_names = ('observations_fit.json', 'observations_validation.json',
                   'prior_fit_targets.json', 'prior_validation_targets.json')
    write(RUN/'FIT_STARTED.json', {'time_ns': time.time_ns(), 'sources': sources,
        'inputs': {name: digest(OLD/name) for name in input_names},
        'new_source_manifest_sha256': digest(SOURCE/'SOURCE_MANIFEST.json'),
        'new_capture_registry_sha256': digest(registry_path),
        'observer_sha256': digest(CHECKPOINT), 'new_test_features_read': False})
    for name in input_names:
        shutil.copyfile(OLD/name, RUN/name)
    shutil.copyfile(CHECKPOINT, RUN/'observer.pt')
    fitting = json.loads((OLD/input_names[0]).read_text())
    validation = json.loads((OLD/input_names[1]).read_text())
    pairs = pair_cases(validation)
    values, targets = [r['values'] for r in pairs], [r['target'] for r in pairs]
    candidates, selected = [], {}

    def evaluate(law, observations, truth):
        return score(law, observations, truth)[0].mean(0).tolist()

    marginal_candidates = []
    for margin in STRENGTHS:
        metrics = evaluate(fit_pair(fitting, 'paired', margin, None), values, targets)
        marginal_candidates.append({'margin': margin, 'metrics': metrics})
    margin = min(marginal_candidates, key=lambda x: x['metrics'][0])['margin']
    for family in ('independent', 'paired', 'speaker_mixture'):
        choices = [None] if family == 'independent' else [None, *STRENGTHS]
        options = []
        for coupling in choices:
            law = fit_pair(fitting, family, margin, coupling)
            metrics = evaluate(law, values, targets)
            row = {'study': 'distinct', 'family': family, 'margin': margin,
                   'coupling': coupling, 'metrics': metrics}
            candidates.append(row)
            options.append((row, law))
        best = min(options, key=lambda item: (round(item[0]['metrics'][0], 12),
                                               item[0]['coupling'] is not None))
        selected['pair_'+family] = best[0]
        write(RUN/f'law_pair_{family}.json', best[1].export())
    rank_values, rank_targets = [rank_views(r) for r in validation], [r['target'] for r in validation]
    rank_margin_candidates = []
    for strength in STRENGTHS:
        metrics = evaluate(fit_rank(fitting, strength, None), rank_values, rank_targets)
        rank_margin_candidates.append({'margin': strength, 'metrics': metrics})
    margin = min(rank_margin_candidates, key=lambda x: x['metrics'][0])['margin']
    options = []
    for coupling in [None, *STRENGTHS]:
        law = fit_rank(fitting, margin, coupling)
        row = {'study': 'same_event', 'family': 'rank', 'margin': margin, 'coupling': coupling,
               'metrics': evaluate(law, rank_values, rank_targets)}
        candidates.append(row)
        options.append((row, law))
    selected['rank_baseline'] = options[0][0]
    write(RUN/'law_rank_baseline.json', options[0][1].export())
    best = min(options, key=lambda item: (round(item[0]['metrics'][0], 12), item[0]['coupling'] is not None))
    selected['rank_joint'] = best[0]
    write(RUN/'law_rank_joint.json', best[1].export())
    prior_fit = json.loads((OLD/input_names[2]).read_text())
    prior_validation = json.loads((OLD/input_names[3]).read_text())
    priors, prior_candidates = {}, []
    for cue in ('uniform', 'plus1', 'plus3', 'plus7'):
        truth = [r['target'] for r in prior_validation if r['cue'] == cue]
        priors[cue] = {}
        for family in ('joint', 'factorized'):
            choices = [(float(-np.log((p := fit_prior(prior_fit, cue, family, s))[truth]).mean()), s, p)
                       for s in STRENGTHS]
            best = min(choices, key=lambda item: item[0])
            priors[cue][family] = best[2].tolist()
            prior_candidates += [{'cue': cue, 'family': family, 'strength': s, 'nll': nll}
                                 for nll, s, _ in choices]
    prior_likelihood = min(('pair_independent', 'pair_paired', 'pair_speaker_mixture'),
                           key=lambda key: selected[key]['metrics'][0])
    write(RUN/'PRIORS.json', priors)
    write(RUN/'SELECTION.json', {'selected': selected, 'candidates': candidates,
          'pair_marginal_candidates': marginal_candidates, 'rank_marginal_candidates': rank_margin_candidates,
          'prior_candidates': prior_candidates, 'prior_likelihood': prior_likelihood,
          'metrics_order': ['conditional_nll', 'posterior_nll', 'accuracy'],
          'fit_wall_seconds': time.perf_counter()-wall, 'fit_cpu_seconds': time.process_time()-cpu})
    files = {p.name: digest(p) for p in RUN.iterdir() if p.is_file()}
    write(RUN/'MODELS_FROZEN.json', {'time_ns': time.time_ns(), 'files': files,
                                  'source_files': sources, 'new_test_model_features_computed': False})
    print(json.dumps({'selected': selected, 'frozen_sha256': digest(RUN/'MODELS_FROZEN.json')}))


if __name__ == '__main__':
    select()

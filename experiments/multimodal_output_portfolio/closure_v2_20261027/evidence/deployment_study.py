"""Historical fit/validation evidence for protected coupling deployment."""

import gzip
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np

from .blocks import JointLaw
from .data import ROOT, digest, write
from .deployment_selection import decisions, select, summarize
from .models import STRENGTHS, capture, fit_pair, fit_rank, pair_cases, rank_views, score


OLD = Path('/workspace/scratch/95988d8d3ab1/ndu-continuation-evidence/study-002')
DEST = ROOT/'decision-development-001'


def public_predict(law, public_rows, prior):
    if any(set(row) != {'sample_id', 'events', 'values'} for row in public_rows):
        raise ValueError('Only public evidence may enter the deployment predictor')
    prior = np.asarray(prior, dtype=float)
    if not law.known[prior > 0].all() or abs(prior.sum()-1) > 1e-12:
        raise ValueError('A separately supported target prior is required')
    values = np.array([row['values'] for row in public_rows], dtype=int)
    likelihood = law.table[values[:, 0], values[:, 1]]
    posterior = likelihood*prior
    if np.any(posterior.sum(1) <= 0):
        raise ValueError('Observation is outside the frozen support')
    posterior /= posterior.sum(1, keepdims=True)
    return likelihood, posterior


def render(action, size):
    if action == size:
        return 'uncertain'
    return str(action) if size == 10 else f'{action//10} {action % 10}'


def parse(text, size):
    if text == 'uncertain':
        return size
    parts = text.split(' ')
    if (len(parts) != (1 if size == 10 else 2)
            or any(part not in tuple(map(str, range(10))) for part in parts)):
        raise ValueError('Delivered validation text is outside the declared vocabulary')
    return int(parts[0]) if size == 10 else 10*int(parts[0])+int(parts[1])


def trial(name, law, rows):
    wall, cpu = time.perf_counter(), time.process_time()
    model_path = DEST/f'law-{name}.json'
    write(model_path, law.export())
    restored = JointLaw.load(json.loads(model_path.read_text()))
    public = [{key: row[key] for key in ('sample_id', 'events', 'values')} for row in rows]
    size = restored.table.shape[-1]
    likelihood, posterior = public_predict(restored, public, np.full(size, 1/size))
    actions = decisions(posterior)
    path = DEST/f'DELIVERED-{name}.jsonl.gz'
    with gzip.open(path, 'xt', encoding='utf-8') as stream:
        for row, labels in zip(public, zip(*actions)):
            output = {'sample_id': row['sample_id'], 'map_text': render(int(labels[0]), size),
                      'mean_text': render(int(labels[1]), size), 'risk_text': render(int(labels[2]), size)}
            stream.write(json.dumps(output, sort_keys=True)+'\n')
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        delivered = [json.loads(line) for line in stream]
    if [record['sample_id'] for record in delivered] != [row['sample_id'] for row in rows]:
        raise ValueError('Actual validation output panel differs')
    actual = [np.array([parse(record[key], size) for record in delivered])
              for key in ('map_text', 'mean_text', 'risk_text')]
    summary = summarize(name, likelihood, posterior, [r['target'] for r in rows],
                        [r['speaker'] for r in rows], [r['sample_id'] for r in rows], actual)
    summary['custody'] = {'law_sha256': digest(model_path), 'delivery_sha256': digest(path),
        'public_evidence_sha256': hashlib.sha256(json.dumps(public, separators=(',', ':')).encode()).hexdigest(),
        'prior': 'separately specified uniform task prior', 'actual_bundles': len(delivered),
        'actual_text_decisions': 3*len(delivered), 'cpu_seconds': time.process_time()-cpu,
        'wall_seconds': time.perf_counter()-wall}
    write(DEST/f'TRIAL-{name}.json', summary)
    return summary


def main():
    DEST.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    names = ('observations_fit.json', 'observations_validation.json')
    fitting, validation = [json.loads((OLD/name).read_text()) for name in names]
    if ({r['speaker'] for r in fitting} != {f'{n:02}' for n in range(1, 9)}
            or {r['speaker'] for r in validation} != {f'{n:02}' for n in range(9, 13)}):
        raise ValueError('Protected development cannot consume a qualification source')
    protocol = {'schema': 'hepta.ndu.evidence.deployment-selection-development.v1',
        'created_ns': time.time_ns(), 'fit_speakers': sorted({r['speaker'] for r in fitting}),
        'validation_speakers': sorted({r['speaker'] for r in validation}),
        'inputs': {name: digest(OLD/name) for name in names}, 'source_paths_opened': [str(OLD/name) for name in names],
        'new_qualification_sources_scored': 0,
        'context': 'A code/selection repair after the immutable speakers21-32 negative qualification; historical development only, not a replacement test.',
        'marginal_selection': 'Same pooled conditional-likelihood selection as before; every coupling candidate has the identical marginals.',
        'coupling_candidates': list(STRENGTHS), 'baseline_always_eligible': True,
        'gate': 'Paired four-source bootstrap97.5% upper posterior-NLL delta<=0 and lower MAP, mean-utility, risk-CE deltas>=0. Conditional likelihood is reported separately and cannot suffice for promotion.',
        'tie_break': 'Highest protected risk CE, lowest proper posterior score, unchanged baseline, candidate name.',
        'bootstrap_seed': 272037, 'bootstrap_samples': 20000,
        'payoffs': {'correct': .99, 'wrong': -.51, 'uncertain': -.003}, 'risk_gamma': 2,
        'source_census': 'Derived pairs are repeated views of four validation speakers; no population or fresh-source claim.'}
    write(DEST/'PROTOCOL.json', protocol)
    snapshot = DEST/'executed_source'
    snapshot.mkdir()
    for name in ('deployment_selection.py', 'deployment_study.py', 'models.py', 'blocks.py', 'data.py'):
        shutil.copyfile(Path(__file__).with_name(name), snapshot/name)
    for name in names:
        shutil.copyfile(OLD/name, DEST/name)
    pairs = pair_cases(validation)
    ranks = [{'sample_id': hashlib.sha256(('historical-rank/'+capture(row).event_id).encode()).hexdigest(),
              'speaker': row['speaker'], 'target': row['target'], 'events': [capture(row).event_id]*2,
              'values': rank_views(row)} for row in validation]
    results = {}
    for study, rows in (('pair', pairs), ('rank', ranks)):
        values, targets = [r['values'] for r in rows], [r['target'] for r in rows]
        margins = []
        for strength in STRENGTHS:
            law = fit_pair(fitting, 'paired', strength, None) if study == 'pair' else fit_rank(fitting, strength, None)
            margins.append((float(score(law, values, targets)[0][:, 0].mean()), strength))
        margin = min(margins)[1]
        baseline = fit_pair(fitting, 'paired', margin, None) if study == 'pair' else fit_rank(fitting, margin, None)
        trials = [trial(study+'_baseline', baseline, rows)]
        families = ('paired', 'speaker_mixture') if study == 'pair' else ('rank',)
        for family in families:
            for strength in STRENGTHS:
                law = fit_pair(fitting, family, margin, strength) if study == 'pair' else fit_rank(fitting, margin, strength)
                name = f'{study}_{family}_{strength}'.replace('.', 'p')
                trials.append(trial(name, law, rows))
        if len({row['custody']['public_evidence_sha256'] for row in trials}) != 1:
            raise ValueError('Candidates received different public evidence')
        decision = select(trials, study+'_baseline')
        results[study] = {'selected': decision, 'trials': trials, 'shared_marginal_strength': margin,
                          'marginal_candidates': margins}
    write(DEST/'RESULTS.json', {'studies': results, 'new_qualification_sources_scored': 0,
        'all_previous_test_results_unchanged': True,
        'whole_development_wall_seconds': time.perf_counter()-wall,
        'whole_development_cpu_seconds': time.process_time()-cpu})
    print(json.dumps({key: value['selected'] for key, value in results.items()}), flush=True)


if __name__ == '__main__':
    main()

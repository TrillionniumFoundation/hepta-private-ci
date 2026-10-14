"""Six-parameter conditional smoothing of a frozen shared-Head ensemble.

Input novelty is computed from TRAINING text only. The scalar is fitted on a
separate labelled calibration population, not inferred to be a probability of
correctness. Smoothing supplies missing alternatives; it cannot change a member's
argmax or certify risk under arbitrary shift. No parser truth enters prediction.
"""
import math
import re
from four_gate_common import digest, require

PROFILE = 'novelty_calibration_v1'
DIMENSION = 6


def tokens(text, names=()):
    require(type(text) is str and 0 < len(text) <= 1024, 'bounded raw input')
    require(type(names) in (tuple, list) and len(names) <= 7 and
            all(type(n) is str and re.fullmatch('[A-Z][a-z]{1,15}', n) for n in names),
            'declared actor coordinates')
    for name in names:
        text = re.sub(r'\b'+re.escape(name)+r'\b', 'ACTOR', text)
    words = re.findall('[a-z]+', text.lower())
    require(words, 'nonempty lexical input')
    return tuple('actor' if w in ('self', 'other', 'actor') else w for w in words)


def support_from_training(texts):
    require(type(texts) is list and 0 < len(texts) <= 4096, 'training-only support inventory')
    rows = [tokens(t) for t in texts]
    return {'unigrams': sorted({w for r in rows for w in r}),
            'bigrams': sorted({' '.join(p) for r in rows for p in zip(r, r[1:])}),
            'training_texts_sha256': digest(texts), 'no_labels_used': True}


def validate_laws(laws):
    require(type(laws) in (tuple, list) and len(laws) == 3, 'three frozen members')
    for row in laws:
        require(type(row) in (list, tuple) and len(row) == 3 and
                all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in row)
                and abs(math.fsum(row)-1) < 1e-12, 'three-pair categorical law')


def features(sentence, names, laws, support):
    validate_laws(laws)
    words = tokens(sentence, names); bigrams = tuple(' '.join(p) for p in zip(words, words[1:]))
    uni, bi = set(support['unigrams']), set(support['bigrams'])
    mean = [math.fsum(row[j] for row in laws)/3 for j in range(3)]
    entropy = -math.fsum(p*math.log(p) for p in mean if p > 0)/math.log(3)
    disagreement = max(math.fsum((r[j]-mean[j])**2 for j in range(3)) for r in laws)
    return [1., sum(w not in uni for w in words)/len(words),
            sum(b not in bi for b in bigrams)/max(1, len(bigrams)),
            entropy, 1-max(mean), disagreement]


def alpha_for(feature, calibration):
    require(type(feature) is list and len(feature) == DIMENSION and
            all(type(x) in (int, float) and math.isfinite(x) for x in feature), 'finite support features')
    weights = calibration['weights']
    require(type(weights) is list and len(weights) == DIMENSION and
            all(type(x) in (float, int) and math.isfinite(x) for x in weights), 'fitted scalar weights')
    value = math.fsum(a*b for a,b in zip(feature, weights))
    require(math.isfinite(value), 'gate logit overflow')
    return 1/(1+math.exp(-value)) if value >= 0 else math.exp(value)/(1+math.exp(value))


def smooth(laws, alpha):
    validate_laws(laws)
    require(type(alpha) in (int, float) and math.isfinite(alpha) and 0 <= alpha <= 1, 'smoothing mass')
    return [[(1-alpha)*p+alpha/3 for p in row] for row in laws]


def fit_gate(torch, calibration_rows):
    """Only features, precomputed laws and local calibration labels may be fitted."""
    require(type(calibration_rows) is list and 6 <= len(calibration_rows) <= 4096, 'calibration inventory')
    require(all(set(r) == {'features', 'laws', 'pair_index', 'source_sha256'} for r in calibration_rows),
            'explicit calibration fields')
    require(len({r['source_sha256'] for r in calibration_rows}) == len(calibration_rows),
            'duplicate calibration source')
    for r in calibration_rows:
        validate_laws(r['laws'])
        require(type(r['pair_index']) is int and 0 <= r['pair_index'] < 3, 'local calibration label')
        alpha_for(r['features'], {'weights': [0.]*DIMENSION})
    x = torch.tensor([r['features'] for r in calibration_rows], dtype=torch.float64)
    q = torch.tensor([math.fsum(row[r['pair_index']] for row in r['laws'])/3
                      for r in calibration_rows], dtype=torch.float64)
    w = torch.tensor([-4., 0., 0., 0., 0., 0.], dtype=torch.float64, requires_grad=True)
    optimizer = torch.optim.Adam([w], lr=.05); losses = []
    import time
    started = time.process_time_ns()
    for _ in range(160):
        optimizer.zero_grad(); mass = (x@w).sigmoid()
        loss = -((1-mass)*q+mass/3).log().mean()
        require(torch.isfinite(loss).item(), 'nonfinite calibration loss')
        loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
        require(time.process_time_ns()-started <= 15_000_000_000, 'calibration CPU budget exhausted')
    return {'weights': w.detach().tolist(), 'losses': losses, 'fit_cpu_ns': time.process_time_ns()-started,
            'calibration_rows_sha256': digest(calibration_rows), 'parameters': DIMENSION,
            'steps': 160, 'learning_rate': .05, 'risk_certificate': False}

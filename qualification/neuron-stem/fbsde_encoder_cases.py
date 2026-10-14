"""Constrained semantic-composition challenge from pinned human-labelled utterances.

Utterance intent labels are publisher data; composite Boolean questions/labels
are generated, not human-authored reasoning labels or future Hepta outcomes.
Only public case inputs are passed to inference; truth stays with the scorer.
"""
import random
import math
from collections import defaultdict

from four_gate_common import digest, require
from fbsde_tree import eval_formula

INTENTS = ('alarm', 'calendar', 'weather', 'time')
DEPTHS = (1, 2, 4, 8, 12)
SENTENCES = ('No, the stated condition is not satisfied.', 'Yes, the stated condition is satisfied.')
TRAIN_FORMULAS = (('and', 0, 1), ('or', 0, 1),
                  ('and', ('or', 0, 1), 2), ('or', ('and', 0, 1), 2))
TEST_FORMULAS = (('and', ('or', 0, 1), ('or', 2, 3)),
                 ('or', ('and', 0, 1), ('and', 2, 3)),
                 ('and', ('and', 0, 1), ('and', 2, 3)),
                 ('or', ('or', 0, 1), ('or', 2, 3)))


def partition_utterances(data):
    """Fixed first-n policy; reject cross-split text duplicates instead of hiding them."""
    result, used = {}, set()
    for output, split, start, end in (('train','train',0,32), ('validation','val',0,10),
                                     ('calibration','val',10,20), ('test','test',0,30)):
        grouped = defaultdict(list)
        for ordinal, (text, intent) in enumerate(data[split]):
            if intent in INTENTS:
                grouped[intent].append({'id': f'{split}:{ordinal}', 'text': text,
                                        'intent': INTENTS.index(intent), 'source_sha256': digest(text)})
        rows = []
        for intent in INTENTS:
            require(len(grouped[intent]) >= end, 'publisher partition too small')
            rows.extend(grouped[intent][start:end])
        ids = {r['source_sha256'] for r in rows}
        require(len(ids) == len(rows) and not ids.intersection(used), 'text overlap in fixed task splits')
        used.update(ids)
        result[output] = rows
    return result


def leaf_count(formula):
    if type(formula) is int: return formula+1
    return max(leaf_count(formula[1]), leaf_count(formula[2]))


def formula_vector(formula):
    """Heap-position one-hot grammar: public syntax, NOT terminal labels."""
    vec = [0.] * (15*7)
    def visit(f, position):
        require(position < 15, 'formula exceeds bound')
        if type(f) is int:
            require(0 <= f < 4, 'leaf bound')
            vec[position*7+2+f] = 1.
        else:
            require(f[0] in ('and','or'), 'unknown operator')
            vec[position*7+(0 if f[0] == 'and' else 1)] = 1.
            visit(f[1], 2*position+1); visit(f[2], 2*position+2)
    visit(formula, 0)
    return vec


def cases(rows, split, count, seed):
    rng = random.Random(seed)
    public, truths = [], {}
    formulas = TEST_FORMULAS if split == 'test' else TRAIN_FORMULAS
    for i in range(count):
        f = formulas[i % len(formulas)]
        selected = rng.sample(rows, leaf_count(f))
        # Target intent is part of the question. Balanced true/false leaves,
        # no truth bit or publisher intent is passed to the predictor.
        targets = [(r['intent'] if rng.randrange(2) else
                    rng.choice([v for v in range(4) if v != r['intent']])) for r in selected]
        identity = f'{split}:{i}'
        public.append({'case_id': identity, 'utterance_ids': [r['id'] for r in selected],
                       'target_intents': targets, 'formula': f})
        leaves = [r['intent'] == t for r, t in zip(selected, targets)]
        truths[identity] = bool(eval_formula(f, leaves))
    return public, truths


def checked_probability(p):
    """Only tolerate floating-point roundoff, never turn solver failure into an answer."""
    require(type(p) in (float, int) and math.isfinite(p), 'nonfinite model/solver probability')
    require(-1e-12 <= p <= 1+1e-12, 'model/solver probability outside roundoff tolerance')
    return min(1., max(0., float(p)))


def decode_probability(p):
    require(type(p) in (float, int) and 0 <= p <= 1, 'finite probability for constrained decoder')
    return SENTENCES[int(p >= .5)]


def score_decoded(records, truths):
    require(len(records) == len(truths) and {r['case_id'] for r in records} == set(truths),
            'complete decoded case coverage')
    require(len({r['case_id'] for r in records}) == len(records), 'duplicate decoded case')
    correct, loss = 0, 0.
    for r in records:
        require(r['text'] in SENTENCES, 'decoder changed output grammar')
        require(r['text'] == decode_probability(r['probability']), 'decoder changed latent decision')
        truth = truths[r['case_id']]
        correct += r['text'] == SENTENCES[int(truth)]
        loss += (r['probability']-int(truth))**2
    return {'count': len(records), 'decoded_exact_accuracy': correct/len(records),
            'binary_brier': loss/len(records)}

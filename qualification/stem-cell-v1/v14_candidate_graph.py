"""V14: label-blind entity-slot proposal from ALL fact sentences.

No registered grammar parser, relation type/level enumeration, gold support, held
labels, model weights, or per-hop candidate lists enter inference. The tokenizer,
corpus DF ranks, sentence-order direction and graph traversal are intentionally
weak surface heuristics, not semantic proofs. Research only / DENY_ALL.
"""
from collections import defaultdict, deque
from hashlib import sha256
import json
import re

PAT_WORD = re.compile(r"[a-z]+", re.ASCII)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def words(sentence):
    if type(sentence) is not str or not 0 < len(sentence) <= 512:
        raise ValueError('bounded literal public string required')
    return PAT_WORD.findall(sentence.lower())


def build_df(rows, *, scope):
    """Sentence words -> independent source GROUP DF, never answer labels."""
    if scope not in ('train_only', 'unlabeled_transductive'):
        raise ValueError('exactly declared source access regime required')
    by_word, groups = defaultdict(set), set()
    for row in rows:
        if type(row) is not dict or set(row) != {'case_id', 'source_group', 'facts', 'question', 'candidate'}:
            raise ValueError('label-free complete source rows required')
        if scope == 'train_only' and not row['case_id'].startswith('train/'):
            continue
        group = row['source_group']
        if type(group) is not str or not group:
            raise ValueError('source-group identity missing')
        groups.add(group)
        for sentence in row['facts']:
            for token in set(words(sentence)):
                by_word[token].add(group)
    if not groups:
        raise ValueError('nonempty independent source groups required')
    return dict(schema='hepta.v14.source-group-document-frequency.v1',
                access=scope, independent_groups=len(groups),
                counts={k: len(v) for k, v in sorted(by_word.items())},
                training_labels_accessed=False, held_answer_labels_accessed=False,
                pretrained_encoder_calls=0, authority='DENY_ALL', production_accepted=False)


def slots(sentence, model, *, reverse=False):
    """Rarest two distinct surface words, in the original text order."""
    tokens = words(sentence)
    if len(tokens) < 2 or len(tokens) > 80:
        raise ValueError('two bounded endpoint candidates per sentence required')
    counts = model['counts']
    # All content occurs as plain public text; higher corpus frequency identifies
    # function words. Unseen terms tie on earliest surface position (a weakness).
    order = sorted(range(len(tokens)), key=lambda i: (counts.get(tokens[i], 0), i))
    selected = sorted(order[:2])
    a, b = tokens[selected[0]], tokens[selected[1]]
    if a == b:
        raise ValueError('duplicate entity token candidates')
    return (b, a) if reverse else (a, b)


def discover_graph(facts, model, *, reverse=False):
    if type(facts) not in (tuple, list) or not 1 <= len(facts) <= 64:
        raise ValueError('full 1..64 fact evidence required')
    graph, vertices, extracted = defaultdict(set), set(), []
    for idx, fact in enumerate(facts):
        first, second = slots(fact, model, reverse=reverse)
        vertices.add(first)
        vertices.add(second)
        graph[first].add(second)
        extracted.append((idx, first, second))
    return graph, vertices, extracted


def first_shared_vertex(text, vertices):
    return next((token for token in words(text) if token in vertices), None)


def shortest_path(graph, source, destination, *, max_hops=6):
    if source is None or destination is None:
        return None
    queue = deque([(source, (source,))])
    seen = {source}
    while queue:
        name, path = queue.popleft()
        if name == destination:
            return path
        if len(path)-1 < max_hops:
            for child in sorted(graph.get(name, ())):
                if child not in seen:
                    queue.append((child, (*path, child)))
                    seen.add(child)
    return None


def distance(row, model, *, reverse=False):
    if type(row) is not dict or set(row) != {'case_id', 'source_group', 'facts', 'question', 'candidate'}:
        raise ValueError('public-only row required; forbidden oracle annotations')
    graph, vertices, extracted = discover_graph(row['facts'], model, reverse=reverse)
    start = first_shared_vertex(row['question'], vertices)
    dest = first_shared_vertex(row['candidate'], vertices)
    path = shortest_path(graph, start, dest)
    return {'path': list(path) if path else [], 'dist': len(path)-1 if path else 99,
            'start': start, 'candidate': dest,
            'fact_slots': [list(s) for s in extracted]}


def predict_pair(a, b, model, *, reverse=False):
    """One public-question pair; no `world`/`candidate-0` lookup or label use."""
    if (a['facts'] != b['facts'] or a['question'] != b['question']
            or a['candidate'] == b['candidate'] or a['source_group'] != b['source_group']):
        raise ValueError('two opposite public candidate texts for same source/question required')
    x, y = distance(a, model, reverse=reverse), distance(b, model, reverse=reverse)
    if x['dist'] == y['dist']:
        predictions = {a['case_id']: None, b['case_id']: None}
    else:
        predictions = {a['case_id']: int(x['dist'] < y['dist']),
                       b['case_id']: int(y['dist'] < x['dist'])}
    return predictions, {a['case_id']: x, b['case_id']: y}


# PUBLIC-ONLY templated paraphrase challenge. These six rules have deliberately
# reversed source/destination noun surface order while preserving original task
# meaning. They are NOT authentic human-written natural language.
PARAPHRASES = (
    (re.compile(r'The ([a-z]+) belongs to ([A-Z][a-z]+)\.', re.ASCII),
     lambda a, b: f'{b} owns the {a}.'),
    (re.compile(r'([A-Z][a-z]+) stores all their possessions in the ([a-z]+) box\.', re.ASCII),
     lambda a, b: f'The {b} box contains possessions owned by {a}.'),
    (re.compile(r'The ([a-z]+) box is on the ([a-z]+) shelf\.', re.ASCII),
     lambda a, b: f'The {b} shelf supports the {a} box.'),
    (re.compile(r'The ([a-z]+) shelf is in the ([a-z]+) room\.', re.ASCII),
     lambda a, b: f'The {b} room contains the {a} shelf.'),
    (re.compile(r'The ([a-z]+) room is in the ([a-z]+) building\.', re.ASCII),
     lambda a, b: f'The {b} building contains the {a} room.'),
    (re.compile(r'The ([a-z]+) building is in the ([a-z]+) district\.', re.ASCII),
     lambda a, b: f'The {b} district contains the {a} building.'),
)


def transform(row, variant):
    if variant not in ('original', 'fact_permutation', 'meaning_preserving_paraphrase'):
        raise ValueError('registered source variant required')
    current = dict(row)
    if variant == 'fact_permutation':
        # Pure fact-order reversal, same semantics and no gold labels.
        current['facts'] = list(reversed(row['facts']))
    elif variant == 'meaning_preserving_paraphrase':
        new = []
        for fact in row['facts']:
            match = [(m, fn) for regex, fn in PARAPHRASES if (m := regex.fullmatch(fact))]
            if len(match) != 1:
                raise ValueError('unsupported grammar in fixed synthetic paraphrase challenge')
            m, fn = match[0]
            new.append(fn(*m.groups()))
        current['facts'] = new
    return current


def build_public_pairs(rows, *, require_role=None):
    by_group, seen = defaultdict(list), set()
    for row in rows:
        if require_role is not None and not row['case_id'].startswith(require_role):
            continue
        if row['case_id'] in seen:
            raise ValueError('duplicate source case')
        seen.add(row['case_id'])
        key = (row['source_group'], tuple(row['facts']), row['question'])
        by_group[key].append(row)
    if not by_group or any(len(v) != 2 for v in by_group.values()):
        raise ValueError('complete public two-alternative question groups required')
    return [tuple(sorted(v, key=lambda item: item['candidate'])) for v in by_group.values()]

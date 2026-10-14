"""Source-bound state transitions for a restricted-English tracking workspace.

The grammar/checker are explicit domain knowledge, not learned semantics. A small
shared gate proposes two participants; only a verified transition can be called
certified. No FBSDE residual is treated as a certificate of a language answer.
"""
from collections import Counter
import hashlib
import itertools
import math
import random
import re
import time
from four_gate_common import digest, require

NAMES = ('Alice', 'Bob', 'Claire', 'Dave', 'Eve', 'Fred', 'Gertrude')
VERBS = ('swap books', 'switch partners', 'swap balls', 'swap their gifts', 'trade positions')
PREAMBLES = ('As the semester proceeds, they start trading around the new books.',
             'Throughout the song, the dancers often trade partners.',
             'As the game progresses, pairs of players trade balls.',
             'As the event progresses, pairs of people swap gifts.',
             'As the game progresses, pairs of players occasionally swap positions.')
HEADERS = (' are friends and avid readers who occasionally trade books. At the start of the semester, they each buy one new book',
           ' are dancers at a square dance. At the start of a song, they each have a partner',
           ' are playing a game. At the start of the game, they are each holding a ball',
           ' are holding a white elephant gift exchange. At the start of the event, they are each holding a present of a different color',
           ' are on the same team in a soccer match. At the start of the match, they are each assigned to a position')
ARMS = ('initial_only', 'last_step_only', 'frozen_recurrent', 'learned_recurrent',
        'verified_recurrent', 'exact_forward', 'exact_reverse', 'fault_verified')


def parse(text):
    """Closed grammar; never discard an unparsed instruction or read a gold label."""
    require(type(text) is str and 0 < len(text) <= 16000, 'bounded tracking text')
    body, separator, option_text = text.partition('\nOptions:\n')
    require(separator and '\nOptions:' not in option_text, 'single option block')
    option_rows = [re.fullmatch(r'\(([A-G])\) (.+)', line) for line in option_text.splitlines()]
    require(3 <= len(option_rows) <= 7 and all(option_rows), 'bounded option inventory')
    options = [(m[1], m[2]) for m in option_rows]
    require([k for k, _ in options] == list('ABCDEFG'[:len(options)]) and
            len({v for _, v in options}) == len(options), 'distinct ordered options')
    initial, separator, rest = body.partition('\n')
    require(separator and initial.endswith('.') and initial.count(': ') == 1, 'initial state grammar')
    inventory = initial.split(': ', 1)[1][:-1]
    clauses = re.split(r', (?:and )?', inventory)
    holdings = [re.fullmatch(r'([A-Z][a-z]+) (?:gets|has a|is dancing with|is playing) (.+)', c)
                for c in clauses]
    require(len(holdings) == len(options) and all(holdings), 'initial ownership grammar')
    names = tuple(m[1] for m in holdings)
    values = tuple(m[2] for m in holdings)
    require(len(set(names)) == len(names) and set(values) == {v for _, v in options},
            'bijective initial ownership')
    preambles = [p for p in PREAMBLES if rest.startswith(p+' ')]
    require(len(preambles) == 1, 'supported narrative preamble')
    kind = PREAMBLES.index(preambles[0])
    actor_list = ', '.join(names[:-1])+', and '+names[-1]
    expected_header = actor_list+HEADERS[kind]
    require(initial.split(': ', 1)[0] == expected_header or kind == 0 and
            initial.split(': ', 1)[0] == 'These friends exchange books. They each have one book',
            'unregistered narrative header')
    rest = rest[len(preambles[0])+1:]
    sequence, marker, question = rest.partition(' At the end of ')
    require(marker, 'final query boundary')
    q = re.fullmatch(r'(?:the semester|the dance|the game|the event|the match), '
                     r'([A-Z][a-z]+) (?:has(?: the)?|is dancing with|is playing)', question)
    require(q and q[1] in names, 'registered final query')
    raw_events = sequence.split('. ')
    require(1 <= len(raw_events) <= 64 and raw_events[-1].endswith('.'), 'bounded event inventory')
    raw_events[-1] = raw_events[-1][:-1]
    events = []
    for sentence in raw_events:
        m = re.fullmatch(r'(?:First|Then|Next|After that|Finally), '
                         r'([A-Z][a-z]+) and ([A-Z][a-z]+) ('+'|'.join(VERBS)+r')', sentence)
        require(m and m[1] in names and m[2] in names and m[1] != m[2] and m[3] == VERBS[kind], 'unsupported transition')
        events.append({'text': sentence+'.', 'pair': (names.index(m[1]), names.index(m[2]))})
    return {'names': names, 'values': values, 'events': events, 'query': names.index(q[1]),
            'options': options, 'input_sha256': digest(text)}


def slot_text(sentence, names, slot):
    """Entity normalization is part of the registered frontend and available to all arms."""
    return re.sub(r'\b('+'|'.join(re.escape(n) for n in names)+r')\b',
                  lambda m: 'SELF' if m[0] == names[slot] else 'OTHER', sentence)


def lexical_vector(text, width=128):
    tokens = re.findall(r'[a-z]+', text.lower())
    grams = tokens + [' '.join(p) for p in zip(tokens, tokens[1:])]
    v = [0.]*width
    for token in grams:
        h = hashlib.sha256(token.encode()).digest()
        v[int.from_bytes(h[:4], 'little') % width] += 1 if h[4] & 1 else -1
    norm = math.sqrt(sum(x*x for x in v)) or 1
    return [x/norm for x in v]


def make_gate(torch, width=128):
    nn = torch.nn
    class Gate(nn.Module):
        def __init__(self):
            super().__init__()
            self.value = nn.Linear(width, 8)
            self.gate = nn.Linear(width, 8)
            self.output = nn.Linear(8, 1)
        def forward(self, x):
            return self.output(self.value(x).tanh()*self.gate(x).sigmoid()).squeeze(-1)
    return Gate()


def execute(text, arm, propose, *, max_steps=64, scope='tracking-research', generation=1):
    """One forward-only immutable state per accepted step. Corrections use source, not labels."""
    require(arm in ARMS and type(max_steps) is int and 0 <= max_steps <= 64, 'registered execution')
    require(type(scope) is str and 0 < len(scope) <= 128 and type(generation) is int and generation > 0,
            'workspace identity')
    start_cpu, start_wall = time.process_time_ns(), time.perf_counter_ns()
    task = parse(text); state = list(task['values']); events = task['events']; trace = []
    binding = digest([task['input_sha256'], scope, generation]); repairs = 0
    if arm == 'exact_reverse':
        holder = task['query']
        for index in reversed(range(len(events))):
            if len(trace) == max_steps:
                return {'status': 'unresolved', 'answer': None, 'text': None, 'trace': trace}
            a, b = events[index]['pair']; previous = holder
            holder = b if holder == a else a if holder == b else holder
            trace.append({'index': index, 'holder_before': previous, 'holder_after': holder})
        answer = task['values'][holder]
    else:
        indices = [] if arm == 'initial_only' else [len(events)-1] if arm == 'last_step_only' else range(len(events))
        for index in indices:
            if len(trace) == max_steps:
                return {'status': 'unresolved', 'answer': None, 'text': None, 'trace': trace}
            event = events[index]; exact = event['pair']
            if arm in ('exact_forward', 'last_step_only'):
                pair = exact
            else:
                pair = tuple(propose(event['text'], task['names']))
            require(len(pair) == 2 and len(set(pair)) == 2 and
                    all(type(i) is int and 0 <= i < len(state) for i in pair), 'bounded proposed participants')
            if arm == 'fault_verified' and index == 0:
                pair = next(p for p in itertools.combinations(range(len(state)), 2) if set(p) != set(exact))
            valid = set(pair) == set(exact)
            checked = arm in ('verified_recurrent', 'fault_verified', 'exact_forward')
            used = exact if checked and not valid else pair
            repairs += int(checked and not valid)
            before = tuple(state); a, b = used; state[a], state[b] = state[b], state[a]
            require(Counter(state) == Counter(task['values']), 'ownership conservation')
            trace.append({'index': index, 'event_sha256': digest(event['text']), 'binding': binding,
                'proposal': pair, 'proposal_valid': valid, 'applied': used,
                'checked': checked, 'before': before, 'after': tuple(state)})
        answer = state[task['query']]
    label = next(k for k, value in task['options'] if value == answer)
    return {'status': 'answered', 'answer': '('+label+')', 'text': answer, 'trace': trace,
            'input_sha256': task['input_sha256'], 'binding': binding, 'arm': arm, 'repairs': repairs,
            'steps': len(trace), 'cpu_ns': time.process_time_ns()-start_cpu,
            'wall_ns': time.perf_counter_ns()-start_wall,
            'semantic_certificate': arm in ('verified_recurrent', 'fault_verified', 'exact_forward', 'exact_reverse'),
            'certificate_scope': 'the_explicit_restricted_tracking_grammar_only',
            'production_promotion_permitted': False}


def training_rows(seed=32452843):
    """Only fresh simulator operation labels; NEVER benchmark inputs or final targets."""
    rng = random.Random(seed); result = []
    names = ('Mira', 'Nolan', 'Priya')
    for _ in range(240):
        a, b = rng.sample(range(3), 2); verb = rng.choice(VERBS)
        sentence = f'Then, {names[a]} and {names[b]} {verb}.'
        result.extend((slot_text(sentence, names, i), float(i in (a, b))) for i in range(3))
    return result


def generated_cases(seed=49979687, count=192):
    """Declared mechanism tests, not BBH and not independently observed language data."""
    rng = random.Random(seed); out = []
    for index in range(count):
        n = (3, 5, 7)[index % 3]; names = NAMES[:n]; values = [f'book {i}' for i in range(n)]
        inventory = ', '.join(f'{s} gets {v}' for s, v in zip(names[:-1], values[:-1]))
        inventory += f', and {names[-1]} gets {values[-1]}'
        events = []
        for step in range(n):
            a, b = rng.sample(range(n), 2); a, b = names[a], names[b]
            events.append(f'{"First" if step == 0 else "Finally" if step == n-1 else "Then"}, {a} and {b} swap books.')
        query = rng.choice(names)
        text = ('These friends exchange books. They each have one book: '+inventory+'.\n'+PREAMBLES[0]+' '+
                ' '.join(events)+f' At the end of the semester, {query} has\nOptions:\n'+
                '\n'.join(f'({chr(65+i)}) {v}' for i, v in enumerate(values)))
        out.append({'input': text, 'source_id': f'generated:{seed}:{index}'})
    return out

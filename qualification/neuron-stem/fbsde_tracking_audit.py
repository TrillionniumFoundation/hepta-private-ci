"""Independent source/transition/output checks; no learner or workspace imports."""
import re
from four_gate_common import digest, require


def source_parts(text):
    body, _, option_text = text.partition('\nOptions:\n')
    first, rest = body.split('\n', 1)
    inventory = first.split(': ', 1)[1][:-1]
    rows = re.split(r', (?:and )?', inventory)
    initial = {}
    for row in rows:
        m = re.fullmatch(r'([A-Z][a-z]+) (?:gets|has a|is dancing with|is playing) (.+)', row)
        require(m is not None, 'audit initial grammar')
        initial[m[1]] = m[2]
    actor_list = ', '.join(tuple(initial)[:-1])+', and '+tuple(initial)[-1]
    allowed = (
        ' are friends and avid readers who occasionally trade books. At the start of the semester, they each buy one new book',
        ' are dancers at a square dance. At the start of a song, they each have a partner',
        ' are playing a game. At the start of the game, they are each holding a ball',
        ' are holding a white elephant gift exchange. At the start of the event, they are each holding a present of a different color',
        ' are on the same team in a soccer match. At the start of the match, they are each assigned to a position')
    require(first.split(': ', 1)[0] in tuple(actor_list+h for h in allowed) +
            ('These friends exchange books. They each have one book',), 'audit narrative header')
    event_text, query_text = rest.rsplit(' At the end of ', 1)
    operations = re.findall(r'([A-Z][a-z]+) and ([A-Z][a-z]+) '
                            r'(?:swap books|switch partners|swap balls|swap their gifts|trade positions)\.', event_text)
    q = re.search(r', ([A-Z][a-z]+) (?:has(?: the)?|is dancing with|is playing)$', query_text)
    require(q and q[1] in initial and 1 <= len(operations) <= 64, 'audit question/events')
    preamble, separator, remaining = event_text.partition('. ')
    allowed_preambles = ('As the semester proceeds, they start trading around the new books',
        'Throughout the song, the dancers often trade partners',
        'As the game progresses, pairs of players trade balls',
        'As the event progresses, pairs of people swap gifts',
        'As the game progresses, pairs of players occasionally swap positions')
    full_events = re.findall(r'(?:First|Then|Next|After that|Finally), [A-Z][a-z]+ and [A-Z][a-z]+ (?:swap books|switch partners|swap balls|swap their gifts|trade positions)\.', remaining)
    require(separator and preamble in allowed_preambles and ' '.join(full_events) == remaining,
            'audit instruction coverage')
    options = dict(re.findall(r'\(([A-G])\) (.+)', option_text))
    return initial, operations, q[1], options


def reference(text):
    """Backward holder tracing, independent of forward mutable-state execution."""
    initial, operations, query, options = source_parts(text)
    for a, b in reversed(operations):
        query = b if query == a else a if query == b else query
    answer = initial[query]
    return '('+next(k for k, v in options.items() if v == answer)+')'


def audit_record(text, record, scope='tracking-research', generation=1):
    require(record['status'] in ('answered', 'unresolved'), 'terminal status')
    if record['status'] == 'unresolved':
        require(record['answer'] is None and record['text'] is None, 'unresolved result cannot answer')
        return {'complete': False, 'certified': False}
    require(record['production_promotion_permitted'] is False and record['certificate_scope'] ==
            'the_explicit_restricted_tracking_grammar_only', 'certificate authority drift')
    initial, operations, query, options = source_parts(text)
    names = tuple(initial); state = list(initial.values()); trace = record['trace']
    sentences = re.findall(r'(?:First|Then|Next|After that|Finally), [A-Z][a-z]+ and [A-Z][a-z]+ (?:swap books|switch partners|swap balls|swap their gifts|trade positions)\.', text)
    require(record['steps'] == len(trace), 'depth count drift')
    require(record['input_sha256'] == digest(text) and record['binding'] ==
            digest([digest(text), scope, generation]), 'source/scope/generation drift')
    arm = record['arm']; indices = ([] if arm == 'initial_only' else [len(operations)-1]
                                   if arm == 'last_step_only' else list(range(len(operations))))
    if arm == 'exact_reverse':
        holder = names.index(query)
        require([r['index'] for r in trace] == list(reversed(range(len(operations)))), 'reverse order/coverage')
        for row in trace:
            a, b = (names.index(s) for s in operations[row['index']])
            require(row['holder_before'] == holder, 'reverse predecessor drift')
            holder = b if holder == a else a if holder == b else holder
            require(row['holder_after'] == holder, 'reverse step wrong')
        result = list(initial.values())[holder]
    else:
        require([r['index'] for r in trace] == indices, 'forward order/coverage')
        repairs = 0
        for row in trace:
            expected = {names.index(s) for s in operations[row['index']]}
            require(row['event_sha256'] == digest(sentences[row['index']]), 'source event drift')
            proposed = set(row['proposal']); applied = row['applied']
            require(row['binding'] == record['binding'] and list(row['before']) == state,
                    'causal predecessor mismatch')
            require(type(applied) in (tuple, list) and len(applied) == 2 and len(set(applied)) == 2 and
                    all(type(i) is int and 0 <= i < len(state) for i in applied), 'invalid applied pair')
            require(row['proposal_valid'] == (proposed == expected), 'invented proposal verification')
            checked = arm in ('verified_recurrent', 'fault_verified', 'exact_forward')
            require(row['checked'] == checked, 'checker bypass')
            require(set(applied) == (expected if checked else proposed), 'invalid checked transition')
            repairs += int(checked and proposed != expected)
            a, b = applied; state[a], state[b] = state[b], state[a]
            require(list(row['after']) == state, 'stored successor differs')
        require(repairs == record['repairs'], 'correction count mismatch')
        result = state[names.index(query)]
    option = '('+next(k for k, v in options.items() if v == result)+')'
    require(record['answer'] == option and record['text'] == result, 'decoded answer drift')
    certified = arm in ('verified_recurrent', 'fault_verified', 'exact_forward', 'exact_reverse')
    require(record['semantic_certificate'] == certified, 'unverified output mislabeled certified')
    if certified:
        require(option == reference(text), 'certified output contradicts source')
    return {'complete': True, 'certified': certified, 'steps': len(trace)}

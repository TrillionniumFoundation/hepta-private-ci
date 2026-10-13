"""Replay checkpoint accounting and finite source tables without runtime owners.

Used as a bounded restart validator. The separate process study also verifies
SQL bytes/anchors and real exit codes; this replay alone is not crash evidence.
"""
import re
from four_gate_common import digest, require
from fbsde_transfer_reference import STATES, tables


def validate_rows(rows):
    require(type(rows) is list and 1 <= len(rows) <= 512, 'complete bounded checkpoint rows')
    first = rows[0]; public = first['snapshot']['public']; initial = first['event']
    require(initial['event'] == 'initial', 'missing original initialization')
    context = initial['context']; revision = attempts = sequence = 0
    limit = first['snapshot']['limit']; history = []; state = 'active'
    require(type(limit) is int and 0 <= limit <= 6, 'original recovery allowance')
    identity = digest(['revocable_rule_transfer_v1',public,context,initial['snapshot']])
    pending = {}; verifying = set(); inflight = None; family = tables(); deferred = None; refuse_after = False
    def identified(h):
        require(type(h) is list and len(h) <= 6 and all(type(x) in (tuple,list) and len(x) == 2
            and all(type(v) is int and 0 <= v < 6 for v in x) for x in h), 'bounded recovery history')
        members = [t for t in family if all(t[s] == o for s,o in h)]
        require(members and len(set(members)) == 1, 'false full-table identification')
        return members[0]
    effect_table = identified(initial['history'])
    require(list(effect_table) == initial['snapshot']['effects'], 'initial effect table')
    previous = None
    for n, entry in enumerate(rows):
        e,s = entry['event'],entry['snapshot']; event = e['event']
        require(e['sequence'] == n and e['previous'] == (digest(previous) if previous else None), 'event chain')
        if event == 'initial': require(n == 0, 'duplicate initial allowance')
        elif event == 'begin':
            t,r = e['ticket'],e['request']; key = digest(t); sequence += 1
            require(state == 'active' and t == dict(slot=identity,revision=revision,sequence=sequence,identity=digest(r))
                and r['sequence'] == sequence and r['revision'] == revision and
                all(r[k] == context[k] for k in ('generation','environment','scope')), 'stale begin or source binding')
            require(type(r['state']) is list and tuple(r['state']) in STATES, 'begin state')
            app = e['application']; names = app['names']; pattern = r'\b(?:'+'|'.join(map(re.escape,names))+r')\b'
            order = list(dict.fromkeys(re.findall(pattern,app['text'])))
            order += [name for name in names if name not in order]
            require(len(order) == 3 and tuple(app['state']) in STATES, 'application coordinates')
            roles = tuple(names.index(name) for name in order); x = tuple(app['state'][j] for j in roles)
            require(list(x) == r['state'], 'application source state mismatch')
            op = STATES[effect_table[STATES.index(x)]]
            value = [app['state'][roles[op[roles.index(j)]]] for j in range(3)]
            require(e['predicted'] == value, 'predicted table result')
            pending[key] = (r,e['predicted'])
        elif event == 'verification_intent':
            keys = [k for k,(r,_) in pending.items() if r == e['request']]
            require(len(keys) == 1 and keys[0] not in verifying, 'unissued verification')
            verifying.add(keys[0])
        elif event == 'verification':
            for k,(r,_) in pending.items():
                if r == e['request']: verifying.discard(k)
        elif event == 'verification_match':
            require(previous['event'] == 'verification' and previous['error'] is None and
                previous['receipt']['request_sha256'] == e['request_sha256'] == digest(previous['request']), 'unverified match')
            idx = STATES.index(tuple(previous['request']['state']))
            require(tuple(previous['receipt']['effect']) == STATES[effect_table[idx]], 'false verification match')
        elif event == 'finish':
            key = digest(e['ticket'])
            require(state == 'active' and key in pending and key not in verifying and
                e['ticket']['revision'] == revision and e['value'] == pending[key][1], 'stale or unissued finish')
            del pending[key]
        elif event == 'retire':
            if e['reason'] == 'owner_generation_changed':
                require(s['context']['generation'] > context['generation'] and all(s['context'][k] == context[k]
                    for k in ('scope','environment')), 'nonmonotone owner generation')
                context = s['context']
            revision += 1; state = 'quarantined'; history = []; effect_table = None
            pending.clear(); verifying.clear()
        elif event == 'context': require(e['context'] == context and state == 'quarantined', 'context without retirement')
        elif event == 'recovery_request':
            r = e['request']
            require(state == 'quarantined' and inflight is None and attempts < limit and
                r['sequence'] == attempts and r['remaining'] == limit-attempts and r['declared_budget'] == limit and
                r['history_sha256'] == digest(history) and r['revision'] == revision and
                all(r[k] == context[k] for k in ('scope','environment','generation')), 'unpaid or stale recovery')
            attempts += 1; inflight = digest(r)
        elif event == 'recovery_receipt':
            r = e['request']; require(inflight == digest(r), 'unissued recovery receipt'); inflight = None
            if r['revision'] == revision and e['error'] is None and e['receipt'] is not None:
                receipt = e['receipt']
                if receipt['request_sha256'] == digest(r):
                    if tuple(receipt['effect']) in STATES:
                        deferred = [STATES.index(tuple(r['state'])),STATES.index(tuple(receipt['effect']))]
                    else: refuse_after = True
        elif event == 'reactivate':
            effect_table = identified(history)
            require(e['snapshot']['effects'] == list(effect_table) and e['history'] == history and
                    e['context'] == context and e['attempts'] == attempts, 'recovery table/evidence')
            state = 'active'
        elif event == 'recovery_exhausted': require(attempts == limit, 'premature exhausted budget')
        elif event == 'refuse': state = 'refused'; effect_table = None
        elif event == 'late_receipt': pass
        elif event == 'restart_quarantine':
            new = e['current_context']
            require(e['prior_state'] == rows[n-1]['snapshot']['state'] and e['no_handles_restored'] is True and
                new['generation'] >= context['generation'] and all(new[k] == context[k] for k in ('scope','environment')),
                'restart context or capability resurrection')
            if state == 'active' or new['generation'] > context['generation']: history = []
            state = 'refused' if state == 'refused' else 'quarantined'
            revision += 1; context = new; effect_table = None; inflight = None
            pending.clear(); verifying.clear()
        else: raise ValueError('unrecognized durable lifecycle event')
        require(s == dict(public=public,identity=identity,context=context,revision=revision,
            sequence=sequence,state=state,history=history,attempts=attempts,limit=limit,
            pending=len(pending),verifying=len(verifying),inflight=inflight), 'checkpoint semantic state/accounting mismatch')
        require(e['revision'] == revision and e['state'] == state, 'event revision/state mismatch')
        if deferred is not None:
            history = history + [deferred]; deferred = None
            if not any(all(t[x] == y for x,y in history) for t in family): refuse_after = True
        if refuse_after: state = 'refused'; refuse_after = False
        previous = e
    return dict(records=len(rows),attempts=attempts,state=state,revision=revision,
        no_native_authority=True,semantic_certificate=False)

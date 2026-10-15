"""Research-only fail-closed audit of bounded *unsuccessful* System2 episodes.

No execution rights. Preserve a real failed invocation as a negative observation
rather than making the entire experimental campaign fail to emit any result.
"""
import hashlib
import json

ABORTS = frozenset({
    'callback_failed', 'resource_budget_stop', 'budget_exhausted',
    'ndu_stop:expired_policy', 'ndu_stop:continuation_support_violated',
})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def audit_abort(row, record, public_answer, family):
    """Check a negative prefix against genuine public evidence and paid calls.

    This does not authenticate model execution. Any unverified callback outcome
    is a *failed* task, never a positive candidate for model promotion.
    """
    if (row.get('execution_status') not in ABORTS
            or row.get('success') is not False
            or row.get('valid_execution') is not False
            or row.get('execution_mode') not in ('fixed', 'ndu')
            or family not in ('dependency', 'constraint', 'temporal', 'composition')
            or (public_answer is not None and
                (type(public_answer) is not int or not 0 <= public_answer < 8))):
        raise ValueError('only failed bounded public-evidence episodes admitted')
    steps, verified = row.get('steps'), row.get('verifier_calls')
    if (type(steps) is not int or not 0 <= steps <= 8
            or type(verified) is not int or not 0 <= verified <= steps
            or type(row.get('search_formula_work')) is not int
            or row['search_formula_work'] < 0):
        raise ValueError('negative episode physical steps and work inconsistent')
    trace, guesses, statuses, bindings = (
        record.get('trace'), record.get('proposed_candidates'),
        record.get('verifier_statuses'), record.get('workspace_bindings'))
    if (any(type(item) is not list or len(item) > 25
            for item in (trace, guesses, statuses, bindings))
            or len(bindings) != steps or len(guesses) > steps
            or len(statuses) > verified or len(trace) != record.get('calls')):
        raise ValueError('negative callback trace not bounded or workspace-matched')
    if sum(e.get('kind') == 'verify' for e in trace) != verified:
        raise ValueError('unpaid verifier invocation')
    # A partial trace is still a strict *prefix*: no reorder/erasure of
    # completed callbacks. Failure can occur at a proposer, verifier or value.
    phase, completed_proposals, completed_verifications, completed_values = 0, [], [], []
    failure_count = 0
    for offset, event in enumerate(trace):
        if type(event) is not dict or event.get('call') != offset + 1:
            raise ValueError('out-of-order failed callback ID')
        kind = event.get('kind')
        if kind != ('propose', 'verify', 'value')[phase]:
            raise ValueError('failed callback did not follow causal propose/verify/value order')
        phase = (phase + 1) % 3
        state = event.get('status')
        if state not in ('completed', 'failed'):
            raise ValueError('missing callback completion status')
        if type(event.get('elapsed_ns')) is not int or event['elapsed_ns'] < 0:
            raise ValueError('failed callback missing elapsed work receipt')
        if state == 'failed':
            failure_count += 1
            if offset != len(trace) - 1 or not isinstance(event.get('error_type'), str):
                raise ValueError('failed callbacks must be terminal and typed')
            if row['execution_status'] not in ('callback_failed', 'resource_budget_stop'):
                raise ValueError('failed callback has inconsistent terminal status')
        else:
            output = event.get('output_digest')
            if type(output) is not str or len(output) != 64 or any(c not in '0123456789abcdef' for c in output):
                raise ValueError('completed callback lacks output binding')
            if kind == 'propose':
                completed_proposals.append(output)
            elif kind == 'verify':
                completed_verifications.append(output)
            else:
                completed_values.append(output)
    if failure_count > 1:
        raise ValueError('multiple failed callbacks in one bounded attempt')
    if (row['execution_status'] in ('callback_failed', 'resource_budget_stop')
            and not failure_count and not completed_values):
        raise ValueError('missing failed callback or policy boundary evidence')
    if (len(guesses) < len(completed_proposals)
            or len(statuses) < len(completed_verifications)):
        raise ValueError('failed trace erased a completed candidate or verification')
    for n, output in enumerate(completed_proposals):
        guess = guesses[n]
        if type(guess) is not str or len(guess) != 1 or not 'A' <= guess <= 'H':
            raise ValueError('invalid negative-episode candidate')
        if output != _digest(guess):
            raise ValueError('failed episode proposer digest changed')
    for n, output in enumerate(completed_verifications):
        guess = guesses[n]
        outcome = ('missing_evidence' if public_answer is None
                   else 'supported' if ord(guess)-65 == public_answer
                   else 'unsupported_' + family)
        if statuses[n] != outcome:
            raise ValueError('negative episode verifier diverged from public facts')
        accept = outcome == 'supported' and (
            row['execution_mode'] == 'ndu' or n == steps-1)
        if output != _digest([accept, outcome]):
            raise ValueError('negative episode verifier digest changed')
    if (len(guesses) and record.get('final_candidate') != guesses[-1]
            or not len(guesses) and record.get('final_candidate') is not None):
        raise ValueError('negative episode terminal candidate differs')
    if row['prediction'] != (
            ord(guesses[-1])-65 if guesses else -1):
        raise ValueError('negative episode final prediction drift')
    if row['execution_mode'] == 'fixed':
        if record.get('ndu_decisions') != []:
            raise ValueError('fixed-depth failed episode emitted NDU decisions')
    else:
        decisions = record.get('ndu_decisions')
        if (type(decisions) is not list or len(decisions) > len(completed_values)
                or any(type(d) is not dict or type(d.get('continue_computation')) is not bool
                       for d in decisions)):
            raise ValueError('failed NDU decisions exceed paid valuations')
        for n, d in enumerate(decisions):
            if d.get('estimate_id') not in (None, completed_values[n]):
                raise ValueError('failed NDU estimate substitution')
    return {'schema': 'hepta.group.negative-trajectory.v1',
            'authority': 'DENY_ALL', 'outcome': 'failed',
            'production_promotion_permitted': False,
            'causal_prefix_checked': True,
            'independent_model_execution_attested': False}

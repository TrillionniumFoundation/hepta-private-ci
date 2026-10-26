"""Read-only H2 outcome audit and fixed writer-cluster comparison; no model import."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np

from ..native.analyze import audit_media, audit_projection, correct, ece, read, sha


POLICIES = ('ndu', 'correctness')
ACTIONS = ('stop', 'refine_semantic', 'refine_image', 'refine_text', 'couple')


def audit(directory, allocation, protocol):
    assert sha(allocation) == read(protocol)['source_allocation_sha256']
    result = read(directory / 'results.json')
    rows = [json.loads(line) for line in (directory / 'rollouts.jsonl').read_text().splitlines()]
    assert sha(directory / 'rollouts.jsonl') == result['rollouts_sha256']
    assert result['registration']['protocol_sha256'] == sha(protocol)
    role = read(allocation)['roles']['execution']
    assert len(rows) == 512 and role['writer_count'] == 64 and role['pair_count'] == 128
    by_key = {(r['policy'], r['pair'], r['view']): r for r in rows}
    assert len(by_key) == len(rows)
    for pair in range(128):
        views = (('clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted')[pair % 5], 'both_missing')
        ids = [r['source_id'] for r in role['source_records'][2 * pair:2 * pair + 2]]
        for view in views:
            matched = [by_key[p, pair, view] for p in POLICIES]
            assert len({r['steps'][0]['prefix_digest'] for r in matched}) == 1
            for row in matched:
                assert row['source_ids'] == ids and row['writer'] == role['pair_writer_ids'][pair]
                assert row['private_truth_scoring_started_after_all_owners_closed'] == result['all_owners_closed_before_private_audit_ns']
    audits = {}
    for policy in POLICIES:
        selected_rows = [r for r in rows if r['policy'] == policy]
        decisions, outcomes, resource = {}, [], []
        previous, modulator, episode_continuation = '0' * 64, None, {}
        for index, line in enumerate((directory / policy / 'state/control.jsonl').read_text().splitlines()):
            record = json.loads(line); event = record['event']
            assert record['previous'] == previous and record['sequence'] == index + 1
            payload = json.dumps(event, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
            digest = hashlib.sha256(b'hepta.closure.online-event.v1' + bytes.fromhex(previous) + payload).hexdigest()
            assert digest == record['digest']
            if event['kind'] == 'decision':
                assert event['modulator'] == modulator and event['request_id'] not in decisions
                assert all(c['prior_modulator'] == modulator for c in event['candidates'])
                if event['remaining'] == 1:
                    prefix, outcome = episode_continuation.pop(event['episode_id'])
                    assert event['prefix_digest'] == prefix and event['parent_outcome_digest'] == outcome
                else: assert event['remaining'] == 2 and event['parent_outcome_digest'] is None
                decisions[event['request_id']] = digest
            elif event['kind'] == 'outcome':
                assert decisions[event['request_id']] == event['decision_digest']
                if not event['done']:
                    assert event['after_remaining'] == 1
                    episode_continuation[event['episode_id']] = (event['after_public_digest'], digest)
                outcomes.append(event)
            else: assert event['kind'] == 'bootstrap' and index == 0
            previous, modulator = digest, event['modulator']
        assert not episode_continuation
        final = result['process_status'][policy][-1]
        assert final['history_digest'] == previous and final['modulator'] == modulator
        assert len(outcomes) == final['outcomes']
        for row in selected_rows:
            for step in row['steps']:
                tag = f"{row['pair']:04d}-{row['view']}-step{step['step']}"
                decision = read(directory / policy / ('decision-' + tag + '.json'))
                candidates = decision['response']['decision']['candidates']
                assert decision['response']['decision_digest'] == step['decision_digest']
                assert decision['response']['decision']['selected_action'] == step['action']
                assert all(c['prior_modulator'] == step['prior_modulator'] for c in candidates)
                resource.extend(candidates)
                eligible = [c for c in candidates if c['admitted'] and not (step['remaining'] == 1 and c['action'] == 'refine_semantic')]
                if policy == 'ndu':
                    chosen = min(eligible, key=lambda c: (float(c['ndu_moments'][ACTIONS.index(c['action'])]), ACTIONS.index(c['action']))) if eligible else None
                else:
                    priority = dict(zip(ACTIONS, (1, 0, 2, 4, 3)))
                    chosen = max(eligible, key=lambda c: (c['probability_q24'], priority[c['action']])) if eligible else None
                assert (chosen['action'] if chosen else None) == step['action']
                if step['action'] is None:
                    assert step['scores']['utility'] == -1
                    continue
                path = directory / policy / ('outcome-' + tag + '.json'); receipt = read(path)
                assert sha(path) == step['outcome_sha256']
                assert receipt['private_truth_utility_supplied'] is False and 'scores' not in receipt and 'source_ids' not in receipt
                public = receipt['public_observation']
                assert public['target_supplied'] is False and public['factual_correctness_claimed'] is False
                proxy = 1 - (not public['caption_valid']) - public['crossmodal_disagreement']
                assert proxy == public['public_utility'] and receipt['utility_q32'] == round(proxy * 2 ** 32)
                assert receipt['decision_received_ns'] < receipt['generation_started_ns'] < receipt['observed_ns']
                assert step['private_audited_ns'] > result['all_owners_closed_before_private_audit_ns']
                audit_media(receipt['media'], step['media_sha256'], step['scores'])
        projection = audit_projection(directory / policy / 'state/ndu/projection.journal', outcomes, final['objective_digest'])
        audits[policy] = {'decisions': len(decisions), 'observed_outputs': len(outcomes),
                          'native_forwards': len(resource), 'projection': projection,
                          'H1_decisions': sum(s['remaining'] == 1 for r in selected_rows for s in r['steps']),
                          'actual_actions': dict(Counter(s['action'] or 'reject' for r in selected_rows for s in r['steps'])),
                          'teacher_action_parity': all(s['teacher_action_parity'] for r in selected_rows for s in r['steps']) if policy == 'ndu' else None,
                          'admission_changes_to_unmasked_teacher': sum(s['admission_changed_teacher_choice'] for r in selected_rows for s in r['steps']),
                          'all_process_resource_summaries_pass': all(s['native_resource_summary_passed'] for s in result['process_status'][policy]),
                          'maximum_owner_peak_bytes': max(c['owner_peak_bytes'] for c in resource)}
    return rows, audits


def estimate(rows, protocol):
    by = {(r['policy'], r['pair']): r for r in rows if r['view'] != 'both_missing'}
    writers = sorted({r['writer'] for r in rows})
    writer_pairs = {w: sorted({r['pair'] for r in rows if r['writer'] == w}) for w in writers}
    assert len(writers) == 64 and all(len(p) == 2 for p in writer_pairs.values())
    def metrics(policy, pairs):
        values = [by[policy, p] for p in pairs]
        u = np.asarray([r['scores']['utility'] for r in values])
        net = u - .002 * np.asarray([r['continuation_actions'] for r in values])
        return np.asarray([-.5 * np.log(np.exp(-2 * net).mean()), u.mean(),
                           np.mean([correct(r['scores']) for r in values]),
                           np.mean([r['request_ns'] / 1e6 for r in values])])
    names = ('CE_gamma2_after_nominal_action_cost', 'raw_utility', 'joint_correct', 'public_request_ms')
    point = {p: metrics(p, list(range(128))) for p in POLICIES}
    spec = read(protocol)['bootstrap']; rng = np.random.default_rng(spec['seed'])
    differences = []
    for _ in range(spec['draws']):
        sampled = [p for w in rng.choice(writers, len(writers), replace=True) for p in writer_pairs[w]]
        differences.append(metrics('ndu', sampled) - metrics('correctness', sampled))
    bounds = np.quantile(differences, spec['interval'], axis=0)
    summaries = {}
    for policy in POLICIES:
        steps = [s for r in rows if r['policy'] == policy and r['view'] != 'both_missing' for s in r['steps'] if s['action'] is not None]
        confidence = np.asarray([s['selected_confidence_ppm'] / 1e6 for s in steps])
        outcomes = np.asarray([correct(s['scores']) for s in steps])
        summaries[policy] = {**dict(zip(names, point[policy].tolist())),
                             'selected_ECE_ID': ece(confidence, outcomes) if len(steps) else None,
                             'selected_steps': len(steps),
                             'selected_ECE_by_horizon': {str(h): ece(confidence[[s['remaining'] == h for s in steps]], outcomes[[s['remaining'] == h for s in steps]])
                                if any(s['remaining'] == h for s in steps) else None for h in (1, 2)}}
    return {'inference_unit': '64 independent writers with both source pairs retained together',
            'policies': summaries,
            'ndu_minus_same_admission_correctness': {name: {'point': float(point['ndu'][i] - point['correctness'][i]),
                                                       'writer_bootstrap_95CI': bounds[:, i].tolist()} for i, name in enumerate(names)},
            'quality_CE_lower95_positive': bool(bounds[0, 0] > 0),
            'public_cost_difference_upper95_negative': bool(bounds[1, 3] < 0),
            'selected_population_ECE_bound_claimed': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('directory', 'allocation', 'protocol', 'output'): p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args(); rows, audits = audit(a.directory, a.allocation, a.protocol)
    result = {'schema': 'hepta.next.native-h2-audit.v1', 'execution': audits, 'estimates': estimate(rows, a.protocol),
              'source_or_observer_reinference_performed': False, 'protocol_sha256': sha(a.protocol)}
    with a.output.open('x') as stream: json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps(result['estimates']), flush=True)

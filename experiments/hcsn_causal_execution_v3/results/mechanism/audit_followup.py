"""Independent raw-score/identity audit, never trains or selects a model."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def audit(protocol):
    protocol = Path(protocol).resolve()
    plan = json.loads(protocol.read_text())
    result = json.loads(protocol.with_name('RESULTS.json').read_text())
    root = Path(__file__).resolve().parents[4]
    base = protocol.parent
    errors = []
    checked = dict(episodes=0, predictions=0, worker_receipts=0, access_events=0,
                   source_files=0, forced_replay_episodes=0, current_prefix_episodes=0)
    all_seeds, raw_deltas = [], {}

    def require(condition, text):
        if not condition:
            errors.append(text)

    for name, expected in plan['source_sha256'].items():
        require(sha(root / name) == expected, 'source:' + name)
        checked['source_files'] += 1
    for receipt_path in sorted(base.glob('*/receipt.json')):
        receipt = json.loads(receipt_path.read_text())
        require(receipt['exit_code'] == 0, 'exit:' + receipt_path.parent.name)
        require(receipt['protocol_sha256'] == sha(protocol), 'protocol:' + receipt_path.parent.name)
        for name, expected in receipt['output_files_sha256'].items():
            require(sha(receipt_path.parent / name) == expected, 'bytes:' + str(receipt_path.parent / name))
        checked['worker_receipts'] += 1
    for condition in plan['conditions']:
        deltas = []
        for fit_seed in plan['fit_seeds']:
            group = base / f'world_{fit_seed}_{condition}'
            worlds = rows(group / 'worlds.jsonl')
            all_seeds += [w['seed'] for w in worlds]
            by_arm = {}
            for arm in plan['arms']:
                directory = base / f'arm_{fit_seed}_{condition}_{arm}'
                records = rows(directory / 'episodes.jsonl')
                by_arm[arm] = records
                identity = json.loads((directory / 'identity.json').read_text())
                require(identity['worlds_sha256'] == sha(group / 'worlds.jsonl'), 'world_identity:' + directory.name)
                require(len(records) == plan['episodes_per_group'], 'episode_count:' + directory.name)
                for world, row in zip(worlds, records, strict=True):
                    tag = directory.name + ':' + str(row['episode_index'])
                    require(row['world_seed'] == world['seed'], 'world_seed:' + tag)
                    correct, nll, brier = [], [], []
                    require([p['tick'] for p in row['predictions']] == plan['config']['deadlines'], 'deadlines:' + tag)
                    for p in row['predictions']:
                        probs = np.asarray(p['probabilities'], float)
                        truth = world['path']['content'][p['tick']]
                        require(truth == p['truth_for_scoring_only'], 'truth:' + tag)
                        require(np.isfinite(probs).all() and probs.min() >= 0 and abs(probs.sum() - 1) < 1e-10, 'probability:' + tag)
                        correct.append(int(probs.argmax() == truth))
                        nll.append(float(-np.log(max(probs[truth], 1e-12))))
                        brier.append(float(np.square(probs - np.eye(len(probs))[truth]).sum()))
                        checked['predictions'] += 1
                    accesses = row['access']
                    for access in accesses:
                        tick, obs = access['reveal_tick'], access['observed_state']
                        require(access['request_tick'] + 1 == tick, 'read_latency:' + tag)
                        require(obs['x'] == world['path']['x'][tick] and obs['refractory_remaining'] == world['path']['refractory_remaining'][tick], 'observed_state:' + tag)
                        require(obs['content_probs'] == np.eye(plan['config']['classes'])[world['path']['content'][tick]].tolist(), 'observed_content:' + tag)
                        checked['access_events'] += 1
                    reads = sum(r['executed_action'] == 'READ' for r in row['trace'])
                    require(reads == len(accesses) <= plan['config']['budget'], 'read_budget:' + tag)
                    recomputed = dict(accuracy=float(np.mean(correct)), nll=float(np.mean(nll)),
                        brier=float(np.mean(brier)), reads=reads,
                        net_reward=float(np.mean(correct)) - plan['config']['read_cost'] * reads)
                    for name, value in recomputed.items():
                        require(abs(value - row['summary'][name]) < 1e-12, 'score:' + tag + ':' + name)
                    checked['episodes'] += 1
            deltas += [d['summary']['net_reward'] - b['summary']['net_reward']
                       for d, b in zip(by_arm['D'], by_arm['B'], strict=True)]
            for i, reference in enumerate(by_arm['D']):
                schedule = [(r['tick'], r['executed_action']) for r in reference['trace']]
                for replay in ('B_on_D', 'hold_on_D'):
                    require(schedule == [(r['tick'], r['executed_action']) for r in by_arm[replay][i]['trace']], 'forced_replay:' + replay)
                    checked['forced_replay_episodes'] += 1
                reveal = min((a['reveal_tick'] for a in reference['access']), default=plan['config']['ticks'] + 1)
                require([r for r in reference['trace'] if r['tick'] < reveal] ==
                        [r for r in by_arm['D_current'][i]['trace'] if r['tick'] < reveal], 'current_pre_read_prefix')
                checked['current_prefix_episodes'] += 1
        raw_deltas[condition] = float(np.mean(deltas))
        require(abs(raw_deltas[condition] - result['findings'][condition]['contrasts']['D-B']['net_reward']['mean']) < 1e-12, 'aggregate:' + condition)
    require(len(all_seeds) == len(set(all_seeds)), 'world_seed_collision')
    report = dict(passed=not errors, errors=errors, checked=checked,
                  worlds=len(all_seeds), independent_raw_D_minus_B=raw_deltas,
                  auditor_sha256=sha(__file__), protocol_sha256=sha(protocol),
                  no_training_or_model_selection=True)
    target = base / 'RAW_AUDIT.json'
    with target.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps(report, indent=2))
    if errors:
        raise RuntimeError('Raw audit failed; full findings preserved')


if __name__ == '__main__':
    audit(sys.argv[1])

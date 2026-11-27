"""Sensitivity analysis charging the physical initializer and table to its BP budget."""
import argparse
import json
from pathlib import Path

import numpy as np


SEEDS = (109, 271, 463)


def select(data, budget):
    """Read training/development receipts only and record the fully charged selection."""
    physical = data / 'hybrid_long'
    price_table_seconds = json.loads((data / 'prepared.json').read_text())['literal_table_s']
    output = {}
    for seed in SEEDS:
        trial = physical / str(seed)
        if not (trial / f'budget-{budget}.json').is_file():
            raise RuntimeError(f'Seed {seed} has not completed {budget} seconds')
        constructor = data / 'short' / f'literal-{seed}' / 'complete.json'
        constructor_seconds = json.loads(constructor.read_text())['fit_and_dev_s']
        overhead = constructor_seconds + price_table_seconds
        history = [json.loads(row) for row in (trial / 'history.jsonl').read_text().splitlines()]
        eligible = [row for row in history if row['state'] and row['time'] + overhead <= budget]
        winner = max(eligible, key=lambda row: (row['dev_r1'], row['dev_r5'], -row['time']))
        output[str(seed)] = {'table_s': price_table_seconds, 'construct_and_select_s': constructor_seconds,
                             'total_to_selected_s': winner['time'] + overhead, 'winner': winner}
    destination = physical / f'cost-seal-{budget}.json'
    body = json.dumps(output, indent=1)
    if destination.exists() and destination.read_text() != body:
        raise RuntimeError('An existing cost-adjusted selection was different')
    destination.write_text(body)


def confirm(data, budget):
    """Load only the sealed states. Reuse cold ranks by hash if the optima coincide."""
    import torch
    from study import ROOT, gallery, load_model, score, setup_data, sha
    from warm import Towers, embeddings
    from warm_long import initializer

    assert data.resolve() == ROOT.resolve()
    torch.set_num_threads(1)
    owner = data / 'hybrid_long'
    sealed_path = owner / f'cost-seal-{budget}.json'
    sealed = json.loads(sealed_path.read_text())
    original = json.loads((owner / f'seal-{budget}.json').read_text())
    dataset, vision = setup_data()
    ix = gallery(dataset, 2)
    _, _, _, source = initializer()
    model, _ = load_model(source)
    with np.load(data / 'law.npz') as law:
        table = dict(law)
    scores = {}; ranks = {}
    with np.load(owner / f'cold-{budget}.npz') as fixed:
        for seed, row in sealed.items():
            selected = row['winner']
            path = owner / seed / selected['state']
            assert sha(path) == selected['hash']
            same = original[seed]['hash'] == selected['hash']
            if same:
                ranks[seed] = fixed[seed]
            else:
                net = Towers(model, table)
                net.load_state_dict(torch.load(path, map_location='cpu', weights_only=True))
                _, retrieved = score(*embeddings(net, dataset, vision, ix), dataset, ix)
                ranks[seed] = np.stack([retrieved['image_to_text'], retrieved['text_to_image']]).astype('int16')
            metrics = {f'R{k}': float((ranks[seed][:, :, 0] <= k).mean()) for k in (1, 5, 10)}
            scores[seed] = {'same_as_incremental': same, **metrics}
    name = owner / f'cost-ranks-{budget}.npz'
    np.savez_compressed(name, **ranks)
    outcome = {'seal_sha': sha(sealed_path), 'ranks_sha': sha(name), 'budget_s': budget, 'seeds': scores}
    (owner / f'cost-outcome-{budget}.json').write_text(json.dumps(outcome, indent=1))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['select', 'confirm'])
    parser.add_argument('data', type=Path)
    parser.add_argument('budget', type=int)
    args = parser.parse_args()
    (select if args.action == 'select' else confirm)(args.data, args.budget)

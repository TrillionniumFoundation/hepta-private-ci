"""Metered software/cost probe on a separate fixed development context."""
import json
from pathlib import Path
import time

import numpy as np

from .campaign import SPECS, rollout, write
from .controller import Policy
from .world import rates


def main():
    here = Path(__file__).resolve().parent
    out = here / 'results/development_probe001'; out.mkdir()
    candidate = json.loads((here / 'results/run001/candidate_211.json').read_text())
    context, cue, profile, rows = [0., 0.], 2, 1, []
    for name, engine, control, projection, prior_name in SPECS:
        started, cpu = time.perf_counter(), time.process_time()
        policy = Policy(candidate, context, profile, engine, control, projection)
        prior = np.asarray(candidate[prior_name][cue])
        predicted, action, q = policy.solve(prior, 3)
        outcomes = [rollout(policy, prior, rates(context), cue, profile, 0, episode, 556173) for episode in range(16)]
        np.savez_compressed(out / f'{name}.npz', **{key: np.stack([row[i] for row in outcomes]) for i, key in enumerate(('utility', 'correct', 'target', 'actions', 'obs', 'before', 'after', 'events', 'fees', 'durations'))})
        rows.append(dict(arm=name, root_action=action, predicted_root_value=predicted, actual_utility=float(np.mean([r[0] for r in outcomes])), wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu, cache_nodes=len(policy.cache)))
    write(out / 'RESULT.json', dict(context=context, cue=cue, profile=profile, world_seed=556173, episodes=16, rows=rows, scope='Development software/cost probe, not registered confirmation; no source/model/profile revision based on these outcomes'))
    print(json.dumps(rows))


if __name__ == '__main__':
    main()

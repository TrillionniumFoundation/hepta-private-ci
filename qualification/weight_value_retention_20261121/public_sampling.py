"""Public schedules only; no labels, truth tables, model or quality imports."""
import hashlib
import numpy as np
from data_contract import canonical

NAMESPACE = 'hepta-value-retention-20261121/own-law-confirmation/v1'


def seed_for(entropy, selection_sha256, fit, domain):
    return int.from_bytes(hashlib.sha256(entropy + canonical(
        [NAMESPACE, selection_sha256, fit, domain]).encode()).digest(), 'big')


def public_world(rng, domain, prior_distances, identifier):
    # Draw order mirrors pinned run_head_edit.make_worlds; packet assets stay unopened.
    return dict(schema='joint-current-at-due-fixed-deadline-v1', id=identifier,
        deadline=6, initial_budget=3, target_tick=6,
        duration=rng.choice(domain['durations'], 6).tolist(),
        drive=rng.choice(domain['drives'], 6).tolist(),
        reliability=rng.choice(domain['reliabilities'], 6).tolist(),
        read_price=rng.choice(domain['prices'], 6).tolist(),
        read_delay=rng.choice(domain['delays'], 6).tolist(),
        prior_distance=float(rng.choice(prior_distances)),
        latency_price=domain['latency_price'], repair_price=domain['repair_price'],
        failure_probability=domain['failure_probability'],
        packets=[f'not_opened_{j}.json' for j in range(6)], packet_sha256=['0' * 64] * 6)

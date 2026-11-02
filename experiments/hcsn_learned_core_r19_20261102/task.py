"""Fresh R15 owner worlds, exported as causal typed learner observations."""

import hashlib
import json
import numpy as np

from tools.hcsn.addressed_decision_r15_20261101.execution import price
from tools.hcsn.addressed_decision_r15_20261101.law import Law
from tools.hcsn.addressed_decision_r15_20261101.world import make_episode

DURATIONS = np.array([.75, 1.5, 2.25, 1.05, 1.95, 2.85], dtype=np.float64)
THETA = (.30, .018)


def dataset(namespace, count, domain, query_count=6):
    law = Law(theta=THETA)
    rows = []
    for ordinal in range(count):
        seed = namespace * 1000000 + ordinal
        ep = make_episode(law, seed, domain, query_count=query_count)
        aliases = np.random.default_rng(seed ^ 0x5AA5).permutation(4)
        writes, tokens, targets, fees, queries = [], [], [], [], []
        for q, key in enumerate(ep.query_keys):
            events = ep.events_at(q)
            write = next(((e["key"], e["value"]) for e in events if e["kind"] == "WRITE"), (-1, 0))
            writes.append(write)
            # A supplied complete B->A permutation is common routing infrastructure.
            alias = int(np.flatnonzero(aliases == key)[0])
            queries.append(int(aliases[alias]))
            tokens.append(ep.observe(int(key), float(ep.deadlines[q]), "refresh", q, 3))
            targets.append(ep.target(int(key), float(ep.deadlines[q])))
            fees.append(.07 * price(seed, q) + .003 * 3 * ep.dts[q])
        rows.append(dict(initial=ep.initial_values.tolist(), writes=writes, tokens=tokens,
                         targets=targets, fees=fees, keys=queries, aliases=aliases.tolist(),
                         durations=(3 * ep.dts).tolist(), seed=seed, owner=ep.fingerprint))
    result = {name: np.array([r[name] for r in rows]) for name in
              ("initial", "writes", "tokens", "targets", "fees", "keys", "aliases")}
    dt = np.array([r["durations"] for r in rows])
    distance = abs(dt[..., None] - DURATIONS)
    if distance.min(-1).max() > 1e-12:
        raise ValueError("Undeclared duration")
    result["duration_indices"] = distance.argmin(-1)
    result["owner_ids"] = np.array([r["owner"] for r in rows])
    result["seeds"] = np.array([r["seed"] for r in rows], dtype=np.int64)
    identity = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result, identity

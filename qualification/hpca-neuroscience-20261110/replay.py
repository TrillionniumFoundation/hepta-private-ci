"""Fact/episode/procedure/recovery replay diagnostics with source-owner constraints.

Kinds are synthetic labels, not demonstrated biological pathways. Exact-key
ledger read is a non-neural control and may outperform hashed associative heads.
"""
from dataclasses import dataclass
import random
import statistics

KINDS = ("fact", "episode", "procedure", "recovery")
POLICIES = ("exact_key", "recent", "uniform", "stratified", "error_priority")


@dataclass(frozen=True)
class Record:
    key: int
    kind: str
    label: int
    revision: int


def prepare_source(seed):
    world = random.Random(500000 + seed)
    initial = [
        Record(i, KINDS[i % len(KINDS)],
               1 if world.randrange(2) else -1, 1)
        for i in range(24)
    ]
    newer = [
        Record(i, KINDS[i % len(KINDS)],
               1 if world.randrange(2) else -1, 1)
        for i in range(24, 32)
    ]
    # A correction supersedes key 2; keys 1 and 5 have been tombstoned.
    tombstones = frozenset((1, 5))
    old = [r for r in initial if r.key not in tombstones | {2}]
    newer.append(Record(2, initial[2].kind, -initial[2].label, 2))
    index = {r.key: r for r in old + newer}
    assert len(index) == len(old) + len(newer)
    return old, newer, index, tombstones


def current_source_lookup(index, tombstones, key):
    if key in tombstones:
        return None
    return index.get(key)


def bucket(key):
    return (key * 7) % 9


def accuracy(weights, records):
    return statistics.fmean(
        (1 if weights[bucket(r.key)] >= 0 else -1) == r.label
        for r in records
    )


def accuracy_by_kind(weights, records):
    return {
        kind: accuracy(weights, [r for r in records if r.kind == kind])
        for kind in KINDS
    }


def run_replay(seed, policy="uniform", steps=160):
    if policy not in POLICIES or steps <= 0:
        raise ValueError("unknown replay policy")

    old, new, current, tombstones = prepare_source(seed)
    eligible = old + new
    assert all(current_source_lookup(current, tombstones, key) is None
               for key in tombstones)
    assert current[2].revision == 2

    # This non-neural baseline has exact active-key values and does no learning.
    if policy == "exact_key":
        return {
            "old_retention": 1.0, "new_accuracy": 1.0,
            "old_by_kind": {kind: 1.0 for kind in KINDS},
            "new_by_kind": {kind: 1.0 for kind in KINDS},
            "parameter_updates": 0, "selection_reads": len(eligible) + 2,
            "revoked_replayed": 0, "deleted_denied": len(tombstones),
            "reference": "canonical_source_exact_key",
        }

    train_rng = random.Random(600000 + seed)
    replay_rng = random.Random(700000 + seed)
    candidate = [0.0] * 9  # hashed features intentionally suffer collisions
    updates = 0
    reads = 0

    def train(record):
        nonlocal updates
        # Replaying an old correction, deleted source, or another revision fails.
        if record.key in tombstones or current.get(record.key) != record:
            raise AssertionError("stale/revoked training item")
        b = bucket(record.key)
        candidate[b] += 0.15 * (record.label - candidate[b])
        updates += 1

    for _ in range(240):
        train(old[train_rng.randrange(len(old))])

    for t in range(steps):
        train(new[train_rng.randrange(len(new))])
        if policy == "recent":
            selected = new[replay_rng.randrange(len(new))]
            reads += 1
        elif policy == "uniform":
            selected = eligible[replay_rng.randrange(len(eligible))]
            reads += 1
        elif policy == "stratified":
            kind = KINDS[t % len(KINDS)]
            pool = [r for r in old if r.kind == kind]
            selected = pool[replay_rng.randrange(len(pool))]
            reads += len(old)  # cost of selecting the old-kind pool
        else:
            # All compared labels are already in the eligible training snapshot.
            selected = max(
                eligible,
                key=lambda r: (abs(r.label - candidate[bucket(r.key)]), -r.key),
            )
            reads += len(eligible)  # full priority scan is billable
        train(selected)

    assert updates == 240 + steps * 2
    return {
        "old_retention": accuracy(candidate, old),
        "new_accuracy": accuracy(candidate, new),
        "old_by_kind": accuracy_by_kind(candidate, old),
        "new_by_kind": accuracy_by_kind(candidate, new),
        "parameter_updates": updates,
        "selection_reads": reads,
        "revoked_replayed": 0, "deleted_denied": len(tombstones),
        "reference": "collision_limited_candidate_head",
    }

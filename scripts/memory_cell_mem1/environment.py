"""Synthetic owner/evaluator. This is not a live CognitiveStore integration."""

from collections import OrderedDict
from dataclasses import asdict, dataclass
import hashlib
import json
import random

WIDTH, OUTPUTS, POOL_CAPACITY = 16, 8, 24


def commitment(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Fact:
    source: str
    label: int
    version: int = 1
    scope: str = "scope:mem1"
    live: bool = True
    replay: bool = True


@dataclass(frozen=True)
class Experience:
    source: str
    version: int
    key: tuple
    label: int
    step: int
    surprise: float
    task: str
    key_generation: int = 1


class Owner:
    def __init__(self, seed):
        rng = random.Random(seed)
        self.generation = 1
        self.checks = 0
        self.facts = {}
        self.features = {}
        self.previous_labels = {}
        for task in "AB":
            for index in range(12):
                source = f"{task}:{index}"
                self.facts[source] = Fact(source, rng.randrange(OUTPUTS))
                self.features[source] = tuple(
                    rng.choice((-0.25, 0.25)) for _ in range(WIDTH)
                )

    def resolve(self, source, purpose="Recall", version=None):
        self.checks += 1
        if purpose not in {"Recall", "Replay"}:
            raise ValueError("unsupported owner purpose")
        fact = self.facts[source]
        if not fact.live or fact.scope != "scope:mem1":
            return None
        if purpose == "Replay" and not fact.replay:
            return None
        if version is not None and fact.version != version:
            return None
        return fact

    def change_rules_and_revoke(self):
        for index in (8, 9):
            old = self.facts[f"A:{index}"]
            self.previous_labels[old.source] = old.label
            self.facts[old.source] = Fact(
                old.source, (old.label + 3) % OUTPUTS, version=2
            )
        old = self.facts["A:10"]
        self.facts[old.source] = Fact(old.source, old.label, version=2, live=False)
        old = self.facts["A:11"]
        self.facts[old.source] = Fact(
            old.source, old.label, version=2, scope="scope:other"
        )
        self.generation += 1

    def support(self, experience):
        fact = self.resolve(experience.source, "Replay", experience.version)
        if (
            fact is None
            or experience.label != fact.label
            or experience.key_generation != self.generation
        ):
            return None
        return commitment(
            {
                "owner_generation": self.generation,
                "purpose": "Replay",
                "fact": asdict(fact),
                "experience": asdict(experience),
                "encoder": "mem1-fixed-features-v1",
            }
        )


class ReplayPool:
    def __init__(self):
        self.rows = OrderedDict()

    def add(self, experience):
        self.rows.pop(experience.source, None)
        self.rows[experience.source] = experience
        while len(self.rows) > POOL_CAPACITY:
            self.rows.popitem(last=False)

    def eligible(self, owner):
        return [row for row in self.rows.values() if owner.support(row) is not None]

    def sample(self, owner, rng, strategy, step):
        rows = self.eligible(owner)
        if not rows:
            return None
        if strategy == "uniform":
            return rng.choice(rows)
        selector = step % 4
        if selector == 0:
            return max(rows, key=lambda row: row.step)
        if selector == 1:
            return max(rows, key=lambda row: (row.surprise, row.source))
        if selector == 2:
            counts = {
                label: sum(row.label == label for row in rows)
                for label in range(OUTPUTS)
            }
            return min(rows, key=lambda row: (counts[row.label], row.source))
        retention = [row for row in rows if row.task == "A"]
        return rng.choice(retention or rows)

    def payload_bytes(self):
        return len(
            json.dumps(
                [asdict(row) for row in self.rows.values()], sort_keys=True
            ).encode()
        )


def schedule(seed):
    rng = random.Random(seed + 10_000)
    result = []
    for task, count in (("A1", 8), ("B", 8), ("A2", 4)):
        population = [
            f"{'B' if task == 'B' else 'A'}:{index}"
            for index in range(12 if task != "A2" else 10)
        ]
        rows = population * count
        rng.shuffle(rows)
        if task == "B":
            rows = ["A:8", "A:9"] * 4 + rows
        result.append((task, rows))
    return result


def panels():
    return {
        "stable": [(f"A:{i}",) for i in range(8)],
        "superseded": [("A:8",), ("A:9",)],
        "revoked": [("A:10",)],
        "scope": [("A:11",)],
        "composition": [(f"A:{i}", f"B:{(i + 3) % 12}") for i in range(8)],
    }

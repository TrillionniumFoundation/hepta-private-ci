"""P6: learned finite world model + nonanticipative budgeted cognitive control.

RESEARCH_ONLY / DENY_ALL. Synthetic outcomes and token units, not LLM forwards,
not a learned NDU FBSDE, and not independent causal or production evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass, replace
from fractions import Fraction as F
from functools import lru_cache
from pathlib import Path

SCHEMA = "hepta.ndu-merton.p6.world-model-finite-control.v1"
REGIMES = ("easy", "hard")
PROBES = ("bit0", "bit1", "hint", "duplicate")
COST = {"bit0": 1, "bit1": 1, "hint": 2, "duplicate": 1}
ARMS = ("direct", "one_step", "neutral", "fixed_risk", "ndu_discrete", "ordinary_same_profile")
TOTAL_STATES = 2**(len(PROBES) + 1)
MODEL_PRIOR = 1  # declared Laplace pseudocount per full joint state
TRAIN_PER_REGIME = 512
HELD_PER_REGIME = 64
INITIAL_TOKENS = 2
INITIAL_CALLS = 2
TOKEN_TARIFF = F(3, 50)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def json_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=json_unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def bernoulli(seed: str, index: int, channel: str, numerator: int, denominator: int) -> int:
    if not seed or type(index) is not int or index < 0 or not 0 <= numerator <= denominator:
        raise ValueError("invalid deterministic generator arguments")
    raw = hashlib.sha256(f"p6|{seed}|{index}|{channel}".encode()).digest()
    return int(int.from_bytes(raw[:8], "big") * denominator < numerator * (1 << 64))


@dataclass(frozen=True)
class World:
    identity: str
    regime: str
    label: int
    signals: tuple[int, int, int, int]


def world(seed: str, index: int, regime: str) -> World:
    if regime not in REGIMES:
        raise ValueError("unregistered regime")
    a = bernoulli(seed, index, "a", 1, 2)
    b = bernoulli(seed, index, "b", 1, 2)
    label = a ^ b
    error = 0 if regime == "easy" else 1
    z0 = a ^ bernoulli(seed, index, "noise0", error, 5)
    z1 = b ^ bernoulli(seed, index, "noise1", error, 5)
    hint = label ^ bernoulli(seed, index, "noise-hint", 1 if regime == "easy" else 2, 5)
    # Explicit common driver: observing duplicate after bit0 brings no new evidence.
    return World(f"{seed}/{regime}/{index}", regime, label, (z0, z1, hint, z0))


def rows(seed: str, n: int) -> tuple[World, ...]:
    if type(n) is not int or not 1 <= n <= 2000:
        raise ValueError("unsupported split size")
    return tuple(world(seed, i, regime) for regime in REGIMES for i in range(n))


@dataclass(frozen=True)
class Belief:
    regime: str
    seen: tuple[tuple[str, int], ...] = ()
    remaining_tokens: int = INITIAL_TOKENS
    remaining_calls: int = INITIAL_CALLS

    def observe(self, probe: str, bit: int) -> Belief:
        if probe not in PROBES or type(bit) is not int or bit not in (0, 1):
            raise ValueError("invalid observation")
        if probe in dict(self.seen) or COST[probe] > self.remaining_tokens or not self.remaining_calls:
            raise ValueError("repeated or unaffordable observation")
        return replace(self, seen=tuple(sorted(self.seen + ((probe, bit),))),
                       remaining_tokens=self.remaining_tokens-COST[probe],
                       remaining_calls=self.remaining_calls-1)


class FittedWorldModel:
    """Categorical action-conditioned observation law trained on TRAIN only."""
    def __init__(self, counts: dict[str, dict[tuple[int, ...], int]]):
        self.counts = counts
        if set(counts) != set(REGIMES):
            raise ValueError("missing regime")
        for regime in REGIMES:
            if len(counts[regime]) != TOTAL_STATES or any(type(v) is not int or v < MODEL_PRIOR
                                                           for v in counts[regime].values()):
                raise ValueError("unsupported fitted table")
        self.posterior = lru_cache(maxsize=1024)(self._posterior)

    @classmethod
    def train(cls, train_rows: tuple[World, ...]) -> FittedWorldModel:
        counts = {r: {tuple((index >> k) & 1 for k in range(5)): MODEL_PRIOR
                      for index in range(TOTAL_STATES)} for r in REGIMES}
        identities = set()
        for row in train_rows:
            if row.identity in identities or row.regime not in REGIMES or type(row.label) is not int:
                raise ValueError("invalid or repeated training row")
            if len(row.signals) != 4 or any(type(x) is not int or x not in (0, 1) for x in row.signals):
                raise ValueError("invalid training signal")
            identities.add(row.identity)
            counts[row.regime][(row.label, *row.signals)] += 1
        if not train_rows or any(not any(row.regime == r for row in train_rows) for r in REGIMES):
            raise ValueError("incomplete TRAIN distribution")
        return cls(counts)

    def wire(self) -> dict:
        return {"schema": SCHEMA, "train_counts": {regime: [self.counts[regime][tuple((idx >> k) & 1 for k in range(5))]
                for idx in range(TOTAL_STATES)] for regime in REGIMES}}

    def _posterior(self, belief: Belief) -> tuple[tuple[F, tuple[int, ...]], ...]:
        if belief.regime not in REGIMES:
            raise ValueError("unknown observable regime")
        filters = {PROBES.index(key): bit for key, bit in belief.seen}
        weighted = [(n, bits) for bits, n in self.counts[belief.regime].items()
                    if all(bits[index+1] == bit for index, bit in filters.items())]
        total = sum(n for n, _ in weighted)
        if total <= 0:
            raise ValueError("unsupported posterior")
        return tuple((F(n, total), bits) for n, bits in weighted)

    def mass(self, belief: Belief, probe: str) -> tuple[tuple[F, int], ...]:
        if probe not in PROBES:
            raise ValueError("unknown probe")
        posterior = self.posterior(belief)
        idx = 1 + PROBES.index(probe)
        return tuple((p, bit) for bit in (0, 1)
                     if (p := sum((n for n, bits in posterior if bits[idx] == bit), F(0))) > 0)


def alpha(arm: str, belief: Belief, model: FittedWorldModel) -> F:
    if arm in ("direct", "one_step", "neutral"):
        return F(0)
    if arm == "fixed_risk":
        return F(1, 4)
    if arm not in ("ndu_discrete", "ordinary_same_profile"):
        raise ValueError("unknown policy")
    p = sum((mass for mass, bits in model.posterior(belief) if bits[0]), F(0))
    uncertainty = 4 * p * (1-p)
    spent = INITIAL_TOKENS - belief.remaining_tokens
    return min(F(1, 2), F(1, 8) + uncertainty/F(4) + F(spent, 16))


def utility(outcomes: tuple[tuple[F, F], ...], risk: F) -> F:
    if not outcomes or not F(0) <= risk <= F(1, 2):
        raise ValueError("unsupported utility")
    if sum((p for p, _ in outcomes), F(0)) != 1 or any(p <= 0 for p, _ in outcomes):
        raise ValueError("unnormalized transition law")
    return (1-risk)*sum((p*v for p, v in outcomes), F(0)) + risk*min(v for _, v in outcomes)


class Planner:
    def __init__(self, model: FittedWorldModel, arm: str):
        if arm not in ARMS:
            raise ValueError("unregistered arm")
        self.model, self.arm = model, arm
        self.value = lru_cache(maxsize=4096)(self._value)

    def legal(self, belief: Belief) -> tuple[str, ...]:
        return ("abstain", "submit0", "submit1") + tuple(
            x for x in PROBES if x not in dict(belief.seen)
            and COST[x] <= belief.remaining_tokens and belief.remaining_calls > 0)

    def immediate(self, belief: Belief) -> tuple[str, F]:
        scored = [(self._q(belief, a, False), a) for a in ("abstain", "submit0", "submit1")]
        v, a = max(scored, key=lambda x: x[0])
        return a, v

    def _q(self, belief: Belief, action: str, continuation: bool = True) -> F:
        risk = alpha(self.arm, belief, self.model)
        if action == "abstain":
            return F(0)
        if action in ("submit0", "submit1"):
            target = int(action[-1])
            return utility(tuple((p, F(int(bits[0] == target)))
                                 for p, bits in self.model.posterior(belief)), risk)
        if action not in self.legal(belief):
            raise ValueError("illegal action")
        if continuation:
            return utility(tuple((p, -TOKEN_TARIFF*COST[action] + self.value(belief.observe(action, bit))[0])
                                 for p, bit in self.model.mass(belief, action)), risk)
        return utility(tuple((p, -TOKEN_TARIFF*COST[action] + self.immediate(belief.observe(action, bit))[1])
                             for p, bit in self.model.mass(belief, action)), risk)

    def _value(self, belief: Belief) -> tuple[F, str]:
        if self.arm == "direct":
            action, value = self.immediate(belief)
            return value, action
        if self.arm == "one_step":
            options = [(self._q(belief, action, False), action) for action in self.legal(belief)]
        else:
            options = [(self._q(belief, action), action) for action in self.legal(belief)]
        best, chosen = max(options, key=lambda x: x[0])
        return best, chosen

    def choose(self, belief: Belief) -> str:
        return self.value(belief)[1]


def execute(planner: Planner, hidden: World) -> dict:
    """Model sees only public regime + previously purchased bit observations."""
    state = Belief(hidden.regime)
    trace = []
    while True:
        action = planner.choose(state)
        if action not in planner.legal(state):
            raise ValueError("planner chose illegal act")
        if action in PROBES:
            bit = hidden.signals[PROBES.index(action)]
            trace.append({"action": action, "observed": bit,
                          "tokens_before": state.remaining_tokens, "calls_before": state.remaining_calls})
            state = state.observe(action, bit)
            continue
        trace.append({"action": action, "observed": None,
                      "tokens_before": state.remaining_tokens, "calls_before": state.remaining_calls})
        return {"case_id": hidden.identity, "regime": hidden.regime, "arm": planner.arm,
                "trace": trace, "used_tokens": INITIAL_TOKENS-state.remaining_tokens,
                "used_calls": INITIAL_CALLS-state.remaining_calls}


def study(train_seed: str = "p6-train-v1", held_seed: str = "p6-held-v1") -> dict:
    if train_seed == held_seed:
        raise ValueError("TRAIN and HELD seeds must differ")
    training = rows(train_seed, TRAIN_PER_REGIME)
    model = FittedWorldModel.train(training)
    held = rows(held_seed, HELD_PER_REGIME)
    training_ids = {r.identity for r in training}
    if any(r.identity in training_ids for r in held):
        raise ValueError("TRAIN / HELD contamination")
    planners = {arm: Planner(model, arm) for arm in ARMS}
    attempts = [execute(planners[arm], hidden) for hidden in held for arm in ARMS]
    payload = {"schema": SCHEMA, "posture": "RESEARCH_ONLY_DENY_ALL",
               "task_class": "synthetic_xor_binary_probe_not_pretrained_llm",
               "train_seed": train_seed, "held_seed": held_seed,
               "train_per_regime": TRAIN_PER_REGIME, "held_per_regime": HELD_PER_REGIME,
               "training_probes_collected": len(training)*len(PROBES),
               "model": model.wire(), "attempts": attempts,
               "no_claims": ["not_a_learned_FBSDE", "not_physical_token_savings",
                             "not_external_human_outcomes", "not_production_activation"]}
    payload["seal"] = digest(payload)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    attempt = study()
    write_new(args.output, attempt)
    print(f"P6 research-only label-blind attempt: {len(attempt['attempts'])} synthetic-policy episodes; seal={attempt['seal']}")


if __name__ == "__main__":
    main()

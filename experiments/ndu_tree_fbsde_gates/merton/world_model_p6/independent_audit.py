"""Independent, label-opening P6 research auditor; no solver/model imports."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from fractions import Fraction as F
from functools import lru_cache
from pathlib import Path

SCHEMA = "hepta.ndu-merton.p6.world-model-finite-control.v1"
ARMS = ("direct", "one_step", "neutral", "fixed_risk", "ndu_discrete", "ordinary_same_profile")
REGIMES = ("easy", "hard")
PROBES = ("bit0", "bit1", "hint", "duplicate")
COST = (1, 1, 2, 1)
TARIFF = F(3, 50)


def serial(v):
    return json.dumps(v, separators=(",", ":"), sort_keys=True, ensure_ascii=True,
                      allow_nan=False).encode()


def strict_pairs(pairs):
    data = {}
    for k, v in pairs:
        if k in data:
            raise ValueError("duplicate field")
        data[k] = v
    return data


def open_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=strict_pairs,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))


def emit(path, v):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(serial(v) + b"\n")
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def draw(seed, index, name, num, denom):
    data = hashlib.sha256(("p6|" + seed + "|" + str(index) + "|" + name).encode()).hexdigest()[:16]
    return int(int(data, 16) * denom < num * 2**64)


def ground(seed, regime, index):
    a, b = draw(seed, index, "a", 1, 2), draw(seed, index, "b", 1, 2)
    y = a ^ b
    error = 0 if regime == "easy" else 1
    s0 = a ^ draw(seed, index, "noise0", error, 5)
    s1 = b ^ draw(seed, index, "noise1", error, 5)
    hint = y ^ draw(seed, index, "noise-hint", 1 if regime == "easy" else 2, 5)
    return (y, s0, s1, hint, s0)


def expected_table():
    tables = {r: [1] * 32 for r in REGIMES}
    for regime in REGIMES:
        for index in range(512):
            bits = ground("p6-train-v1", regime, index)
            key = sum(bit << i for i, bit in enumerate(bits))
            tables[regime][key] += 1
    return {"schema": SCHEMA, "train_counts": tables}


class IndependentReference:
    """Second mathematical implementation of the full finite public-history policy."""
    def __init__(self, wire, arm):
        self.wire, self.arm = wire, arm
        self.solve = lru_cache(maxsize=8192)(self._solve)
        self.posterior = lru_cache(maxsize=2048)(self._posterior)

    def _posterior(self, state):
        regime, seen, _, _ = state
        observations = dict(seen)
        support = []
        for idx, count in enumerate(self.wire["train_counts"][regime]):
            bits = tuple((idx >> k) & 1 for k in range(5))
            if all(bits[PROBES.index(name)+1] == value for name, value in observations.items()):
                support.append((count, bits))
        denom = sum(n for n, _ in support)
        if denom <= 0:
            raise ValueError("zero likelihood")
        return tuple((F(n, denom), bits) for n, bits in support)

    def actions(self, state):
        _, seen, tokens, calls = state
        used = {name for name, _ in seen}
        return ("abstain", "submit0", "submit1") + tuple(
            name for name, c in zip(PROBES, COST) if name not in used and tokens >= c and calls > 0)

    def risk(self, state):
        if self.arm in ("direct", "one_step", "neutral"):
            return F(0)
        if self.arm == "fixed_risk":
            return F(1, 4)
        p = sum((v for v, bits in self.posterior(state) if bits[0]), F(0))
        return min(F(1, 2), F(1, 8) + p*(1-p) + F(2-state[2], 16))

    @staticmethod
    def aggregator(terms, alpha):
        if not terms or sum((p for p, _ in terms), F(0)) != 1:
            raise ValueError("bad transition")
        return (1-alpha)*sum((p*v for p, v in terms), F(0)) + alpha*min(v for _, v in terms)

    def immediate(self, state):
        return self._choice(state, ("abstain", "submit0", "submit1"), continuation=False)

    def branch(self, state, action, continuation=True):
        risk = self.risk(state)
        if action == "abstain":
            return F(0)
        if action in ("submit0", "submit1"):
            goal = int(action[-1])
            return self.aggregator(tuple((p, F(bits[0] == goal)) for p, bits in self.posterior(state)), risk)
        idx = PROBES.index(action)
        cost = COST[idx]
        by_bit = []
        for bit in (0, 1):
            prob = sum((p for p, bits in self.posterior(state) if bits[idx+1] == bit), F(0))
            if prob <= 0:
                continue
            nxt = (state[0], tuple(sorted(state[1] + ((action, bit),))), state[2]-cost, state[3]-1)
            value = self.solve(nxt)[0] if continuation else self.immediate(nxt)[0]
            by_bit.append((prob, value-TARIFF*cost))
        return self.aggregator(tuple(by_bit), risk)

    def _choice(self, state, actions, continuation):
        ranked = [(self.branch(state, a, continuation), a) for a in actions]
        return max(ranked, key=lambda pair: pair[0])

    def _solve(self, state):
        if self.arm == "direct":
            return self.immediate(state)
        return self._choice(state, self.actions(state), continuation=self.arm != "one_step")


def audit(doc):
    required = {"schema", "posture", "task_class", "train_seed", "held_seed",
                "train_per_regime", "held_per_regime", "training_probes_collected",
                "model", "attempts", "no_claims", "seal"}
    if not isinstance(doc, dict) or set(doc) != required:
        raise ValueError("missing/extra manifest key")
    seal = doc["seal"]
    content = {k: v for k, v in doc.items() if k != "seal"}
    if type(seal) is not str or hashlib.sha256(serial(content)).hexdigest() != seal:
        raise ValueError("mismatched attempt seal")
    if (doc["schema"] != SCHEMA or doc["posture"] != "RESEARCH_ONLY_DENY_ALL"
            or doc["task_class"] != "synthetic_xor_binary_probe_not_pretrained_llm"
            or doc["train_seed"] != "p6-train-v1" or doc["held_seed"] != "p6-held-v1"
            or type(doc["train_per_regime"]) is not int or doc["train_per_regime"] != 512
            or type(doc["held_per_regime"]) is not int or doc["held_per_regime"] != 64
            or type(doc["training_probes_collected"]) is not int or doc["training_probes_collected"] != 4096
            or set(doc["no_claims"]) != {"not_a_learned_FBSDE", "not_physical_token_savings",
                                         "not_external_human_outcomes", "not_production_activation"}):
        raise ValueError("unsupported protocol or source generation")
    model = expected_table()
    if doc["model"] != model or set(doc["model"]) != {"schema", "train_counts"}:
        raise ValueError("TRAIN model is not independently reproducible")
    attempts = doc["attempts"]
    if not isinstance(attempts, list) or len(attempts) != 2*64*len(ARMS):
        raise ValueError("missing or extra online actions")
    references = {a: IndependentReference(model, a) for a in ARMS}
    totals = {a: {"correct": 0, "tokens": 0, "calls": 0, "net": F(0), "abstentions": 0}
              for a in ARMS}
    position = 0
    matched_trace = {}
    for regime in REGIMES:
        for index in range(64):
            bits = ground("p6-held-v1", regime, index)
            case = f"p6-held-v1/{regime}/{index}"
            for arm in ARMS:
                attempt = attempts[position]
                position += 1
                if not isinstance(attempt, dict) or set(attempt) != {"case_id", "regime", "arm", "trace", "used_tokens", "used_calls"}:
                    raise ValueError("invalid attempt shape")
                if attempt["case_id"] != case or attempt["regime"] != regime or attempt["arm"] != arm:
                    raise ValueError("reordered or mislabeled row")
                trace = attempt["trace"]
                if not isinstance(trace, list) or not 1 <= len(trace) <= 3:
                    raise ValueError("missing or unbounded action")
                state = (regime, (), 2, 2)
                answer = None
                for step, entry in enumerate(trace):
                    if not isinstance(entry, dict) or set(entry) != {"action", "observed", "tokens_before", "calls_before"}:
                        raise ValueError("invalid trace entry")
                    chosen = references[arm].solve(state)[1]
                    if (entry["action"] != chosen or type(entry["tokens_before"]) is not int
                            or entry["tokens_before"] != state[2] or type(entry["calls_before"]) is not int
                            or entry["calls_before"] != state[3]):
                        raise ValueError("policy, budget or history violation")
                    if chosen in PROBES:
                        observed = bits[PROBES.index(chosen)+1]
                        if type(entry["observed"]) is not int or entry["observed"] != observed:
                            raise ValueError("forged sensor result")
                        if step == len(trace)-1:
                            raise ValueError("unterminated reasoning")
                        state = (regime, tuple(sorted(state[1] + ((chosen, observed),))),
                                 state[2]-COST[PROBES.index(chosen)], state[3]-1)
                    else:
                        if entry["observed"] is not None or step != len(trace)-1:
                            raise ValueError("malformed terminal action")
                        answer = chosen
                if (type(attempt["used_tokens"]) is not int or attempt["used_tokens"] != 2-state[2]
                        or type(attempt["used_calls"]) is not int or attempt["used_calls"] != 2-state[3]):
                    raise ValueError("falsified resource meter")
                summary = totals[arm]
                correct = int(answer == f"submit{bits[0]}")
                summary["correct"] += correct
                summary["tokens"] += 2-state[2]
                summary["calls"] += 2-state[3]
                summary["abstentions"] += int(answer == "abstain")
                summary["net"] += F(correct) - TARIFF*(2-state[2])
                if arm == "ndu_discrete":
                    matched_trace[case] = trace
                if arm == "ordinary_same_profile" and matched_trace[case] != trace:
                    raise ValueError("NDU/ordinary same-profile parity is mandatory")
    scores = {a: {"accuracy": f"{d['correct']}/128", "correct": d["correct"],
                  "used_probe_tokens": d["tokens"], "used_probe_calls": d["calls"],
                  "abstained": d["abstentions"], "external_net_task_utility": str(d["net"])}
              for a, d in totals.items()}
    return {"schema": "hepta.ndu-merton.p6.independent-synthetic-audit.v1",
            "posture": "RESEARCH_ONLY_DENY_ALL", "source_seal": seal,
            "sampled_held_worlds": 128, "online_policy_episodes": len(attempts),
            "full_train_observation_calls": doc["training_probes_collected"],
            "score": scores, "same_profile_parity": True,
            "claim": "synthetic finite conditional-control comparison only; no LLM or FBSDE training claim"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    summary = audit(open_json(options.attempt))
    emit(options.output, summary)
    print(json.dumps({"audited": summary["online_policy_episodes"], "score": summary["score"]}, sort_keys=True))


if __name__ == "__main__":
    main()

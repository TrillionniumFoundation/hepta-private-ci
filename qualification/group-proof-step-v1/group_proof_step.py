"""Research-only, public-text proof-step Cell pilot.

The grammar-specific parser is a diagnostic Reader, NOT a general language
model. The trainable Cell selects evidence lines; a separate deterministic
transition checker owns state updates. No labels, task.target, private fields,
model weights, or future observations enter its inference interface.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import random
import re
import time

HEADER = re.compile(r"Start at (n[0-9]{1,4}) and follow every link\. What is the endpoint class\? Answer one of A B C D E F G H\.")
LINK = re.compile(r"(n[0-9]{1,4}) links to (n[0-9]{1,4})\.")
LABEL = re.compile(r"(n[0-9]{1,4}) has class ([A-H])\.")
MAX_BYTES = 65_536
MAX_LINES = 64
MAX_HOPS = 32


def digest(value):
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Fact:
    kind: str
    source: str
    value: str
    index: int


@dataclass(frozen=True)
class PublicProof:
    start: str
    facts: tuple[Fact, ...]
    text_sha256: str
    source_group_sha256: str


def parse_public(text):
    """Parse only the visible prompt; reject partial, ambiguous and extra data."""
    if not isinstance(text, str) or not 1 <= len(text.encode()) <= MAX_BYTES:
        raise ValueError("bounded public text required")
    lines = text.splitlines()
    if not 1 <= len(lines) <= MAX_LINES or (match := HEADER.fullmatch(lines[0])) is None:
        raise ValueError("unsupported or ambiguous proof grammar")
    facts, occupied = [], set()
    for index, line in enumerate(lines[1:]):
        if m := LINK.fullmatch(line):
            kind, source, value = "link", *m.groups()
        elif m := LABEL.fullmatch(line):
            kind, source, value = "label", *m.groups()
        else:
            raise ValueError("unrecognized public evidence fact")
        if (kind, source) in occupied:
            raise ValueError("ambiguous duplicate outgoing link or label")
        occupied.add((kind, source))
        facts.append(Fact(kind, source, value, index))
    canonical = json.dumps({"start": match.group(1), "facts": sorted((f.kind, f.source, f.value) for f in facts)},
                           separators=(",", ":"), sort_keys=True)
    return PublicProof(match.group(1), tuple(facts), digest(text), digest(canonical))


def oracle_trace(proof):
    """Grammar oracle for TRAIN-ONLY supervision and independent diagnostics.

    Never call this from the learned policy's inference path.
    """
    if not isinstance(proof, PublicProof):
        raise TypeError("parsed public proof required")
    links = {f.source: f for f in proof.facts if f.kind == "link"}
    labels = {f.source: f for f in proof.facts if f.kind == "label"}
    node, visited, trace = proof.start, set(), []
    for _ in range(MAX_HOPS):
        if node in visited:
            return None, tuple(trace), "cycle"
        visited.add(node)
        if node in links:
            fact = links[node]
            trace.append(fact.index)
            node = fact.value
        elif node in labels:
            fact = labels[node]
            trace.append(fact.index)
            return fact.value, tuple(trace), "supported"
        else:
            return None, tuple(trace), "missing_evidence"
    return None, tuple(trace), "depth_limit"


def _render(proof, excluded=(), replacements=None):
    replacements = replacements or {}
    lines = [f"Start at {proof.start} and follow every link. What is the endpoint class? Answer one of A B C D E F G H."]
    for fact in proof.facts:
        if fact.index in excluded:
            continue
        value = replacements.get(fact.index, fact.value)
        lines.append(f"{fact.source} links to {value}." if fact.kind == "link"
                     else f"{fact.source} has class {value}.")
    return "\n".join(lines)


def counterfactual_panel(text):
    """Four-arm sufficiency plus a fifth truth-flip arm when supported.

    Critical deletion must change the oracle answer or make it unsupported;
    distractor deletion must not. No task-label or answer is supplied to a
    downstream learned Reader. The oracle values are offline diagnostics only.
    """
    proof = parse_public(text)
    answer, steps, status = oracle_trace(proof)
    if status != "supported":
        raise ValueError("counterfactual controls require a supported full source")
    result = {"full": text, "question_only": _render(proof, tuple(f.index for f in proof.facts))}
    critical = next((i for i in steps if oracle_trace(parse_public(_render(proof, (i,))))[0] != answer), None)
    if critical is None:
        raise ValueError("no causally important evidence available")
    result["critical_removed"] = _render(proof, (critical,))
    irrelevant = next((f.index for f in proof.facts if f.index not in steps and
                       oracle_trace(parse_public(_render(proof, (f.index,))))[0] == answer), None)
    if irrelevant is not None:
        result["distractor_removed"] = _render(proof, (irrelevant,))
    terminal = next((f for f in proof.facts if f.index == steps[-1] and f.kind == "label"), None)
    if terminal is not None:
        flipped = chr(65 + (ord(terminal.value) - 64) % 8)
        result["truth_flipped"] = _render(proof, replacements={terminal.index: flipped})
        if oracle_trace(parse_public(result["truth_flipped"]))[0] == answer:
            raise AssertionError("truth intervention failed to flip answer")
    return result


def _features(fact, node, total):
    # No final class, source ID, test label or oracle target is an input.
    return (float(fact.source == node), float(fact.kind == "link"),
            float(fact.kind == "label"), fact.index / max(1, total), 1.0)


def _probabilities(weights, vectors):
    scores = [sum(w * v for w, v in zip(weights, row)) for row in vectors]
    peak = max(scores)
    exps = [math.exp(max(-40.0, score - peak)) for score in scores]
    denom = sum(exps)
    return [x / denom for x in exps]


@dataclass(frozen=True)
class FrozenLinePolicy:
    weights: tuple[float, ...]
    training_source_sha256: tuple[str, ...]
    completed_updates: int
    fitting_cpu_ns: int
    policy_sha256: str


def fit_line_policy(train_texts, *, epochs=12, learning_rate=0.4, seed=41):
    """Actual SGD on public TRAIN proof-step labels only.

    Source groups cannot be duplicated. Caller must enforce disjoint future
    evaluation groups; this routine never accepts evaluation records.
    """
    if type(epochs) is not int or not 1 <= epochs <= 128 or not 0 < learning_rate <= 1:
        raise ValueError("bounded optimizer policy required")
    if not isinstance(train_texts, (list, tuple)) or not 1 <= len(train_texts) <= 4096:
        raise ValueError("bounded training inventory required")
    cases, identities = [], set()
    for text in train_texts:
        proof = parse_public(text)
        if proof.source_group_sha256 in identities:
            raise ValueError("duplicate training source")
        identities.add(proof.source_group_sha256)
        answer, indices, status = oracle_trace(proof)
        if status != "supported" or len(proof.facts) < 2:
            raise ValueError("training only admits independently supportable proofs")
        node, steps = proof.start, []
        for index in indices:
            steps.append((_features(proof.facts[index], node, len(proof.facts)),
                          tuple(_features(f, node, len(proof.facts)) for f in proof.facts)))
            f = proof.facts[index]
            if f.kind == "link":
                node = f.value
        cases.extend(steps)
    start = time.process_time_ns()
    weights, rng, updates = [0.0] * 5, random.Random(seed), 0
    for _ in range(epochs):
        rng.shuffle(cases)
        for target, candidates in cases:
            probs = _probabilities(weights, candidates)
            expectation = [sum(p * row[j] for p, row in zip(probs, candidates)) for j in range(5)]
            for j in range(5):
                weights[j] += learning_rate * (target[j] - expectation[j])
            updates += 1
    cost = time.process_time_ns() - start
    serialized = json.dumps({"weights": weights, "sources": sorted(identities),
                             "updates": updates}, sort_keys=True, separators=(",", ":"))
    return FrozenLinePolicy(tuple(weights), tuple(sorted(identities)), updates, cost, digest(serialized))


def execute_policy(text, policy):
    """No oracle use. A separate transition verifier rejects unsupported moves."""
    if not isinstance(policy, FrozenLinePolicy) or len(policy.weights) != 5 or not all(
        isinstance(x, (int, float)) and math.isfinite(x) for x in policy.weights):
        raise ValueError("frozen policy required")
    canonical = json.dumps({"weights": list(policy.weights), "sources": list(policy.training_source_sha256),
                            "updates": policy.completed_updates}, sort_keys=True, separators=(",", ":"))
    if (digest(canonical) != policy.policy_sha256 or
            len(set(policy.training_source_sha256)) != len(policy.training_source_sha256)):
        raise ValueError("frozen policy identity mismatch")
    proof = parse_public(text)
    if proof.source_group_sha256 in policy.training_source_sha256:
        raise ValueError("train/evaluation source overlap")
    start_ns = time.perf_counter_ns()
    node, visited, choices, scored = proof.start, set(), [], 0
    for _ in range(MAX_HOPS):
        if node in visited:
            status, answer = "cycle", None
            break
        visited.add(node)
        if not proof.facts:
            status, answer = "missing_evidence", None
            break
        vectors = [_features(f, node, len(proof.facts)) for f in proof.facts]
        probs = _probabilities(policy.weights, vectors)
        selected = max(range(len(probs)), key=lambda i: (probs[i], -i))
        fact = proof.facts[selected]
        choices.append(selected)
        scored += len(proof.facts)
        if fact.source != node:
            status, answer = "unsupported_transition", None
            break
        if fact.kind == "label":
            status, answer = "supported", fact.value
            break
        node = fact.value
    else:
        status, answer = "depth_limit", None
    return {"schema": "hepta.group.proof-step-pilot.v1", "status": status, "answer": answer,
            "source_sha256": proof.text_sha256, "source_group_sha256": proof.source_group_sha256,
            "policy_sha256": policy.policy_sha256,
            "selected_fact_indices": choices, "candidate_scores": scored,
            "steps": len(choices), "wall_ns": time.perf_counter_ns() - start_ns,
            "external_effect": False, "native_ndu_integrated": False,
            "general_language_reasoning_established": False}

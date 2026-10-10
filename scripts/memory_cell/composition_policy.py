"""Small evidence-set policy, gated by measured DEVELOPMENT reader readiness.

The eight scalars learn publisher support membership, not semantic non-entailment.
The frozen consumer is plain numeric JSON; it never runs an optimizer at read time.
No readiness result is an independent review or production installation authority.
"""

from dataclasses import asdict
import math
import re
import time

from composition_evidence import parse_json, sha
from native import digest

INITIAL = (1.0, 0.5, 0.0, 0.0, 0.0, -0.25, 0.0, 0.0)
PROFILE = "hepta.composition-membership-policy.v1"
GATE = dict(full_f1_minimum=0.6, evidence_gain_minimum=0.1,
            reversed_f1_minimum=0.6, cases_required=8)


def terms(text):
    return set(re.findall(r"\w+", text.casefold())) - {
        "a", "an", "the", "is", "are", "what", "which", "of", "to", "in", "and"}


def features(question, document, chosen):
    q, d = terms(question.content), terms(document.content)
    used = set().union(*(terms(x.content) for x in chosen)) if chosen else set()
    overlap = len(q & d) / max(1, len(q))
    union = q | d
    return (overlap, len(q & d) / max(1, len(union)),
            -math.log1p(len(document.content.encode())) / 10,
            len((q - used) & d) / max(1, len(q)),
            len((used - q) & d) / max(1, len(d)),
            len(used & d) / max(1, len(used | d)), float(bool(chosen)), 1.0)


def choose(query, documents, weights=INITIAL, *, count=2):
    if type(count) is not int or not 1 <= count <= 8 or len(weights) != 8:
        raise ValueError("bounded selection profile")
    if any(not math.isfinite(w) or abs(w) > 100 for w in weights):
        raise ValueError("invalid policy scalar")
    if not 1 <= len(documents) <= 2000 or len({d.identity for d in documents}) != len(documents):
        raise ValueError("unique bounded candidate view required")
    if any(d.scope != query.scope for d in documents):
        raise ValueError("cross-scope policy view")
    chosen = []
    remaining = list(documents)
    for _ in range(min(count, len(remaining))):
        selected = min(remaining, key=lambda d: (
            -sum(a * b for a, b in zip(weights, features(query, d, chosen))), d.identity))
        chosen.append(selected)
        remaining.remove(selected)
    return tuple(chosen)


def readiness(rows, expected, reader_identity, plan_digest):
    required = {(q, arm) for q in expected for arm in (
        "publisher_pair", "without_fact1", "without_fact2", "pair_reversed",
        "noise_before", "noise_after", "empty", "retrieved1", "retrieved2")}
    if len(expected) != GATE["cases_required"] or len(set(expected)) != len(expected):
        raise ValueError("predeclared capability census required")
    if len(rows) != len(required) or {(r["question_id"], r["arm"]) for r in rows} != required:
        raise ValueError("missing or duplicated readiness case")
    if any(r["phase"] != "capability" for r in rows):
        raise ValueError("readiness must not consume transfer/retention scores")
    means = {}
    for arm in sorted({a for _, a in required}):
        subset = [r for r in rows if r["arm"] == arm]
        values = [r.get("f1") for r in subset]
        if any(v is not None and (type(v) not in (float, int) or not 0 <= v <= 1)
               for v in values):
            raise ValueError("invalid readiness score")
        if any(r["status"] == "succeeded" and
               r["receipt"]["reader_identity"] != reader_identity for r in subset):
            raise ValueError("mixed reader identities")
        means[arm] = sum(v if v is not None else 0 for v in values) / len(values)
    passed = (all(r["status"] == "succeeded" for r in rows)
              and means["publisher_pair"] >= GATE["full_f1_minimum"]
              and means["pair_reversed"] >= GATE["reversed_f1_minimum"]
              and means["publisher_pair"] - means["empty"] >= GATE["evidence_gain_minimum"])
    return dict(profile=GATE, reader_identity=reader_identity, plan_digest=plan_digest,
                means=means, rows_digest=digest(rows), development_ready=passed,
                independent_sufficiency_verified=False, production_accepted=False)


def fit(training_cases, labels, *, gate, plan_digest, forbidden_roots, steps=256):
    import torch
    from native import Document, Question

    if (gate.get("development_ready") is not True or gate.get("profile") != GATE
        or gate.get("plan_digest") != plan_digest or not gate.get("rows_digest")
        or not re.fullmatch(r"[0-9a-f]{64}", gate.get("reader_identity", ""))):
        raise ValueError("reader readiness must precede learning")
    if type(steps) is not int or not 1 <= steps <= 256:
        raise ValueError("update bound")
    prepared, roots, seen = [], set(), set()
    for case in training_cases:
        q = Question(**case["question"])
        if case["phase"] != "train" or q.identity in seen:
            raise ValueError("only unique admitted training cases")
        seen.add(q.identity)
        docs = tuple(Document(**(d | {"assets": tuple(d["assets"])})) for d in case["originals"])
        if digest([asdict(d) for d in docs]) != case["frontier"]:
            raise ValueError("training frontier drift")
        support = set(labels[q.identity]["support_roots"])
        current = {d.root for d in docs}
        if len(support) != 2 or not support <= current or current & forbidden_roots:
            raise ValueError("missing support or training/holdout source leak")
        if any(d.scope != q.scope for d in docs):
            raise ValueError("training scope")
        roots.update(current)
        prepared.append((q, docs, support))
    if not 1 <= len(prepared) <= 128:
        raise ValueError("training case budget")
    prepared.sort(key=lambda x: x[0].identity)
    weight = torch.nn.Parameter(torch.tensor(INITIAL, dtype=torch.float64))
    optimizer = torch.optim.AdamW([weight], lr=0.03)
    before = weight.detach().clone()
    losses, operations = [], 0
    started = time.perf_counter()
    for step in range(steps):
        q, docs, support = prepared[step % len(prepared)]
        selected, remaining, loss = [], list(docs), weight.sum() * 0
        for _ in range(2):
            x = torch.tensor([features(q, d, selected) for d in remaining], dtype=torch.float64)
            logits = x @ weight
            good = [i for i, d in enumerate(remaining) if d.root in support]
            if not good:
                raise ValueError("lost annotated training target")
            loss = loss + torch.logsumexp(logits, 0) - torch.logsumexp(logits[good], 0)
            teacher = sorted(good, key=lambda i: remaining[i].identity)[step % len(good)]
            selected.append(remaining.pop(teacher))
            operations += x.numel() * 6
        loss = loss / 2 + 0.001 * (weight - before).square().sum()
        if not torch.isfinite(loss):
            raise ValueError("nonfinite policy loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_([weight], 1.0, error_if_nonfinite=True)
        optimizer.step()
        if not torch.isfinite(weight).all() or weight.abs().max() > 100:
            raise ValueError("invalid updated policy")
        losses.append(float(loss.detach()))
    delta = float((weight.detach() - before).square().sum())
    if not delta > 0:
        raise ValueError("no policy update")
    return dict(schema=PROFILE, weights=weight.detach().tolist(), roots=sorted(roots),
        plan_digest=plan_digest, reader_identity=gate["reader_identity"],
        capability_gate_digest=digest(gate), training_digest=digest(training_cases),
        updates=len(losses), parameters=8, losses=losses, parameter_delta_squared_norm=delta,
        operation_estimate=operations, train_seconds=time.perf_counter() - started,
        frozen_at_unix_ns=time.time_ns(), test_labels_used=False,
        objective="publisher_support_membership_not_semantic_negatives",
        production_accepted=False)


def load(raw, *, expected_sha, plan_digest, reader_identity, revoked):
    if len(raw) > 128 * 1024 or sha(raw) != expected_sha:
        raise ValueError("policy artifact byte/hash mismatch")
    value = parse_json(raw.decode())
    if (value["schema"] != PROFILE or value["plan_digest"] != plan_digest
        or value["reader_identity"] != reader_identity or value["production_accepted"] is not False
        or not isinstance(value["roots"], list) or len(set(value["roots"])) != len(value["roots"])
        or set(value["roots"]) & revoked or len(value["weights"]) != 8
        or any(type(w) not in (int, float) or not math.isfinite(w) or abs(w) > 100
               for w in value["weights"])):
        raise ValueError("incompatible or revoked frozen policy")
    return tuple(value["weights"])

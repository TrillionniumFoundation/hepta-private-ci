"""Separate target priors and shared-marginal observation dependency models."""

import hashlib

import numpy as np

from .blocks import Capture, JointLaw
from .data import SOURCE_ID


STRENGTHS = (.5, 2., 10., 50., 200., 1000., 4000.)


def project(raw, left, right):
    result = raw.copy()
    for _ in range(2000):
        result *= (left/result.sum(1))[:, None]
        result *= (right/result.sum(0))[None, :]
        if max(abs(result.sum(1)-left).max(), abs(result.sum(0)-right).max()) < 1e-12:
            return result
    raise ArithmeticError("Information projection did not converge")


def capture(row):
    if 'capture' in row:
        return Capture(**row['capture'])
    opaque = hashlib.sha256(row["source_path"].encode()).hexdigest()
    return Capture(SOURCE_ID, opaque, row["event_id"])


def pair_cases(rows):
    lookup = {(r["speaker"], r["target"], r["index"]): r for r in rows}
    result = []
    for speaker in sorted({r["speaker"] for r in rows}):
        for left in range(10):
            for right in range(10):
                for index in range(20):
                    a, b = lookup[speaker, left, index], lookup[speaker, right, (7*index+11) % 20]
                    events = [capture(a).event_id, capture(b).event_id]
                    if events[0] == events[1]:
                        raise ValueError("Distinct-acquisition qualification forbids alias side information")
                    result.append({"sample_id": hashlib.sha256(f"pair/{speaker}/{left}/{right}/{index}".encode()).hexdigest(),
                                   "speaker": speaker, "target": 10*left+right, "events": events,
                                   "values": [a["observation"], b["observation"]]})
    return result


def fit_pair(rows, family, margin, coupling):
    speakers = sorted({r["speaker"] for r in rows})
    positions = {speaker: index for index, speaker in enumerate(speakers)}
    counts = np.zeros((len(speakers), 10, 10))
    identities = {}
    for row in rows:
        event = capture(row).event_id
        detail = (row["speaker"], row["observation"], row["target"], capture(row).content_sha256)
        if event in identities:
            if identities[event] != detail:
                raise ValueError("Conflicting physical event in fitting")
            continue
        identities[event] = detail
        counts[positions[row["speaker"]], row["observation"], row["target"]] += 1
    total = counts.sum(0)
    known = total.sum(0) > 0
    marginals = (total+margin/10)/(total.sum(0)+margin)
    table = np.full((10, 10, 100), np.nan)
    paired = np.zeros_like(table)
    for row in pair_cases(rows):
        paired[*row["values"], row["target"]] += 1
    if coupling is not None:
        conditional = (counts+coupling*marginals[None])/(counts.sum(1)[:, None, :]+coupling)
    for target in range(100):
        left, right = divmod(target, 10)
        if not known[left] or not known[right]:
            continue
        product = np.outer(marginals[:, left], marginals[:, right])
        if coupling is None:
            table[:, :, target] = product
        else:
            if family == "paired":
                raw = paired[:, :, target]+coupling*product
            elif family == "speaker_mixture":
                raw = np.einsum("si,sj->ij", conditional[:, :, left], conditional[:, :, right])
            else:
                raise ValueError("Unknown shared-speaker family")
            table[:, :, target] = project(raw/raw.sum(), marginals[:, left], marginals[:, right])
    return JointLaw(table, ("left", "right"))


def rank_views(row):
    return np.argsort(-np.asarray(row["probabilities"]), kind="stable")[:2].tolist()


def fit_rank(rows, margin, coupling):
    counts = np.zeros((10, 10, 10))
    seen = {}
    for row in rows:
        identity = capture(row).event_id
        detail = (row["target"], rank_views(row), capture(row).content_sha256)
        if identity in seen:
            if seen[identity] != detail:
                raise ValueError("Conflicting views for one fitted acquisition")
            continue
        seen[identity] = detail
        counts[*rank_views(row), row["target"]] += 1
    left, right = counts.sum(1), counts.sum(0)
    known = left.sum(0) > 0
    left = (left+margin/10)/(left.sum(0)+margin)
    right = (right+margin/10)/(right.sum(0)+margin)
    table = np.full_like(counts, np.nan)
    for target in range(10):
        if not known[target]:
            continue
        raw = np.outer(left[:, target], right[:, target])*(1-np.eye(10))
        max_entropy = project(raw, left[:, target], right[:, target])
        if coupling is None:
            table[:, :, target] = max_entropy
        else:
            raw = counts[:, :, target]+coupling*max_entropy
            table[:, :, target] = project(raw/raw.sum(), left[:, target], right[:, target])
    return JointLaw(table, ("top1", "runner_up"))


def score(law, values, targets, prior=None):
    values = np.asarray(values, dtype=int)
    targets = np.asarray(targets, dtype=int)
    likelihood = law.table[values[:, 0], values[:, 1]]
    prior = np.full(law.table.shape[-1], 1/law.table.shape[-1]) if prior is None else np.asarray(prior)
    posterior = likelihood*prior
    posterior /= posterior.sum(1, keepdims=True)
    selected = posterior.argmax(1)
    return np.column_stack((-np.log(likelihood[np.arange(len(targets)), targets]),
                            -np.log(posterior[np.arange(len(targets)), targets]),
                            selected == targets)), posterior


def fit_prior(rows, cue, family, strength):
    permitted = {"sample_id", "speaker", "cue", "target"}
    if any(set(row) != permitted for row in rows):
        raise ValueError("Target prior fitting accepts cue and targets, not observations or event identity")
    counts = np.bincount([r["target"] for r in rows if r["cue"] == cue], minlength=100).reshape(10, 10)
    if family == "joint":
        return ((counts+strength/100)/(counts.sum()+strength)).ravel()
    if family == "factorized":
        left = (counts.sum(1)+strength/10)/(counts.sum()+strength)
        right = (counts.sum(0)+strength/10)/(counts.sum()+strength)
        return np.outer(left, right).ravel()
    raise ValueError("Unknown target-prior family")

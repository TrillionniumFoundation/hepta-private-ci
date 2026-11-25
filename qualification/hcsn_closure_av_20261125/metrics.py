"""Float64 metrics; pairing is exact recording identity, not emotion identity."""

import numpy as np


def classification(logits, labels):
    values = np.asarray(logits, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    if values.shape != (len(y), 6) or not np.isfinite(values).all():
        raise ValueError("finite six-class logits required")
    z = values-values.max(1, keepdims=True)
    p = np.exp(z)/np.exp(z).sum(1, keepdims=True)
    guess = p.argmax(1)
    correct = guess == y
    confidence = p.max(1)
    f1 = []
    for label in range(6):
        tp = np.sum((guess == label) & (y == label))
        denominator = np.sum(guess == label)+np.sum(y == label)
        f1.append(float(2*tp/denominator) if denominator else 0.)
    ece = 0.
    for i in range(10):
        chosen = (confidence >= i/10) & ((confidence < (i+1)/10) if i < 9 else (confidence <= 1))
        if chosen.any():
            ece += chosen.mean()*abs(correct[chosen].mean()-confidence[chosen].mean())
    return {"accuracy": float(correct.mean()), "macro_f1": float(np.mean(f1)),
        "cross_entropy": float((np.log(np.exp(z).sum(1))-z[np.arange(len(y)), y]).mean()),
        "brier": float(np.square(p-np.eye(6)[y]).sum(1).mean()), "ece_10": float(ece)}


def ranks(scores, actor=None):
    x = np.asarray(scores, dtype=np.float64).copy()
    if x.shape[0] != x.shape[1] or not np.isfinite(x).all():
        raise ValueError("finite paired square score matrix required")
    if actor is not None:
        actor = np.asarray(actor)
        x[actor[:, None] != actor[None, :]] = -np.inf
    order = np.argsort(-x, axis=1, kind="stable")
    rank = np.argmax(order == np.arange(len(x))[:, None], axis=1)+1
    return {"recall_at_1": float((rank == 1).mean()), "recall_at_5": float((rank <= 5).mean()),
            "mean_reciprocal_rank": float((1/rank).mean()), "mean_rank": float(rank.mean())}


def compute(output, labels, actor):
    result = {name: classification(output[name+"_logits"], labels) for name in ("fused", "audio", "video")}
    a, v = (np.asarray(output[name+"_embedding"], dtype=np.float64).copy() for name in ("audio", "video"))
    a /= np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
    scores = a@v.T
    for name, matrix in (("audio_to_video", scores), ("video_to_audio", scores.T)):
        result[name] = ranks(matrix)
        result[name+"_within_actor"] = ranks(matrix, actor)
        result[name+"_cross_actor_semantic"] = semantic(matrix, labels, actor)
    result["actor_fused_accuracy"] = {str(key): classification(output["fused_logits"][np.asarray(actor) == key],
        np.asarray(labels)[np.asarray(actor) == key])["accuracy"] for key in np.unique(actor)}
    return result


def semantic(scores, labels, actor):
    """Exclude every gallery clip from the query actor; same emotion is relevant."""
    scores = np.asarray(scores, dtype=np.float64)
    y, actors = np.asarray(labels), np.asarray(actor)
    first, average = [], []
    for i in range(len(y)):
        candidates = np.flatnonzero(actors != actors[i])
        ranking = candidates[np.argsort(-scores[i, candidates], kind="stable")]
        relevant = y[ranking] == y[i]
        if not relevant.any():
            raise ValueError("semantic query lacks cross-actor positives")
        precision = np.cumsum(relevant)/np.arange(1, len(relevant)+1)
        first.append(bool(relevant[0]))
        average.append(float(precision[relevant].mean()))
    return {"class_recall_at_1": float(np.mean(first)), "mean_average_precision": float(np.mean(average)),
            "queries": len(y), "relevance": "same acted emotion; exclude all same-actor candidates"}


def duration_reference(data):
    duration = np.asarray(data["dt_seconds"], dtype=np.float64).sum(1)
    scores = -np.abs(duration[:, None]-duration[None, :])
    return {"scope": "No fitting. Exact shared duration provides a possible paired-recording shortcut; stable lowest-index tie break.",
            "all_candidates": ranks(scores), "within_actor": ranks(scores, data["actor"]),
            "unique_durations": len(np.unique(duration)), "examples": len(duration)}

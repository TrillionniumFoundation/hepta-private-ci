"""Calibration, within-actor retrieval, and outcome-independent pair shuffles."""

import numpy as np

from ..content.study import metrics as classification_metrics


def derangement(size, seed, groups=None):
    if size < 2:
        raise ValueError("A pair intervention requires at least two examples")
    rng = np.random.default_rng(seed)
    result = np.empty(size, dtype=np.int64)
    pools = [np.arange(size)] if groups is None else [np.flatnonzero(groups == group) for group in np.unique(groups)]
    for pool in pools:
        if len(pool) < 2:
            raise ValueError("Each within-actor pool must contain at least two clips")
        order = rng.permutation(pool)
        result[order] = np.roll(order, 1)
    if not np.array_equal(np.sort(result), np.arange(size)) or np.any(result == np.arange(size)):
        raise AssertionError("Declared pair shuffle is not a derangement")
    return result


def retrieval_ranks(audio, video, actors):
    audio, video = np.asarray(audio, np.float64), np.asarray(video, np.float64)
    if audio.shape != video.shape or audio.ndim != 2 or len(actors) != len(audio):
        raise ValueError("Aligned modality embeddings and actor identities required")
    if not np.isfinite(audio).all() or not np.isfinite(video).all():
        raise FloatingPointError("Nonfinite retrieval embedding")
    audio = audio / np.maximum(np.linalg.norm(audio, axis=1, keepdims=True), 1e-12)
    video = video / np.maximum(np.linalg.norm(video, axis=1, keepdims=True), 1e-12)
    similarity = audio @ video.T
    count = len(audio)
    earlier = np.arange(count)[None, :] < np.arange(count)[:, None]
    same_actor = np.asarray(actors)[:, None] == np.asarray(actors)[None, :]
    result = {}
    for direction, scores in (("audio_to_video", similarity), ("video_to_audio", similarity.T)):
        positive = np.diag(scores)[:, None]
        better = (scores > positive) | ((scores == positive) & earlier)
        result[direction+"_whole"] = 1+better.sum(1)
        result[direction+"_same_actor"] = 1+(better & same_actor).sum(1)
    return result, same_actor.sum(1)


def describe_ranks(ranks, candidates):
    ranks = np.asarray(ranks)
    return dict(recall_at1=float(np.mean(ranks <= 1)), recall_at5=float(np.mean(ranks <= 5)),
                mean_reciprocal_rank=float(np.mean(1/ranks)), median_rank=float(np.median(ranks)),
                chance_recall_at1=float(np.mean(1/np.asarray(candidates))),
                candidates_min=int(np.min(candidates)), candidates_max=int(np.max(candidates)))


def evaluation_arrays(outputs, labels, actors, clips, split):
    labels, actors, clips = np.asarray(labels), np.asarray(actors), np.asarray(clips)
    n = len(labels)
    if len(np.unique(clips)) != n or len(actors) != n:
        raise ValueError("Unique paired recording identities are required")
    if split not in ("validation", "test", "synthetic"):
        raise ValueError("Unknown evaluation split")
    seed = 882901+{"validation": 0, "test": 1, "synthetic": 2}[split]
    permutation = derangement(n, seed)
    actor_permutation = derangement(n, seed+1009, actors)
    arrays = {key: np.asarray(value) for key, value in outputs.items()}
    arrays.update(labels=labels, actor=actors, clip=clips,
                  global_derangement=permutation, same_actor_derangement=actor_permutation)
    arrays["fused_global_derangement_logits"] = .5*(arrays["audio_logits"]+arrays["video_logits"][permutation])
    arrays["fused_same_actor_derangement_logits"] = .5*(arrays["audio_logits"]+arrays["video_logits"][actor_permutation])
    classification = {key.removesuffix("_logits"): classification_metrics(value, labels)
                      for key, value in arrays.items() if key.endswith("_logits")}
    ranks, same_counts = retrieval_ranks(arrays["audio_embedding"], arrays["video_embedding"], actors)
    arrays.update({"rank_"+key: value for key, value in ranks.items()})
    retrieval = {key: describe_ranks(value, same_counts if key.endswith("same_actor") else np.full(n, n))
                 for key, value in ranks.items()}
    return arrays, dict(classification=classification, retrieval=retrieval, examples=n,
                       actors=sorted(np.unique(actors).tolist()),
                       shuffle_global_preserves_actor_fraction=float(np.mean(actors == actors[permutation])),
                       shuffle_within_actor_preserves_actor=bool(np.array_equal(actors, actors[actor_permutation])),
                       intervention_scope="Embedding-level mispairing; independent encoders and shared linear head make stored-logit recombination exact")

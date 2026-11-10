"""Bounded semantic ranking and exact-source completion, without evaluator access."""

import re
import time

import numpy as np
from PIL import Image, ImageDraw

from .schema import require, sha
from .semantic_contract import extract_span, validate_text_evidence
from .semantic_data import COLORS, SHAPES, draw_symbol


def current_candidates(packet):
    if not packet["captures"]:
        return []
    current = max(
        packet["captures"], key=lambda c: (c["frame_index"], c["timestamp_micros"])
    )
    return [c for c in packet["candidates"] if c["capture_id"] == current["capture_id"]]


def goal(packet):
    text = packet["instruction"].lower()
    if "changed between frames" in text:
        return {"temporal": True, "shape": None, "color": None}
    shapes = [s for s in SHAPES if re.search(r"\b" + s + r"\b", text)]
    color_text = (
        " ".join(packet["context"]).lower() if "priority color" in text else text
    )
    colors = [c for c in COLORS if re.search(r"\b" + c + r"\b", color_text)]
    require(
        len(shapes) == len(colors) == 1,
        "missing or ambiguous controlled task semantics",
    )
    return {"temporal": False, "shape": shapes[0], "color": colors[0]}


def vectors(packet, embeddings, arm):
    """Use only public task semantics, spatial positions and observed embeddings."""
    require(arm in ("global", "dense"), "unknown neural arm")
    query = goal(packet)
    q = [float(query["shape"] == s) for s in SHAPES]
    q += [float(query["color"] == c) for c in COLORS] + [float(query["temporal"])]
    current = current_candidates(packet)
    require(
        len(current) == 4 and len(embeddings) in (1, 2), "unsupported frame/grid count"
    )
    now, previous = embeddings[-1], embeddings[0] if len(embeddings) > 1 else None
    rows = []
    for index, candidate in enumerate(current):
        v = np.asarray(now[0 if arm == "global" else index], dtype=np.float64)
        p = (
            np.zeros_like(v)
            if previous is None
            else np.asarray(previous[0 if arm == "global" else index], dtype=np.float64)
        )
        capture = next(
            c for c in packet["captures"] if c["capture_id"] == candidate["capture_id"]
        )
        x, y, w, h = candidate["rectangle"]
        rows.append(
            np.r_[
                v,
                p,
                v - p,
                q,
                (x + w / 2) / capture["width"],
                (y + h / 2) / capture["height"],
            ]
        )
    result = np.asarray(rows)
    require(np.isfinite(result).all(), "nonfinite policy features")
    return result


def rule_scores(packet, images):
    """Strong deterministic color/template and frame-difference ranking baseline."""
    query = goal(packet)
    frames = sorted(
        packet["captures"], key=lambda c: (c["frame_index"], c["timestamp_micros"])
    )
    result = []
    for candidate in current_candidates(packet):
        x, y, w, h = candidate["rectangle"]
        crop = np.asarray(
            images[candidate["capture_id"]].crop((x, y, x + w, y + h)), dtype=float
        )
        if query["temporal"]:
            previous = np.asarray(
                images[frames[0]["capture_id"]].crop((x, y, x + w, y + h)), dtype=float
            )
            result.append(float(np.abs(crop - previous).sum()))
            continue
        palette = np.asarray(list(COLORS.values()), dtype=float)
        distances = ((crop[:, :, None, :] - palette) ** 2).sum(axis=3)
        nearest = distances.argmin(axis=2)
        foreground = distances.min(axis=2) < 90**2
        color_index = list(COLORS).index(query["color"])
        mask = foreground & (nearest == color_index)
        if not mask.any():
            result.append(-1.0)
            continue
        ys, xs = np.where(mask)
        cropped = Image.fromarray(
            mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1].astype("uint8") * 255
        )
        observed = np.asarray(cropped.resize((24, 24), Image.Resampling.NEAREST)) > 0
        target = Image.new("L", (24, 24))
        draw_symbol(ImageDraw.Draw(target), query["shape"], 255, (0, 0, 23, 23))
        expected = np.asarray(target) > 0
        overlap = (observed & expected).sum() / max(1, (observed | expected).sum())
        result.append(float(2 + overlap))
    return result


def fit_head(x, labels, *, seed, steps=200, hidden=24):
    """Fit TRAIN-only four-candidate softmax ranking with seeded SGD/momentum."""
    require(1 <= steps <= 2000 and 1 <= hidden <= 64, "training budget exceeds bound")
    started = time.perf_counter_ns()
    x, labels = np.asarray(x, dtype=np.float64), np.asarray(labels, dtype=int)
    require(
        x.ndim == 3 and x.shape[1] == 4 and len(x) == len(labels),
        "training shape mismatch",
    )
    require(
        np.isfinite(x).all() and ((0 <= labels) & (labels < 4)).all(),
        "invalid training rows",
    )
    mean, scale = x.mean(axis=(0, 1)), np.maximum(x.std(axis=(0, 1)), 1e-5)
    x = (x - mean) / scale
    init, order = [
        np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(2)
    ]
    w1 = init.normal(0, (2 / x.shape[2]) ** 0.5, (x.shape[2], hidden))
    b1, w2 = np.zeros(hidden), init.normal(0, hidden**-0.5, hidden)
    initial = sha([w1.tolist(), b1.tolist(), w2.tolist()])
    velocity = [np.zeros_like(v) for v in (w1, b1, w2)]
    trace = []
    for step in range(steps):
        indices = order.choice(len(x), min(len(x), 16), replace=False)
        batch = x[indices]
        a = np.tanh(batch @ w1 + b1)
        logits = a @ w2
        probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        loss = float(
            -np.log(
                np.maximum(
                    probabilities[np.arange(len(indices)), labels[indices]], 1e-300
                )
            ).mean()
        )
        delta = probabilities.copy()
        delta[np.arange(len(indices)), labels[indices]] -= 1
        delta /= len(indices)
        back = delta[:, :, None] * w2 * (1 - a * a)
        gradients = [
            np.einsum("bcd,bch->dh", batch, back),
            back.sum(axis=(0, 1)),
            np.einsum("bc,bch->h", delta, a),
        ]
        norm = np.sqrt(sum(float((g * g).sum()) for g in gradients))
        for i, parameter in enumerate((w1, b1, w2)):
            velocity[i] *= 0.9
            velocity[i] += gradients[i] * min(1.0, 10 / max(norm, 1e-12))
            parameter -= 0.025 * velocity[i]
        require(all(np.isfinite(v).all() for v in (w1, b1, w2)), "nonfinite head")
        trace.append(
            dict(
                step=step + 1,
                batch_sha256=sha(indices.tolist()),
                loss=loss,
                parameters_sha256=sha([w1.tolist(), b1.tolist(), w2.tolist()]),
            )
        )
    return dict(
        schema="perc1.semantic-ranking-head.v1",
        scientific_qualified=False,
        seed=seed,
        normalization=dict(mean=mean.tolist(), scale=scale.tolist()),
        parameters=dict(w1=w1.tolist(), b1=b1.tolist(), w2=w2.tolist()),
        training=dict(
            steps=steps,
            rows=len(x),
            initial_sha256=initial,
            final_sha256=trace[-1]["parameters_sha256"],
            trace=trace,
            elapsed_ns=time.perf_counter_ns() - started,
        ),
    )


def head_scores(head, values):
    p, n = head["parameters"], head["normalization"]
    x = (values - np.asarray(n["mean"])) / np.asarray(n["scale"])
    scores = np.tanh(x @ np.asarray(p["w1"]) + p["b1"]) @ np.asarray(p["w2"])
    require(scores.shape == (4,) and np.isfinite(scores).all(), "invalid head scores")
    return scores.tolist()


def execute(packet, ranking, read_source):
    """Acquire at most the public read cap; exact source fields decide completion.

    read_source accepts only a candidate ID and returns its original source bytes.
    The private evaluator, target candidate and answer never enter this function.
    """
    started = time.perf_counter_ns()
    query = goal(packet)
    candidates = {c["candidate_id"]: c for c in current_candidates(packet)}
    require(
        len(ranking) == len(set(ranking)) and set(ranking) == set(candidates),
        "ranking/catalog mismatch",
    )
    actions, answer = [], None
    for candidate_id in ranking[: packet["read_budget"]]:
        begin = time.perf_counter_ns()
        raw = read_source(candidate_id)
        require(
            type(raw) is bytes and 0 < len(raw) <= 8192, "exact source exceeds bound"
        )
        fields, offset, start, end = {}, 0, None, None
        for line in raw.decode("utf-8").splitlines(keepends=True):
            body = line.rstrip("\r\n")
            require(body.count("=") == 1, "invalid source field delimiter")
            key, value = body.split("=", 1)
            require(key not in fields, "duplicate source field")
            fields[key] = value
            if key == "code":
                start = offset + len(b"code=")
                end = start + len(value.encode())
            offset += len(line.encode())
        require(
            set(fields) == {"color", "shape", "previous_shape", "code"},
            "source field set mismatch",
        )
        require(
            fields["color"] in COLORS
            and fields["shape"] in SHAPES
            and fields["previous_shape"] in SHAPES
            and re.fullmatch(r"[0-9]{1,32}", fields["code"]) is not None,
            "invalid controlled source value",
        )
        candidate = candidates[candidate_id]
        capture = next(
            c for c in packet["captures"] if c["capture_id"] == candidate["capture_id"]
        )
        x, y, w, h = candidate["rectangle"]
        evidence = dict(
            schema="perc1.semantic-text.v1",
            kind="source_text",
            content_sha256=sha(raw),
            fidelity="source_bytes_preserved",
            spans=[
                dict(
                    span_id="code",
                    start=start,
                    end=end,
                    references=[
                        dict(
                            kind="bytes",
                            origin_sha256=sha(raw),
                            start=start,
                            end=end,
                            total=len(raw),
                        ),
                        dict(
                            kind="raster",
                            capture_id=candidate["capture_id"],
                            x=x,
                            y=y,
                            width=w,
                            height=h,
                            frame_index=capture["frame_index"],
                            timestamp_micros=capture["timestamp_micros"],
                        ),
                    ],
                )
            ],
        )
        validate_text_evidence(evidence, raw, packet["captures"])
        matches = (
            (fields["shape"] != fields["previous_shape"])
            if query["temporal"]
            else (
                fields["shape"] == query["shape"] and fields["color"] == query["color"]
            )
        )
        actions.append(
            dict(
                candidate_id=candidate_id,
                raw_text=raw.decode(),
                evidence=evidence,
                elapsed_ns=time.perf_counter_ns() - begin,
                matched=matches,
            )
        )
        if matches:
            answer = dict(
                candidate_id=candidate_id,
                text=extract_span(evidence, raw, "code", packet["captures"]),
                evidence_sha256=sha(evidence),
                span_id="code",
            )
            break
    return dict(
        answer=answer,
        reads=len(actions),
        actions=actions,
        source_bytes=sum(len(a["raw_text"].encode()) for a in actions),
        completion_ns=time.perf_counter_ns() - started,
    )


def rank(packet, scores):
    candidates = current_candidates(packet)
    require(
        len(scores) == len(candidates) and np.isfinite(scores).all(),
        "invalid ranking scores",
    )
    return [
        c["candidate_id"]
        for _, c in sorted(
            zip(scores, candidates),
            key=lambda pair: (-pair[0], pair[1]["candidate_id"]),
        )
    ]

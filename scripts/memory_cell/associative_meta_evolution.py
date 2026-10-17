"""Source-only, bounded trainable MemoryCell graph gate; research/DENY_ALL.

This is NOT a production MemoryCell, a semantic Reader, a source owner, or
proof of self-organizing general memory. Parent and typed children are tiny
numerical routing heads trained on a source-only continuity proxy. Historical
answer/evidence annotations are inaccessible to the producer.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

SCHEMA = "hepta.memory-meta-evolution-shadow.v1"
ARMS = (
    "bm25",
    "temporal",
    "fixed_graph",
    "shared_gate",
    "typed_split",
    "swapped_type",
    "rewired_typed",
)
KIND = ("temporal", "lexical")
DIM = 4
PARAMETERS = 4
PARENT_UPDATES = 128
SPLIT_UPDATES = 256
MAX_TRAIN_EDGES = 512
LR = 0.18
BOUND = 8.0


def source_digest(family, docs):
    import associative_graph_causal as g

    return g.digest(g.canonical({"family": family, "sources": docs}))


def _finite(xs, n):
    return (
        type(xs) is list
        and len(xs) == n
        and all(type(v) is float and math.isfinite(v) and abs(v) <= BOUND for v in xs)
    )


def _features(docs, edge):
    """Observable source-only features; no question/answer/annotation dependence."""
    import associative_graph_causal as g

    kind, i, j, weight = edge
    if (
        kind not in KIND
        or type(i) is not int
        or type(j) is not int
        or i < 0
        or i >= j
        or j >= len(docs)
        or not isinstance(weight, (float, int))
        or not 0 < weight <= 1
    ):
        raise ValueError("invalid registered source edge")
    a = set(t for t in g.words(docs[i]["text"]) if len(t) >= 3 and t not in g.STOPWORDS)
    b = set(t for t in g.words(docs[j]["text"]) if len(t) >= 3 and t not in g.STOPWORDS)
    overlap = len(a & b) / max(1, len(a | b))
    session = docs[i]["session"] == docs[j]["session"]
    temporal = 1.0 / (j - i) if session else 0.0
    is_temporal = 1.0 if kind == "temporal" else 0.0
    return (temporal, overlap, float(weight), is_temporal)


def _proxy(docs, edge, features):
    """Fixed weak self-supervision, *not* downstream relevance or causality."""
    kind, i, j, _ = edge
    # Uses a temporal-continuity proxy and a lexical association proxy.
    # Their arbitrary tradeoff MUST NOT be mistaken for a learned task utility.
    close = 1.0 if (docs[i]["session"] == docs[j]["session"] and j - i == 1) else 0.0
    return min(1.0, max(0.0, 0.65 * close + 0.35 * min(1.0, features[1] * 4)))


def _sigmoid(z):
    return 1 / (1 + math.exp(-max(-20.0, min(20.0, z))))


def _values(f, typed=False, wrong=False):
    if not typed:
        return f
    # Typed child: temporal and lexical heads each use TWO scalar weights.
    # Swapping changes only the routing, never the source edges or parameters.
    temporal = f[3] == 1.0
    if wrong:
        temporal = not temporal
    return (f[0], f[2]) if temporal else (f[1], f[2])


def _score(weights, features):
    return _sigmoid(sum(w * v for w, v in zip(weights, features)))


def _sgd(weights, features, target):
    predicted = _score(weights, features)
    error = (predicted - target) * predicted * (1.0 - predicted)
    return [
        max(-BOUND, min(BOUND, w - LR * error * x)) for w, x in zip(weights, features)
    ]


def _learn(docs, edges, family, *, revoked=()):
    """Produces immutable parent/typed candidates; zero model runtime mutation."""
    if revoked:
        raise ValueError("source-root withdrawal denies all derived candidate heads")
    if not edges or len(docs) < 2 or not re.fullmatch(r"conv-\d{1,4}", family):
        raise ValueError("incomplete authorized source cut")
    ordered = sorted(edges, key=lambda e: (e[1], e[2], e[0]))[:MAX_TRAIN_EDGES]
    if not all(x[0] in KIND for x in ordered) or len({e[0] for e in ordered}) != 2:
        raise ValueError("both registered edge populations are required")
    samples = [(e, _features(docs, e)) for e in ordered]
    targets = [_proxy(docs, e, f) for e, f in samples]
    parent = [0.0] * 4
    child = {"temporal": [0.0, 0.0], "lexical": [0.0, 0.0]}
    # Parent: 128 samples * 4 scalar touches; split: 256 * 2 touches.
    # Different sample counts; equal approximate parameter touches, NOT FLOPs.
    for step in range(PARENT_UPDATES):
        _, f = samples[step % len(samples)]
        parent = _sgd(parent, _values(f), targets[step % len(samples)])
    for step in range(SPLIT_UPDATES):
        edge, f = samples[step % len(samples)]
        route = edge[0]
        child[route] = _sgd(
            child[route], _values(f, typed=True), targets[step % len(samples)]
        )
    roots = sorted(d["id"] for d in docs)
    artifact = {
        "schema": SCHEMA,
        "family": family,
        "source_digest": source_digest(family, docs),
        "source_root_set_digest": hashlib.sha256("\n".join(roots).encode()).hexdigest(),
        "source_root_count": len(roots),
        "encoder": "source-only-token-and-time-features.v1",
        "parent": parent,
        "children": child,
        "parent_updates": PARENT_UPDATES,
        "split_updates": SPLIT_UPDATES,
        "train_edge_count": len(samples),
        "parent_parameter_touches": PARENT_UPDATES * 4,
        "split_parameter_touches": SPLIT_UPDATES * 2,
        "parent_parameters": 4,
        "split_parameters": 4,
        "scope": family,
        "training_labels_visible": False,
        "production_accepted": False,
    }
    verify_artifact(artifact, docs, family)
    return artifact


def verify_artifact(artifact, docs, family, *, revoked=()):
    required = {
        "schema",
        "family",
        "source_digest",
        "source_root_set_digest",
        "source_root_count",
        "encoder",
        "parent",
        "children",
        "parent_updates",
        "split_updates",
        "train_edge_count",
        "parent_parameter_touches",
        "split_parameter_touches",
        "parent_parameters",
        "split_parameters",
        "scope",
        "training_labels_visible",
        "production_accepted",
    }
    roots = sorted(d["id"] for d in docs)
    if (
        not isinstance(artifact, dict)
        or set(artifact) != required
        or artifact["schema"] != SCHEMA
        or artifact["family"] != family
        or artifact["scope"] != family
        or artifact["encoder"] != "source-only-token-and-time-features.v1"
        or artifact["source_digest"] != source_digest(family, docs)
        or artifact["source_root_set_digest"]
        != hashlib.sha256("\n".join(roots).encode()).hexdigest()
        or artifact["source_root_count"] != len(roots)
        or type(artifact["children"]) is not dict
        or set(artifact["children"]) != set(KIND)
        or not _finite(artifact["parent"], 4)
        or any(not _finite(artifact["children"][k], 2) for k in KIND)
        or artifact["parent_updates"] != PARENT_UPDATES
        or artifact["split_updates"] != SPLIT_UPDATES
        or not 0 < artifact["train_edge_count"] <= MAX_TRAIN_EDGES
        or artifact["parent_parameter_touches"] != PARENT_UPDATES * 4
        or artifact["split_parameter_touches"] != SPLIT_UPDATES * 2
        or artifact["parent_parameters"] != PARAMETERS
        or artifact["split_parameters"] != PARAMETERS
        or artifact["training_labels_visible"] is not False
        or artifact["production_accepted"] is not False
    ):
        raise ValueError("candidate mismatched source, scope, shape or budget")
    # Without certified unlearning, revoke the COMPLETE descendant artifact.
    if set(revoked) & set(roots):
        raise ValueError(
            "revoked training root invalidates candidate and split children"
        )


def _new_edges(docs, edges, artifact, *, mode):
    verify_artifact(artifact, docs, artifact["family"])
    results = []
    for edge in edges:
        features = _features(docs, edge)
        if mode == "shared_gate":
            p = _score(artifact["parent"], _values(features))
        elif mode in ("typed_split", "swapped_type"):
            route = (
                edge[0]
                if mode == "typed_split"
                else ("lexical" if edge[0] == "temporal" else "temporal")
            )
            p = _score(
                artifact["children"][route],
                _values(features, typed=True, wrong=(mode == "swapped_type")),
            )
        else:
            raise ValueError("unknown candidate gate")
        # Bounded scores and exactly unchanged endpoints/edge type and count.
        results.append((edge[0], edge[1], edge[2], round(0.10 + 0.85 * p, 8)))
    return tuple(results)


def _rank(docs, query, edges):
    import associative_graph_causal as g

    texts = [d["speaker"] + ": " + d["text"] for d in docs]
    scores = g.bm25_scores(texts, query)
    highest = max(scores, default=0.0)
    normalized = [v / highest if highest > 0 else 0.0 for v in scores]
    boosts = g.propagated(scores, edges)
    combined = [b + 0.92 * boost for b, boost in zip(normalized, boosts)]
    ids = sorted(range(len(docs)), key=lambda i: (-combined[i], docs[i]["id"]))[
        : g.TOP_K
    ]
    return [docs[i]["id"] for i in ids]


def predictions(public):
    import associative_graph_causal as g

    g.validate_public(public)
    rows, artifacts, counts = [], {}, {}
    for section in public["families"]:
        family, docs = section["family"], section["sources"]
        edges = g.graph_edges(docs)
        artifact = _learn(docs, edges, family)
        artifacts[family] = artifact
        counts[family] = Counter(kind for kind, *_ in edges)
        learned = {
            name: _new_edges(docs, edges, artifact, mode=name)
            for name in ("shared_gate", "typed_split", "swapped_type")
        }
        lesion = g.permute_edges(learned["typed_split"], len(docs), family)
        for q in section["questions"]:
            baseline, _ = g.rank_arms(docs, q["text"], family, existing_edges=edges)
            results = {
                name: baseline[name] for name in ("bm25", "temporal", "fixed_graph")
            }
            for name, derived in learned.items():
                results[name] = _rank(docs, q["text"], derived)
            results["rewired_typed"] = _rank(docs, q["text"], lesion)
            rows.append({"family": family, "question_id": q["id"], "arms": results})
    return rows, artifacts, {key: dict(value) for key, value in counts.items()}


def run(public_dir, output_dir):
    import associative_graph_causal as g

    public, manifest = g.load_public(public_dir)
    started = time.perf_counter()
    rows, artifacts, edge_counts = predictions(public)
    elapsed = time.perf_counter() - started
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    journal = {
        "schema": SCHEMA,
        "source_schema": g.SCHEMA,
        "public_sha256": manifest["public_sha256"],
        "arms": list(ARMS),
        "top_k": g.TOP_K,
        "rows": rows,
        "artifacts": artifacts,
        "edge_counts": edge_counts,
    }
    sha = g.create_only(out / "predictions.json", journal)
    seal = {
        "schema": SCHEMA,
        "source_schema": g.SCHEMA,
        "public_sha256": manifest["public_sha256"],
        "predictions_sha256": sha,
        "question_count": len(rows),
        "family_count": len(artifacts),
        "elapsed_seconds": elapsed,
        "trainable_parameters_per_family": PARAMETERS,
        "parent_parameter_touches_per_family": PARENT_UPDATES * 4,
        "split_parameter_touches_per_family": SPLIT_UPDATES * 2,
        "reader_calls": 0,
        "answer_labels_visible": False,
        "full_lifecycle_cost_measured": False,
        "production_accepted": False,
    }
    g.create_only(out / "seal.json", seal)
    return seal


def review(prepared_dir, run_dir, target_file):
    """Source-recompute before opening sealed question evidence annotations."""
    import associative_graph_causal as g

    pub, manifest = g.load_public(prepared_dir, reviewer=True)
    raw = g.regular_bytes(Path(run_dir) / "predictions.json")
    journal = g.strict_load(raw)
    seal = g.strict_load(g.regular_bytes(Path(run_dir) / "seal.json"))
    expected_seal = {
        "schema": SCHEMA,
        "source_schema": g.SCHEMA,
        "public_sha256": manifest["public_sha256"],
        "predictions_sha256": g.digest(raw),
        "question_count": 240,
        "family_count": 10,
        "trainable_parameters_per_family": PARAMETERS,
        "parent_parameter_touches_per_family": PARENT_UPDATES * 4,
        "split_parameter_touches_per_family": SPLIT_UPDATES * 2,
        "reader_calls": 0,
        "answer_labels_visible": False,
        "full_lifecycle_cost_measured": False,
        "production_accepted": False,
    }
    if (
        not isinstance(seal, dict)
        or set(seal) != set(expected_seal) | {"elapsed_seconds"}
        or any(seal[k] != v for k, v in expected_seal.items())
        or type(seal["elapsed_seconds"]) not in (float, int)
        or not math.isfinite(seal["elapsed_seconds"])
        or seal["elapsed_seconds"] < 0
    ):
        raise ValueError("unverified research execution seal")
    rows, artifacts, counts = predictions(pub)
    expected = {
        "schema": SCHEMA,
        "source_schema": g.SCHEMA,
        "public_sha256": manifest["public_sha256"],
        "arms": list(ARMS),
        "top_k": g.TOP_K,
        "rows": rows,
        "artifacts": artifacts,
        "edge_counts": counts,
    }
    if journal != expected or g.canonical(expected) != raw:
        raise ValueError("original source-only prediction or model artifact mismatch")
    private = g.regular_bytes(Path(prepared_dir) / "private.json")
    if g.digest(private) != manifest["private_sha256"]:
        raise ValueError("reference source hash mismatch")
    hidden = g.strict_load(private)
    if (
        not isinstance(hidden, dict)
        or set(hidden) != {"schema", "annotations"}
        or hidden["schema"] != g.SCHEMA
        or set(hidden["annotations"]) != {r["question_id"] for r in rows}
    ):
        raise ValueError("incomplete or drifted reference annotations")
    by_family = {}
    totals = {a: Counter() for a in ARMS}
    sources = {s["family"]: set(d["id"] for d in s["sources"]) for s in pub["families"]}
    for family in sorted(sources):
        by_arm = {a: Counter() for a in ARMS}
        for row in (r for r in rows if r["family"] == family):
            label = hidden["annotations"][row["question_id"]]
            if (
                not isinstance(label, dict)
                or set(label) != {"evidence", "unresolved_reference"}
                or type(label["unresolved_reference"]) is not bool
                or not isinstance(label["evidence"], list)
                or any(
                    not isinstance(s, str) or not re.fullmatch(r"D\d+:\d+", s)
                    for s in label["evidence"]
                )
            ):
                raise ValueError("invalid original evidence annotation")
            refs = set(label["evidence"])
            for arm in ARMS:
                if label["unresolved_reference"]:
                    by_arm[arm]["unresolved"] += 1
                elif not refs:
                    by_arm[arm]["zero_gold"] += 1
                else:
                    retrieved = set(row["arms"][arm])
                    by_arm[arm]["reference_questions"] += 1
                    by_arm[arm]["all_sources_available"] += int(refs <= sources[family])
                    by_arm[arm]["any_at_8"] += int(bool(refs & retrieved))
                    by_arm[arm]["complete_at_8"] += int(refs <= retrieved)
        by_family[family] = {a: dict(c) for a, c in by_arm.items()}
        for arm in ARMS:
            totals[arm].update(by_arm[arm])
    report = {
        "schema": SCHEMA,
        "source_sha256": g.DATASET_SHA256,
        "public_sha256": manifest["public_sha256"],
        "predictions_sha256": g.digest(raw),
        "by_family": by_family,
        "by_arm": {name: dict(counts) for name, counts in totals.items()},
        "effective_independent_families_at_most": 10,
        "retrospective_source_only_proxy": True,
        "language_answers_generated": 0,
        "independent_semantic_judge": False,
        "trained_memory_content": False,
        "learned_graph_topology": False,
        "equal_wall_cost": False,
        "statistical_superiority": False,
        "production_accepted": False,
    }
    g.create_only(target_file, report)
    return report


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 3 and args[0] == "run":
        output = run(args[1], args[2])
    elif len(args) == 4 and args[0] == "review":
        output = review(args[1], args[2], args[3])
    else:
        raise SystemExit(
            "run SOURCE_PUBLIC_DIR NEW_RUN_DIR | review TRUSTED_PREPARED SEALED_RUN NEW_REVIEW"
        )
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

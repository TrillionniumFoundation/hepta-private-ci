"""Recompute six HNMF relation coefficients from the ORIGINAL Torch graph owner.

One candidate-only adapter of amcn_learning.train_relation_router; it never
labels an edge factually true, chooses a topology, manufactures source owners,
or promotes a graph. Independently cross-checks the real SGD coefficient math.
"""
from __future__ import annotations

from hashlib import sha256
from math import exp, isfinite

from amcn_causal_task_audit import bytes_sha, digest, is_sha, require
from amcn_causal_route_plan import GRAPH_PROFILE, RELATIONS


def _valid_training(training, edge_relations, *, expected_training_sha256,
                    forbidden_future_families):
    require(is_sha(expected_training_sha256) and
            digest(training) == expected_training_sha256,
            "externally pinned original graph TRAIN rows changed")
    require(isinstance(training, list) and 4 <= len(training) <= 4096,
            "original graph TRAIN population unavailable")
    require(isinstance(forbidden_future_families, (tuple, list, set, frozenset))
            and all(isinstance(f, str) and f for f in forbidden_future_families),
            "incomplete future family exclusion roster")
    known = set(forbidden_future_families)
    families, labels = set(), set()
    for row in training:
        require(isinstance(row, dict) and set(row) == {
            "relation", "label", "family", "split"},
            "graph trainer received an unapproved supervision field")
        require(row["split"] == "train" and row["relation"] in edge_relations
                and type(row["label"]) is int and row["label"] in (0, 1)
                and isinstance(row["family"], str) and row["family"]
                and row["family"] not in known,
                "graph TRAIN label or future-family contamination")
        labels.add(row["label"])
        families.add(row["family"])
    require(labels == {0, 1} and len(families) >= 2,
            "graph trainer needs two real TRAIN classes and source families")
    return families


def independent_sgd(training, *, steps):
    """Independent scalar recurrence for ORIGINAL six-zero/SGD/BCE-with-logits.

    Uses Python double precision only as a *numerical witness* of the original
    FP32 optimizer; real PyTorch training MUST run separately and match.
    """
    require(type(steps) is int and 1 <= steps <= 1000,
            "registered original SGD step count")
    require(isinstance(training, list) and 4 <= len(training) <= 4096,
            "bounded scalar replay population")
    weights = {name: 0.0 for name in RELATIONS}
    n = len(training)
    for _ in range(steps):
        gradients = {name: 0.0 for name in RELATIONS}
        for row in training:
            require(isinstance(row, dict) and row.get("relation") in RELATIONS
                    and type(row.get("label")) is int
                    and row["label"] in (0, 1),
                    "invalid independent SGD training sample")
            r = row["relation"]
            gradient = (1.0 / (1.0 + exp(-weights[r]))) - row["label"]
            gradients[r] += gradient / n
        for r in RELATIONS:
            weights[r] = max(-8.0, min(8.0, weights[r] - 0.1 * gradients[r]))
    return weights


def _original_sources(case):
    require(isinstance(case, dict) and all(k in case for k in (
            "question_id", "scope", "generation", "eligible_sources")),
            "graph owner original question/scope missing")
    from amcn_core import Evidence
    sources = []
    for row in case["eligible_sources"]:
        require(isinstance(row, dict) and all(k in row for k in (
            "source_id", "source_root", "scope", "generation", "revision",
            "content_sha256", "text", "revoked"))
                and row["scope"] == case["scope"]
                and row["generation"] == case["generation"]
                and row["revoked"] is False
                and row["content_sha256"] == bytes_sha(row["text"].encode("utf-8")),
                "original source graph relation unsupported or stale")
        sources.append(Evidence(
            evidence_id=row["source_id"], source_root=row["source_root"],
            scope=row["scope"], revision=row["revision"], text=row["text"],
            content_sha256=row["content_sha256"],
            generation=row["generation"], revoked=row["revoked"]))
    return sources


def physical_relation_packet(case, registered_edges, original_train_rows,
                             *, expected_train_sha256, expected_graph_sha256,
                             forbidden_future_families, lesion_edge, steps=50,
                             seed=17, tolerance=2e-5):
    """Execute ORIGINAL graph trainer and recheck with independent SGD witness.

    Genuine owner source/label signatures, task benefit and causal relation
    truth are independent external conditions; all outputs remain DENY_ALL.
    """
    from amcn_core import Edge, FrozenGraph
    from amcn_learning import train_relation_router

    require(isinstance(registered_edges, list)
            and 1 <= len(registered_edges) <= 32768,
            "original registered graph edge inventory required")
    edges = []
    for raw in registered_edges:
        require(isinstance(raw, dict) and set(raw) == {
            "source_id", "target_id", "relation", "support_sha256"},
            "original graph edge provenance drift")
        edges.append(Edge(source=raw["source_id"], target=raw["target_id"],
                          relation=raw["relation"],
                          support_sha256=raw["support_sha256"]))
    _valid_training(original_train_rows, {e.relation for e in edges},
                    expected_training_sha256=expected_train_sha256,
                    forbidden_future_families=forbidden_future_families)
    require(type(seed) is int and 0 <= seed < 2**31
            and type(steps) is int and 1 <= steps <= 1000
            and type(tolerance) is float and 0 < tolerance <= 2e-5,
            "unregistered original SGD seed, steps or parity tolerance")
    graph = FrozenGraph(_original_sources(case), edges,
                        scope=case["scope"], generation=case["generation"])
    require(is_sha(expected_graph_sha256)
            and graph.snapshot_digest == expected_graph_sha256,
            "original HNMF source/edge snapshot identity changed")
    # No synthetic or secondary torch operator: call the original AMCN owner.
    weights, receipt = train_relation_router(
        graph, original_train_rows, steps=steps, seed=seed)
    require(isinstance(weights, dict) and set(weights) == set(RELATIONS)
            and all(type(v) is float and isfinite(v) and -8 <= v <= 8
                    for v in weights.values()),
            "original physical trained relation coefficient population invalid")
    expected = independent_sgd(original_train_rows, steps=steps)
    require(all(abs(weights[r] - expected[r]) <= tolerance for r in RELATIONS),
            "original Torch graph coefficients fail independent SGD parity")
    require(isinstance(receipt, dict) and receipt.get("production_accepted") is False
            and isinstance(receipt.get("metrics"), dict),
            "original graph trainer falsely claimed authority")
    metrics = receipt["metrics"]
    require(metrics.get("profile") == "hepta.amcn.fixed-topology-learned-route.v1"
            and metrics.get("graph_sha256") == graph.snapshot_digest
            and metrics.get("candidate_weights_sha256") == digest(weights)
            and metrics.get("optimizer_steps") == steps
            and metrics.get("topology_mutation") is False,
            "original physical Torch graph training receipt drift")
    require(isinstance(lesion_edge, list) and len(lesion_edge) == 3
            and tuple(lesion_edge) in {(e.source, e.target, e.relation)
                                       for e in edges},
            "graph lesion not precommitted in original actual topology")
    inventory = sorted((e.evidence_id, e.source_root, e.revision,
                        e.content_sha256) for e in _original_sources(case))
    frontier_sha = digest(inventory)
    ordered_edges = sorted(registered_edges, key=lambda e: (
        e["source_id"], e["target_id"], e["relation"]))
    return {
        "profile": GRAPH_PROFILE, "question_id": case["question_id"],
        "original_source_frontier_sha256": frontier_sha,
        "edges": ordered_edges, "lesion_edge": lesion_edge,
        "trained_relation_weights": weights,
        "training_receipt": {
            "graph_sha256": digest({"source": frontier_sha,
                                    "edges": ordered_edges}),
            "candidate_weights_sha256": digest(weights),
            "optimizer_steps": steps, "source_training_split": "train",
            "training_source_digest": expected_train_sha256,
            "original_parameter_sha256": digest({
                "optimizer": "torch.optim.SGD", "initial_q": 0,
                "initial_zeros": [0.0] * len(RELATIONS),
                "owner_graph_sha256": graph.snapshot_digest})},
    }

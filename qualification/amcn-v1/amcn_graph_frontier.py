"""Pure, source-bound AMCN experimental graph-frontier comparison.

A fixed label-blind temporal association graph expands BM25 seeds and then
reselects a HARD final Top-K. Does not read publisher labels, execute a Reader,
claim causal edges, install HNMF ABI, or authorize model/graph promotion.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from math import isfinite, log

from amcn_core import Evidence, digest, require, shadow_disposition
from amcn_source_first import (
    MAX_CANDIDATES, MAX_TOTAL_SOURCE_BYTES, MAX_WORDS,
    MAX_QUERY_WORDS, WORDS, lexical_shortlist,
)

PROFILE = "hepta.amcn.fixed-temporal-final-frontier.v1"
MAX_GRAPH_EDGES = 32768
MAX_EXPANSION = 128
MAX_HOPS = 2
SEED_K = 16
FINAL_K = 16
COEFFICIENT = 0.5


def _rank_all(question: str, sources: list[Evidence]):
    terms = sorted(set(WORDS.findall(question.casefold())))
    require(0 < len(terms) <= MAX_QUERY_WORDS, "bounded lexical query")
    bags = []
    document_frequency = Counter()
    for s in sources:
        tokens = WORDS.findall(s.text.casefold())
        require(len(tokens) <= MAX_WORDS, "bounded lexical source tokens")
        bag = Counter(tokens)
        bags.append(bag)
        for t in terms:
            document_frequency[t] += t in bag
    n = len(sources)
    avg = max(1.0, sum(sum(b.values()) for b in bags) / n)
    ranked = []
    for item, bag in zip(sources, bags):
        score = 0.0
        width = sum(bag.values())
        for t in terms:
            tf = bag.get(t, 0)
            if tf:
                df = document_frequency[t]
                score += log(1 + (n - df + 0.5) / (df + 0.5)) * (
                    tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * width / avg))
                )
        require(isfinite(score) and score >= 0, "invalid lexical score")
        ranked.append((item.evidence_id, score))
    ranked.sort(key=lambda z: (-z[1], z[0]))
    return ranked


def _admit_graph(sources: dict[str, Evidence], adjacency):
    require(isinstance(adjacency, dict), "fixed temporal adjacency required")
    require(set(adjacency) <= set(sources), "edge from invalid source")
    graph = {}
    seen = 0
    for sid in sorted(adjacency):
        raw = adjacency[sid]
        require(isinstance(raw, (tuple, list, set, frozenset))
                and all(isinstance(z, str) for z in raw), "adjacency shape")
        neighbors = sorted(raw)
        require(len(neighbors) == len(set(neighbors)), "repeated edge")
        for z in neighbors:
            require(z in sources and z != sid and
                    sources[z].source_root == sources[sid].source_root,
                    "unadmitted cross-root/self edge")
        seen += len(neighbors)
        graph[sid] = neighbors
    require(seen <= MAX_GRAPH_EDGES, "adjacency resource ceiling")
    for sid, out in graph.items():
        for other in out:
            require(sid in graph.get(other, ()), "temporal retrieval edges require reciprocal witness")
    return graph, seen


def freeze_graph_frontier(question, sources, adjacency, *, scope, generation,
                          max_expansion=MAX_EXPANSION):
    """Always rank from entire admitted source inventory, never from gold labels.

    The source-only baseline is the same corpus and BM25 statistic profile for
    Top-16 and Top-64. Graph traversal expands from Top-16, but downstream
    receive IDs for at most 16 source-bound references, never raw source bytes.
    """
    require(type(max_expansion) is int and SEED_K <= max_expansion <= MAX_EXPANSION,
            "fixed candidate expansion budget")
    require(isinstance(sources, (tuple, list))
            and 1 <= len(sources) <= MAX_CANDIDATES, "bounded source inventory")
    require(all(isinstance(s, Evidence) and s.current(scope, generation)
                for s in sources), "stale or foreign source")
    inv = {s.evidence_id: s for s in sources}
    require(len(inv) == len(sources) and
            sum(len(s.text.encode("utf-8")) for s in sources) <= MAX_TOTAL_SOURCE_BYTES,
            "duplicate or oversized source inventory")
    ordered = [inv[x] for x in sorted(inv)]
    graph, edge_count = _admit_graph(inv, adjacency)
    all_ranked = _rank_all(question, ordered)
    sourcefirst = lexical_shortlist(question, ordered, scope=scope,
                                   generation=generation, top_k=min(SEED_K, len(ordered)))
    seeds = all_ranked[:SEED_K]
    require(sourcefirst["ranked_source_ids"] == [sid for sid, _ in seeds],
            "BM25 implementation discrepancy")
    seed_scores = dict(seeds)
    base_scores = dict(all_ranked)
    touched = {s for s, _ in seeds}
    propagated = defaultdict(float)
    queue = deque((sid, 0, sid) for sid, _ in seeds)
    while queue:
        current, depth, original_seed = queue.popleft()
        if depth >= MAX_HOPS:
            continue
        for neighbor in graph.get(current, ()):
            new_depth = depth + 1
            if neighbor not in seed_scores:
                propagated[neighbor] = max(
                    propagated[neighbor], seed_scores[original_seed] / new_depth)
            if neighbor in touched:
                continue
            # Fail BEFORE truncating graph and pretending it was exhaustive.
            require(len(touched) < max_expansion, "expansion cap exceeded; no partial recall")
            touched.add(neighbor)
            queue.append((neighbor, new_depth, original_seed))
    ranked = sorted(touched, key=lambda sid:
                    (-(base_scores[sid] + COEFFICIENT * propagated[sid]), sid))
    final = ranked[:FINAL_K]
    starts = [sid for sid, _ in seeds]
    all_bytes = sum(len(s.text.encode("utf-8")) for s in ordered)
    expanded_bytes = sum(len(inv[sid].text.encode("utf-8")) for sid in touched)
    final_bytes = sum(len(inv[sid].text.encode("utf-8")) for sid in final)
    manifest = sorted((s.evidence_id, s.source_root, s.revision,
                       s.content_sha256) for s in ordered)
    return shadow_disposition(
        profile=PROFILE, query_sha256=digest(question),
        scope=scope, generation=generation,
        source_inventory_sha256=digest(manifest),
        source_first_plan_sha256=digest(sourcefirst),
        graph_adjacency_sha256=digest(graph),
        admitted_temporal_edges=edge_count,
        retrieval_semantics="symmetrical temporal neighbors; not causal truth",
        propagation_coefficient=COEFFICIENT, hops=MAX_HOPS,
        seeds=starts, lexical_top64=[sid for sid, _ in all_ranked[:64]],
        expanded_ids=sorted(touched), final_source_ids=final,
        full_source_count=len(ordered), expanded_node_count=len(touched),
        final_evidence_count=len(final),
        input_corpus_bytes=all_bytes, expanded_source_bytes=expanded_bytes,
        final_source_bytes=final_bytes,
        score_field="BM25(full-snapshot) + 0.5 * bounded_temporal_propagation",
        original_source_ids_and_digests=[
            (sid, inv[sid].revision, inv[sid].content_sha256) for sid in final
        ],
        actual_reader_calls=0, final_reader_tokens=None,
        independent_source_entailment_verified=False,
        labels_accessed=False, topology_update=False,
    )


def score_publisher_weak_only(frozen_packet, publisher_support):
    """Post-seal descriptive scoring only; never grants a truth or utility label."""
    require(isinstance(frozen_packet, dict) and frozen_packet.get("schema") == "hepta.amcn.shadow.v1"
            and frozen_packet.get("production_accepted") is False,
            "research packet required")
    p = frozen_packet.get("metrics")
    require(isinstance(p, dict) and p.get("profile") == PROFILE and
            p.get("labels_accessed") is False, "not label-blind graph plan")
    require(isinstance(publisher_support, (list, tuple)) and len(publisher_support) <= MAX_CANDIDATES
            and all(isinstance(x, str) and x for x in publisher_support)
            and len(set(publisher_support)) == len(publisher_support),
            "publisher reference IDs invalid")
    weak_support = set(publisher_support)
    def evaluate(ids):
        recovered = len(set(ids) & weak_support)
        return {"any_support": recovered > 0,
                "all_support": recovered == len(weak_support) if weak_support else None,
                "supported_count": recovered,
                "annotated_support_total": len(weak_support),
                "publisher_recall": recovered / len(weak_support) if weak_support else None}
    return shadow_disposition(
        profile=PROFILE + ".publisher-weak-score.v1",
        frozen_plan_sha256=digest(frozen_packet),
        lexical_top16=evaluate(p["seeds"]),
        lexical_top64=evaluate(p["lexical_top64"]),
        temporal_expand=evaluate(p["expanded_ids"]),
        graph_final_top16=evaluate(p["final_source_ids"]),
        original_source_bytes_expanded=p["expanded_source_bytes"],
        original_source_bytes_delivered=p["final_source_bytes"],
        model_answer_evaluated=False, true_future_calendar_windows=0,
        publisher_support_not_independent_human_entailment=True,
    )

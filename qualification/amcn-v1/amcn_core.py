"""AMCN research-only evidence contracts and fixed HNMF graph controls.

No memory writer, source authority, online training, model selection or FinalUse.
Actual authorizations and independent evidence reviews remain with existing Hepta owners.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from collections import defaultdict, deque
from math import isfinite, log
import json
import re

ARMS = ("no_evidence", "ordinary_retrieval", "human_sufficient", "critical_premise_removed")
SPLITS = ("train", "select", "future_a", "future_b", "retention")
RELATIONS = ("supports", "temporal", "causal_candidate", "procedural", "associative", "contradicts")
SCHEMA = "hepta.amcn.shadow.v1"
MAX_SOURCES = 512
MAX_EDGES = 32768
MAX_HOPS = 2


class Refused(ValueError):
    """Inadmissible research input: fail before making or exposing a result."""


def require(ok, why):
    if not ok:
        raise Refused(why)


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(data):
    return sha256(canonical(data)).hexdigest()


def is_sha(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_root: str
    scope: str
    revision: int
    text: str
    content_sha256: str
    generation: str
    revoked: bool = False

    def __post_init__(self):
        require(all(isinstance(x, str) and 0 < len(x) <= 256 for x in
                    (self.evidence_id, self.source_root, self.scope, self.generation)), "evidence identity")
        require(type(self.revision) is int and self.revision >= 1, "source revision")
        require(isinstance(self.text, str) and len(self.text.encode("utf-8")) <= 32768, "evidence bytes")
        require(is_sha(self.content_sha256)
                and self.content_sha256 == sha256(self.text.encode("utf-8")).hexdigest(),
                "evidence content digest")
        require(type(self.revoked) is bool, "revocation field")

    def current(self, scope, generation, *, current_revision=None):
        if self.revoked or self.scope != scope or self.generation != generation:
            return False
        return current_revision is None or current_revision == self.revision


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    support_sha256: str

    def __post_init__(self):
        require(self.source != self.target and self.relation in RELATIONS
                and is_sha(self.support_sha256), "invalid supported edge")


class FrozenGraph:
    """Immutable, generation-fenced research projection. Edge weights are not facts."""
    def __init__(self, sources, edges, *, scope, generation):
        require(isinstance(sources, (list, tuple)) and 1 <= len(sources) <= MAX_SOURCES,
                "bounded source inventory")
        require(isinstance(edges, (list, tuple)) and len(edges) <= MAX_EDGES, "edge count")
        self.sources = {}
        for item in sources:
            require(isinstance(item, Evidence) and item.scope == scope
                    and item.generation == generation and not item.revoked, "stale or foreign source")
            require(item.evidence_id not in self.sources, "duplicate source")
            self.sources[item.evidence_id] = item
        seen = set()
        self.edges = []
        for edge in edges:
            require(isinstance(edge, Edge) and edge.source in self.sources
                    and edge.target in self.sources, "dangling edge")
            key = (edge.source, edge.target, edge.relation)
            require(key not in seen, "duplicate edge")
            seen.add(key)
            self.edges.append(edge)
        self.edges.sort(key=lambda e: (e.source, e.target, e.relation))
        self.scope, self.generation = scope, generation
        self.snapshot_digest = digest({
            "scope": scope, "generation": generation,
            "sources": [(x.evidence_id, x.revision, x.content_sha256)
                        for x in sorted(self.sources.values(), key=lambda x: x.evidence_id)],
            "edges": [(e.source, e.target, e.relation, e.support_sha256) for e in self.edges],
        })
        self.adjacency = defaultdict(list)
        for edge in self.edges:
            if edge.relation != "contradicts":
                self.adjacency[edge.source].append(edge.target)

    def candidates(self, starting_ids, *, maximum_hops=MAX_HOPS, maximum_results=16):
        require(type(maximum_hops) is int and 0 <= maximum_hops <= MAX_HOPS, "hop bound")
        require(type(maximum_results) is int and 1 <= maximum_results <= 16, "result bound")
        starting = list(starting_ids)
        require(starting and all(x in self.sources for x in starting), "unknown start")
        queue = deque((x, 0) for x in sorted(set(starting)))
        visited, out = set(), []
        while queue and len(out) < maximum_results:
            node, depth = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            out.append(node)
            if depth < maximum_hops:
                queue.extend((dest, depth + 1) for dest in sorted(self.adjacency[node]))
        return out

    def revalidate(self, latest_by_id, *, scope, generation):
        require(scope == self.scope and generation == self.generation, "frontier drift")
        for eid, source in self.sources.items():
            current = latest_by_id.get(eid)
            require(isinstance(current, Evidence) and current.current(scope, generation,
                    current_revision=source.revision)
                    and current.content_sha256 == source.content_sha256,
                    "revoked or changed evidence")
        return True


def freeze_reader_quartets(rows):
    """Sanity-check four original execution requests, never author a human verdict.

    The independently authenticated reviewer intake is upstream; a receipt digest
    here is only a binding, not proof of human independence or entailment.
    """
    require(isinstance(rows, list) and rows, "nonempty reader requests")
    groups, roots, ids = defaultdict(dict), defaultdict(set), set()
    needed = {"case_id", "family", "split", "arm", "reader_sha256", "prompt_sha256",
              "question_sha256", "max_input_tokens", "max_new_tokens",
              "source_frontier_sha256", "evidence_ids", "review_receipt_sha256"}
    for row in rows:
        require(isinstance(row, dict) and set(row) == needed, "reader record shape")
        require(all(isinstance(row[k], str) and row[k] for k in ("case_id", "family", "split")),
                "case/family/split")
        require(row["split"] in SPLITS and row["arm"] in ARMS, "unknown split/arm")
        require(all(is_sha(row[k]) for k in ("reader_sha256", "prompt_sha256",
                "question_sha256", "source_frontier_sha256")), "request identity")
        require(type(row["max_input_tokens"]) is int and 1 <= row["max_input_tokens"] <= 32768,
                "reader input budget")
        require(type(row["max_new_tokens"]) is int and 1 <= row["max_new_tokens"] <= 4096,
                "reader output budget")
        require(isinstance(row["evidence_ids"], list)
                and len(row["evidence_ids"]) <= 512
                and all(isinstance(x, str) and x for x in row["evidence_ids"])
                and len(set(row["evidence_ids"])) == len(row["evidence_ids"]), "evidence set")
        if row["arm"] in ("human_sufficient", "critical_premise_removed"):
            require(is_sha(row["review_receipt_sha256"]), "missing external human-review binding")
        else:
            require(row["review_receipt_sha256"] is None, "unexpected review claim")
        key = (row["case_id"], row["split"])
        require(row["arm"] not in groups[key], "duplicate arm")
        groups[key][row["arm"]] = row
        ids.add(row["case_id"])
        roots[row["family"]].add(row["split"])
    require(len(ids) == len(groups), "same case ID reused between splits")
    for family, splits in roots.items():
        require(not (set(splits) & {"future_a", "future_b"} and len(splits) != 1),
                "future family overlaps other splits")
    for key, group in groups.items():
        require(set(group) == set(ARMS), "missing four-arm comparison")
        a, b, c, d = [group[x] for x in ARMS]
        for name in ("family", "reader_sha256", "prompt_sha256", "question_sha256",
                     "max_input_tokens", "max_new_tokens", "source_frontier_sha256"):
            require(a[name] == b[name] == c[name] == d[name], "unmatched reader")
        require(a["evidence_ids"] == [], "no-evidence arm carries sources")
        assert_ids, removed_ids = set(c["evidence_ids"]), set(d["evidence_ids"])
        require(assert_ids and removed_ids < assert_ids, "critical premise not strictly removed")
        require(c["review_receipt_sha256"] == d["review_receipt_sha256"],
                "mismatched independent review binding")
    return {"schema": SCHEMA + ".reader_quartets",
            "request_sha256": digest(rows), "cases": len(groups),
            "arms": len(rows), "review_semantics_verified": False,
            "reader_capability_qualified": False}


def bm25(query, sources, *, scope, generation, maximum=16):
    """Transparent lexical CONTROL only, not a strong tuned hybrid-RAG claim."""
    require(type(maximum) is int and 1 <= maximum <= 16, "k")
    words = re.findall(r"\w+", query.casefold())
    require(words and len(words) <= 4096, "query")
    usable = [s for s in sources if s.current(scope, generation)]
    require(len(usable) <= MAX_SOURCES, "source bound")
    if not usable:
        return []
    docs = [re.findall(r"\w+", item.text.casefold()) for item in usable]
    avg = max(1.0, sum(len(x) for x in docs) / len(docs))
    dfs = {t: sum(t in d for d in docs) for t in set(words)}
    results = []
    for source, doc in zip(usable, docs):
        score = 0.0
        for t in set(words):
            tf = doc.count(t)
            if tf:
                idf = log(1 + (len(docs) - dfs[t] + 0.5) / (dfs[t] + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(doc) / avg))
        results.append((source.evidence_id, score))
    results.sort(key=lambda r: (-r[1], r[0]))
    return results[:maximum]


def bounded_route(graph, seeds, *, mode, edge_weights=None, maximum=16):
    require(mode in ("independent", "fixed_graph", "learned_router"), "router mode")
    if mode == "independent":
        require(all(s in graph.sources for s in seeds), "unknown starting evidence")
        return sorted(set(seeds))[:maximum]
    if mode == "fixed_graph":
        return graph.candidates(seeds, maximum_results=maximum)
    require(isinstance(edge_weights, dict) and set(edge_weights) == set(RELATIONS),
            "complete frozen relation-weight profile")
    require(all(type(v) in (float, int) and isfinite(v) and -8 <= v <= 8
                for v in edge_weights.values()), "relation weights")
    require(all(s in graph.sources for s in seeds), "unknown seed")
    ranks = {s: 1.0 for s in seeds}
    for e in graph.edges:
        if e.source in seeds and e.relation != "contradicts":
            ranks[e.target] = max(ranks.get(e.target, float("-inf")),
                                  1.0 + edge_weights[e.relation])
    return sorted(ranks, key=lambda s: (-ranks[s], s))[:maximum]


def shadow_disposition(**metrics):
    """Never create acceptance authority from numerical experiment records."""
    return {"schema": SCHEMA, "metrics": metrics, "production_accepted": False,
            "qualified_for_parameter_memory": False,
            "independent_semantic_citation_precision": None,
            "future_windows_verified": False,
            "independent_evaluator_accepted": False}

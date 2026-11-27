"""Sanitized post-run retrieval derivative; no network or answer generation.

Ranking, tokenizer, PRF, graph selection, hash control and packing mechanics
are retained from the measured code. This is not the original run artifact.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping

VERSION = "sanitized-pilot-evaluator-v1"
PRIMARY_ARMS = ("bm25", "prf", "links", "hash_links")
ARMS = PRIMARY_ARMS + ("bm25_top8",)
BYTE_CAP = 8192
TOKEN_RE = re.compile(r"[a-z0-9]+")


def terms(text: str) -> list[str]:
    """Exact v2 tokenizer: Python lower, followed by ASCII alphanumeric runs."""
    return TOKEN_RE.findall(text.lower())


class BM25Index:
    """Reusable sparse postings index; stable sorted unique query terms and ID ties."""

    def __init__(self, documents: Mapping[str, str]):
        self.ids = tuple(sorted(documents))
        self.n = len(self.ids)
        self.counts = {i: Counter(terms(documents[i])) for i in self.ids}
        self.lengths = {i: sum(self.counts[i].values()) for i in self.ids}
        self.average_length = sum(self.lengths.values()) / self.n if self.n else 0
        self.postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for i in self.ids:
            for term, frequency in self.counts[i].items():
                self.postings[term].append((i, frequency))
        self.df = {term: len(postings) for term, postings in self.postings.items()}
        self.idf = {
            term: math.log(1 + (self.n - frequency + .5) / (frequency + .5))
            for term, frequency in self.df.items()
        }
        self.norm = {
            i: 1.2 * (.25 + .75 * self.lengths[i] / (self.average_length or 1))
            for i in self.ids
        }

    def scores(self, query: str) -> dict[str, float]:
        contributions = {i: [] for i in self.ids}
        # Same per-document summation order as the reference's sum(sorted(q)).
        for term in sorted(set(terms(query))):
            for i, frequency in self.postings.get(term, ()):
                contributions[i].append(self.idf[term] * frequency * 2.2 / (frequency + self.norm[i]))
        # Built-in sum is intentional: Python 3.12+ compensates float summation.
        # Repeated += changes near-tie ranks relative to the frozen reference.
        return {i: sum(values) for i, values in contributions.items()}

    def rank(self, query: str) -> list[str]:
        scores = self.scores(query)
        return sorted(self.ids, key=lambda i: (-scores[i], i))

    def expansions(self, query: str, seeds: list[str]) -> list[str]:
        """Exact fixed v2 PRF: two seeds, collection-IDF weighted TF, four terms."""
        query_terms = set(terms(query))
        counts: Counter[str] = Counter()
        for i in seeds:
            counts.update({t: n for t, n in self.counts[i].items()
                           if len(t) >= 3 and t not in query_terms})
        return sorted(counts, key=lambda term: (
            -counts[term] * math.log(1 + (self.n + .5) / (self.df[term] + .5)), term
        ))[:4]


def serialize_parent(document: Mapping) -> str:
    """Citation must be the parser's real source line URL, with no added ID."""
    return document["citation"] + "\n" + document["title"] + "\n" + document["text"] + "\n"


def pack(order, docs: Mapping, *, max_parents: int = 4, byte_cap: int = BYTE_CAP) -> dict:
    if max_parents not in (4, 8) or byte_cap != BYTE_CAP:
        raise ValueError("Frozen pilot budgets: four or eight whole parents and exactly 8192 bytes")
    selected, payloads, skipped, seen = [], [], [], set()
    used = 0
    for i in order:
        if i in seen:
            continue
        seen.add(i)
        payload = serialize_parent(docs[i])
        size = len(payload.encode("utf-8"))
        if used + size > byte_cap:
            skipped.append(i)
            continue
        selected.append(i)
        payloads.append(payload)
        used += size
        if len(selected) == max_parents:
            break
    return {"ids": selected, "bytes": used, "payloads": payloads,
            "skipped_over_budget": skipped, "parent_cap": max_parents,
            "byte_cap": byte_cap}


class Retriever:
    """One fixed arm. Non-link arms never inspect a `links` field or build a graph."""

    def __init__(self, docs: Mapping, arm: str):
        if arm not in ARMS:
            raise ValueError(f"Unknown arm: {arm}")
        self.docs, self.arm = docs, arm
        self.index = BM25Index({i: docs[i]["title"] + " " + docs[i]["text"] for i in docs})

    def retrieve(self, query: str) -> dict:
        base = self.index.rank(query)
        seeds = base[:2]
        extra, expansions = [], []
        link_reads = 0
        if self.arm in ("links", "hash_links"):
            anchors: dict[str, set[str]] = {}
            for i in seeds:
                link_reads += 1
                for link in self.docs[i].get("links", ()):
                    j = link["target"]
                    if j in self.docs and j not in seeds and self.docs[j]["source"] == self.docs[i]["source"]:
                        anchors.setdefault(j, set()).add(link["anchor"])
            if self.arm == "links":
                # Local target collection and its own IDF, exactly like mechanics-v2.
                target_index = BM25Index({j: " ".join(sorted(a)) + " " + self.docs[j]["title"]
                                          for j, a in anchors.items()})
                extra = target_index.rank(query)[:2]
            else:
                extra = sorted(anchors, key=lambda j: (hashlib.sha256(j.encode()).hexdigest(), j))[:2]
            order = seeds + extra + base
        elif self.arm == "prf":
            expansions = self.index.expansions(query, seeds)
            order = self.index.rank(query + " " + " ".join(expansions))
        else:
            order = base
        result = pack(order, self.docs, max_parents=8 if self.arm == "bm25_top8" else 4)
        result.update({"arm": self.arm, "seeds": seeds, "extra_targets": extra,
                       "expansions": expansions, "link_field_reads": link_reads})
        return result


def navigate(query: str, docs: Mapping, arm: str = "links") -> dict:
    """Convenience entrypoint for synthetic tests, not the measured reusable path."""
    return Retriever(docs, arm).retrieve(query)

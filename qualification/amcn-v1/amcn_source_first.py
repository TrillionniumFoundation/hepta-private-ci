"""Label-blind, source-first lexical shortlist for AMCN research.

An explicit bounded BM25-like candidate control, NOT a production strong
hybrid RAG or pretrained retrieval model. Neither the candidate constructor
nor its sort key accepts gold answers, publisher support labels or judgments.
"""
from __future__ import annotations

from collections import Counter
from math import log, isfinite
import re

from amcn_core import Evidence, Refused, digest, require

PROFILE = "hepta.amcn.source-first-candidates.v1"
WORDS = re.compile(r"\w+", re.UNICODE)
MAX_CANDIDATES = 8192
MAX_WORDS = 8192
MAX_QUERY_WORDS = 256


def lexical_shortlist(question, sources, *, scope, generation, top_k=16):
    """Compute full-source lexical statistics before sorting any candidates.

    This function has intentionally NO target/evidence-gold input. Any source
    omission is explicit. Input permutation cannot change the canonical order.
    """
    require(isinstance(question, str)
            and 1 <= len(question.encode("utf-8")) <= 8192,
            "bounded source-first question")
    require(type(top_k) is int and 1 <= top_k <= 16, "bounded shortlist width")
    require(isinstance(sources, (tuple, list))
            and 1 <= len(sources) <= MAX_CANDIDATES, "complete eligible source inventory")
    ordered = sorted(sources, key=lambda x: x.evidence_id)
    require(all(isinstance(src, Evidence)
                and src.current(scope, generation) for src in ordered),
            "invalid, revoked, stale or foreign source")
    require(len({s.evidence_id for s in ordered}) == len(ordered),
            "duplicate source identity")
    words = WORDS.findall(question.casefold())
    require(0 < len(words) <= MAX_QUERY_WORDS,
            "unscorable question tokens")
    terms = sorted(set(words))
    counts = []
    document_frequencies = Counter()
    lengths = []
    for src in ordered:
        tokens = WORDS.findall(src.text.casefold())
        require(len(tokens) <= MAX_WORDS, "source lexical work bound")
        bucket = Counter(tokens)
        counts.append(bucket)
        lengths.append(len(tokens))
        for t in terms:
            if t in bucket:
                document_frequencies[t] += 1
    n = len(ordered)
    avg_length = max(1.0, sum(lengths) / n)
    ranked = []
    for source, freq, length in zip(ordered, counts, lengths):
        score = 0.0
        for term in terms:
            tf = freq.get(term, 0)
            if tf:
                df = document_frequencies[term]
                idf = log(1.0 + (n - df + 0.5) / (df + 0.5))
                score += idf * (2.2 * tf / (tf + 1.2 * (0.25 + 0.75 * length / avg_length)))
        require(isfinite(score) and score >= 0, "nonfinite relevance")
        ranked.append((source.evidence_id, score))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    chosen = ranked[:top_k]
    inventory = [(s.evidence_id, s.source_root, s.revision,
                  s.content_sha256) for s in ordered]
    return {
        "schema": PROFILE,
        "question_sha256": digest(question),
        "source_scope": scope,
        "source_generation": generation,
        "source_inventory_sha256": digest(inventory),
        "eligible_source_count": n,
        "shortlist_size": len(chosen),
        "ranked_source_ids": [item[0] for item in chosen],
        "ranked_scores": [item[1] for item in chosen],
        "labels_accessed": False,
        "independent_semantic_support_verified": False,
    }


def source_first_weak_score(shortlist, publisher_support_ids):
    """The entire shortlist stays in the denominator, including zero-hit cases.

    Publisher support IDs here are a weak post-hoc diagnostic; they do NOT
    establish human-sufficient evidence or citation entailment.
    """
    require(isinstance(shortlist, dict) and shortlist.get("schema") == PROFILE
            and shortlist.get("labels_accessed") is False, "non-source-first candidate plan")
    require(isinstance(publisher_support_ids, (list, tuple))
            and all(isinstance(x, str) and x for x in publisher_support_ids),
            "publisher support must be a bounded ID set")
    require(len(publisher_support_ids) <= 8192
            and len(set(publisher_support_ids)) == len(publisher_support_ids),
            "noncanonical source support annotations")
    sources = shortlist["ranked_source_ids"]
    require(len(sources) == shortlist["shortlist_size"]
            and len(set(sources)) == len(sources), "shortlist drift")
    support = set(publisher_support_ids)
    hits = [x in support for x in sources]
    return {
        "schema": "hepta.amcn.source-first-weak-score.v1",
        "candidate_plan_sha256": digest(shortlist),
        "shortlist_candidates": len(sources),
        "publisher_support_count": len(support),
        "publisher_support_in_shortlist": sum(hits),
        "lexical_hit_at_1": bool(hits[0]) if hits else False,
        "lexical_any_hit_at_k": any(hits),
        "publisher_recall_at_k": sum(hits) / len(support) if support else None,
        "publisher_support_is_human_entailment": False,
        "independent_test_success": None,
        "production_accepted": False,
    }

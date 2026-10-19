"""Optional stopword-filtered FTS5 channel on an unchanged as-of hybrid index.

This changes ONLY lexical query terms. Dense vectors, RRF weighting, original
source text, candidate K and authority cut remain identical to frozen RAG.
It is an experimental source-recall candidate, not a new memory writer.
"""

import math
import re

import numpy as np

# Frozen before any held-out labels; no corpus-derived TF-IDF or test fitting.
FUNCTION_WORDS = frozenset(
    """a an the and or but if of to in on at by for from with without as is
    are was were be been being do does did have has had would could should
    will shall can may might what which who whom whose where when why how
    this that these those it its they them their he she his her we our
    you your i me my us there here please tell about explain describe
    give show find name identify according based question answer""".split()
)
PROFILE = "content-filtered-or-v1"


def content_terms(question):
    """Remove only a fixed set of English function words; preserve identifiers.

    The original OR query remains the fallback for all-function-word inputs.
    Term ordering and the original 128-token scanning bound are unchanged.
    """
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question.encode("utf-8")) > 16384
    ):
        raise ValueError("nonempty bounded question required")
    original = list(dict.fromkeys(re.findall(r"\w+", question.lower())))[:128]
    filtered = [term for term in original if term not in FUNCTION_WORDS]
    return tuple(filtered or original)


def query_filtered(index, question, vector, policy, *, current_cut, revoked):
    """Recompute frozen RRF with only the lexical OR list changed."""
    policy.validate()
    index.revalidate(current_cut, revoked)
    if (
        question.scope != index.meta["scope"]
        or not index.documents
        or len(index.documents) != len(index.vectors)
    ):
        raise ValueError("cross-scope or invalid frozen index")
    query_vector = np.asarray(vector, dtype=np.float32)
    if (
        query_vector.shape != index.vectors.shape[1:]
        or not np.isfinite(query_vector).all()
    ):
        raise ValueError("nonfinite or mismatched frozen Encoder vector")
    terms = content_terms(question.content)
    lexical = []
    if terms:
        expr = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        lexical = [
            r[0] - 1
            for r in index.db.execute(
                "SELECT rowid FROM lexical WHERE lexical MATCH ? "
                "ORDER BY bm25(lexical), rowid LIMIT ?",
                (expr, policy.channel_k),
            )
        ]
    norm = max(float(np.linalg.norm(query_vector)), 1e-12)
    similarities = index.vectors @ (query_vector / norm)
    dense = np.argsort(-similarities, kind="stable")[: policy.channel_k].tolist()
    scores = {}
    for channel, weight in (
        (lexical, policy.lexical_weight),
        (dense, 1 - policy.lexical_weight),
    ):
        for rank, i in enumerate(channel):
            scores[i] = scores.get(i, 0.0) + weight / (policy.rrf_constant + rank)
    if not scores or any(not math.isfinite(s) for s in scores.values()):
        raise ValueError("missing or invalid matched RRF scores")
    ranked = sorted(
        scores,
        key=lambda i: (-scores[i], index.documents[i].identity),
    )[: policy.top_k]
    return tuple(index.documents[i] for i in ranked), dict(
        lexical_profile=PROFILE,
        source_cut=current_cut,
        original_index_sha256=index.file_digest,
        encoder_identity=index.meta["encoder"],
        policy_k=policy.top_k,
        channel_k=policy.channel_k,
        lexical_weight=policy.lexical_weight,
        matched_dense_vector=True,
        lexical_term_count=len(terms),
        source_labels_used=False,
    )

"""Strict as-of native source admission *before* retrieval or Encoder use.

A source dated after the question must not influence a retrieval index, frozen
Encoder, learned Head, lineage Adapter, or Reader. Research-only: this is not
a production ACL/retention owner. Unknown times fail closed, not silently
rewritten, truncated or interpreted as no-answer.
"""

from dataclasses import asdict
import time

from native import digest
from stem_cell_time import source_not_after_question


def admit_history(query, documents, *, revoked):
    """Return exactly the source subset observable by the question timestamp."""
    if (
        not isinstance(documents, (tuple, list))
        or not 1 <= len(documents) <= 10000
        or not isinstance(revoked, set)
        or any(
            not isinstance(doc.identity, str)
            or not doc.identity
            or not isinstance(doc.root, str)
            or not doc.root
            or doc.scope != query.scope
            or doc.root in revoked
            for doc in documents
        )
        or len({d.identity for d in documents}) != len(documents)
    ):
        raise ValueError("unbounded, withdrawn, duplicate or cross-scope history")
    visible, excluded = [], []
    for doc in documents:
        try:
            eligible = source_not_after_question(doc.observed_at, query.observed_at)
        except ValueError as error:
            raise ValueError(
                "uncomparable native source time; no partial as-of index"
            ) from error
        if eligible:
            visible.append(doc)
        else:
            excluded.append(doc)
    if not visible:
        raise ValueError("no as-of-admissible sources; cannot build an index")
    return tuple(visible), dict(
        schema="hepta.stem-as-of-source-admission.v1",
        question_identity=query.identity,
        source_scope=query.scope,
        question_observed_at=query.observed_at,
        source_query_digest=digest(asdict(query)),
        original_count=len(documents),
        admitted_count=len(visible),
        excluded_future_count=len(excluded),
        source_identity_digest=digest(
            [(d.identity, d.root, d.observed_at) for d in visible]
        ),
        excluded_future_identity_digest=digest(
            [(d.identity, d.root, d.observed_at) for d in excluded]
        ),
        native_gold_targets_inspected=False,
        source_content_rewritten=False,
        source_permissions_expanded=False,
    )


def build_as_of_index(source, query, encoder, output, *, revoked):
    """Build a sealed source-time index; never embed future source bytes."""
    from index import PersistentIndex

    started = time.perf_counter()
    docs, admission = admit_history(query, source.history(query), revoked=revoked)
    key = (source.source_sha256, query.scope, query.observed_at)
    as_of_cut = digest(
        (
            "stem-native-as-of-v1",
            key,
            admission["source_identity_digest"],
        )
    )
    vectors = encoder.encode([f"{doc.observed_at}: {doc.content}" for doc in docs])
    path = output / f"index-{digest(key)}.sqlite"
    pinned = PersistentIndex.build(
        path,
        docs,
        vectors,
        encoder.identity,
        as_of_cut,
    )
    index = PersistentIndex(
        path,
        as_of_cut,
        revoked,
        expected_file_digest=pinned,
        expected_encoder=encoder.identity,
    )
    return index, dict(
        receipt=admission,
        as_of_cut=as_of_cut,
        verified_index_digest=pinned,
        index_cost=dict(
            scope=query.scope,
            question_observed_at=query.observed_at,
            source_admission=admission,
            as_of_index_cut=as_of_cut,
            documents=len(docs),
            file_bytes=path.stat().st_size,
            seconds=time.perf_counter() - started,
        ),
    )

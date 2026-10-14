"""Independent label-free source-selection replay for the fixed BBC cohort.

A structurally valid 128-row index can be cherry-picked from the 1,000
publisher records. The complete publisher TEXT column and original exclusion
set must reproduce every selected SHA, order, source index and Cell. Neither
model scores nor gold labels are accepted by this mechanism.
"""
from __future__ import annotations

from experiments.shared_stem_cell import external_bbc_shift as b

SCHEMA = "hepta.shared-stem.bbc-source-attestation.v1"


def attest(texts, excluded, public_rows):
    """Refuse valid-looking, rehashed but noncanonical publisher selections."""
    b.validate_public_cohort(public_rows)
    replayed = b.public_cohort(b.sample(texts, excluded))
    b.require(public_rows == replayed,
              "BBC cohort not selected from complete publisher text inventory")
    b.require(type(texts) in (list, tuple) and type(excluded) in (list, tuple),
              "unqualified source or old-text exclusion input")
    source_hashes = [b.digest(t.encode("utf-8")) for t in texts]
    excluded_hashes = [b.digest(b.normalized(t).encode("utf-8")) for t in excluded]
    return {
        "schema": SCHEMA, "source_id": b.SOURCE, "publisher_revision": b.REVISION,
        "source_split": "test", "full_text_column_rows": len(texts),
        "full_text_column_sha256": b.digest(b.canonical(source_hashes)),
        "previous_exclusion_sha256": b.digest(b.canonical(excluded_hashes)),
        "selection_rule": "sha256(hepta-bbc-ood-v1:original-article-hash)-ascending",
        "selected_rows": len(public_rows),
        "selected_index_sha256": b.digest(b.canonical(public_rows)),
        "label_accessed": False, "model_output_accessed": False,
        "source_authorship_independent_of_pretraining_verified": False,
        "production_accepted": False,
    }

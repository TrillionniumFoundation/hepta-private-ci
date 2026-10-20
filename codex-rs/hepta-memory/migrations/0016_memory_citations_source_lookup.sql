-- Graph source frontiers ask whether each immutable source has a citation.
-- Keep that lookup indexed instead of rebuilding a temporary source index on
-- every revision publication. This changes no ledger or citation semantics.
CREATE INDEX memory_citations_source_lookup
    ON memory_citations(source_id, source_revision);

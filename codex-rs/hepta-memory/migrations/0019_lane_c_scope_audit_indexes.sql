-- Keep canonical counter audits while avoiding cross-scope history scans.
-- These indexes and views belong to the existing durable SQLite owner; no
-- independent state, authority or hot-path authorization cache is introduced.
CREATE INDEX source_ledger_lane_c_scope_lookup
ON source_ledger(owner_agent_id, scope_kind, COALESCE(workspace_sha256, ''));

CREATE INDEX memory_revisions_lane_c_scope_lookup
ON memory_revisions(owner_agent_id, scope_kind, COALESCE(workspace_sha256, ''));

DROP VIEW lane_c_scope_witness_audit;
CREATE VIEW lane_c_scope_witness_audit AS
SELECT
    e.owner_agent_id,
    e.scope_kind,
    e.workspace_key,
    'missing_or_mismatched' AS problem
FROM lane_c_scope_witness_expected e
LEFT JOIN lane_c_scope_witness w
  ON w.owner_agent_id = e.owner_agent_id
 AND w.scope_kind = e.scope_kind
 AND w.workspace_key = e.workspace_key
WHERE w.owner_agent_id IS NULL
   OR w.memory_revision_count != e.memory_revision_count
   OR w.source_count != e.source_count
   OR w.citation_count != e.citation_count
   OR w.tombstone_count != e.tombstone_count
   OR w.knowledge_fact_count != e.knowledge_fact_count
   OR w.head_count != e.head_count
   OR w.state_revision < (
        e.memory_revision_count + e.source_count + e.citation_count
        + e.knowledge_fact_count + e.head_count
   )
UNION ALL
SELECT
    w.owner_agent_id,
    w.scope_kind,
    w.workspace_key,
    'unexpected' AS problem
FROM lane_c_scope_witness w
WHERE NOT EXISTS (
    SELECT 1 FROM source_ledger l
    WHERE l.owner_agent_id = w.owner_agent_id
      AND l.scope_kind = w.scope_kind
      AND COALESCE(l.workspace_sha256, '') = w.workspace_key
) AND NOT EXISTS (
    SELECT 1 FROM memory_revisions r
    WHERE r.owner_agent_id = w.owner_agent_id
      AND r.scope_kind = w.scope_kind
      AND COALESCE(r.workspace_sha256, '') = w.workspace_key
);

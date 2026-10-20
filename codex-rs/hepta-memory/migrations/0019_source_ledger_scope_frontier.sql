-- Count cited evidence through the owner/scope frontier without reading source
-- payloads. The EXISTS citation predicate remains the authority for inclusion.
CREATE INDEX source_ledger_scope_frontier
    ON source_ledger(
        owner_agent_id, scope_kind, workspace_sha256, source_id, source_revision
    );

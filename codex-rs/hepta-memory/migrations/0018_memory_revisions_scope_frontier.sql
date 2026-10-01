-- Cover the retained revision frontiers without reading revision content.
-- The fact-set lookup remains on its unique revision primary key, and all
-- existing owner, scope, lifecycle, and history count semantics stay intact.
CREATE INDEX memory_revisions_scope_frontier
    ON memory_revisions(
        owner_agent_id, scope_kind, workspace_sha256, lifecycle, memory_id, revision
    );

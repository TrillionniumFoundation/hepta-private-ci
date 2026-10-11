CREATE TABLE memory_federation_events (
    capability_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0 AND revision <= 1024),
    generation INTEGER NOT NULL CHECK (generation > 0),
    owner_agent_id TEXT NOT NULL CHECK (length(owner_agent_id) = 36),
    consumer_agent_id TEXT NOT NULL CHECK (length(consumer_agent_id) = 36),
    scope_kind TEXT NOT NULL CHECK (scope_kind IN ('agent_private', 'workspace_private')),
    owner_workspace_sha256 TEXT,
    consumer_workspace_sha256 TEXT NOT NULL CHECK (
        length(consumer_workspace_sha256) = 64 AND
        consumer_workspace_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    action TEXT NOT NULL CHECK (action IN ('grant', 'revoke')),
    effective_at_unix_seconds INTEGER NOT NULL,
    expires_at_unix_seconds INTEGER NOT NULL,
    recorded_at_unix_seconds INTEGER NOT NULL,
    PRIMARY KEY (capability_id, revision),
    CHECK (owner_agent_id != consumer_agent_id),
    CHECK (
        (scope_kind = 'agent_private' AND owner_workspace_sha256 IS NULL) OR
        (scope_kind = 'workspace_private' AND length(owner_workspace_sha256) = 64 AND
         owner_workspace_sha256 NOT GLOB '*[^0-9a-f]*')
    ),
    CHECK (action = 'revoke' OR expires_at_unix_seconds > effective_at_unix_seconds)
) STRICT;

CREATE TRIGGER memory_federation_events_no_update
BEFORE UPDATE ON memory_federation_events BEGIN
    SELECT RAISE(ABORT, 'memory federation events are immutable');
END;

CREATE TRIGGER memory_federation_events_no_delete
BEFORE DELETE ON memory_federation_events BEGIN
    SELECT RAISE(ABORT, 'memory federation events are immutable');
END;

CREATE TABLE memory_federation_heads (
    capability_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision > 0 AND revision <= 1024),
    FOREIGN KEY (capability_id, revision)
        REFERENCES memory_federation_events(capability_id, revision) ON DELETE RESTRICT
) STRICT;

CREATE INDEX memory_federation_consumer_heads
ON memory_federation_events(consumer_agent_id, capability_id, revision);

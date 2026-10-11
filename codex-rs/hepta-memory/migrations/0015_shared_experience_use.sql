-- Purpose-specific owner grants, separate from recall federation capabilities.
-- Stored in the existing cognitive writer: no shared writable database or new owner.
CREATE TABLE shared_experience_use_events (
    policy_id TEXT NOT NULL CHECK(length(policy_id)=64 AND policy_id NOT GLOB '*[^0-9a-f]*'),
    -- One final slot is reserved for withdrawal, never a renewed active grant.
    revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 1025),
    revoked INTEGER NOT NULL CHECK(revoked IN (0,1)),
    memory_id TEXT NOT NULL,
    memory_revision INTEGER NOT NULL CHECK(memory_revision>0),
    content_sha256 TEXT NOT NULL CHECK(length(content_sha256)=64),
    consumer_agent_id TEXT NOT NULL,
    consumer_workspace_sha256 TEXT NOT NULL CHECK(length(consumer_workspace_sha256)=64),
    purpose TEXT NOT NULL CHECK(purpose IN ('recall','replay')),
    parameter_scope TEXT NOT NULL CHECK(length(parameter_scope)<=128),
    artifact_consumer_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL CHECK(expires_at>0),
    CHECK((purpose='recall' AND parameter_scope='' AND artifact_consumer_id='') OR
          (purpose='replay' AND length(parameter_scope)>0 AND length(artifact_consumer_id)>0)),
    CHECK(revision <= 1024 OR revoked = 1),
    PRIMARY KEY(policy_id,revision),
    FOREIGN KEY(memory_id,memory_revision) REFERENCES memory_revisions(memory_id,revision)
) STRICT;
CREATE TRIGGER shared_experience_use_no_update BEFORE UPDATE ON shared_experience_use_events BEGIN
    SELECT RAISE(ABORT,'shared experience use history is immutable');
END;
CREATE TRIGGER shared_experience_use_no_delete BEFORE DELETE ON shared_experience_use_events BEGIN
    SELECT RAISE(ABORT,'shared experience use history is immutable');
END;
CREATE INDEX shared_experience_use_consumer_lookup
ON shared_experience_use_events(consumer_agent_id,consumer_workspace_sha256,policy_id,revision);

-- Current quota projection; immutable use history remains the authorization source.
-- Expired/revoked identities retain their predecessor and cannot be resurrected by GC.
CREATE TABLE shared_experience_use_heads (
    policy_id TEXT PRIMARY KEY NOT NULL,
    revision INTEGER NOT NULL,
    revoked INTEGER NOT NULL CHECK(revoked IN (0,1)),
    expires_at INTEGER NOT NULL CHECK(expires_at>0),
    FOREIGN KEY(policy_id,revision)
        REFERENCES shared_experience_use_events(policy_id,revision)
) STRICT;
INSERT INTO shared_experience_use_heads
SELECT e.policy_id,e.revision,e.revoked,e.expires_at
FROM shared_experience_use_events e
JOIN (SELECT policy_id,MAX(revision) AS revision
      FROM shared_experience_use_events GROUP BY policy_id) h
USING(policy_id,revision);
CREATE INDEX shared_experience_use_active_expiry
ON shared_experience_use_heads(expires_at,policy_id) WHERE revoked=0;

CREATE TRIGGER shared_experience_use_project_head
AFTER INSERT ON shared_experience_use_events BEGIN
    INSERT INTO shared_experience_use_heads VALUES
        (NEW.policy_id,NEW.revision,NEW.revoked,NEW.expires_at)
    ON CONFLICT(policy_id) DO UPDATE SET
        revision=excluded.revision,revoked=excluded.revoked,expires_at=excluded.expires_at
    WHERE excluded.revision>shared_experience_use_heads.revision;
END;
CREATE TRIGGER shared_experience_use_heads_valid_insert
BEFORE INSERT ON shared_experience_use_heads BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM shared_experience_use_events e
        WHERE e.policy_id=NEW.policy_id AND e.revision=NEW.revision
          AND e.revoked=NEW.revoked AND e.expires_at=NEW.expires_at
          AND e.revision=(SELECT MAX(revision) FROM shared_experience_use_events
                          WHERE policy_id=NEW.policy_id)
    ) THEN RAISE(ABORT,'shared use head must match current immutable history') END;
END;
CREATE TRIGGER shared_experience_use_heads_valid_update
BEFORE UPDATE ON shared_experience_use_heads BEGIN
    SELECT CASE WHEN NEW.policy_id<>OLD.policy_id OR NOT EXISTS (
        SELECT 1 FROM shared_experience_use_events e
        WHERE e.policy_id=NEW.policy_id AND e.revision=NEW.revision
          AND e.revoked=NEW.revoked AND e.expires_at=NEW.expires_at
          AND e.revision=(SELECT MAX(revision) FROM shared_experience_use_events
                          WHERE policy_id=NEW.policy_id)
    ) THEN RAISE(ABORT,'shared use head must match current immutable history') END;
END;
CREATE TRIGGER shared_experience_use_heads_no_delete
BEFORE DELETE ON shared_experience_use_heads BEGIN
    SELECT RAISE(ABORT,'shared use predecessors are retained after expiry or revocation');
END;

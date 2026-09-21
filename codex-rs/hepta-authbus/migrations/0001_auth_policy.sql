PRAGMA foreign_keys = ON;

CREATE TABLE auth_policy_revisions (
    revision INTEGER PRIMARY KEY NOT NULL CHECK(revision > 0),
    policy_digest TEXT NOT NULL CHECK(length(policy_digest) = 64),
    source_digest TEXT NOT NULL CHECK(length(source_digest) = 64),
    rule_count INTEGER NOT NULL CHECK(rule_count >= 0),
    UNIQUE(policy_digest)
) STRICT;

CREATE TABLE auth_policy_rules (
    revision INTEGER NOT NULL REFERENCES auth_policy_revisions(revision),
    principal_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    allowed INTEGER NOT NULL CHECK(allowed IN (0, 1)),
    PRIMARY KEY(revision, principal_id, action_id, resource_id)
) STRICT;

CREATE TABLE auth_policy_current (
    singleton INTEGER PRIMARY KEY NOT NULL CHECK(singleton = 1),
    revision INTEGER NOT NULL REFERENCES auth_policy_revisions(revision),
    policy_digest TEXT NOT NULL CHECK(length(policy_digest) = 64)
) STRICT;

CREATE TRIGGER auth_policy_revisions_no_update BEFORE UPDATE ON auth_policy_revisions BEGIN
    SELECT RAISE(ABORT, 'auth policy revisions are immutable');
END;
CREATE TRIGGER auth_policy_revisions_no_delete BEFORE DELETE ON auth_policy_revisions BEGIN
    SELECT RAISE(ABORT, 'auth policy revisions are immutable');
END;
CREATE TRIGGER auth_policy_rules_no_update BEFORE UPDATE ON auth_policy_rules BEGIN
    SELECT RAISE(ABORT, 'auth policy rules are immutable');
END;
CREATE TRIGGER auth_policy_rules_no_delete BEFORE DELETE ON auth_policy_rules BEGIN
    SELECT RAISE(ABORT, 'auth policy rules are immutable');
END;

CREATE TABLE authority_role_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    profile_sha256 BLOB NOT NULL CHECK(length(profile_sha256) = 32),
    last_wall_time_ms INTEGER NOT NULL CHECK(last_wall_time_ms >= 0),
    next_time_revision INTEGER NOT NULL CHECK(next_time_revision > 0)
) STRICT;
CREATE TABLE authority_role_frontier (
    owner_id TEXT PRIMARY KEY NOT NULL CHECK(length(owner_id) BETWEEN 1 AND 256),
    authority_epoch INTEGER NOT NULL CHECK(authority_epoch > 0),
    revocation_revision INTEGER NOT NULL CHECK(revocation_revision > 0),
    state_sha256 BLOB NOT NULL CHECK(length(state_sha256) = 32),
    governed_head_json BLOB NOT NULL CHECK(length(governed_head_json) BETWEEN 1 AND 65536)
) STRICT;
CREATE TABLE authority_role_grant (
    original_operation_id TEXT PRIMARY KEY NOT NULL CHECK(length(original_operation_id) BETWEEN 1 AND 200),
    grant_sha256 BLOB UNIQUE NOT NULL CHECK(length(grant_sha256) = 32),
    grant_json BLOB NOT NULL CHECK(length(grant_json) BETWEEN 1 AND 16384)
) STRICT;
CREATE TABLE authority_role_original_begin (
    original_operation_id TEXT PRIMARY KEY NOT NULL REFERENCES authority_role_grant(original_operation_id),
    grant_sha256 BLOB NOT NULL CHECK(length(grant_sha256) = 32),
    approval_sha256 BLOB NOT NULL CHECK(length(approval_sha256) = 32),
    approval_json BLOB NOT NULL CHECK(length(approval_json) BETWEEN 1 AND 16384)
) STRICT;
CREATE TRIGGER authority_grant_no_update BEFORE UPDATE ON authority_role_grant
BEGIN SELECT RAISE(ABORT, 'immutable original grant'); END;
CREATE TRIGGER authority_grant_no_delete BEFORE DELETE ON authority_role_grant
BEGIN SELECT RAISE(ABORT, 'immutable original grant'); END;
CREATE TRIGGER authority_begin_no_update BEFORE UPDATE ON authority_role_original_begin
BEGIN SELECT RAISE(ABORT, 'immutable original begin'); END;
CREATE TRIGGER authority_begin_no_delete BEFORE DELETE ON authority_role_original_begin
BEGIN SELECT RAISE(ABORT, 'immutable original begin'); END;
CREATE TABLE authority_role_frontier_history (
    state_sha256 BLOB PRIMARY KEY NOT NULL CHECK(length(state_sha256) = 32)
) STRICT;
CREATE TRIGGER authority_frontier_history_no_update BEFORE UPDATE ON authority_role_frontier_history
BEGIN SELECT RAISE(ABORT, 'immutable frontier history'); END;
CREATE TRIGGER authority_frontier_history_no_delete BEFORE DELETE ON authority_role_frontier_history
BEGIN SELECT RAISE(ABORT, 'immutable frontier history'); END;

CREATE TABLE operator_role_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    profile_sha256 BLOB NOT NULL CHECK(length(profile_sha256)=32),
    last_wall_time_ms INTEGER NOT NULL CHECK(last_wall_time_ms>=0),
    last_source_revision INTEGER NOT NULL CHECK(last_source_revision>=0),
    head_json BLOB NOT NULL CHECK(length(head_json) BETWEEN 1 AND 65536)
) STRICT;
CREATE TABLE operator_role_approval (
    original_operation_id TEXT PRIMARY KEY NOT NULL CHECK(length(original_operation_id) BETWEEN 1 AND 200),
    grant_sha256 BLOB UNIQUE NOT NULL CHECK(length(grant_sha256)=32),
    grant_json BLOB NOT NULL CHECK(length(grant_json) BETWEEN 1 AND 16384),
    approval_json BLOB NOT NULL CHECK(length(approval_json) BETWEEN 1 AND 16384)
) STRICT;
CREATE TRIGGER operator_approval_no_update BEFORE UPDATE ON operator_role_approval
BEGIN SELECT RAISE(ABORT,'immutable independent approval'); END;
CREATE TRIGGER operator_approval_no_delete BEFORE DELETE ON operator_role_approval
BEGIN SELECT RAISE(ABORT,'immutable independent approval'); END;

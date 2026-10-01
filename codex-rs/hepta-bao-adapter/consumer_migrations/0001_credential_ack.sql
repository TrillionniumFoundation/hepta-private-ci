CREATE TABLE credential_consumer_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    next_revision INTEGER NOT NULL CHECK(next_revision > 0)
) STRICT;
INSERT INTO credential_consumer_meta(singleton, next_revision) VALUES (1, 1);

CREATE TABLE credential_consumer_ack (
    operation_id TEXT PRIMARY KEY NOT NULL CHECK(length(operation_id) BETWEEN 1 AND 256),
    consumer_id TEXT NOT NULL CHECK(length(consumer_id) BETWEEN 1 AND 256),
    semantic_sha256 BLOB NOT NULL CHECK(length(semantic_sha256) = 32),
    durable_revision INTEGER UNIQUE NOT NULL CHECK(durable_revision > 0),
    acknowledgement_json BLOB NOT NULL CHECK(length(acknowledgement_json) BETWEEN 1 AND 32768)
) STRICT;
CREATE TRIGGER credential_ack_no_update
BEFORE UPDATE ON credential_consumer_ack BEGIN SELECT RAISE(ABORT, 'immutable credential acknowledgement'); END;
CREATE TRIGGER credential_ack_no_delete
BEFORE DELETE ON credential_consumer_ack BEGIN SELECT RAISE(ABORT, 'immutable original credential operation'); END;

CREATE TABLE credential_receipt_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    profile_sha256 BLOB NOT NULL CHECK(length(profile_sha256) = 32),
    source_wall_ms INTEGER NOT NULL CHECK(source_wall_ms >= 0),
    source_revision INTEGER NOT NULL CHECK(source_revision >= 0)
) STRICT;
CREATE TABLE credential_receipt_preparation (
    operation_id TEXT PRIMARY KEY NOT NULL CHECK(length(operation_id) BETWEEN 1 AND 256),
    preparation_sha256 BLOB NOT NULL CHECK(length(preparation_sha256) = 32),
    preparation_json BLOB NOT NULL CHECK(length(preparation_json) BETWEEN 1 AND 32768)
) STRICT;
CREATE TRIGGER credential_preparation_no_update BEFORE UPDATE ON credential_receipt_preparation BEGIN SELECT RAISE(ABORT, 'immutable original receipt preparation'); END;
CREATE TRIGGER credential_preparation_no_delete BEFORE DELETE ON credential_receipt_preparation BEGIN SELECT RAISE(ABORT, 'immutable original receipt preparation'); END;
CREATE TABLE credential_settlement_binding (
    operation_id TEXT PRIMARY KEY NOT NULL REFERENCES credential_consumer_ack(operation_id),
    reservation_id TEXT UNIQUE NOT NULL CHECK(length(reservation_id) BETWEEN 1 AND 256),
    receipt_sha256 BLOB NOT NULL CHECK(length(receipt_sha256) = 32),
    acknowledgement_sha256 BLOB NOT NULL CHECK(length(acknowledgement_sha256) = 32),
    cost INTEGER NOT NULL CHECK(cost > 0)
) STRICT;
CREATE TRIGGER credential_settlement_binding_no_update BEFORE UPDATE ON credential_settlement_binding BEGIN SELECT RAISE(ABORT, 'immutable original settlement binding'); END;
CREATE TRIGGER credential_settlement_binding_no_delete BEFORE DELETE ON credential_settlement_binding BEGIN SELECT RAISE(ABORT, 'immutable original settlement binding'); END;
CREATE TABLE credential_settlement_evidence (
    sequence INTEGER PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES credential_settlement_binding(operation_id),
    evidence_sha256 BLOB UNIQUE NOT NULL CHECK(length(evidence_sha256) = 32),
    evidence_json BLOB NOT NULL CHECK(length(evidence_json) BETWEEN 1 AND 32768)
) STRICT;
CREATE TRIGGER credential_settlement_evidence_no_update BEFORE UPDATE ON credential_settlement_evidence BEGIN SELECT RAISE(ABORT, 'immutable signed settlement evidence'); END;
CREATE TRIGGER credential_settlement_evidence_no_delete BEFORE DELETE ON credential_settlement_evidence BEGIN SELECT RAISE(ABORT, 'immutable signed settlement evidence'); END;

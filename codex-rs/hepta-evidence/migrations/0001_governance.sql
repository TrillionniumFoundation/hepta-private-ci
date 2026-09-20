CREATE TABLE governance_decisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL UNIQUE,
    action_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('admission', 'authorization')),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    UNIQUE(action_id, phase),
    UNIQUE(decision_id, action_id, phase)
);

CREATE INDEX governance_decisions_thread_seq
    ON governance_decisions(thread_id, seq);

CREATE TABLE governance_receipts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    action_id TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    admission_decision_id TEXT NOT NULL,
    admission_phase TEXT NOT NULL DEFAULT 'admission'
        CHECK (admission_phase = 'admission'),
    authorization_decision_id TEXT,
    authorization_phase TEXT CHECK (authorization_phase = 'authorization'),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (
        length(payload_sha256) = 64
        AND payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ms INTEGER NOT NULL,
    CHECK (
        (authorization_decision_id IS NULL AND authorization_phase IS NULL)
        OR
        (authorization_decision_id IS NOT NULL AND authorization_phase = 'authorization')
    ),
    FOREIGN KEY(admission_decision_id, action_id, admission_phase)
        REFERENCES governance_decisions(decision_id, action_id, phase)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY(authorization_decision_id, action_id, authorization_phase)
        REFERENCES governance_decisions(decision_id, action_id, phase)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE INDEX governance_receipts_thread_seq
    ON governance_receipts(thread_id, seq);

CREATE TRIGGER governance_decisions_no_update
BEFORE UPDATE ON governance_decisions
BEGIN
    SELECT RAISE(ABORT, 'governance decisions are immutable');
END;

CREATE TRIGGER governance_decisions_no_delete
BEFORE DELETE ON governance_decisions
BEGIN
    SELECT RAISE(ABORT, 'governance decisions are immutable');
END;

CREATE TRIGGER governance_receipts_no_update
BEFORE UPDATE ON governance_receipts
BEGIN
    SELECT RAISE(ABORT, 'governance receipts are immutable');
END;

CREATE TRIGGER governance_receipts_no_delete
BEFORE DELETE ON governance_receipts
BEGIN
    SELECT RAISE(ABORT, 'governance receipts are immutable');
END;

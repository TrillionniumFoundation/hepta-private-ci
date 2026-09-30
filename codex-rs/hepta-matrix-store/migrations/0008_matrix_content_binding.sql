-- Pin semantic send content and the authenticated transaction domain once.
-- This is not another queue, sender, authority, or external-outcome ledger.

CREATE TABLE matrix_dispatch_content_bindings (
    stable_txn_id TEXT PRIMARY KEY,
    canonicalization_version INTEGER NOT NULL CHECK (canonicalization_version = 1),
    canonical_content_sha256 TEXT NOT NULL CHECK (
        length(canonical_content_sha256) = 64
        AND canonical_content_sha256 NOT GLOB '*[^0-9a-f]*'
        AND canonical_content_sha256 != printf('%064d', 0)
    ),
    scope_sha256 TEXT NOT NULL CHECK (
        length(scope_sha256) = 64 AND scope_sha256 NOT GLOB '*[^0-9a-f]*'
        AND scope_sha256 != printf('%064d', 0)
    ),
    source_payload_sha256 TEXT NOT NULL CHECK (
        length(source_payload_sha256) = 64
        AND source_payload_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    pinned_at_ms INTEGER NOT NULL CHECK (pinned_at_ms >= 0),
    FOREIGN KEY (stable_txn_id) REFERENCES matrix_dispatch_ledger(stable_txn_id)
        ON DELETE RESTRICT
) STRICT;

CREATE TRIGGER matrix_dispatch_content_bindings_no_update
BEFORE UPDATE ON matrix_dispatch_content_bindings BEGIN
    SELECT RAISE(ABORT, 'Matrix canonical content and transaction domain are immutable');
END;

CREATE TRIGGER matrix_dispatch_content_bindings_no_delete
BEFORE DELETE ON matrix_dispatch_content_bindings BEGIN
    SELECT RAISE(ABORT, 'Matrix canonical content binding is durable');
END;

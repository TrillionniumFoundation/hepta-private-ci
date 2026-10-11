-- E.16 schema-level lease/fence binding.
--
-- The H8/H10 local journals intentionally predate an explicit authority
-- epoch/owner epoch/expiry contract.  Keep the columns nullable so an
-- existing local-development database can be opened for inspection, but
-- never treat a NULL row as a bound lease or compact journal.  The Rust
-- loaders fail closed for the new bound writer and preserve the old
-- unbound qualification API for compatibility.
ALTER TABLE cognitive_local_leases
    ADD COLUMN authority_epoch INTEGER
    CHECK (authority_epoch IS NULL OR authority_epoch > 0);

ALTER TABLE cognitive_local_leases
    ADD COLUMN owner_epoch INTEGER
    CHECK (owner_epoch IS NULL OR owner_epoch > 0);

ALTER TABLE cognitive_local_leases
    ADD COLUMN lease_expires_at_unix_seconds INTEGER
    CHECK (
        lease_expires_at_unix_seconds IS NULL OR
        lease_expires_at_unix_seconds > 0
    );

ALTER TABLE cognitive_compact_events
    ADD COLUMN lease_id TEXT
    CHECK (lease_id IS NULL OR (length(trim(lease_id)) BETWEEN 1 AND 512 AND instr(lease_id, char(0)) = 0));

ALTER TABLE cognitive_compact_events
    ADD COLUMN lease_head_sha256 TEXT
    CHECK (
        lease_head_sha256 IS NULL OR
        (length(lease_head_sha256) = 64 AND lease_head_sha256 NOT GLOB '*[^0-9a-f]*')
    );

-- Keep the compact chain predecessor explicit at the SQLite boundary.  It
-- must equal the serialized event's previous_sha256; a separate column makes
-- the row-level binding auditable without parsing event_json.
ALTER TABLE cognitive_compact_events
    ADD COLUMN compact_previous_sha256 TEXT
    CHECK (
        compact_previous_sha256 IS NULL OR
        (length(compact_previous_sha256) = 64 AND compact_previous_sha256 NOT GLOB '*[^0-9a-f]*')
    );

-- Digest over the local lease identity/head and the compact event identity.
-- This is not a secret; it is an immutable cross-journal consistency witness.
ALTER TABLE cognitive_compact_events
    ADD COLUMN compact_event_binding_sha256 TEXT
    CHECK (
        compact_event_binding_sha256 IS NULL OR
        (length(compact_event_binding_sha256) = 64 AND compact_event_binding_sha256 NOT GLOB '*[^0-9a-f]*')
    );

CREATE INDEX cognitive_compact_events_lease_binding
ON cognitive_compact_events(lease_id, lease_head_sha256, sequence);

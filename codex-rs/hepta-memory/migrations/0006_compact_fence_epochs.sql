-- Bind compact persistence rows to the complete CompactFence.
--
-- Existing v1 rows intentionally receive NULLs rather than guessed epoch
-- values.  The loader treats NULL/mismatched epochs as corrupt, so old rows
-- cannot be silently reused under a new authority or owner epoch.  New rows
-- are written with non-zero values by the typed executor.
ALTER TABLE cognitive_compact_events
    ADD COLUMN authority_epoch INTEGER
    CHECK (authority_epoch IS NULL OR authority_epoch > 0);

ALTER TABLE cognitive_compact_events
    ADD COLUMN owner_epoch INTEGER
    CHECK (owner_epoch IS NULL OR owner_epoch > 0);

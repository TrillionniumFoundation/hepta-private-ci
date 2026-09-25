-- The path that produced a provider ACK is local provenance, not provider
-- authority.  Existing rows intentionally remain NULL: they predate this
-- witness and the startup oracle must fail closed rather than infer a source.
ALTER TABLE provider_effect_acknowledgements
ADD COLUMN source TEXT CHECK (
    source IS NULL
    OR source IN ('dispatch_response', 'status_lookup')
);

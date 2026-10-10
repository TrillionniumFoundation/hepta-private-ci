ALTER TABLE provider_invocation_intents
ADD COLUMN host_request_binding_id_sha256 TEXT CHECK (
    host_request_binding_id_sha256 IS NULL
    OR (
        length(host_request_binding_id_sha256) = 64
        AND host_request_binding_id_sha256 NOT GLOB '*[^0-9a-f]*'
    )
);

CREATE TRIGGER provider_invocation_intents_host_binding_required
BEFORE INSERT ON provider_invocation_intents
WHEN NEW.host_request_binding_id_sha256 IS NULL
BEGIN
    SELECT RAISE(ABORT, 'provider invocation intent requires host request binding digest');
END;

CREATE INDEX provider_invocation_intents_host_binding_seq
ON provider_invocation_intents(host_request_binding_id_sha256, seq);

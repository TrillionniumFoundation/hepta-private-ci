ALTER TABLE provider_invocation_intents
ADD COLUMN ephemeral_input_sha256 TEXT CHECK (
    ephemeral_input_sha256 IS NULL
    OR (
        length(ephemeral_input_sha256) = 64
        AND ephemeral_input_sha256 NOT GLOB '*[^0-9a-f]*'
    )
);

ALTER TABLE provider_invocation_intents
ADD COLUMN ephemeral_input_witness_sha256 TEXT CHECK (
    (
        ephemeral_input_witness_sha256 IS NULL
        OR (
            length(ephemeral_input_witness_sha256) = 64
            AND ephemeral_input_witness_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    )
    AND (
        (ephemeral_input_sha256 IS NULL)
        = (ephemeral_input_witness_sha256 IS NULL)
    )
);

DROP TRIGGER provider_invocation_intents_no_update;

UPDATE provider_invocation_intents
SET
    ephemeral_input_sha256 = CASE
        WHEN json_type(payload_json, '$.binding.ephemeral_input_sha256') IS NULL
            THEN NULL
        WHEN json_type(payload_json, '$.binding.ephemeral_input_sha256') = 'text'
            THEN json_extract(payload_json, '$.binding.ephemeral_input_sha256')
        ELSE 'invalid'
    END,
    ephemeral_input_witness_sha256 = CASE
        WHEN json_type(payload_json, '$.binding.ephemeral_input_witness_sha256') IS NULL
            THEN NULL
        WHEN json_type(payload_json, '$.binding.ephemeral_input_witness_sha256') = 'text'
            THEN json_extract(payload_json, '$.binding.ephemeral_input_witness_sha256')
        ELSE 'invalid'
    END;

CREATE TRIGGER provider_invocation_intents_no_update
BEFORE UPDATE ON provider_invocation_intents
BEGIN
    SELECT RAISE(ABORT, 'provider invocation intents are immutable');
END;

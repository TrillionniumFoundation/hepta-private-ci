-- Preserve enough authenticated admission material to re-commit and audit the
-- exact qualification decision after restart. Historical rows from earlier
-- migrations remain NULL and therefore cannot satisfy the production-complete
-- provenance gate without an explicit re-attestation or fresh lineage.
ALTER TABLE qualification_evidence
    ADD COLUMN auth_signature BLOB
    CHECK (auth_signature IS NULL OR length(auth_signature) = 64);

ALTER TABLE qualification_evidence
    ADD COLUMN trust_registry_generation BLOB
    CHECK (
        trust_registry_generation IS NULL
        OR length(trust_registry_generation) = 8
    );

ALTER TABLE qualification_evidence
    ADD COLUMN trust_registry_sha256 TEXT
    CHECK (
        trust_registry_sha256 IS NULL
        OR (
            length(trust_registry_sha256) = 64
            AND trust_registry_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    );

CREATE TRIGGER qualification_evidence_auth_provenance_consistent
BEFORE INSERT ON qualification_evidence
WHEN (NEW.trust_registry_generation IS NULL)
        != (NEW.trust_registry_sha256 IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'qualification trust provenance is incomplete');
END;

CREATE TRIGGER qualification_evidence_auth_provenance_update_denied
BEFORE UPDATE OF auth_signature, trust_registry_generation, trust_registry_sha256
ON qualification_evidence
BEGIN
    SELECT RAISE(ABORT, 'qualification authentication provenance is immutable');
END;

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS compaction_trust_registry (
    owner_id TEXT NOT NULL CHECK (length(trim(owner_id)) BETWEEN 1 AND 128),
    role TEXT NOT NULL CHECK (role IN ('retention-selector', 'semantic-generator', 'tokenizer', 'evaluator')),
    key_id TEXT NOT NULL CHECK (length(trim(key_id)) BETWEEN 1 AND 128),
    trust_epoch INTEGER NOT NULL CHECK (trust_epoch > 0),
    valid_from_unix_seconds INTEGER NOT NULL CHECK (valid_from_unix_seconds >= 0),
    valid_until_unix_seconds INTEGER NOT NULL CHECK (valid_until_unix_seconds > valid_from_unix_seconds),
    predecessor_key_digest TEXT CHECK (predecessor_key_digest IS NULL OR length(predecessor_key_digest) = 64),
    implementation_digest TEXT NOT NULL CHECK (length(implementation_digest) = 64),
    attestation_digest TEXT NOT NULL CHECK (length(attestation_digest) = 64),
    key_digest TEXT NOT NULL CHECK (length(key_digest) = 64),
    verifying_key BLOB NOT NULL CHECK (length(verifying_key) = 32),
    enrollment_digest TEXT NOT NULL CHECK (length(enrollment_digest) = 64),
    enrolled_at_unix_seconds INTEGER NOT NULL CHECK (enrolled_at_unix_seconds >= 0),
    revoked_at_unix_seconds INTEGER CHECK (revoked_at_unix_seconds IS NULL OR revoked_at_unix_seconds >= valid_from_unix_seconds),
    PRIMARY KEY (owner_id, role, key_id, trust_epoch),
    UNIQUE (owner_id, role, trust_epoch),
    UNIQUE (owner_id, role, key_digest, trust_epoch),
    UNIQUE (owner_id, enrollment_digest)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS compaction_payloads (
    owner_id TEXT NOT NULL,
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    payload_bytes BLOB NOT NULL CHECK (length(payload_bytes) BETWEEN 1 AND 67108864),
    payload_bytes_digest TEXT NOT NULL CHECK (length(payload_bytes_digest) = 64),
    encoded_bytes INTEGER NOT NULL CHECK (encoded_bytes BETWEEN 1 AND 67108864),
    token_count INTEGER NOT NULL CHECK (token_count BETWEEN 1 AND 8000000),
    generator_key_id TEXT NOT NULL,
    generator_trust_epoch INTEGER NOT NULL CHECK (generator_trust_epoch > 0),
    tokenizer_key_id TEXT NOT NULL,
    tokenizer_trust_epoch INTEGER NOT NULL CHECK (tokenizer_trust_epoch > 0),
    created_at_unix_seconds INTEGER NOT NULL CHECK (created_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, payload_digest)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS compaction_candidates (
    owner_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (length(trim(idempotency_key)) BETWEEN 1 AND 128),
    scope_id TEXT NOT NULL CHECK (length(trim(scope_id)) BETWEEN 1 AND 128),
    purpose_id TEXT NOT NULL CHECK (length(trim(purpose_id)) BETWEEN 1 AND 128),
    generation INTEGER NOT NULL CHECK (generation > 0),
    predecessor_checkpoint_digest TEXT CHECK (predecessor_checkpoint_digest IS NULL OR length(predecessor_checkpoint_digest) = 64),
    source_snapshot_digest TEXT NOT NULL CHECK (length(source_snapshot_digest) = 64),
    source_memory_snapshot_digest TEXT NOT NULL CHECK (length(source_memory_snapshot_digest) = 64),
    source_retention_fence_digest TEXT NOT NULL CHECK (length(source_retention_fence_digest) = 64),
    retain_source_until_unix_seconds INTEGER NOT NULL CHECK (retain_source_until_unix_seconds >= 0),
    policy_digest TEXT NOT NULL CHECK (length(policy_digest) = 64),
    candidate_digest TEXT NOT NULL CHECK (length(candidate_digest) = 64),
    candidate_image BLOB NOT NULL CHECK (length(candidate_image) BETWEEN 1 AND 67108864),
    candidate_image_digest TEXT NOT NULL CHECK (length(candidate_image_digest) = 64),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    selector_key_id TEXT NOT NULL,
    selector_trust_epoch INTEGER NOT NULL CHECK (selector_trust_epoch > 0),
    generator_key_id TEXT NOT NULL,
    generator_trust_epoch INTEGER NOT NULL CHECK (generator_trust_epoch > 0),
    tokenizer_key_id TEXT NOT NULL,
    tokenizer_trust_epoch INTEGER NOT NULL CHECK (tokenizer_trust_epoch > 0),
    accepted_at_unix_seconds INTEGER NOT NULL CHECK (accepted_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, candidate_digest),
    UNIQUE (owner_id, idempotency_key),
    UNIQUE (owner_id, scope_id, purpose_id, generation),
    UNIQUE (owner_id, source_snapshot_digest, policy_digest, generation),
    FOREIGN KEY (owner_id, payload_digest)
        REFERENCES compaction_payloads(owner_id, payload_digest) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS compaction_evaluations (
    owner_id TEXT NOT NULL,
    evaluation_digest TEXT NOT NULL CHECK (length(evaluation_digest) = 64),
    candidate_digest TEXT NOT NULL CHECK (length(candidate_digest) = 64),
    evaluator_key_id TEXT NOT NULL,
    evaluator_trust_epoch INTEGER NOT NULL CHECK (evaluator_trust_epoch > 0),
    evaluation_image BLOB NOT NULL CHECK (length(evaluation_image) BETWEEN 1 AND 67108864),
    evaluation_image_digest TEXT NOT NULL CHECK (length(evaluation_image_digest) = 64),
    accepted_at_unix_seconds INTEGER NOT NULL CHECK (accepted_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, evaluation_digest),
    UNIQUE (owner_id, candidate_digest, evaluator_key_id, evaluator_trust_epoch),
    FOREIGN KEY (owner_id, candidate_digest)
        REFERENCES compaction_candidates(owner_id, candidate_digest) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS compaction_proofs (
    owner_id TEXT NOT NULL,
    proof_digest TEXT NOT NULL CHECK (length(proof_digest) = 64),
    candidate_digest TEXT NOT NULL CHECK (length(candidate_digest) = 64),
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    evaluation_digest TEXT NOT NULL CHECK (length(evaluation_digest) = 64),
    proof_image BLOB NOT NULL CHECK (length(proof_image) BETWEEN 1 AND 67108864),
    proof_image_digest TEXT NOT NULL CHECK (length(proof_image_digest) = 64),
    proof_witness BLOB NOT NULL CHECK (length(proof_witness) = 96),
    accepted_at_unix_seconds INTEGER NOT NULL CHECK (accepted_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, proof_digest),
    UNIQUE (owner_id, candidate_digest),
    FOREIGN KEY (owner_id, candidate_digest)
        REFERENCES compaction_candidates(owner_id, candidate_digest) ON DELETE RESTRICT,
    FOREIGN KEY (owner_id, evaluation_digest)
        REFERENCES compaction_evaluations(owner_id, evaluation_digest) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS compaction_checkpoints (
    owner_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    purpose_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    predecessor_checkpoint_digest TEXT CHECK (predecessor_checkpoint_digest IS NULL OR length(predecessor_checkpoint_digest) = 64),
    source_snapshot_digest TEXT NOT NULL CHECK (length(source_snapshot_digest) = 64),
    source_memory_snapshot_digest TEXT NOT NULL CHECK (length(source_memory_snapshot_digest) = 64),
    candidate_digest TEXT NOT NULL CHECK (length(candidate_digest) = 64),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    proof_digest TEXT NOT NULL CHECK (length(proof_digest) = 64),
    checkpoint_image BLOB NOT NULL CHECK (length(checkpoint_image) BETWEEN 1 AND 67108864),
    checkpoint_image_digest TEXT NOT NULL CHECK (length(checkpoint_image_digest) = 64),
    publication_digest TEXT NOT NULL CHECK (length(publication_digest) = 64),
    published_at_unix_seconds INTEGER NOT NULL CHECK (published_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, scope_id, purpose_id, generation),
    UNIQUE (owner_id, checkpoint_digest),
    UNIQUE (owner_id, publication_digest),
    FOREIGN KEY (owner_id, candidate_digest)
        REFERENCES compaction_candidates(owner_id, candidate_digest) ON DELETE RESTRICT,
    FOREIGN KEY (owner_id, payload_digest)
        REFERENCES compaction_payloads(owner_id, payload_digest) ON DELETE RESTRICT,
    FOREIGN KEY (owner_id, proof_digest)
        REFERENCES compaction_proofs(owner_id, proof_digest) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS active_compaction_checkpoint (
    owner_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    purpose_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    predecessor_checkpoint_digest TEXT CHECK (predecessor_checkpoint_digest IS NULL OR length(predecessor_checkpoint_digest) = 64),
    publication_digest TEXT NOT NULL CHECK (length(publication_digest) = 64),
    updated_at_unix_seconds INTEGER NOT NULL CHECK (updated_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, scope_id, purpose_id),
    FOREIGN KEY (owner_id, scope_id, purpose_id, generation)
        REFERENCES compaction_checkpoints(owner_id, scope_id, purpose_id, generation) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS compaction_outbox (
    owner_id TEXT NOT NULL,
    event_id TEXT NOT NULL CHECK (length(event_id) = 64),
    publication_digest TEXT NOT NULL CHECK (length(publication_digest) = 64),
    event_kind TEXT NOT NULL CHECK (event_kind IN ('checkpoint-published', 'checkpoint-revoked', 'payload-gc')),
    payload BLOB NOT NULL CHECK (length(payload) BETWEEN 1 AND 1048576),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    state TEXT NOT NULL CHECK (state IN ('pending', 'claimed', 'delivered', 'terminal-failure')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 1000),
    claim_token TEXT,
    next_attempt_at_unix_seconds INTEGER NOT NULL CHECK (next_attempt_at_unix_seconds >= 0),
    created_at_unix_seconds INTEGER NOT NULL CHECK (created_at_unix_seconds >= 0),
    delivered_at_unix_seconds INTEGER,
    terminal_error_digest TEXT CHECK (terminal_error_digest IS NULL OR length(terminal_error_digest) = 64),
    PRIMARY KEY (owner_id, event_id),
    UNIQUE (owner_id, publication_digest, event_kind)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS compaction_checkpoint_revocations (
    owner_id TEXT NOT NULL,
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    revocation_digest TEXT NOT NULL CHECK (length(revocation_digest) = 64),
    reason_digest TEXT NOT NULL CHECK (length(reason_digest) = 64),
    revoked_at_unix_seconds INTEGER NOT NULL CHECK (revoked_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, checkpoint_digest),
    UNIQUE (owner_id, revocation_digest),
    FOREIGN KEY (owner_id, checkpoint_digest)
        REFERENCES compaction_checkpoints(owner_id, checkpoint_digest) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS compaction_candidates_source_idx
    ON compaction_candidates(owner_id, scope_id, purpose_id, source_snapshot_digest, generation);
CREATE INDEX IF NOT EXISTS compaction_checkpoints_lineage_idx
    ON compaction_checkpoints(owner_id, scope_id, purpose_id, generation DESC);
CREATE INDEX IF NOT EXISTS compaction_outbox_ready_idx
    ON compaction_outbox(owner_id, state, next_attempt_at_unix_seconds, created_at_unix_seconds);
CREATE INDEX IF NOT EXISTS compaction_trust_current_idx
    ON compaction_trust_registry(owner_id, role, trust_epoch DESC, valid_until_unix_seconds);

CREATE TRIGGER IF NOT EXISTS compaction_payloads_no_update
BEFORE UPDATE ON compaction_payloads BEGIN
    SELECT RAISE(ABORT, 'compaction payloads are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_payloads_no_delete
BEFORE DELETE ON compaction_payloads BEGIN
    SELECT RAISE(ABORT, 'compaction payloads require fenced GC');
END;
CREATE TRIGGER IF NOT EXISTS compaction_candidates_no_update
BEFORE UPDATE ON compaction_candidates BEGIN
    SELECT RAISE(ABORT, 'compaction candidates are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_candidates_no_delete
BEFORE DELETE ON compaction_candidates BEGIN
    SELECT RAISE(ABORT, 'compaction candidates are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_evaluations_no_update
BEFORE UPDATE ON compaction_evaluations BEGIN
    SELECT RAISE(ABORT, 'compaction evaluations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_evaluations_no_delete
BEFORE DELETE ON compaction_evaluations BEGIN
    SELECT RAISE(ABORT, 'compaction evaluations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_proofs_no_update
BEFORE UPDATE ON compaction_proofs BEGIN
    SELECT RAISE(ABORT, 'compaction proofs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_proofs_no_delete
BEFORE DELETE ON compaction_proofs BEGIN
    SELECT RAISE(ABORT, 'compaction proofs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_checkpoints_no_update
BEFORE UPDATE ON compaction_checkpoints BEGIN
    SELECT RAISE(ABORT, 'compaction checkpoints are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_checkpoints_no_delete
BEFORE DELETE ON compaction_checkpoints BEGIN
    SELECT RAISE(ABORT, 'compaction checkpoints are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_revocations_no_update
BEFORE UPDATE ON compaction_checkpoint_revocations BEGIN
    SELECT RAISE(ABORT, 'compaction revocations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_revocations_no_delete
BEFORE DELETE ON compaction_checkpoint_revocations BEGIN
    SELECT RAISE(ABORT, 'compaction revocations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS active_compaction_checkpoint_monotonic
BEFORE UPDATE ON active_compaction_checkpoint
WHEN NEW.generation != OLD.generation + 1
  OR NEW.predecessor_checkpoint_digest != OLD.checkpoint_digest
BEGIN
    SELECT RAISE(ABORT, 'active compaction checkpoint CAS is not monotonic');
END;
CREATE TRIGGER IF NOT EXISTS compaction_trust_registry_update_guard
BEFORE UPDATE ON compaction_trust_registry
WHEN OLD.revoked_at_unix_seconds IS NOT NULL
  OR NEW.owner_id != OLD.owner_id
  OR NEW.role != OLD.role
  OR NEW.key_id != OLD.key_id
  OR NEW.trust_epoch != OLD.trust_epoch
  OR NEW.valid_from_unix_seconds != OLD.valid_from_unix_seconds
  OR NEW.valid_until_unix_seconds != OLD.valid_until_unix_seconds
  OR NEW.predecessor_key_digest IS NOT OLD.predecessor_key_digest
  OR NEW.implementation_digest != OLD.implementation_digest
  OR NEW.attestation_digest != OLD.attestation_digest
  OR NEW.key_digest != OLD.key_digest
  OR NEW.verifying_key != OLD.verifying_key
  OR NEW.enrollment_digest != OLD.enrollment_digest
  OR NEW.enrolled_at_unix_seconds != OLD.enrolled_at_unix_seconds
  OR NEW.revoked_at_unix_seconds IS NULL
BEGIN
    SELECT RAISE(ABORT, 'only one-way trust revocation is permitted');
END;
CREATE TRIGGER IF NOT EXISTS compaction_trust_registry_no_delete
BEFORE DELETE ON compaction_trust_registry BEGIN
    SELECT RAISE(ABORT, 'compaction trust registry is append-only');
END;
CREATE TRIGGER IF NOT EXISTS compaction_outbox_identity_guard
BEFORE UPDATE ON compaction_outbox
WHEN NEW.owner_id != OLD.owner_id
  OR NEW.event_id != OLD.event_id
  OR NEW.publication_digest != OLD.publication_digest
  OR NEW.event_kind != OLD.event_kind
  OR NEW.payload != OLD.payload
  OR NEW.payload_digest != OLD.payload_digest
  OR NEW.created_at_unix_seconds != OLD.created_at_unix_seconds
  OR NEW.attempt_count < OLD.attempt_count
BEGIN
    SELECT RAISE(ABORT, 'compaction outbox identity is immutable');
END;
CREATE TRIGGER IF NOT EXISTS compaction_outbox_no_delete
BEFORE DELETE ON compaction_outbox BEGIN
    SELECT RAISE(ABORT, 'compaction outbox is append-only');
END;

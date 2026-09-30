#!/usr/bin/env python3
"""Separate effect authority from independent quarantine-resolution authority."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: str, transform) -> None:
    target = ROOT / path
    before = target.read_text(encoding="utf-8")
    after = transform(before)
    if after != before:
        target.write_text(after, encoding="utf-8")


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one source block, found {text.count(old)}")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: legacy block and migrated marker are both absent")


def protocol(text: str) -> str:
    text = replace_once(
        text,
        '''    pub authority_epoch: u64,
    pub resolution_sequence: u64,
''',
        '''    /// Original final-use/effect authority epoch bound by quarantine.
    pub authority_epoch: u64,
    /// Independent resolution authority epoch; never inferred from the effect epoch.
    pub resolution_authority_epoch: u64,
    /// Monotonic key epoch inside the independent resolution authority.
    pub resolution_key_epoch: u64,
    pub resolution_sequence: u64,
''',
        "pub resolution_authority_epoch: u64",
    )
    text = replace_once(
        text,
        '''            || self.authority_epoch == 0
            || self.resolution_sequence == 0
''',
        '''            || self.authority_epoch == 0
            || self.resolution_authority_epoch == 0
            || self.resolution_key_epoch == 0
            || self.resolution_sequence == 0
''',
        "self.resolution_authority_epoch == 0",
    )
    text = replace_once(
        text,
        '''                if let Some(digest) = constraints.compensation_prerequisite_sha256 {
                    require_digest(digest)?;
                }
''',
        '''                // Schema v1 permits a replacement only after an exact,
                // independently reviewable compensation prerequisite exists.
                // Provider-absence and provider-global-idempotency proofs require
                // their own future typed evidence variants; they are not ambient
                // substitutes for this mandatory digest.
                let compensation = constraints
                    .compensation_prerequisite_sha256
                    .ok_or(QuarantineProtocolError::UnsafeNewOperation)?;
                require_digest(compensation)?;
''',
        "let compensation = constraints",
    )
    text = replace_once(
        text,
        '''pub struct QuarantineResolutionFrontierV1 {
    pub authority_epoch: u64,
    pub resolution_sequence: u64,
''',
        '''pub struct QuarantineResolutionFrontierV1 {
    pub authority_epoch: u64,
    pub key_epoch: u64,
    pub resolution_sequence: u64,
''',
        "pub key_epoch: u64",
    )
    text = replace_once(
        text,
        '''    authority_epoch: u64,
    resolution_sequence: u64,
''',
        '''    resolution_authority_epoch: u64,
    resolution_key_epoch: u64,
    resolution_sequence: u64,
''',
        "resolution_authority_epoch: u64",
    )
    text = replace_once(
        text,
        '''            .field("authority_epoch", &self.authority_epoch)
            .field("resolution_sequence", &self.resolution_sequence)
''',
        '''            .field(
                "resolution_authority_epoch",
                &self.resolution_authority_epoch,
            )
            .field("resolution_key_epoch", &self.resolution_key_epoch)
            .field("resolution_sequence", &self.resolution_sequence)
''',
        '"resolution_key_epoch"',
    )
    text = replace_once(
        text,
        '''        authority_epoch: u64,
        resolution_sequence: u64,
        used_nonces: BTreeSet<[u8; 32]>,
''',
        '''        resolution_authority_epoch: u64,
        resolution_key_epoch: u64,
        resolution_sequence: u64,
        used_nonces: BTreeSet<[u8; 32]>,
''',
        "resolution_key_epoch: u64",
    )
    text = replace_once(
        text,
        '''            || authority_epoch == 0
            || used_nonces.len() > MAX_USED_NONCES
''',
        '''            || resolution_authority_epoch == 0
            || resolution_key_epoch == 0
            || used_nonces.len() > MAX_USED_NONCES
''',
        "|| resolution_key_epoch == 0",
    )
    text = replace_once(
        text,
        '''            authority_epoch,
            resolution_sequence,
            used_nonces,
''',
        '''            resolution_authority_epoch,
            resolution_key_epoch,
            resolution_sequence,
            used_nonces,
''',
        "resolution_authority_epoch,\n            resolution_key_epoch",
    )
    text = replace_once(
        text,
        '''        if resolution.authority_epoch != self.authority_epoch
            || resolution.authority_epoch != quarantine.authority_epoch
        {
            return Err(QuarantineProtocolError::AuthorityEpochMismatch);
        }
''',
        '''        if resolution.authority_epoch != quarantine.authority_epoch {
            return Err(QuarantineProtocolError::AuthorityEpochMismatch);
        }
        if resolution.resolution_authority_epoch != self.resolution_authority_epoch
            || resolution.resolution_key_epoch != self.resolution_key_epoch
        {
            return Err(QuarantineProtocolError::ResolutionAuthorityMismatch);
        }
''',
        "ResolutionAuthorityMismatch",
    )
    text = replace_once(
        text,
        '''        digest.update(self.authority_epoch.to_le_bytes());
        digest.update(self.resolution_sequence.to_le_bytes());
''',
        '''        digest.update(self.resolution_authority_epoch.to_le_bytes());
        digest.update(self.resolution_key_epoch.to_le_bytes());
        digest.update(self.resolution_sequence.to_le_bytes());
''',
        "digest.update(self.resolution_key_epoch.to_le_bytes())",
    )
    text = replace_once(
        text,
        '''        QuarantineResolutionFrontierV1 {
            authority_epoch: self.authority_epoch,
            resolution_sequence: self.resolution_sequence,
''',
        '''        QuarantineResolutionFrontierV1 {
            authority_epoch: self.resolution_authority_epoch,
            key_epoch: self.resolution_key_epoch,
            resolution_sequence: self.resolution_sequence,
''',
        "key_epoch: self.resolution_key_epoch",
    )
    text = replace_once(
        text,
        '''    AuthorityEpochMismatch,
    ResolutionRollback,
''',
        '''    AuthorityEpochMismatch,
    ResolutionAuthorityMismatch,
    ResolutionRollback,
''',
        "ResolutionAuthorityMismatch,",
    )
    text = replace_once(
        text,
        '''            authority_epoch: quarantine.authority_epoch,
            resolution_sequence: 1042,
''',
        '''            authority_epoch: quarantine.authority_epoch,
            resolution_authority_epoch: 42,
            resolution_key_epoch: 7,
            resolution_sequence: 1042,
''',
        "resolution_authority_epoch: 42",
    )
    text = replace_once(
        text,
        '''            12,
            1000,
            BTreeSet::new(),
''',
        '''            42,
            7,
            1000,
            BTreeSet::new(),
''',
        "            42,\n            7,\n            1000,",
    )
    if "replacement_without_compensation_is_rejected" not in text:
        anchor = '''    #[test]
    fn unknown_fields_and_empty_evidence_are_rejected() {
'''
        addition = r'''    #[test]
    fn replacement_without_compensation_is_rejected() {
        let quarantine = quarantine();
        let mut proposal = resolution(
            &quarantine,
            QuarantineResolutionDispositionV1::AuthorizeNewOperation,
        );
        proposal
            .new_operation_constraints
            .as_mut()
            .unwrap()
            .compensation_prerequisite_sha256 = None;
        assert!(matches!(
            proposal.signing_bytes(),
            Err(QuarantineProtocolError::UnsafeNewOperation)
        ));
    }

''' + anchor
        if anchor not in text:
            raise RuntimeError("quarantine negative-test anchor absent")
        text = text.replace(anchor, addition, 1)
    return text


def durable_store(text: str) -> str:
    text = replace_once(
        text,
        '''                authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
                verifying_key BLOB NOT NULL CHECK (length(verifying_key) = 32),
                resolution_sequence INTEGER NOT NULL CHECK (resolution_sequence >= 0),
                state_sha256 BLOB NOT NULL CHECK (length(state_sha256) = 32),
                PRIMARY KEY (signer_id, authority_epoch)
''',
        '''                authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
                key_epoch INTEGER NOT NULL CHECK (key_epoch > 0),
                verifying_key BLOB NOT NULL CHECK (length(verifying_key) = 32),
                resolution_sequence INTEGER NOT NULL CHECK (resolution_sequence >= 0),
                state_sha256 BLOB NOT NULL CHECK (length(state_sha256) = 32),
                PRIMARY KEY (signer_id, authority_epoch, key_epoch)
''',
        "PRIMARY KEY (signer_id, authority_epoch, key_epoch)",
    )
    text = replace_once(
        text,
        '''                authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
                nonce BLOB NOT NULL CHECK (length(nonce) = 32),
                resolution_sequence INTEGER NOT NULL CHECK (resolution_sequence > 0),
                PRIMARY KEY (signer_id, authority_epoch, nonce),
                UNIQUE (signer_id, authority_epoch, resolution_sequence),
                FOREIGN KEY (signer_id, authority_epoch)
                    REFERENCES runtime_codex_quarantine_frontiers(signer_id, authority_epoch)
''',
        '''                authority_epoch INTEGER NOT NULL CHECK (authority_epoch > 0),
                key_epoch INTEGER NOT NULL CHECK (key_epoch > 0),
                nonce BLOB NOT NULL CHECK (length(nonce) = 32),
                resolution_sequence INTEGER NOT NULL CHECK (resolution_sequence > 0),
                PRIMARY KEY (signer_id, authority_epoch, key_epoch, nonce),
                UNIQUE (signer_id, authority_epoch, key_epoch, resolution_sequence),
                FOREIGN KEY (signer_id, authority_epoch, key_epoch)
                    REFERENCES runtime_codex_quarantine_frontiers(signer_id, authority_epoch, key_epoch)
''',
        "PRIMARY KEY (signer_id, authority_epoch, key_epoch, nonce)",
    )
    anchor = '''        let frontier_row = sqlx::query(
'''
    prefix = '''        let resolution_authority_epoch = signed.resolution.resolution_authority_epoch;
        let resolution_key_epoch = signed.resolution.resolution_key_epoch;
''' + anchor
    text = replace_once(text, anchor, prefix, "let resolution_authority_epoch = signed.resolution")
    text = replace_once(
        text,
        '''               WHERE signer_id = ? AND authority_epoch = ?"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(quarantine.authority_epoch, "authority epoch")?)
''',
        '''               WHERE signer_id = ? AND authority_epoch = ? AND key_epoch = ?"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(
            resolution_authority_epoch,
            "resolution authority epoch",
        )?)
        .bind(quarantine_i64(resolution_key_epoch, "resolution key epoch")?)
''',
        "WHERE signer_id = ? AND authority_epoch = ? AND key_epoch = ?",
    )
    text = replace_once(
        text,
        '''               WHERE signer_id = ? AND authority_epoch = ? ORDER BY nonce"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(quarantine.authority_epoch, "authority epoch")?)
''',
        '''               WHERE signer_id = ? AND authority_epoch = ? AND key_epoch = ? ORDER BY nonce"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(
            resolution_authority_epoch,
            "resolution authority epoch",
        )?)
        .bind(quarantine_i64(resolution_key_epoch, "resolution key epoch")?)
''',
        "WHERE signer_id = ? AND authority_epoch = ? AND key_epoch = ? ORDER BY nonce",
    )
    text = replace_once(
        text,
        '''            quarantine.authority_epoch,
            current_sequence,
            used_nonces,
''',
        '''            resolution_authority_epoch,
            resolution_key_epoch,
            current_sequence,
            used_nonces,
''',
        "resolution_authority_epoch,\n            resolution_key_epoch,",
    )
    text = replace_once(
        text,
        '''               (signer_id, authority_epoch, verifying_key, resolution_sequence, state_sha256)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(signer_id, authority_epoch) DO UPDATE SET
''',
        '''               (signer_id, authority_epoch, key_epoch, verifying_key, resolution_sequence, state_sha256)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(signer_id, authority_epoch, key_epoch) DO UPDATE SET
''',
        "ON CONFLICT(signer_id, authority_epoch, key_epoch)",
    )
    text = replace_once(
        text,
        '''        .bind(quarantine_i64(frontier.authority_epoch, "frontier authority epoch")?)
        .bind(verifying_key.as_slice())
''',
        '''        .bind(quarantine_i64(frontier.authority_epoch, "frontier authority epoch")?)
        .bind(quarantine_i64(frontier.key_epoch, "frontier key epoch")?)
        .bind(verifying_key.as_slice())
''',
        "frontier.key_epoch",
    )
    text = replace_once(
        text,
        '''               (signer_id, authority_epoch, nonce, resolution_sequence)
               VALUES (?, ?, ?, ?)"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(frontier.authority_epoch, "nonce authority epoch")?)
        .bind(signed.resolution.nonce.as_slice())
''',
        '''               (signer_id, authority_epoch, key_epoch, nonce, resolution_sequence)
               VALUES (?, ?, ?, ?, ?)"#,
        )
        .bind(&signer_id)
        .bind(quarantine_i64(frontier.authority_epoch, "nonce authority epoch")?)
        .bind(quarantine_i64(frontier.key_epoch, "nonce key epoch")?)
        .bind(signed.resolution.nonce.as_slice())
''',
        "nonce key epoch",
    )
    return text


def main() -> None:
    rewrite(
        "codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs",
        protocol,
    )
    rewrite(
        "codex-rs/hepta-infer-worker-host/src/runtime_codex_quarantine.rs",
        durable_store,
    )


if __name__ == "__main__":
    main()

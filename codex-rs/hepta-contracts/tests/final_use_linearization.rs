#[cfg(unix)]
mod unix {
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::mpsc;
    use std::time::Duration;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseBinding;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    #[test]
    fn callback_reentrant_revocation_is_ordered_after_final_entry_without_deadlock() {
        let issuer = SigningKey::from_bytes(&[61; 32]);
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        let binding = FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "provider:heptabao".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        };
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 17,
            grant_id: "reentrant-revoke".into(),
            nonce: [8; 32],
            binding: binding.clone(),
            not_before_unix_ms: now - 1_000,
            expires_at_unix_ms: now + 30_000,
        };
        let signature = issuer.sign(&grant.signing_bytes().unwrap()).to_bytes().to_vec();
        let signed = SignedFinalUseGrant { grant, signature };
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .unwrap();
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 17,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .unwrap();
        let token = authority.claim(&signed, &binding).unwrap();

        let callback_authority = authority.clone();
        let grant_id = signed.grant.grant_id.clone();
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let result = callback_authority.with_verified_use(token, &binding, || {
                callback_authority
                    .update_revocations(FinalUseRevocations {
                        authority_epoch: 17,
                        revision: 2,
                        revoked_grant_ids: BTreeSet::from([grant_id]),
                    })
                    .unwrap();
                7
            });
            let _ = tx.send(result);
        });

        assert_eq!(
            rx.recv_timeout(Duration::from_secs(2))
                .expect("consumer callback remained blocked on the revocation mutex"),
            Ok(7)
        );
    }
}

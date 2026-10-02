use super::*;
use pretty_assertions::assert_eq;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

fn private_tempdir() -> std::io::Result<tempfile::TempDir> {
    let directory = tempfile::tempdir()?;
    #[cfg(unix)]
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    Ok(directory)
}

#[test]
fn legacy_single_key_and_key_ring_snapshots_preserve_nonce_claims() {
    for trust in [
        StoreTrust::SingleKey([47; 32]),
        StoreTrust::IssuerKeyRing([91; 32]),
    ] {
        let directory = private_tempdir().unwrap();
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let state = State {
            head: head.clone(),
            used_nonces: BTreeSet::from([[5; 32], [6; 32]]),
            pending_revocations: None,
            failed: false,
        };
        let (owner, _) = Store::open_inner(
            directory.path(),
            "owner",
            trust,
            head.clone(),
            StartupHeadPolicy::Exact,
        )
        .unwrap();
        drop(owner);
        let legacy = match trust {
            StoreTrust::SingleKey(key) => serde_json::json!({
                "schema": 1, "signer_id": "owner", "verifying_key": key, "state": state,
            }),
            StoreTrust::IssuerKeyRing(digest) => serde_json::json!({
                "schema": 2, "signer_id": "owner", "issuer_trust_sha256": digest, "state": state,
            }),
        };
        std::fs::write(
            directory.path().join("authority.json"),
            serde_json::to_vec(&legacy).unwrap(),
        )
        .unwrap();
        std::fs::remove_file(directory.path().join("authority.claims")).unwrap();
        let (owner, migrated) = Store::open_inner(
            directory.path(),
            "owner",
            trust,
            head.clone(),
            StartupHeadPolicy::Exact,
        )
        .unwrap();
        assert_eq!(migrated.head, state.head);
        assert_eq!(migrated.used_nonces, state.used_nonces);
        assert_eq!(migrated.pending_revocations, None);
        owner.append_claim(9, [7; 32]).unwrap();
        drop(owner);
        let (_, reopened) = Store::open_inner(
            directory.path(),
            "owner",
            trust,
            head,
            StartupHeadPolicy::Exact,
        )
        .unwrap();
        assert_eq!(
            reopened.used_nonces,
            BTreeSet::from([[5; 32], [6; 32], [7; 32]])
        );
        assert_eq!(reopened.pending_revocations, None);
    }
}

#[test]
fn legacy_journal_keeps_trust_binding_and_exact_head_checks() {
    let directory = private_tempdir().unwrap();
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, _) = Store::open(directory.path(), "owner", [47; 32], head.clone()).unwrap();
    owner.append_claim(9, [5; 32]).unwrap();
    drop(owner);
    let legacy = serde_json::json!({
        "schema": 2, "signer_id": "owner", "verifying_key": ([47; 32]), "head": head,
    });
    std::fs::write(
        directory.path().join("authority.json"),
        serde_json::to_vec(&legacy).unwrap(),
    )
    .unwrap();
    assert!(matches!(
        Store::open(directory.path(), "owner", [48; 32], head.clone()),
        Err(FinalUseError::InvalidTrust)
    ));
    let (owner, migrated) =
        Store::open_exact(directory.path(), "owner", [47; 32], head.clone()).unwrap();
    assert_eq!(migrated.used_nonces, BTreeSet::from([[5; 32]]));
    assert_eq!(migrated.pending_revocations, None);
    drop(owner);
    let newer = FinalUseRevocations {
        revision: 2,
        ..head
    };
    assert!(matches!(
        Store::open_exact(directory.path(), "owner", [47; 32], newer),
        Err(FinalUseError::InvalidTrust)
    ));
}

#[test]
fn fifo_snapshot_and_claim_journal_are_rejected_without_waiting_for_a_writer() {
    for name in ["authority.json", "authority.claims"] {
        let directory = private_tempdir().unwrap();
        let root = prepare_directory(directory.path()).unwrap();
        rustix::fs::mknodat(
            &root,
            name,
            rustix::fs::FileType::Fifo,
            rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
            0,
        )
        .unwrap();
        let (tx, rx) = std::sync::mpsc::channel();
        let worker = std::thread::spawn(move || {
            let result = open_private(&root, name, Access::Read).map(|_| ());
            tx.send(result).unwrap();
            drop(directory);
        });
        assert_eq!(
            rx.recv_timeout(std::time::Duration::from_secs(2))
                .expect("FIFO authority input open waited for a writer"),
            Err(FinalUseError::UnsafeStateDirectory)
        );
        worker.join().unwrap();
    }
}

fn epoch_rollover_crash(
    frame_count: usize,
) -> Result<
    (
        tempfile::TempDir,
        ed25519_dalek::SigningKey,
        FinalUseRevocations,
    ),
    Box<dyn std::error::Error>,
> {
    let directory = private_tempdir()?;
    let signing_key = ed25519_dalek::SigningKey::from_bytes(&[47; 32]);
    let old_head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let (owner, _) = Store::open(
        directory.path(),
        "owner",
        signing_key.verifying_key().to_bytes(),
        old_head,
    )?;
    let mut bytes = Vec::with_capacity(frame_count * CLAIM_FRAME_BYTES);
    for index in 1..=frame_count {
        bytes.extend_from_slice(&9_u64.to_be_bytes());
        let mut nonce = [0; 32];
        nonce[..8].copy_from_slice(&u64::try_from(index)?.to_be_bytes());
        bytes.extend_from_slice(&nonce);
    }
    let mut journal = open_private(&owner.root, "authority.claims", Access::Write)?;
    journal.write_all(&bytes)?;
    journal.sync_all()?;
    let next_head = FinalUseRevocations {
        authority_epoch: 10,
        revision: 2,
        revoked_grant_ids: BTreeSet::new(),
    };
    owner.persist_snapshot(&State {
        head: next_head.clone(),
        used_nonces: BTreeSet::new(),
        pending_revocations: None,
        failed: false,
    })?;
    // Model process loss after snapshot publication but before journal replacement.
    drop(journal);
    drop(owner);
    Ok((directory, signing_key, next_head))
}

#[test]
fn recovered_epoch_compacts_obsolete_claims_before_new_claims() {
    use ed25519_dalek::Signer;

    let (directory, signing_key, head) = epoch_rollover_crash(MAX_CLAIMS).unwrap();
    let authority = crate::FinalUseAuthority::open_state_dir(
        directory.path(),
        "owner".into(),
        signing_key.verifying_key().to_bytes(),
        head.clone(),
    )
    .unwrap();
    let now = crate::AuthorityClock::now_unix_ms(&crate::SystemAuthorityClock).unwrap();
    let binding = crate::FinalUseBinding {
        subject_id: "agent".into(),
        destination_id: "effect".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    for nonce in [[7; 32], [8; 32]] {
        let grant = crate::FinalUseGrant {
            schema_version: 1,
            signer_id: "owner".into(),
            authority_epoch: head.authority_epoch,
            grant_id: format!("grant-{}", nonce[0]),
            nonce,
            binding: binding.clone(),
            not_before_unix_ms: now,
            expires_at_unix_ms: now + 60_000,
        };
        let signature = signing_key
            .sign(&grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        authority
            .claim(&crate::SignedFinalUseGrant { grant, signature }, &binding)
            .unwrap();
    }
    drop(authority);
    let (_, reopened) = Store::open_exact(
        directory.path(),
        "owner",
        signing_key.verifying_key().to_bytes(),
        head,
    )
    .unwrap();
    assert_eq!(reopened.used_nonces, BTreeSet::from([[7; 32], [8; 32]]));
}

#[test]
fn recovery_compaction_waits_for_external_frontier_match() {
    struct FixedFrontier(crate::FinalUseFrontier);
    impl crate::AuthorityFrontierStore<crate::FinalUseFrontier> for FixedFrontier {
        fn load(
            &self,
            _owner_id: &str,
        ) -> Result<crate::FinalUseFrontier, crate::AuthorityTrustError> {
            Ok(self.0)
        }

        fn compare_and_set(
            &self,
            _owner_id: &str,
            _expected: &crate::FinalUseFrontier,
            _next: &crate::FinalUseFrontier,
        ) -> Result<(), crate::AuthorityTrustError> {
            Err(crate::AuthorityTrustError::Unavailable)
        }
    }

    let (directory, signing_key, head) = epoch_rollover_crash(/*frame_count*/ 2).unwrap();
    let journal = directory.path().join("authority.claims");
    let before = std::fs::read(&journal).unwrap();
    let frontier = crate::FinalUseFrontier::for_initial_head(&head).unwrap();
    let mut wrong_frontier = frontier;
    wrong_frontier.state_sha256[0] ^= 1;
    let rejected = crate::FinalUseAuthority::open_state_dir_with_trust(
        directory.path(),
        "owner".into(),
        signing_key.verifying_key().to_bytes(),
        head.clone(),
        std::sync::Arc::new(crate::SystemAuthorityClock),
        std::sync::Arc::new(FixedFrontier(wrong_frontier)),
    );
    assert!(matches!(
        rejected,
        Err(FinalUseError::AntiRollbackViolation)
    ));
    assert_eq!(std::fs::read(&journal).unwrap(), before);
    let owner = crate::FinalUseAuthority::open_state_dir_with_trust(
        directory.path(),
        "owner".into(),
        signing_key.verifying_key().to_bytes(),
        head,
        std::sync::Arc::new(crate::SystemAuthorityClock),
        std::sync::Arc::new(FixedFrontier(frontier)),
    )
    .unwrap();
    assert_eq!(owner.frontier().unwrap(), frontier);
    assert!(std::fs::read(&journal).unwrap().is_empty());
}

#[test]
fn recovered_epoch_retains_existing_current_nonce_across_compaction() {
    use ed25519_dalek::Signer;

    let (directory, signing_key, head) = epoch_rollover_crash(/*frame_count*/ 2).unwrap();
    let journal = directory.path().join("authority.claims");
    let nonce = [7; 32];
    let mut live_frame = head.authority_epoch.to_be_bytes().to_vec();
    live_frame.extend_from_slice(&nonce);
    let mut file = std::fs::OpenOptions::new()
        .append(true)
        .open(&journal)
        .unwrap();
    file.write_all(&live_frame).unwrap();
    file.sync_all().unwrap();
    drop(file);
    let now = crate::AuthorityClock::now_unix_ms(&crate::SystemAuthorityClock).unwrap();
    let binding = crate::FinalUseBinding {
        subject_id: "agent".into(),
        destination_id: "effect".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    };
    let grant = crate::FinalUseGrant {
        schema_version: 1,
        signer_id: "owner".into(),
        authority_epoch: head.authority_epoch,
        grant_id: "retained-current-claim".into(),
        nonce,
        binding: binding.clone(),
        not_before_unix_ms: now,
        expires_at_unix_ms: now + 60_000,
    };
    let signature = signing_key
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    let signed = crate::SignedFinalUseGrant { grant, signature };
    for _ in 0..2 {
        let owner = crate::FinalUseAuthority::open_state_dir(
            directory.path(),
            "owner".into(),
            signing_key.verifying_key().to_bytes(),
            head.clone(),
        )
        .unwrap();
        assert_eq!(owner.capacity().unwrap().used_nonces, 1);
        assert!(matches!(
            owner.claim(&signed, &binding),
            Err(FinalUseError::AlreadyClaimed)
        ));
        assert_eq!(std::fs::read(&journal).unwrap(), live_frame);
    }
}

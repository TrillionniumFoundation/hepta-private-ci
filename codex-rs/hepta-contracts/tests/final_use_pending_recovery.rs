#[cfg(unix)]
mod unix {
    use std::collections::BTreeSet;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::Arc;
    use std::sync::Mutex;
    use std::sync::mpsc;
    use std::thread;

    use codex_hepta_contracts::AuthorityClock;
    use codex_hepta_contracts::AuthorityFrontierStore;
    use codex_hepta_contracts::AuthorityTrustError;
    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseBinding;
    use codex_hepta_contracts::FinalUseError;
    use codex_hepta_contracts::FinalUseFrontier;
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseIssuerTrustKey;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    #[derive(Debug)]
    struct FixedClock(u64);

    impl AuthorityClock for FixedClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(self.0)
        }
    }

    #[derive(Debug)]
    struct MemoryFrontier(Mutex<FinalUseFrontier>);

    impl AuthorityFrontierStore<FinalUseFrontier> for MemoryFrontier {
        fn load(&self, _owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
            self.0
                .lock()
                .map(|current| *current)
                .map_err(|_| AuthorityTrustError::Unavailable)
        }

        fn compare_and_set(
            &self,
            _owner_id: &str,
            expected: &FinalUseFrontier,
            next: &FinalUseFrontier,
        ) -> Result<(), AuthorityTrustError> {
            let mut current = self
                .0
                .lock()
                .map_err(|_| AuthorityTrustError::Unavailable)?;
            if &*current != expected {
                return Err(AuthorityTrustError::Conflict);
            }
            *current = *next;
            Ok(())
        }
    }

    fn initial_head() -> FinalUseRevocations {
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        }
    }

    fn revoked_head(grant_id: &str) -> FinalUseRevocations {
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([grant_id.to_string()]),
        }
    }

    fn binding() -> FinalUseBinding {
        FinalUseBinding {
            subject_id: "agent-one".into(),
            destination_id: "provider:fixture".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        }
    }

    fn signed_grant(issuer: &SigningKey, grant_id: &str, nonce: [u8; 32]) -> SignedFinalUseGrant {
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "security-owner".into(),
            authority_epoch: 9,
            grant_id: grant_id.into(),
            nonce,
            binding: binding(),
            not_before_unix_ms: 1_000,
            expires_at_unix_ms: 8_000,
        };
        let signature = issuer
            .sign(&grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        SignedFinalUseGrant { grant, signature }
    }

    fn issuer_keys(issuer: &SigningKey) -> Vec<FinalUseIssuerTrustKey> {
        vec![FinalUseIssuerTrustKey {
            key_id: "issuer-2026-a".into(),
            verifying_key: issuer.verifying_key().to_bytes(),
            not_before_authority_epoch: 1,
            not_after_authority_epoch: 20,
        }]
    }

    fn open(
        directory: &std::path::Path,
        issuer: &SigningKey,
        frontier: Arc<MemoryFrontier>,
    ) -> FinalUseAuthority {
        FinalUseAuthority::open_state_dir_with_issuer_keys(
            directory,
            "security-owner".into(),
            issuer_keys(issuer),
            initial_head(),
            Arc::new(FixedClock(2_000)),
            frontier,
        )
        .unwrap()
    }

    fn recover(
        directory: &std::path::Path,
        issuer: &SigningKey,
        authenticated_head: FinalUseRevocations,
        frontier: Arc<MemoryFrontier>,
    ) -> FinalUseAuthority {
        FinalUseAuthority::recover_state_dir_with_issuer_keys(
            directory,
            "security-owner".into(),
            issuer_keys(issuer),
            authenticated_head,
            Arc::new(FixedClock(2_000)),
            frontier,
        )
        .unwrap()
    }

    fn begin_active_dispatch(
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
    ) -> (
        mpsc::Sender<()>,
        thread::JoinHandle<Result<(), FinalUseError>>,
    ) {
        let token = authority.claim(grant, &grant.grant.binding).unwrap();
        let worker_authority = authority.clone();
        let worker_binding = grant.grant.binding.clone();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let worker = thread::spawn(move || {
            worker_authority.with_verified_effect(token, &worker_binding, || {
                entered_tx.send(()).unwrap();
                release_rx.recv().unwrap();
            })
        });
        entered_rx.recv().unwrap();
        (release_tx, worker)
    }

    #[test]
    fn pending_revocation_survives_restart_and_commits_exactly() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let issuer = SigningKey::from_bytes(&[47; 32]);
        let initial = initial_head();
        let frontier = Arc::new(MemoryFrontier(Mutex::new(
            FinalUseFrontier::for_initial_head(&initial).unwrap(),
        )));
        let authority = open(directory.path(), &issuer, frontier.clone());
        let grant = signed_grant(&issuer, "durable-pending", [5; 32]);
        let later = signed_grant(&issuer, "blocked-while-pending", [6; 32]);
        let revoked = revoked_head(&grant.grant.grant_id);

        let (release, worker) = begin_active_dispatch(&authority, &grant);
        assert_eq!(
            authority.update_revocations(revoked.clone()),
            Err(FinalUseError::DispatchInProgress)
        );
        assert_eq!(
            authority.claim(&later, &later.grant.binding).unwrap_err(),
            FinalUseError::RevocationPending
        );
        release.send(()).unwrap();
        worker.join().unwrap().unwrap();
        drop(authority);

        let recovered = recover(directory.path(), &issuer, revoked.clone(), frontier.clone());
        assert_eq!(
            recovered.claim(&later, &later.grant.binding).unwrap_err(),
            FinalUseError::RevocationPending
        );
        recovered.update_revocations(revoked.clone()).unwrap();
        assert_eq!(recovered.revocation_head().unwrap(), revoked);
        assert_eq!(
            recovered.claim(&grant, &grant.grant.binding).unwrap_err(),
            FinalUseError::Revoked
        );
    }

    #[test]
    fn recovery_closes_both_frontier_first_crash_windows() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let issuer = SigningKey::from_bytes(&[51; 32]);
        let initial = initial_head();
        let frontier = Arc::new(MemoryFrontier(Mutex::new(
            FinalUseFrontier::for_initial_head(&initial).unwrap(),
        )));
        let authority = open(directory.path(), &issuer, frontier.clone());
        let grant = signed_grant(&issuer, "frontier-first-crash", [7; 32]);
        let later = signed_grant(&issuer, "blocked-after-repair", [8; 32]);
        let revoked = revoked_head(&grant.grant.grant_id);

        let (release, worker) = begin_active_dispatch(&authority, &grant);
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o500)).unwrap();
        assert_eq!(
            authority.update_revocations(revoked.clone()),
            Err(FinalUseError::Unavailable),
            "the external pending frontier advances before a failed local snapshot"
        );
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        release.send(()).unwrap();
        worker.join().unwrap().unwrap();
        drop(authority);

        let repaired_pending =
            recover(directory.path(), &issuer, revoked.clone(), frontier.clone());
        assert_eq!(
            repaired_pending
                .claim(&later, &later.grant.binding)
                .unwrap_err(),
            FinalUseError::RevocationPending
        );

        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o500)).unwrap();
        assert_eq!(
            repaired_pending.update_revocations(revoked.clone()),
            Err(FinalUseError::Unavailable),
            "the external committed frontier advances before a failed local snapshot"
        );
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        drop(repaired_pending);

        let repaired_commit = recover(directory.path(), &issuer, revoked.clone(), frontier);
        assert_eq!(repaired_commit.revocation_head().unwrap(), revoked);
        assert_eq!(
            repaired_commit
                .claim(&grant, &grant.grant.binding)
                .unwrap_err(),
            FinalUseError::Revoked
        );
    }
}

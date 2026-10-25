use super::*;
use codex_hepta_contracts::SystemAuthorityClock;
use ed25519_dalek::Verifier;
use pretty_assertions::assert_eq;

fn policy() -> DeploymentGrantPolicy {
    DeploymentGrantPolicy {
        subject_id: "agent.local".into(),
        destination_id: "notes.local".into(),
        scope_sha256: [2; 32],
        lifetime_ms: 30_000,
    }
}

fn binding() -> FinalUseBinding {
    FinalUseBinding {
        subject_id: "agent.local".into(),
        destination_id: "notes.local".into(),
        request_sha256: [1; 32],
        scope_sha256: [2; 32],
        payload_sha256: [3; 32],
    }
}

#[test]
fn actual_random_key_signs_original_grant_and_ids_survive_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("issuer");
    let clock: Arc<dyn AuthorityClock> = Arc::new(SystemAuthorityClock);
    let issuer = DeploymentFinalUseIssuer::create(
        &path,
        "local-issuer".into(),
        vec![policy()],
        Arc::clone(&clock),
    )
    .unwrap();
    let first = issuer.issue(&binding()).unwrap().unwrap();
    let public = issuer.trust_key().unwrap();
    let key = ed25519_dalek::VerifyingKey::from_bytes(&public.verifying_key).unwrap();
    key.verify(
        &first.grant.signing_bytes().unwrap(),
        &ed25519_dalek::Signature::from_slice(&first.signature).unwrap(),
    )
    .unwrap();
    drop(issuer);
    let issuer = DeploymentFinalUseIssuer::open(&path, clock).unwrap();
    let second = issuer.issue(&binding()).unwrap().unwrap();
    assert_ne!(first.grant.grant_id, second.grant.grant_id);
    assert_ne!(first.grant.nonce, second.grant.nonce);
    assert_eq!(
        issuer.trust_key().unwrap().verifying_key,
        public.verifying_key
    );
    assert!(
        DeploymentFinalUseIssuer::create(
            &path,
            "replacement".into(),
            vec![policy()],
            Arc::new(SystemAuthorityClock)
        )
        .is_err()
    );
}

#[test]
fn out_of_scope_and_invalid_grants_do_not_issue_and_revocation_is_durable() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("issuer");
    let issuer = DeploymentFinalUseIssuer::create(
        &path,
        "local-issuer".into(),
        vec![policy()],
        Arc::new(SystemAuthorityClock),
    )
    .unwrap();
    let mut wrong = binding();
    wrong.destination_id = "other-device".into();
    assert_eq!(issuer.issue(&wrong).unwrap(), None);
    let mut invalid = binding();
    invalid.payload_sha256 = [0; 32];
    assert!(issuer.issue(&invalid).is_err());
    let grant = issuer.issue(&binding()).unwrap().unwrap();
    let before = issuer.revocations().unwrap();
    assert!(issuer.revoke("invalid id").is_err());
    assert!(issuer.revoke("invalid-é").is_err());
    assert_eq!(issuer.revocations().unwrap(), before);
    let head = issuer.revoke(&grant.grant.grant_id).unwrap();
    assert!(head.revoked_grant_ids.contains(&grant.grant.grant_id));
    drop(issuer);
    let issuer = DeploymentFinalUseIssuer::open(&path, Arc::new(SystemAuthorityClock)).unwrap();
    assert_eq!(issuer.revocations().unwrap(), head);
    assert_eq!(issuer.revoke(&grant.grant.grant_id).unwrap(), head);
}

#[test]
fn original_agentd_client_reads_real_server_grant_and_denial_on_same_channel() {
    let directory = tempfile::tempdir().unwrap();
    let issuer = DeploymentFinalUseIssuer::create(
        &directory.path().join("issuer"),
        "local-issuer".into(),
        vec![policy()],
        Arc::new(SystemAuthorityClock),
    )
    .unwrap();
    let (client, mut server) = UnixStream::pair().unwrap();
    let worker = std::thread::spawn(move || {
        assert!(issuer.serve_next(&mut server).unwrap());
        assert!(issuer.serve_next(&mut server).unwrap());
    });
    // SAFETY: geteuid has no arguments or borrowed memory.
    let peer = crate::AgentdFinalUseIssuerPeer {
        uid: unsafe { libc::geteuid() },
        pid: std::process::id(),
    };
    let client =
        crate::AgentdUnixFinalUseGrantProvider::from_stream(client, peer, Duration::from_secs(2))
            .unwrap();
    assert_eq!(
        client.request_grant(&binding()).unwrap().grant.binding,
        binding()
    );
    let mut wrong = binding();
    wrong.scope_sha256 = [9; 32];
    assert_eq!(
        client.request_grant(&wrong),
        Err(crate::AgentdFinalUseIssuerError::Denied)
    );
    worker.join().unwrap();
}

#[test]
fn original_final_use_owner_rejects_replay_revocation_and_local_state_rollback() {
    use codex_hepta_contracts::FinalUseAuthority;
    use codex_hepta_contracts::FinalUseError;
    use codex_hepta_contracts::FinalUseFrontier;

    let directory = tempfile::tempdir().unwrap();
    let clock: Arc<dyn AuthorityClock> = Arc::new(SystemAuthorityClock);
    let issuer = DeploymentFinalUseIssuer::create(
        &directory.path().join("independent-issuer"),
        "local-issuer".into(),
        vec![policy()],
        Arc::clone(&clock),
    )
    .unwrap();
    let head = issuer.revocations().unwrap();
    let frontier = Arc::new(
        DeploymentFrontierStore::<FinalUseFrontier>::create(
            &directory.path().join("independent-frontier"),
        )
        .unwrap(),
    );
    frontier
        .provision(
            "local-issuer",
            &FinalUseFrontier::for_initial_head(&head).unwrap(),
        )
        .unwrap();
    let local = directory.path().join("agentd-final-use");
    let authority = FinalUseAuthority::open_state_dir_with_issuer_keys(
        &local,
        "local-issuer".into(),
        vec![issuer.trust_key().unwrap()],
        head.clone(),
        Arc::clone(&clock),
        frontier.clone(),
    )
    .unwrap();
    let snapshot: Vec<_> = std::fs::read_dir(&local)
        .unwrap()
        .map(|entry| {
            let path = entry.unwrap().path();
            (path.clone(), std::fs::read(path).unwrap())
        })
        .collect();
    let signed = issuer.issue(&binding()).unwrap().unwrap();
    let claimed = authority.claim(&signed, &binding()).unwrap();
    assert!(matches!(
        authority.claim(&signed, &binding()),
        Err(FinalUseError::AlreadyClaimed)
    ));
    drop(claimed);
    let pending = issuer.issue(&binding()).unwrap().unwrap();
    let revoked_head = issuer.revoke(&pending.grant.grant_id).unwrap();
    // Explicit trusted-host publication, not the unsigned issuer RPC reply.
    authority.update_revocations(revoked_head).unwrap();
    assert!(authority.claim(&pending, &binding()).is_err());
    drop(authority);
    // Restore only Agentd's earlier local state. The independent trust domain
    // retains its newer frontier, so original FinalUse refuses the rollback.
    for (path, bytes) in snapshot {
        std::fs::write(path, bytes).unwrap();
    }
    assert!(matches!(
        FinalUseAuthority::open_state_dir_with_issuer_keys(
            &local,
            "local-issuer".into(),
            vec![issuer.trust_key().unwrap()],
            head,
            clock,
            frontier,
        ),
        Err(FinalUseError::AntiRollbackViolation)
    ));
}

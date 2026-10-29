use super::*;
use ml_dsa::Keypair;
use ml_dsa::SigningKey;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicBool;

struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(5_000)
    }
}
struct Frontier {
    head: Mutex<FinalUseFrontier>,
    fail: AtomicBool,
}
impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, _owner: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        self.head
            .lock()
            .map(|value| *value)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
    fn compare_and_set(
        &self,
        _owner: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        let mut head = self
            .head
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if self.fail.load(Ordering::SeqCst) || *head != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *head = *next;
        Ok(())
    }
}
fn head() -> FinalUseRevocations {
    FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    }
}
fn frontier() -> Result<Arc<Frontier>, FinalUseError> {
    Ok(Arc::new(Frontier {
        head: Mutex::new(FinalUseFrontier::for_initial_head(&head())?),
        fail: AtomicBool::new(false),
    }))
}
fn key() -> SigningKey<MlDsa65> {
    SigningKey::from_seed(&[41; 32].into())
}
fn trust(key: &SigningKey<MlDsa65>) -> Vec<FinalUseMlDsa65IssuerTrustKeyV2> {
    vec![FinalUseMlDsa65IssuerTrustKeyV2 {
        key_id: "issuer-pq".into(),
        verifying_key: key.verifying_key().encode().to_vec(),
        not_before_authority_epoch: 9,
        not_after_authority_epoch: 9,
    }]
}
fn grant(nonce: u8) -> FinalUseGrant {
    FinalUseGrant {
        schema_version: 2,
        signer_id: "owner".into(),
        authority_epoch: 9,
        grant_id: format!("grant-{nonce}"),
        nonce: [nonce; 32],
        binding: FinalUseBinding {
            subject_id: "agent".into(),
            destination_id: "runtime.codex.turn_start".into(),
            request_sha256: [1; 32],
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        not_before_unix_ms: 4_000,
        expires_at_unix_ms: 6_000,
    }
}
fn sign(
    key: &SigningKey<MlDsa65>,
    grant: FinalUseGrant,
    context: &[u8],
) -> Result<SignedFinalUseGrant, FinalUseError> {
    let signature = key
        .expanded_key()
        .sign_deterministic(&grant.ml_dsa65_v2_signing_bytes("issuer-pq")?, context)
        .map_err(|_| FinalUseError::InvalidSignature)?;
    Ok(SignedFinalUseGrant {
        grant,
        signature: encode_ml_dsa65_final_use_signature_v2("issuer-pq", &signature.encode())?,
    })
}
fn open(
    path: &std::path::Path,
    key: &SigningKey<MlDsa65>,
    frontier: Arc<Frontier>,
) -> Result<FinalUseAuthority, FinalUseError> {
    FinalUseAuthority::open_state_dir_with_ml_dsa65_v2(
        path,
        "owner".into(),
        trust(key),
        head(),
        Arc::new(Clock),
        frontier,
    )
}

#[test]
fn real_pq_claim_reopen_and_final_entry_share_the_original_nonce_and_revocation_owner() {
    let root = tempfile::tempdir().unwrap();
    let key = key();
    let frontier = frontier().unwrap();
    let path = root.path().join("owner");
    let authority = open(&path, &key, frontier.clone()).unwrap();
    let signed = sign(&key, grant(7), FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap();
    let token = authority.claim(&signed, &signed.grant.binding).unwrap();
    assert!(matches!(
        authority.claim(&signed, &signed.grant.binding),
        Err(FinalUseError::AlreadyClaimed)
    ));
    let entered = token.enter(&signed.grant.binding).unwrap();
    assert!(entered.matches(&signed.grant.binding));
    drop(entered);
    drop(authority);
    let authority = open(&path, &key, frontier.clone()).unwrap();
    assert_eq!(
        authority.check_unclaimed_grant(&signed, &signed.grant.binding),
        Err(FinalUseError::AlreadyClaimed)
    );
    let next = sign(&key, grant(8), FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap();
    let token = authority.claim(&next, &next.grant.binding).unwrap();
    let mut revoked = head();
    revoked.revision += 1;
    revoked
        .revoked_grant_ids
        .insert(next.grant.grant_id.clone());
    authority.update_revocations(revoked.clone()).unwrap();
    assert!(matches!(
        token.enter(&next.grant.binding),
        Err(FinalUseError::Revoked)
    ));
    drop(authority);
    let authority = FinalUseAuthority::open_state_dir_with_ml_dsa65_v2(
        &path,
        "owner".into(),
        trust(&key),
        revoked,
        Arc::new(Clock),
        frontier,
    )
    .unwrap();
    assert!(matches!(
        authority.claim(&next, &next.grant.binding),
        Err(FinalUseError::Revoked)
    ));
    assert_eq!(authority.capacity().unwrap().used_nonces, 2);
}

#[test]
fn pq_owner_rejects_classical_cross_domain_and_malformed_carriers_without_consuming_nonce() {
    use ed25519_dalek::Signer;
    let root = tempfile::tempdir().unwrap();
    let key = key();
    let authority = open(&root.path().join("owner"), &key, frontier().unwrap()).unwrap();
    let signed = sign(&key, grant(7), FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap();
    let mut negatives = vec![sign(&key, grant(7), &[]).unwrap()];
    for index in [0, 4, 5, 6, 8, signed.signature.len() - 1] {
        let mut changed = signed.clone();
        changed.signature[index] ^= 1;
        negatives.push(changed);
    }
    for schema in [1, 3] {
        let mut changed = signed.clone();
        changed.grant.schema_version = schema;
        negatives.push(changed);
    }
    let mut classical = signed.clone();
    classical.grant.schema_version = 1;
    classical.signature = ed25519_dalek::SigningKey::from_bytes(&[31; 32])
        .sign(&classical.grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    negatives.push(classical);
    let mut trailing = signed.clone();
    trailing.signature.push(0);
    negatives.push(trailing);
    let mut altered_binding = signed.clone();
    altered_binding.grant.binding.payload_sha256[0] ^= 1;
    negatives.push(altered_binding);
    let other_key = SigningKey::from_seed(&[42; 32].into());
    negatives.push(sign(&other_key, grant(7), FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap());
    for candidate in negatives {
        assert!(
            authority
                .claim(&candidate, &candidate.grant.binding)
                .is_err()
        );
    }
    assert_eq!(authority.capacity().unwrap().used_nonces, 0);
    assert_eq!(
        authority.check_unclaimed_grant(&signed, &signed.grant.binding),
        Ok(())
    );
}

#[test]
fn original_signing_api_and_pq_epoch_time_key_id_and_frame_bounds_are_closed() {
    let root = tempfile::tempdir().unwrap();
    let key = key();
    let authority = open(&root.path().join("owner"), &key, frontier().unwrap()).unwrap();
    assert_eq!(grant(7).signing_bytes(), Err(FinalUseError::InvalidGrant));
    let mut candidates = Vec::new();
    let mut retired = grant(7);
    retired.authority_epoch = 8;
    candidates.push(sign(&key, retired, FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap());
    let mut expired = grant(7);
    expired.expires_at_unix_ms = 5_000;
    candidates.push(sign(&key, expired, FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap());
    let mut future = grant(7);
    future.not_before_unix_ms = 5_001;
    candidates.push(sign(&key, future, FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap());
    let mut alias = sign(&key, grant(7), FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap();
    let raw = key
        .expanded_key()
        .sign_deterministic(
            &alias.grant.ml_dsa65_v2_signing_bytes("issuer-pq").unwrap(),
            FINAL_USE_ML_DSA65_V2_CONTEXT,
        )
        .unwrap();
    alias.signature =
        encode_ml_dsa65_final_use_signature_v2("issuer-other", &raw.encode()).unwrap();
    candidates.push(alias);
    for candidate in candidates {
        assert!(
            authority
                .claim(&candidate, &candidate.grant.binding)
                .is_err()
        );
    }
    for length in [0, 3_308, 3_310, 65_536] {
        assert!(encode_ml_dsa65_final_use_signature_v2("issuer-pq", &vec![0; length]).is_err());
    }
    assert!(encode_ml_dsa65_final_use_signature_v2(&"a".repeat(129), &[0; 3_309]).is_err());
    assert_eq!(authority.capacity().unwrap().used_nonces, 0);
}

#[test]
fn classical_owner_directory_cannot_be_relabelled_or_reset_by_pq_configuration() {
    use ed25519_dalek::Signer;
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("owner");
    let classical = ed25519_dalek::SigningKey::from_bytes(&[31; 32]);
    let old = FinalUseAuthority::open_state_dir_with_clock(
        &path,
        "owner".into(),
        classical.verifying_key().to_bytes(),
        head(),
        Arc::new(Clock),
    )
    .unwrap();
    let pq = sign(&key(), grant(/*nonce*/ 7), FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap();
    assert!(matches!(
        old.claim(&pq, &pq.grant.binding),
        Err(FinalUseError::InvalidGrant)
    ));
    let mut old_grant = grant(7);
    old_grant.schema_version = 1;
    let signed = SignedFinalUseGrant {
        signature: classical
            .sign(&old_grant.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        grant: old_grant,
    };
    drop(old.claim(&signed, &signed.grant.binding).unwrap());
    drop(old);
    let state = std::fs::read(path.join("authority.json")).unwrap();
    let claims = std::fs::read(path.join("authority.claims")).unwrap();
    assert!(matches!(
        open(&path, &key(), frontier().unwrap()),
        Err(FinalUseError::InvalidTrust)
    ));
    assert_eq!(
        (
            std::fs::read(path.join("authority.json")).unwrap(),
            std::fs::read(path.join("authority.claims")).unwrap()
        ),
        (state, claims)
    );
}

#[test]
fn mixed_pq_and_classical_keyring_is_rejected_as_a_whole_before_owner_creation() {
    let root = tempfile::tempdir().unwrap();
    let pq = trust(&key()).remove(0);
    let mut classical = pq.clone();
    classical.key_id = "classical-unsupported".into();
    classical.verifying_key = ed25519_dalek::SigningKey::from_bytes(&[31; 32])
        .verifying_key()
        .to_bytes()
        .to_vec();
    for (index, keys) in [vec![pq.clone(), classical.clone()], vec![classical, pq]]
        .into_iter()
        .enumerate()
    {
        let path = root.path().join(format!("rejected-{index}"));
        assert!(matches!(
            FinalUseAuthority::open_state_dir_with_ml_dsa65_v2(
                &path,
                "owner".into(),
                keys,
                head(),
                Arc::new(Clock),
                frontier().unwrap(),
            ),
            Err(FinalUseError::InvalidTrust)
        ));
        assert!(!path.exists());
    }
}

#[test]
fn pq_local_rollback_and_external_cas_failure_do_not_issue_use_tokens() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("owner");
    let key = key();
    let frontier = frontier().unwrap();
    let authority = open(&path, &key, frontier.clone()).unwrap();
    let state = std::fs::read(path.join("authority.json")).unwrap();
    let claims = std::fs::read(path.join("authority.claims")).unwrap();
    let signed = sign(&key, grant(7), FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap();
    drop(authority.claim(&signed, &signed.grant.binding).unwrap());
    drop(authority);
    std::fs::write(path.join("authority.json"), state).unwrap();
    std::fs::write(path.join("authority.claims"), claims).unwrap();
    assert!(matches!(
        open(&path, &key, frontier),
        Err(FinalUseError::AntiRollbackViolation)
    ));

    let frontier = self::frontier().unwrap();
    let authority = open(&root.path().join("cas-owner"), &key, frontier.clone()).unwrap();
    frontier.fail.store(true, Ordering::SeqCst);
    assert!(matches!(
        authority.claim(&signed, &signed.grant.binding),
        Err(FinalUseError::AntiRollbackViolation)
    ));
    assert_eq!(
        authority.check_unclaimed_grant(&signed, &signed.grant.binding),
        Err(FinalUseError::Unavailable)
    );
}

#[test]
fn pre_pinned_pq_generation_changes_only_through_the_original_epoch_transition() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("owner");
    let first = key();
    let next = SigningKey::<MlDsa65>::from_seed(&[42; 32].into());
    let mut keys = trust(&first);
    keys.push(FinalUseMlDsa65IssuerTrustKeyV2 {
        key_id: "issuer-next".into(),
        verifying_key: next.verifying_key().encode().to_vec(),
        not_before_authority_epoch: 10,
        not_after_authority_epoch: 10,
    });
    let frontier = frontier().unwrap();
    let authority = FinalUseAuthority::open_state_dir_with_ml_dsa65_v2(
        &path,
        "owner".into(),
        keys.clone(),
        head(),
        Arc::new(Clock),
        frontier.clone(),
    )
    .unwrap();
    let prior = sign(&first, grant(/*nonce*/ 7), FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap();
    drop(authority.claim(&prior, &prior.grant.binding).unwrap());
    let sign_next = |grant: FinalUseGrant| {
        let raw = next
            .expanded_key()
            .sign_deterministic(
                &grant.ml_dsa65_v2_signing_bytes("issuer-next").unwrap(),
                FINAL_USE_ML_DSA65_V2_CONTEXT,
            )
            .unwrap();
        SignedFinalUseGrant {
            grant,
            signature: encode_ml_dsa65_final_use_signature_v2("issuer-next", &raw.encode())
                .unwrap(),
        }
    };
    let premature = sign_next(grant(/*nonce*/ 8));
    assert!(matches!(
        authority.claim(&premature, &premature.grant.binding),
        Err(FinalUseError::InvalidSignature)
    ));
    let mut next_grant = grant(/*nonce*/ 7);
    next_grant.authority_epoch = 10;
    let signed = sign_next(next_grant);
    assert_eq!(
        authority.check_unclaimed_grant(&signed, &signed.grant.binding),
        Err(FinalUseError::EpochMismatch)
    );
    let mut advanced = head();
    advanced.authority_epoch = 10;
    advanced.revision = 2;
    authority.update_revocations(advanced.clone()).unwrap();
    let mut expired_window = grant(/*nonce*/ 8);
    expired_window.authority_epoch = 10;
    let expired_window = sign(&first, expired_window, FINAL_USE_ML_DSA65_V2_CONTEXT).unwrap();
    assert!(matches!(
        authority.claim(&expired_window, &expired_window.grant.binding),
        Err(FinalUseError::InvalidSignature)
    ));
    assert_eq!(
        authority.check_unclaimed_grant(&prior, &prior.grant.binding),
        Err(FinalUseError::EpochMismatch)
    );
    drop(authority);
    let authority = FinalUseAuthority::open_state_dir_with_ml_dsa65_v2(
        &path,
        "owner".into(),
        keys,
        advanced,
        Arc::new(Clock),
        frontier,
    )
    .unwrap();
    drop(
        authority
            .claim(&signed, &signed.grant.binding)
            .unwrap()
            .enter(&signed.grant.binding)
            .unwrap(),
    );
    assert_eq!(authority.capacity().unwrap().used_nonces, 1);
}

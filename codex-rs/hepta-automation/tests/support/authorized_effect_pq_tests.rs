//! PQ grants traverse the original durable automation dispatcher.
//! The retained CAS frontier and clock below are test trust fixtures, not an
//! independently deployed service or proof of whole-machine rollback safety.

use super::*;
use codex_hepta_automation::TaskFlowStepReceipt;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use pretty_assertions::assert_eq;
use std::sync::Arc;

const SIGNER_ID: &str = "security-owner";
const COMMAND_ID: &str = "pq-authorized-effect-dispatch";

struct FixedClock;

impl AuthorityClock for FixedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(2_000)
    }
}

struct RetainedFrontier(Mutex<FinalUseFrontier>);

impl AuthorityFrontierStore<FinalUseFrontier> for RetainedFrontier {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        if owner_id != SIGNER_ID {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(*self.0.lock().expect("frontier lock"))
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if owner_id != SIGNER_ID {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut current = self.0.lock().expect("frontier lock");
        if &*current != expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *current = *next;
        Ok(())
    }
}

struct PqAuthorityFixture {
    directory: tempfile::TempDir,
    key: PqNativeSigningKey,
    trust: PqAuthorityTrustKey,
    frontier: Arc<RetainedFrontier>,
}

impl PqAuthorityFixture {
    fn new(binding: FinalUseBinding) -> (Self, FinalUseAuthority, SignedFinalUseGrant) {
        let seed = [17; 32].into();
        let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
        let public_key_id = ml_dsa_65_key_id_from_spki(&spki).expect("PQ key ID");
        let key = PqNativeSigningKey::from_owned_seed(seed, public_key_id).expect("PQ issuer");
        let directory = tempfile::tempdir().expect("authority state dir");
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
            .expect("private authority dir");
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let fixture = Self {
            directory,
            key,
            trust: PqAuthorityTrustKey {
                key_id: "pq-issuer-key".into(),
                public_key_id,
                public_key_spki: spki.to_vec(),
                not_before_authority_epoch: 9,
                not_after_authority_epoch: 10,
            },
            frontier: Arc::new(RetainedFrontier(Mutex::new(
                FinalUseFrontier::for_initial_head_with_profile(
                    &head,
                    FinalUseAuthenticationProfile::MlDsa65V2,
                )
                .expect("initial PQ frontier"),
            ))),
        };
        let authority = fixture.open(head).expect("PQ authority");
        let signed = fixture.sign(FinalUseGrant {
            schema_version: 2,
            signer_id: SIGNER_ID.into(),
            authority_epoch: 9,
            grant_id: "pq-effect-grant".into(),
            nonce: [3; 32],
            binding,
            not_before_unix_ms: 1_000,
            expires_at_unix_ms: 3_000,
        });
        (fixture, authority, signed)
    }

    fn open(&self, head: FinalUseRevocations) -> Result<FinalUseAuthority, FinalUseError> {
        FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
            self.directory.path(),
            SIGNER_ID.into(),
            vec![self.trust.clone()],
            head,
            Arc::new(FixedClock),
            self.frontier.clone(),
        )
    }

    fn sign(&self, grant: FinalUseGrant) -> SignedFinalUseGrant {
        SignedFinalUseGrant {
            signature: self
                .key
                .sign_exact_message(&grant.signing_bytes().expect("grant signing bytes"))
                .expect("PQ signature")
                .to_vec(),
            grant,
        }
    }
}

struct DispatchCase {
    fixture: Fixture,
    store: AutomationStore,
    owner: TaskFlowFence,
    effect: AuthorizedEffectIntent,
    expected: FinalUseBinding,
}

impl DispatchCase {
    async fn new() -> Self {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        Self {
            fixture,
            store,
            owner,
            effect,
            expected,
        }
    }

    async fn dispatch(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        driver: &mut RecordingDriver,
    ) -> Result<TaskFlowStepReceipt, AuthorizedEffectError> {
        self.store
            .execute_authorized_taskflow_effect(
                authority,
                driver,
                AuthorizedEffectExecutionInput {
                    intent: &self.effect,
                    wire_payload: EFFECT_PAYLOAD,
                    fence: &self.owner,
                    signed_grant: signed,
                    expected_binding: &self.expected,
                    command_id: COMMAND_ID,
                    now_ms: 30,
                },
            )
            .await
    }

    async fn assert_no_attempt(&self) {
        assert!(
            self.store
                .authorized_taskflow_effect_attempt(
                    &self.effect.run_id,
                    &self.effect.step_id,
                    self.effect.attempt,
                )
                .await
                .expect("attempt read")
                .is_none()
        );
    }

    async fn reopen(&mut self) {
        self.store.close().await;
        self.store = AutomationStore::open(&self.fixture.layout)
            .await
            .expect("reopen automation store");
    }
}

#[tokio::test]
async fn pq_effect_dispatch_and_spent_nonce_survive_owner_and_outbox_reopen() {
    let mut case = DispatchCase::new().await;
    let (trust, authority, signed) = PqAuthorityFixture::new(case.expected.clone());
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"pq-success");
    let receipt = case
        .dispatch(&authority, &signed, &mut driver)
        .await
        .expect("PQ dispatch");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Succeeded)
    );
    assert_eq!(driver.calls, 1);
    let head = authority.revocation_head().expect("current head");
    let frontier = authority.frontier().expect("spent frontier");
    drop(authority);
    case.reopen().await;
    let reopened = trust.open(head).expect("reopen PQ owner");
    assert_eq!(reopened.frontier().expect("reopened frontier"), frontier);
    assert_eq!(
        reopened
            .claim(&signed, &case.expected)
            .expect_err("spent nonce"),
        FinalUseError::AlreadyClaimed
    );
    assert_eq!(
        case.store
            .read_authorized_taskflow_effect_receipt(&case.effect, COMMAND_ID)
            .await
            .expect("durable receipt"),
        Some(receipt)
    );
    let mut replay = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-run");
    assert!(
        case.dispatch(&reopened, &signed, &mut replay)
            .await
            .is_err()
    );
    assert_eq!(replay.calls, 0);
}

#[tokio::test]
async fn pq_effect_rejects_classical_wire_and_signature_before_consumption() {
    let case = DispatchCase::new().await;
    let (_trust, authority, signed) = PqAuthorityFixture::new(case.expected.clone());
    let initial = authority.frontier().expect("initial frontier");
    let issuer = SigningKey::from_bytes(&[47; 32]);
    let mut classic = signed.clone();
    classic.grant.schema_version = 1;
    classic.signature = issuer
        .sign(&classic.grant.signing_bytes().expect("classic input"))
        .to_bytes()
        .to_vec();
    let mut mislabeled = signed.clone();
    mislabeled.signature = issuer
        .sign(&mislabeled.grant.signing_bytes().expect("PQ input"))
        .to_bytes()
        .to_vec();
    let mut driver =
        RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"pq-after-refusal");
    for (rejected, expected_error) in [
        (classic, FinalUseError::InvalidGrant),
        (mislabeled, FinalUseError::InvalidSignature),
    ] {
        assert!(matches!(
            case.dispatch(&authority, &rejected, &mut driver).await,
            Err(AuthorizedEffectError::FinalUse(error)) if error == expected_error
        ));
        assert_eq!(driver.calls, 0);
        assert_eq!(authority.frontier().expect("unchanged frontier"), initial);
        case.assert_no_attempt().await;
    }
    case.dispatch(&authority, &signed, &mut driver)
        .await
        .expect("same PQ grant remains usable");
    assert_eq!(driver.calls, 1);
}

#[tokio::test]
async fn pq_effect_refuses_spent_revoked_and_previous_epoch_grants() {
    let case = DispatchCase::new().await;
    let (trust, authority, signed) = PqAuthorityFixture::new(case.expected.clone());
    drop(
        authority
            .claim(&signed, &case.expected)
            .expect("consume without provider contact"),
    );
    let spent = authority.frontier().expect("spent frontier");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"pq-current");
    assert!(matches!(
        case.dispatch(&authority, &signed, &mut driver).await,
        Err(AuthorizedEffectError::FinalUse(
            FinalUseError::AlreadyClaimed
        ))
    ));
    assert_eq!(authority.frontier().expect("same spent frontier"), spent);
    let mut next = signed.grant.clone();
    next.grant_id = "pq-revoked-effect".into();
    next.nonce = [4; 32];
    let revoked = trust.sign(next.clone());
    let mut head = authority.revocation_head().expect("head");
    head.revision += 1;
    head.revoked_grant_ids.insert(next.grant_id.clone());
    authority
        .update_revocations(head.clone())
        .expect("revoke grant");
    let revoked_frontier = authority.frontier().expect("revoked frontier");
    assert!(matches!(
        case.dispatch(&authority, &revoked, &mut driver).await,
        Err(AuthorizedEffectError::FinalUse(FinalUseError::Revoked))
    ));
    assert_eq!(
        authority.frontier().expect("same revoked frontier"),
        revoked_frontier
    );
    next.grant_id = "pq-current-effect".into();
    next.nonce = [5; 32];
    let old_epoch = trust.sign(next.clone());
    head.authority_epoch = 10;
    head.revision += 1;
    authority
        .update_revocations(head)
        .expect("advance current epoch");
    let current_frontier = authority.frontier().expect("current frontier");
    assert!(matches!(
        case.dispatch(&authority, &old_epoch, &mut driver).await,
        Err(AuthorizedEffectError::FinalUse(
            FinalUseError::EpochMismatch
        ))
    ));
    assert_eq!(
        authority.frontier().expect("same current frontier"),
        current_frontier
    );
    assert_eq!(driver.calls, 0);
    case.assert_no_attempt().await;
    next.authority_epoch = 10;
    case.dispatch(&authority, &trust.sign(next), &mut driver)
        .await
        .expect("current PQ grant");
    assert_eq!(driver.calls, 1);
    assert_eq!(
        authority
            .capacity()
            .expect("current epoch capacity")
            .used_nonces,
        1
    );
}

#[tokio::test]
async fn pq_effect_external_owner_progress_refuses_stale_dispatch() {
    let case = DispatchCase::new().await;
    let (trust, stale, signed) = PqAuthorityFixture::new(case.expected.clone());
    let current_directory = tempfile::tempdir().expect("second durable owner");
    std::fs::set_permissions(
        current_directory.path(),
        std::fs::Permissions::from_mode(0o700),
    )
    .expect("private second owner");
    for name in ["authority.json", "authority.claims"] {
        std::fs::copy(
            trust.directory.path().join(name),
            current_directory.path().join(name),
        )
        .expect("same initial durable state");
    }
    let mut head = stale.revocation_head().expect("initial head");
    let current = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
        current_directory.path(),
        SIGNER_ID.into(),
        vec![trust.trust.clone()],
        head.clone(),
        Arc::new(FixedClock),
        trust.frontier.clone(),
    )
    .expect("second owner with retained shared frontier");
    head.revision += 1;
    head.revoked_grant_ids.insert(signed.grant.grant_id.clone());
    current
        .update_revocations(head)
        .expect("current owner revocation");
    let frontier = current.frontier().expect("advanced frontier");
    let claims_before =
        std::fs::read(trust.directory.path().join("authority.claims")).expect("claims");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-run");
    assert!(matches!(
        case.dispatch(&stale, &signed, &mut driver).await,
        Err(AuthorizedEffectError::FinalUse(
            FinalUseError::AntiRollbackViolation
        ))
    ));
    assert_eq!(driver.calls, 0);
    case.assert_no_attempt().await;
    assert_eq!(stale.capacity(), Err(FinalUseError::Unavailable));
    assert_eq!(
        trust.frontier.load(SIGNER_ID).expect("retained frontier"),
        frontier
    );
    assert_eq!(
        std::fs::read(trust.directory.path().join("authority.claims")).expect("unchanged claims"),
        claims_before
    );
}

#[tokio::test]
async fn pq_effect_old_image_refuses_reopen_then_current_image_preserves_consumption() {
    let mut case = DispatchCase::new().await;
    let (trust, authority, signed) = PqAuthorityFixture::new(case.expected.clone());
    let state_path = trust.directory.path().join("authority.json");
    let claims_path = trust.directory.path().join("authority.claims");
    let old_state = std::fs::read(&state_path).expect("initial state");
    let old_claims = std::fs::read(&claims_path).expect("initial claims");
    let initial_head = authority.revocation_head().expect("initial head");
    drop(
        authority
            .claim(&signed, &case.expected)
            .expect("consume before crash"),
    );
    let mut head = initial_head.clone();
    head.revision += 1;
    authority
        .update_revocations(head.clone())
        .expect("current revocation head");
    let current_state = std::fs::read(&state_path).expect("current state");
    let current_claims = std::fs::read(&claims_path).expect("current claims");
    let frontier = authority.frontier().expect("current frontier");
    drop(authority);
    case.reopen().await;
    std::fs::write(&state_path, old_state).expect("restore old local state");
    std::fs::write(&claims_path, old_claims).expect("restore old local claims");
    assert_eq!(
        trust
            .open(initial_head)
            .expect_err("old image must not resurrect authority"),
        FinalUseError::AntiRollbackViolation
    );
    assert_eq!(
        trust.frontier.load(SIGNER_ID).expect("retained frontier"),
        frontier
    );
    std::fs::write(&state_path, current_state).expect("restore actual current state");
    std::fs::write(&claims_path, current_claims).expect("restore actual current claims");
    let recovered = trust.open(head).expect("current image recovery");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"pq-recovered");
    assert!(matches!(
        case.dispatch(&recovered, &signed, &mut driver).await,
        Err(AuthorizedEffectError::FinalUse(
            FinalUseError::AlreadyClaimed
        ))
    ));
    assert_eq!(driver.calls, 0);
    case.assert_no_attempt().await;
    let mut next = signed.grant.clone();
    next.grant_id = "pq-after-recovery".into();
    next.nonce = [4; 32];
    case.dispatch(&recovered, &trust.sign(next), &mut driver)
        .await
        .expect("fresh recovered grant");
    assert_eq!(driver.calls, 1);
    assert_eq!(
        recovered
            .capacity()
            .expect("recovered capacity")
            .used_nonces,
        2
    );
}

#[tokio::test]
async fn pq_effect_unknown_outcome_reopens_for_reconciliation_without_redispatch() {
    let mut case = DispatchCase::new().await;
    let (trust, authority, signed) = PqAuthorityFixture::new(case.expected.clone());
    let mut first = RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"pq-unknown");
    let receipt = case
        .dispatch(&authority, &signed, &mut first)
        .await
        .expect("unknown outcome");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(first.calls, 1);
    let head = authority.revocation_head().expect("head");
    drop(authority);
    case.reopen().await;
    let reopened = trust.open(head).expect("reopen PQ owner");
    let mut replay = RecordingDriver::receipt(AuthorizedEffectOutcome::Succeeded, b"must-not-run");
    assert!(
        case.dispatch(&reopened, &signed, &mut replay)
            .await
            .is_err()
    );
    assert_eq!(replay.calls, 0);
    assert_eq!(reopened.capacity().expect("still consumed").used_nonces, 1);
    let observed = case
        .store
        .recover_authorized_taskflow_effect(
            &case.effect.run_id,
            &case.effect.step_id,
            case.effect.attempt,
            &case.owner,
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(b"pq-provider-terminal"),
                provider_ack: None,
            }),
            32,
        )
        .await
        .expect("reconcile retained provider observation");
    let AuthorizedEffectRecoveryResult::Observed(terminal) = observed else {
        panic!("provider observation must settle the original occurrence");
    };
    assert_eq!(
        terminal.final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded)
    );
    assert_eq!(
        case.store
            .read_authorized_taskflow_effect_receipt(&case.effect, COMMAND_ID)
            .await
            .expect("read reconciled receipt"),
        Some(*terminal)
    );
    assert_eq!(replay.calls, 0);
}

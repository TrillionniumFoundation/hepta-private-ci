use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

#[derive(Debug)]
struct FixtureAuthenticator {
    principal: TrustedUiPrincipal,
}

impl UiControlSessionAuthenticator for FixtureAuthenticator {
    fn authenticate(
        &self,
        session_id: &StableId,
        connection_generation: Generation,
    ) -> Result<TrustedUiPrincipal, UiControlGatewayError> {
        if self.principal.session_id != *session_id
            || self.principal.connection_generation != connection_generation
        {
            return Err(UiControlGatewayError::Unauthenticated);
        }
        Ok(self.principal.clone())
    }
}

#[derive(Debug)]
struct FixtureViewVerifier {
    generation: Generation,
    revision: Revision,
    digest: Digest32,
}

impl UiControlRuntimeViewVerifier for FixtureViewVerifier {
    fn verify_current_view(
        &self,
        _principal: &TrustedUiPrincipal,
        runtime_generation: Generation,
        displayed_revision: Revision,
        runtime_digest: Digest32,
    ) -> Result<(), UiControlGatewayError> {
        if runtime_generation != self.generation
            || displayed_revision != self.revision
            || runtime_digest != self.digest
        {
            return Err(UiControlGatewayError::StaleView);
        }
        Ok(())
    }
}

struct FixtureGrantProvider {
    signer: SigningKey,
    sequence: AtomicU64,
}

impl fmt::Debug for FixtureGrantProvider {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("FixtureGrantProvider([TEST KEY])")
    }
}

impl UiControlFinalUseGrantProvider for FixtureGrantProvider {
    fn grant_for(
        &self,
        _principal: &TrustedUiPrincipal,
        binding: &FinalUseBinding,
    ) -> Result<SignedFinalUseGrant, UiControlGatewayError> {
        let sequence = self.sequence.fetch_add(1, Ordering::SeqCst) + 1;
        let now = now_unix_ms()?;
        let mut nonce = [0_u8; 32];
        nonce[..8].copy_from_slice(&sequence.to_be_bytes());
        nonce[8..].fill(0x5a);
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "ui-security-owner".to_string(),
            authority_epoch: 9,
            grant_id: format!("ui-grant-{sequence}"),
            nonce,
            binding: binding.clone(),
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now + 30_000,
        };
        let signature = self
            .signer
            .sign(
                &grant
                    .signing_bytes()
                    .map_err(|_| UiControlGatewayError::AuthorityRejected)?,
            )
            .to_bytes()
            .to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }
}

#[derive(Debug)]
struct FixtureOwner {
    revision: Revision,
    dispatches: AtomicUsize,
    terminal: Mutex<Option<OwnerTerminalObservation>>,
}

impl FixtureOwner {
    fn set_terminal(&self, observation: OwnerTerminalObservation) {
        *self.terminal.lock().expect("terminal lock") = Some(observation);
    }
}

impl UiControlOwnerAdapter for FixtureOwner {
    fn destination_id(
        &self,
        target_id: &StableId,
        _action: UiControlAction,
    ) -> Result<StableId, UiControlGatewayError> {
        if target_id.as_str() != "runtime.agentd" {
            return Err(UiControlGatewayError::OwnerUnavailable);
        }
        StableId::new("runtime.agentd.ui-control")
            .map_err(|_| UiControlGatewayError::OwnerUnavailable)
    }

    fn current_revision(
        &self,
        target_id: &StableId,
    ) -> Result<Revision, UiControlGatewayError> {
        if target_id.as_str() != "runtime.agentd" {
            return Err(UiControlGatewayError::OwnerUnavailable);
        }
        Ok(self.revision)
    }

    fn preflight(
        &self,
        _principal: &TrustedUiPrincipal,
        dispatch: &OwnerDispatch,
    ) -> Result<(), UiControlGatewayError> {
        if dispatch.target_id.as_str() != "runtime.agentd"
            || dispatch.expected_revision != Some(self.revision)
        {
            return Err(UiControlGatewayError::StaleTargetRevision);
        }
        Ok(())
    }

    fn dispatch(
        &self,
        dispatch: &OwnerDispatch,
    ) -> Result<OwnerDispatchReceipt, OwnerDispatchFailure> {
        self.dispatches.fetch_add(1, Ordering::SeqCst);
        Ok(OwnerDispatchReceipt {
            dispatch_digest: dispatch.dispatch_digest,
        })
    }

    fn observe_terminal(
        &self,
        _operation_id: &StableId,
        _target_id: &StableId,
    ) -> Result<Option<OwnerTerminalObservation>, UiControlGatewayError> {
        Ok(*self.terminal.lock().expect("terminal lock"))
    }
}

struct Fixture {
    directory: tempfile::TempDir,
    ledger: DurableOperationLedger,
    authority: FinalUseAuthority,
    authenticator: Arc<FixtureAuthenticator>,
    view_verifier: Arc<FixtureViewVerifier>,
    grant_provider: Arc<FixtureGrantProvider>,
    owner: Arc<FixtureOwner>,
    runtime_digest: Digest32,
    owner_generation: Generation,
}

async fn fixture(roles: BTreeSet<UiControlRole>) -> Fixture {
    let directory = tempfile::tempdir().expect("tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("secure fixture directory");

    let signer = SigningKey::from_bytes(&[71; 32]);
    let authority_dir = directory.path().join("authority");
    std::fs::create_dir(&authority_dir).expect("authority dir");
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))
        .expect("secure authority dir");
    let authority = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "ui-security-owner".to_string(),
        signer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");

    let ledger = DurableOperationLedger::open(&directory.path().join("operations.sqlite3"))
        .await
        .expect("ledger");
    let runtime_digest = Digest32::of_bytes(b"runtime-view");
    let principal = TrustedUiPrincipal {
        principal_id: StableId::new("operator.one").expect("principal"),
        session_id: StableId::new("session.1").expect("session"),
        connection_generation: Generation::new(1).expect("connection generation"),
        authentication_context_digest: Digest32::of_bytes(b"authenticated-cookie-session"),
        roles,
    };

    Fixture {
        directory,
        ledger,
        authority,
        authenticator: Arc::new(FixtureAuthenticator { principal }),
        view_verifier: Arc::new(FixtureViewVerifier {
            generation: Generation::new(7).expect("runtime generation"),
            revision: Revision::new(9).expect("view revision"),
            digest: runtime_digest,
        }),
        grant_provider: Arc::new(FixtureGrantProvider {
            signer,
            sequence: AtomicU64::new(0),
        }),
        owner: Arc::new(FixtureOwner {
            revision: Revision::new(44).expect("target revision"),
            dispatches: AtomicUsize::new(0),
            terminal: Mutex::new(None),
        }),
        runtime_digest,
        owner_generation: Generation::new(5).expect("owner generation"),
    }
}

fn gateway(fixture: &Fixture, ledger: DurableOperationLedger) -> UiControlGateway {
    UiControlGateway::new(
        ledger,
        fixture.authority.clone(),
        fixture.authenticator.clone(),
        fixture.view_verifier.clone(),
        fixture.grant_provider.clone(),
        fixture.owner.clone(),
        fixture.owner_generation,
    )
}

fn operation_request(
    runtime_digest: Digest32,
    action: &str,
) -> UiControlTransportRequestV1 {
    let intent = UiOperationProposalV1 {
        kind: "UiOperationProposalV1".to_string(),
        operation_id: "operation.ui.1".to_string(),
        subject_id: "runtime.agentd".to_string(),
        action: action.to_string(),
        expected_revision: 44,
        authority_granted: false,
        direct_store_write: false,
    };
    let payload = serde_json::to_value(intent.clone()).expect("intent value");
    let session_id = StableId::new("session.1").expect("session");
    let operation_id = StableId::new("operation.ui.1").expect("operation");
    let semantic = request_semantics_value(
        "operation/request",
        &session_id,
        Generation::new(1).expect("connection generation"),
        Generation::new(7).expect("runtime generation"),
        Revision::new(9).expect("view revision"),
        runtime_digest,
        &operation_id,
        &payload,
    );
    UiControlTransportRequestV1 {
        schema: TRANSPORT_SCHEMA.to_string(),
        session_id: "session.1".to_string(),
        connection_generation: 1,
        runtime_generation: 7,
        runtime_digest: runtime_digest.to_string(),
        displayed_revision: 9,
        operation_id: "operation.ui.1".to_string(),
        semantic_digest: canonical_digest(&semantic)
            .expect("semantic digest")
            .to_string(),
        intent: Some(intent),
        scope: None,
    }
}

#[tokio::test]
async fn authenticated_request_is_durable_deduplicated_and_terminal_after_reopen() {
    let fixture = fixture(BTreeSet::from([UiControlRole::Operator])).await;
    let request = operation_request(fixture.runtime_digest, "request_retry");
    let semantic_digest: Digest32 = request.semantic_digest.parse().expect("semantic digest");
    let service = gateway(&fixture, fixture.ledger.clone());

    let acknowledgement = service
        .submit_request("operation/request", request.clone())
        .await
        .expect("accepted request");
    assert!(acknowledgement.accepted);
    assert_eq!(fixture.owner.dispatches.load(Ordering::SeqCst), 1);

    let duplicate = service
        .submit_request("operation/request", request)
        .await
        .expect("idempotent duplicate");
    assert!(duplicate.accepted);
    assert_eq!(fixture.owner.dispatches.load(Ordering::SeqCst), 1);

    let record = fixture
        .ledger
        .get(&StableId::new("operation.ui.1").expect("operation"))
        .await
        .expect("query")
        .expect("record");
    assert_eq!(record.operation.key.payload_digest, semantic_digest);
    assert!(matches!(
        record.operation.state,
        OperationState::Dispatched { .. }
    ));
    assert!(!record.operation.state.is_terminal());

    drop(service);
    fixture.ledger.close().await;

    let reopened = DurableOperationLedger::open(
        &fixture.directory.path().join("operations.sqlite3"),
    )
    .await
    .expect("reopen ledger");
    fixture.owner.set_terminal(OwnerTerminalObservation {
        outcome: ReconciliationOutcome::Applied,
        outcome_digest: Digest32::of_bytes(b"owner-terminal-applied"),
        observer_generation: fixture.owner_generation,
    });
    let restarted = gateway(&fixture, reopened);

    let observation = restarted
        .reconcile(UiControlReconcileQueryV1 {
            session_id: "session.1".to_string(),
            connection_generation: 1,
            method: "operation/request".to_string(),
            operation_id: "operation.ui.1".to_string(),
            semantic_digest: semantic_digest.to_string(),
            origin_session_id: "session.1".to_string(),
            origin_connection_generation: 1,
            runtime_generation: 7,
        })
        .await
        .expect("reconcile")
        .expect("observation");
    assert_eq!(observation.status, "succeeded");
    assert!(observation.terminal_observed);
    assert!(observation.outcome_digest.is_some());
}

#[tokio::test]
async fn semantic_drift_and_insufficient_rbac_fail_before_dispatch() {
    let fixture = fixture(BTreeSet::from([UiControlRole::Operator])).await;
    let service = gateway(&fixture, fixture.ledger.clone());

    let mut drifted = operation_request(fixture.runtime_digest, "request_retry");
    drifted.semantic_digest = Digest32::of_bytes(b"attacker-digest").to_string();
    assert_eq!(
        service
            .submit_request("operation/request", drifted)
            .await
            .expect_err("semantic drift"),
        UiControlGatewayError::SemanticDigestMismatch
    );
    assert_eq!(fixture.owner.dispatches.load(Ordering::SeqCst), 0);

    let rollback = operation_request(fixture.runtime_digest, "request_rollback");
    assert_eq!(
        service
            .submit_request("operation/request", rollback)
            .await
            .expect_err("rollback requires runtime admin"),
        UiControlGatewayError::Forbidden
    );
    assert_eq!(fixture.owner.dispatches.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn stale_target_revision_fails_before_final_use_and_owner_dispatch() {
    let fixture = fixture(BTreeSet::from([UiControlRole::Operator])).await;
    let service = gateway(&fixture, fixture.ledger.clone());
    let mut request = operation_request(fixture.runtime_digest, "request_retry");
    let mut intent = request.intent.take().expect("intent");
    intent.expected_revision = 43;
    let payload = serde_json::to_value(intent.clone()).expect("payload");
    let semantic = request_semantics_value(
        "operation/request",
        &StableId::new("session.1").expect("session"),
        Generation::new(1).expect("connection"),
        Generation::new(7).expect("runtime"),
        Revision::new(9).expect("view"),
        fixture.runtime_digest,
        &StableId::new("operation.ui.1").expect("operation"),
        &payload,
    );
    request.semantic_digest = canonical_digest(&semantic)
        .expect("semantic digest")
        .to_string();
    request.intent = Some(intent);

    assert_eq!(
        service
            .submit_request("operation/request", request)
            .await
            .expect_err("stale target"),
        UiControlGatewayError::StaleTargetRevision
    );
    assert_eq!(fixture.owner.dispatches.load(Ordering::SeqCst), 0);
}


#[tokio::test]
async fn reconciliation_cannot_cross_authenticated_principal_identity() {
    let fixture = fixture(BTreeSet::from([UiControlRole::Operator])).await;
    let request = operation_request(fixture.runtime_digest, "request_retry");
    let semantic_digest: Digest32 = request.semantic_digest.parse().expect("semantic digest");
    let service = gateway(&fixture, fixture.ledger.clone());
    service
        .submit_request("operation/request", request)
        .await
        .expect("seed operation");

    let intruder = TrustedUiPrincipal {
        principal_id: StableId::new("operator.two").expect("principal"),
        session_id: StableId::new("session.1").expect("session"),
        connection_generation: Generation::new(1).expect("connection generation"),
        authentication_context_digest: Digest32::of_bytes(b"other-authenticated-session"),
        roles: BTreeSet::from([UiControlRole::Operator]),
    };
    let intruder_service = UiControlGateway::new(
        fixture.ledger.clone(),
        fixture.authority.clone(),
        Arc::new(FixtureAuthenticator { principal: intruder }),
        fixture.view_verifier.clone(),
        fixture.grant_provider.clone(),
        fixture.owner.clone(),
        fixture.owner_generation,
    );

    let error = intruder_service
        .reconcile(UiControlReconcileQueryV1 {
            session_id: "session.1".to_string(),
            connection_generation: 1,
            method: "operation/request".to_string(),
            operation_id: "operation.ui.1".to_string(),
            semantic_digest: semantic_digest.to_string(),
            origin_session_id: "session.1".to_string(),
            origin_connection_generation: 1,
            runtime_generation: 7,
        })
        .await
        .expect_err("another authenticated principal cannot reconcile this operation");
    assert_eq!(error, UiControlGatewayError::ReconciliationMismatch);
}

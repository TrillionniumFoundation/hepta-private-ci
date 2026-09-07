#![cfg(feature = "authbus-local-qualification")]

use std::collections::VecDeque;
use std::fmt::Debug;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::OpaqueSecretRef;
use codex_hepta_contracts::RefreshStatusByOperationKeyRequest;
use codex_hepta_contracts::RefreshWithSecretRefRequest;
use codex_hepta_contracts::RotateSecretRefRequest;
use codex_hepta_contracts::SecretProviderStatus;
use codex_hepta_contracts::SecretRefOutcome;
use codex_hepta_contracts::SecretRefState;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_AUTHORITY;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_EFFECT_AUTHORITY;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_EXECUTE_ALLOWED;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_G5_ALLOWED;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_OPERATOR_ACCEPTANCE;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_PRODUCTION_CALLER;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_PRODUCTION_WRITER;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_PROMOTION;
use codex_hepta_contracts::authbus_b3_adapter::AUTHBUS_B3_ADAPTER_QUALIFICATION_ONLY;
use codex_hepta_contracts::authbus_b3_adapter::B3AdapterError;
use codex_hepta_contracts::authbus_b3_adapter::ProcessBoundSecret;
use codex_hepta_contracts::authbus_b3_adapter::ProcessBoundSecretRefAdapter;
use codex_hepta_contracts::authbus_b3_adapter::ProviderAdapterError;
use codex_hepta_contracts::authbus_b3_adapter::ProviderRefreshResult;
use codex_hepta_contracts::authbus_b3_adapter::ProviderRotationResult;
use codex_hepta_contracts::authbus_b3_adapter::ProviderStatusResult;
use codex_hepta_contracts::authbus_b3_adapter::QualificationSecretBackend;
use codex_hepta_contracts::authbus_b3_adapter::SecretBackendError;
use codex_hepta_contracts::authbus_b3_adapter::SecretRefProvider;
use codex_hepta_contracts::derive_refresh_operation_id;
use codex_hepta_contracts::derive_refresh_operation_key;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn must<T, E: Debug>(result: Result<T, E>, context: &str) -> T {
    result.unwrap_or_else(|error| panic!("{context}: {error:?}"))
}

fn secret_ref(key: &str, bytes: &[u8]) -> OpaqueSecretRef {
    OpaqueSecretRef::new(
        "qualification-backend",
        "oauth",
        key,
        /*version*/ 1,
        Sha256Digest::for_bytes(bytes),
    )
    .unwrap_or_else(|error| panic!("valid opaque reference: {error:?}"))
}

fn refresh_request(
    profile: &str,
    idempotency_key: &str,
    reference: OpaqueSecretRef,
) -> RefreshWithSecretRefRequest {
    let provider_id = "provider-qualification";
    let token_family_id = "family-qualification";
    let payload_digest = digest(&format!("payload:{idempotency_key}"));
    let scope_digest = digest("scope");
    let purpose_digest = digest("purpose");
    let policy_digest = digest("policy");
    let fencing_token = digest("fence");
    let refresh_operation_key = derive_refresh_operation_key(
        provider_id,
        profile,
        token_family_id,
        idempotency_key,
        /*expected_secret_revision*/ 1,
        &scope_digest,
        &purpose_digest,
        &payload_digest,
        &policy_digest,
        /*authority_epoch*/ 2,
        /*owner_epoch*/ 3,
        /*generation*/ 4,
        &fencing_token,
    );
    let operation_id =
        derive_refresh_operation_id(&refresh_operation_key, idempotency_key, &payload_digest);
    RefreshWithSecretRefRequest {
        schema_version: 1,
        operation_id,
        refresh_operation_key,
        command_id: format!("command:{idempotency_key}"),
        run_id: format!("run:{idempotency_key}"),
        profile_id: profile.to_string(),
        provider_id: provider_id.to_string(),
        token_family_id: token_family_id.to_string(),
        secret_ref: reference,
        expected_secret_revision: 1,
        idempotency_key: idempotency_key.to_string(),
        payload_digest,
        policy_digest,
        scope_digest,
        authority_epoch: 2,
        owner_epoch: 3,
        generation: 4,
        fencing_token,
        logical_clock: 5,
        causal_parent_event_id: "parent-event".to_string(),
        deadline_at: 100,
        purpose_digest,
        audience: "hepta.auth.local-mode".to_string(),
    }
}

fn rotate_request(
    profile: &str,
    idempotency_key: &str,
    reference: OpaqueSecretRef,
) -> RotateSecretRefRequest {
    let refresh = refresh_request(profile, idempotency_key, reference);
    RotateSecretRefRequest {
        schema_version: refresh.schema_version,
        operation_id: refresh.operation_id,
        refresh_operation_key: refresh.refresh_operation_key,
        command_id: refresh.command_id,
        run_id: refresh.run_id,
        profile_id: refresh.profile_id,
        provider_id: refresh.provider_id,
        token_family_id: refresh.token_family_id,
        secret_ref: refresh.secret_ref,
        expected_secret_revision: refresh.expected_secret_revision,
        idempotency_key: refresh.idempotency_key,
        payload_digest: refresh.payload_digest,
        policy_digest: refresh.policy_digest,
        scope_digest: refresh.scope_digest,
        authority_epoch: refresh.authority_epoch,
        owner_epoch: refresh.owner_epoch,
        generation: refresh.generation,
        fencing_token: refresh.fencing_token,
        logical_clock: refresh.logical_clock,
        causal_parent_event_id: refresh.causal_parent_event_id,
        deadline_at: refresh.deadline_at,
        purpose_digest: refresh.purpose_digest,
        audience: refresh.audience,
    }
}

fn status_request(request: &RefreshWithSecretRefRequest) -> RefreshStatusByOperationKeyRequest {
    RefreshStatusByOperationKeyRequest {
        schema_version: request.schema_version,
        operation_id: request.operation_id.clone(),
        provider_id: request.provider_id.clone(),
        profile_id: request.profile_id.clone(),
        token_family_id: request.token_family_id.clone(),
        refresh_operation_key: request.refresh_operation_key.clone(),
        idempotency_key: request.idempotency_key.clone(),
        payload_digest: request.payload_digest.clone(),
        expected_secret_revision: request.expected_secret_revision,
        authority_epoch: request.authority_epoch,
        owner_epoch: request.owner_epoch,
        generation: request.generation,
        fencing_token: request.fencing_token.clone(),
        deadline_at: request.deadline_at,
        audience: request.audience.clone(),
        expected_execution_mode: "qualification".to_string(),
        policy_digest: request.policy_digest.clone(),
    }
}

#[derive(Clone, Default)]
struct ScriptedProvider {
    refresh: Arc<Mutex<VecDeque<Result<ProviderRefreshResult, ProviderAdapterError>>>>,
    rotate: Arc<Mutex<VecDeque<Result<ProviderRotationResult, ProviderAdapterError>>>>,
    status: Arc<Mutex<VecDeque<Result<ProviderStatusResult, ProviderAdapterError>>>>,
    refresh_calls: Arc<AtomicUsize>,
    rotate_calls: Arc<AtomicUsize>,
    status_calls: Arc<AtomicUsize>,
    observed_secret_len: Arc<Mutex<Vec<usize>>>,
}

impl ScriptedProvider {
    fn push_refresh(&self, result: Result<ProviderRefreshResult, ProviderAdapterError>) {
        self.refresh
            .lock()
            .unwrap_or_else(|_| panic!("refresh queue poisoned"))
            .push_back(result);
    }

    fn push_rotate(&self, result: Result<ProviderRotationResult, ProviderAdapterError>) {
        self.rotate
            .lock()
            .unwrap_or_else(|_| panic!("rotate queue poisoned"))
            .push_back(result);
    }

    fn push_status(&self, result: Result<ProviderStatusResult, ProviderAdapterError>) {
        self.status
            .lock()
            .unwrap_or_else(|_| panic!("status queue poisoned"))
            .push_back(result);
    }

    fn refresh_call_count(&self) -> usize {
        self.refresh_calls.load(Ordering::SeqCst)
    }

    fn status_call_count(&self) -> usize {
        self.status_calls.load(Ordering::SeqCst)
    }
}

impl SecretRefProvider for ScriptedProvider {
    fn refresh(
        &self,
        _request: &RefreshWithSecretRefRequest,
        secret: &ProcessBoundSecret,
    ) -> Result<ProviderRefreshResult, ProviderAdapterError> {
        self.refresh_calls.fetch_add(1, Ordering::SeqCst);
        self.observed_secret_len
            .lock()
            .unwrap_or_else(|_| panic!("secret lengths poisoned"))
            .push(secret.len());
        self.refresh
            .lock()
            .unwrap_or_else(|_| panic!("refresh queue poisoned"))
            .pop_front()
            .unwrap_or(Err(ProviderAdapterError::Unknown))
    }

    fn rotate(
        &self,
        _request: &RotateSecretRefRequest,
        secret: &ProcessBoundSecret,
    ) -> Result<ProviderRotationResult, ProviderAdapterError> {
        self.rotate_calls.fetch_add(1, Ordering::SeqCst);
        self.observed_secret_len
            .lock()
            .unwrap_or_else(|_| panic!("secret lengths poisoned"))
            .push(secret.len());
        self.rotate
            .lock()
            .unwrap_or_else(|_| panic!("rotate queue poisoned"))
            .pop_front()
            .unwrap_or(Err(ProviderAdapterError::Unknown))
    }

    fn status_by_operation_key(
        &self,
        _request: &RefreshStatusByOperationKeyRequest,
    ) -> Result<ProviderStatusResult, ProviderAdapterError> {
        self.status_calls.fetch_add(1, Ordering::SeqCst);
        self.status
            .lock()
            .unwrap_or_else(|_| panic!("status queue poisoned"))
            .pop_front()
            .unwrap_or(Err(ProviderAdapterError::Unknown))
    }
}

fn successful_refresh(request: &RefreshWithSecretRefRequest) -> ProviderRefreshResult {
    ProviderRefreshResult {
        response_id: "provider-refresh-response".to_string(),
        provider_status: SecretProviderStatus::Rotated,
        access_secret_ref: Some(secret_ref("access-v2", b"access-v2")),
        refresh_secret_ref: Some(secret_ref("refresh-v2", b"refresh-v2")),
        secret_revision: Some(request.expected_secret_revision + 1),
        response_digest: digest("provider-refresh-response"),
    }
}

fn successful_rotation(request: &RotateSecretRefRequest) -> ProviderRotationResult {
    ProviderRotationResult {
        response_id: "provider-rotate-response".to_string(),
        provider_status: SecretProviderStatus::Rotated,
        new_refresh_secret_ref: Some(secret_ref("refresh-rotated", b"refresh-rotated")),
        secret_revision: Some(request.expected_secret_revision + 1),
        response_digest: digest("provider-rotate-response"),
    }
}

fn successful_status(request: &RefreshStatusByOperationKeyRequest) -> ProviderStatusResult {
    ProviderStatusResult {
        response_id: "provider-status-response".to_string(),
        provider_status: SecretProviderStatus::Rotated,
        secret_revision: request.expected_secret_revision + 1,
        response_digest: digest("provider-status-response"),
        status_revision: 1,
        observed_at: 10,
        provider_query_receipt_digest: digest("provider-query"),
        new_access_secret_ref: Some(secret_ref("access-status-v2", b"access-status-v2")),
        new_refresh_secret_ref: Some(secret_ref("refresh-status-v2", b"refresh-status-v2")),
    }
}

fn backend_with_reference(reference: &OpaqueSecretRef, bytes: &[u8]) -> QualificationSecretBackend {
    let mut backend = QualificationSecretBackend::default();
    backend
        .insert(reference.clone(), bytes)
        .unwrap_or_else(|error| panic!("backend reference: {error:?}"));
    backend
}

#[test]
fn adapter_flags_are_fail_closed_and_direct_success_is_opaque() {
    const {
        assert!(AUTHBUS_B3_ADAPTER_QUALIFICATION_ONLY);
        assert!(!AUTHBUS_B3_ADAPTER_AUTHORITY);
        assert!(!AUTHBUS_B3_ADAPTER_EFFECT_AUTHORITY);
        assert!(!AUTHBUS_B3_ADAPTER_PRODUCTION_CALLER);
        assert!(!AUTHBUS_B3_ADAPTER_PRODUCTION_WRITER);
        assert!(!AUTHBUS_B3_ADAPTER_OPERATOR_ACCEPTANCE);
        assert!(!AUTHBUS_B3_ADAPTER_PROMOTION);
        assert!(!AUTHBUS_B3_ADAPTER_G5_ALLOWED);
        assert!(!AUTHBUS_B3_ADAPTER_EXECUTE_ALLOWED);
    }

    let raw = b"refresh-secret-never-leaves-process";
    let reference = secret_ref("refresh-v1", raw);
    let backend = backend_with_reference(&reference, raw);
    let provider = ScriptedProvider::default();
    let request = refresh_request("profile-direct", "direct", reference);
    provider.push_refresh(Ok(successful_refresh(&request)));
    let mut adapter = ProcessBoundSecretRefAdapter::new(backend, provider.clone());

    let response = must(adapter.refresh(request.clone()), "direct success");
    assert_eq!(response.outcome, SecretRefOutcome::Succeeded);
    assert_eq!(
        adapter.operation_state(&request.operation_id),
        Some(SecretRefState::Succeeded)
    );
    assert_eq!(provider.refresh_call_count(), 1);
    assert_eq!(
        provider
            .observed_secret_len
            .lock()
            .unwrap_or_else(|_| panic!("lengths poisoned"))
            .as_slice(),
        &[raw.len()]
    );

    let encoded = must(serde_json::to_string(&response), "response json");
    assert!(!encoded.contains("refresh-secret-never-leaves-process"));
    assert!(!encoded.contains("access_token"));
    assert_eq!(
        must(adapter.refresh(request), "idempotent replay"),
        response
    );
    assert_eq!(provider.refresh_call_count(), 1);
}

#[test]
fn backend_openbao_error_matrix_is_typed_and_does_not_call_provider() {
    let cases = [
        (
            "not-found",
            SecretBackendError::NotFound,
            SecretProviderStatus::Unavailable,
        ),
        (
            "unauthorized",
            SecretBackendError::Unauthorized,
            SecretProviderStatus::Unauthorized,
        ),
        (
            "timeout",
            SecretBackendError::Timeout,
            SecretProviderStatus::Timeout,
        ),
        (
            "sealed",
            SecretBackendError::Sealed,
            SecretProviderStatus::Sealed,
        ),
    ];
    for (label, backend_error, expected_status) in cases {
        let raw = format!("raw-{label}");
        let reference = secret_ref(label, raw.as_bytes());
        let mut backend = backend_with_reference(&reference, raw.as_bytes());
        backend.set_error(Some(backend_error));
        let provider = ScriptedProvider::default();
        let request = refresh_request(label, label, reference);
        let mut adapter = ProcessBoundSecretRefAdapter::new(backend, provider.clone());
        let response = must(adapter.refresh(request), "typed backend response");
        assert_eq!(response.outcome, SecretRefOutcome::TransientFailure);
        assert_eq!(response.provider_status, expected_status);
        assert_eq!(provider.refresh_call_count(), 0);
    }
}

#[test]
fn invalid_grant_is_quarantined_once_and_terminal_replay_is_local() {
    let raw = b"grant";
    let reference = secret_ref("invalid-grant", raw);
    let provider = ScriptedProvider::default();
    let request = refresh_request("profile-invalid", "invalid", reference.clone());
    provider.push_refresh(Err(ProviderAdapterError::InvalidGrant));
    let mut adapter = ProcessBoundSecretRefAdapter::new(
        backend_with_reference(&reference, raw),
        provider.clone(),
    );

    let response = must(adapter.refresh(request.clone()), "quarantine response");
    assert_eq!(response.outcome, SecretRefOutcome::Quarantined);
    assert_eq!(response.access_secret_ref, None);
    assert_eq!(response.refresh_secret_ref, None);
    assert_eq!(
        adapter.operation_state(&request.operation_id),
        Some(SecretRefState::Quarantined)
    );
    assert_eq!(must(adapter.refresh(request), "replay"), response);
    assert_eq!(provider.refresh_call_count(), 1);
}

#[test]
fn response_loss_requires_status_lookup_and_never_blind_retries() {
    let raw = b"response-loss";
    let reference = secret_ref("response-loss", raw);
    let provider = ScriptedProvider::default();
    let request = refresh_request("profile-loss", "loss", reference.clone());
    provider.push_refresh(Err(ProviderAdapterError::Unknown));
    provider.push_status(Ok(successful_status(&status_request(&request))));
    let mut adapter = ProcessBoundSecretRefAdapter::new(
        backend_with_reference(&reference, raw),
        provider.clone(),
    );

    let lost = must(adapter.refresh(request.clone()), "indeterminate response");
    assert_eq!(lost.outcome, SecretRefOutcome::Indeterminate);
    assert_eq!(
        adapter.operation_state(&request.operation_id),
        Some(SecretRefState::Indeterminate)
    );
    assert_eq!(
        must(adapter.refresh(request.clone()), "indeterminate replay"),
        lost
    );
    assert_eq!(provider.refresh_call_count(), 1);

    let status = must(
        adapter.status_by_effect_key(status_request(&request)),
        "provider-owned status lookup",
    );
    assert_eq!(status.outcome, SecretRefOutcome::Succeeded);
    assert_eq!(
        adapter.operation_state(&request.operation_id),
        Some(SecretRefState::Succeeded)
    );
    assert_eq!(provider.status_call_count(), 1);
}

#[test]
fn stale_status_fence_is_rejected_before_provider_lookup() {
    let raw = b"stale-status";
    let reference = secret_ref("stale-status", raw);
    let provider = ScriptedProvider::default();
    let request = refresh_request("profile-stale", "stale", reference.clone());
    provider.push_refresh(Err(ProviderAdapterError::Unknown));
    let mut adapter = ProcessBoundSecretRefAdapter::new(
        backend_with_reference(&reference, raw),
        provider.clone(),
    );
    must(adapter.refresh(request.clone()), "indeterminate");

    let mut stale = status_request(&request);
    stale.generation += 1;
    assert_eq!(
        adapter.status_by_operation_key(stale),
        Err(B3AdapterError::Conflict)
    );
    assert_eq!(provider.status_call_count(), 0);
}

#[test]
fn rotation_uses_the_same_process_bound_boundary() {
    let raw = b"rotation-secret";
    let reference = secret_ref("rotation", raw);
    let provider = ScriptedProvider::default();
    let request = rotate_request("profile-rotate", "rotate", reference.clone());
    provider.push_rotate(Ok(successful_rotation(&request)));
    let mut adapter = ProcessBoundSecretRefAdapter::new(
        backend_with_reference(&reference, raw),
        provider.clone(),
    );

    let response = must(adapter.rotate(request), "rotation success");
    assert_eq!(response.outcome, SecretRefOutcome::Succeeded);
    assert!(response.new_refresh_secret_ref.is_some());
    assert_eq!(provider.rotate_calls.load(Ordering::SeqCst), 1);
    let encoded = must(serde_json::to_string(&response), "rotation json");
    assert!(!encoded.contains("rotation-secret"));
}

#[test]
fn malformed_provider_success_is_quarantined_without_a_second_call() {
    let raw = b"malformed";
    let reference = secret_ref("malformed", raw);
    let provider = ScriptedProvider::default();
    let request = refresh_request("profile-malformed", "malformed", reference.clone());
    provider.push_refresh(Ok(ProviderRefreshResult {
        response_id: "malformed-response".to_string(),
        provider_status: SecretProviderStatus::Rotated,
        access_secret_ref: None,
        refresh_secret_ref: None,
        secret_revision: Some(request.expected_secret_revision + 1),
        response_digest: digest("malformed-response"),
    }));
    let mut adapter = ProcessBoundSecretRefAdapter::new(
        backend_with_reference(&reference, raw),
        provider.clone(),
    );

    assert!(matches!(
        adapter.refresh(request.clone()),
        Err(B3AdapterError::ProviderResponseInvalid(_))
    ));
    assert_eq!(
        adapter.operation_state(&request.operation_id),
        Some(SecretRefState::Indeterminate)
    );
    assert_eq!(
        adapter.refresh(request),
        Err(B3AdapterError::ReconcileRequired)
    );
    assert_eq!(provider.refresh_call_count(), 1);
}

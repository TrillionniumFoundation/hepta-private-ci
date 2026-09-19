use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;

use anyhow::Result;
use pretty_assertions::assert_eq;

use super::shell_runtime::BackendConnector;
use super::shell_runtime::BackendSession;
use super::shell_runtime::EndpointManifest;
use super::shell_runtime::GrantVerifier;
use super::shell_runtime::InvokeObservation;
use super::shell_runtime::NativeShellRuntime;
use super::shell_runtime::PermissionDecision;
use super::shell_runtime::PlatformAction;
use super::shell_runtime::PlatformAdapter;
use super::shell_runtime::PlatformReceipt;
use super::shell_runtime::PlatformRequest;
use super::shell_runtime::PlatformStatus;
use super::shell_runtime::ReconcileObservation;
use super::shell_runtime::SessionKey;
use super::shell_runtime::TerminalStatus;
use super::shell_runtime::VerifiedPlatformGrant;
use super::shell_runtime::ViewInput;

const D1: &str = "1111111111111111111111111111111111111111111111111111111111111111";
const D2: &str = "2222222222222222222222222222222222222222222222222222222222222222";
const D3: &str = "3333333333333333333333333333333333333333333333333333333333333333";
const D4: &str = "4444444444444444444444444444444444444444444444444444444444444444";

#[derive(Clone)]
struct FixtureBackend {
    sessions: Arc<Mutex<VecDeque<BackendSession>>>,
}

impl FixtureBackend {
    fn new(sessions: impl IntoIterator<Item = BackendSession>) -> Self {
        Self {
            sessions: Arc::new(Mutex::new(sessions.into_iter().collect())),
        }
    }
}

impl BackendConnector for FixtureBackend {
    fn connect(&self, _manifest: &EndpointManifest) -> Result<BackendSession> {
        Ok(self
            .sessions
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .pop_front()
            .expect("fixture backend session"))
    }

    fn close(&self, _session: &SessionKey) -> Result<()> {
        Ok(())
    }
}

#[derive(Clone, Debug)]
struct FixtureGrantVerifier;

impl GrantVerifier for FixtureGrantVerifier {
    fn verify(
        &self,
        session: &SessionKey,
        request: &PlatformRequest,
    ) -> Result<VerifiedPlatformGrant> {
        Ok(VerifiedPlatformGrant {
            session: session.clone(),
            operation_id: request.operation_id.clone(),
            action: request.action,
            payload_digest: request.payload_digest.clone(),
        })
    }
}

#[derive(Debug)]
struct PlatformState {
    reconcile: VecDeque<ReconcileObservation>,
    permission: PermissionDecision,
    invoke: InvokeObservation,
    reconcile_calls: usize,
    permission_calls: usize,
    invoke_calls: usize,
}

#[derive(Clone)]
struct FixturePlatform {
    state: Arc<Mutex<PlatformState>>,
}

impl FixturePlatform {
    fn new(
        reconcile: impl IntoIterator<Item = ReconcileObservation>,
        permission: PermissionDecision,
        invoke: InvokeObservation,
    ) -> Self {
        Self {
            state: Arc::new(Mutex::new(PlatformState {
                reconcile: reconcile.into_iter().collect(),
                permission,
                invoke,
                reconcile_calls: 0,
                permission_calls: 0,
                invoke_calls: 0,
            })),
        }
    }

    fn counts(&self) -> (usize, usize, usize) {
        let state = self
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        (
            state.reconcile_calls,
            state.permission_calls,
            state.invoke_calls,
        )
    }
}

impl PlatformAdapter for FixturePlatform {
    fn permission(&self, _request: &PlatformRequest) -> Result<PermissionDecision> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        state.permission_calls += 1;
        Ok(state.permission.clone())
    }

    fn reconcile(
        &self,
        _session: &SessionKey,
        _request: &PlatformRequest,
    ) -> Result<ReconcileObservation> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        state.reconcile_calls += 1;
        Ok(state
            .reconcile
            .pop_front()
            .unwrap_or(ReconcileObservation::Indeterminate))
    }

    fn invoke(&self, _session: &SessionKey, _request: &PlatformRequest) -> Result<InvokeObservation> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        state.invoke_calls += 1;
        Ok(state.invoke.clone())
    }
}

fn backend_session(session_id: &str, generation: u64) -> BackendSession {
    BackendSession {
        authenticated: true,
        protocol_version: 1,
        session_id: session_id.to_string(),
        generation,
    }
}

fn manifest() -> EndpointManifest {
    EndpointManifest {
        endpoint_id: "runtime.1".to_string(),
        manifest_digest: D1.to_string(),
        protocol_version: 1,
    }
}

fn request(operation_id: &str, revision: u64) -> PlatformRequest {
    PlatformRequest {
        operation_id: operation_id.to_string(),
        action: PlatformAction::Notify,
        resource: "notification.channel.1".to_string(),
        displayed_revision: revision,
        payload_digest: D3.to_string(),
        grant: "fixture-grant".to_string(),
    }
}

fn connect_view(
    runtime: &mut NativeShellRuntime<FixtureBackend, FixturePlatform, FixtureGrantVerifier>,
) -> Result<SessionKey> {
    let session = runtime.connect_runtime(manifest())?;
    runtime.render_runtime_view(ViewInput {
        session: session.clone(),
        generation: 9,
        revision: 11,
        digest: D2.to_string(),
        modules: vec!["runtime.agentd".to_string(), "ui.native".to_string()],
    })?;
    Ok(session)
}

fn expected_receipt(session: SessionKey, status: PlatformStatus, outcome: Option<&str>) -> PlatformReceipt {
    PlatformReceipt {
        session,
        operation_id: "operation.1".to_string(),
        action: PlatformAction::Notify,
        status,
        terminal_observed: status != PlatformStatus::Indeterminate,
        outcome_digest: outcome.map(str::to_string),
    }
}

#[test]
fn indeterminate_retry_reconciles_without_reinvoking() -> Result<()> {
    let platform = FixturePlatform::new(
        [
            ReconcileObservation::NotFound,
            ReconcileObservation::Terminal {
                status: TerminalStatus::Succeeded,
                outcome_digest: D4.to_string(),
            },
        ],
        PermissionDecision::Allowed,
        InvokeObservation::Indeterminate,
    );
    let mut runtime = NativeShellRuntime::new(
        FixtureBackend::new([backend_session("session.1", 3)]),
        platform.clone(),
        FixtureGrantVerifier,
    );
    let session = connect_view(&mut runtime)?;

    assert_eq!(
        runtime.request_platform_capability(request("operation.1", 11))?,
        expected_receipt(session.clone(), PlatformStatus::Indeterminate, None)
    );
    assert_eq!(
        runtime.request_platform_capability(request("operation.1", 11))?,
        expected_receipt(session, PlatformStatus::Succeeded, Some(D4))
    );
    assert_eq!(platform.counts(), (2, 1, 1));
    Ok(())
}

#[test]
fn indeterminate_not_found_remains_fenced_and_is_never_replayed() -> Result<()> {
    let platform = FixturePlatform::new(
        [
            ReconcileObservation::NotFound,
            ReconcileObservation::NotFound,
        ],
        PermissionDecision::Allowed,
        InvokeObservation::Indeterminate,
    );
    let mut runtime = NativeShellRuntime::new(
        FixtureBackend::new([backend_session("session.1", 3)]),
        platform.clone(),
        FixtureGrantVerifier,
    );
    connect_view(&mut runtime)?;

    let first = runtime.request_platform_capability(request("operation.1", 11))?;
    let second = runtime.request_platform_capability(request("operation.1", 11))?;
    assert_eq!(second, first);
    assert_eq!(platform.counts(), (2, 1, 1));
    Ok(())
}

#[test]
fn a_fresh_runtime_reconciles_existing_terminal_effect_before_invoke() -> Result<()> {
    let platform = FixturePlatform::new(
        [ReconcileObservation::Terminal {
            status: TerminalStatus::Succeeded,
            outcome_digest: D4.to_string(),
        }],
        PermissionDecision::Allowed,
        InvokeObservation::Terminal {
            status: TerminalStatus::Failed,
            outcome_digest: D2.to_string(),
        },
    );
    let mut runtime = NativeShellRuntime::new(
        FixtureBackend::new([backend_session("session.1", 3)]),
        platform.clone(),
        FixtureGrantVerifier,
    );
    let session = connect_view(&mut runtime)?;

    assert_eq!(
        runtime.request_platform_capability(request("operation.1", 11))?,
        expected_receipt(session, PlatformStatus::Succeeded, Some(D4))
    );
    assert_eq!(platform.counts(), (1, 0, 0));
    Ok(())
}

#[test]
fn reconnect_fences_receipts_by_session_and_generation() -> Result<()> {
    let platform = FixturePlatform::new(
        [
            ReconcileObservation::NotFound,
            ReconcileObservation::NotFound,
        ],
        PermissionDecision::Allowed,
        InvokeObservation::Terminal {
            status: TerminalStatus::Succeeded,
            outcome_digest: D4.to_string(),
        },
    );
    let mut runtime = NativeShellRuntime::new(
        FixtureBackend::new([
            backend_session("session.1", 3),
            backend_session("session.2", 4),
        ]),
        platform.clone(),
        FixtureGrantVerifier,
    );
    connect_view(&mut runtime)?;
    runtime.request_platform_capability(request("operation.1", 11))?;

    let session = connect_view(&mut runtime)?;
    let receipt = runtime.request_platform_capability(request("operation.1", 11))?;
    assert_eq!(receipt.session, session);
    assert_eq!(platform.counts(), (2, 2, 2));
    Ok(())
}

#[test]
fn operation_identity_cannot_change_payload_within_a_session() -> Result<()> {
    let platform = FixturePlatform::new(
        [ReconcileObservation::NotFound],
        PermissionDecision::Allowed,
        InvokeObservation::Indeterminate,
    );
    let mut runtime = NativeShellRuntime::new(
        FixtureBackend::new([backend_session("session.1", 3)]),
        platform,
        FixtureGrantVerifier,
    );
    connect_view(&mut runtime)?;
    runtime.request_platform_capability(request("operation.1", 11))?;

    let mut changed = request("operation.1", 11);
    changed.payload_digest = D2.to_string();
    let error = runtime.request_platform_capability(changed).unwrap_err();
    assert!(error.to_string().contains("reused with changed payload"));
    Ok(())
}

#[test]
fn stale_view_is_rejected_before_permission_or_effect() -> Result<()> {
    let platform = FixturePlatform::new(
        [ReconcileObservation::NotFound],
        PermissionDecision::Allowed,
        InvokeObservation::Terminal {
            status: TerminalStatus::Succeeded,
            outcome_digest: D4.to_string(),
        },
    );
    let mut runtime = NativeShellRuntime::new(
        FixtureBackend::new([backend_session("session.1", 3)]),
        platform.clone(),
        FixtureGrantVerifier,
    );
    connect_view(&mut runtime)?;

    let error = runtime
        .request_platform_capability(request("operation.1", 10))
        .unwrap_err();
    assert!(error.to_string().contains("stale view"));
    assert_eq!(platform.counts(), (0, 0, 0));
    Ok(())
}

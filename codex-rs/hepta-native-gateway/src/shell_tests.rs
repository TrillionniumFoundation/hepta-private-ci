use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::PoisonError;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use crate::platform::PermissionDecision;
use crate::platform::PlatformAction;
use crate::platform::PlatformAdapter;
use crate::platform::PlatformError;
use crate::platform::PlatformObservation;
use crate::platform::PlatformPayload;

use super::*;

#[derive(Debug, Default)]
struct MockPlatformState {
    invoke_count: usize,
    reconcile_count: usize,
    permission: Option<PermissionDecision>,
    next_invoke: Option<PlatformObservation>,
    fail_invoke: bool,
    reconciliation: BTreeMap<SessionOperationKey, PlatformObservation>,
}

#[derive(Clone, Debug, Default)]
struct MockPlatform {
    state: Arc<Mutex<MockPlatformState>>,
}

impl MockPlatform {
    fn set_invoke(&self, observation: PlatformObservation) {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .next_invoke = Some(observation);
    }

    fn fail_next_invoke(&self) {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .fail_invoke = true;
    }

    fn set_reconciliation(&self, key: SessionOperationKey, observation: PlatformObservation) {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .reconciliation
            .insert(key, observation);
    }

    fn invoke_count(&self) -> usize {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .invoke_count
    }

    fn reconcile_count(&self) -> usize {
        self.state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .reconcile_count
    }
}

impl PlatformAdapter for MockPlatform {
    type Error = PlatformError;

    fn permission(
        &self,
        _action: PlatformAction,
        _payload: &PlatformPayload,
    ) -> Result<PermissionDecision, Self::Error> {
        Ok(self
            .state
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .permission
            .clone()
            .unwrap_or(PermissionDecision::Allowed))
    }

    fn invoke(
        &self,
        _key: &SessionOperationKey,
        _payload: &PlatformPayload,
        _payload_digest: Digest32,
    ) -> Result<PlatformObservation, Self::Error> {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        state.invoke_count += 1;
        if state.fail_invoke {
            state.fail_invoke = false;
            return Err(PlatformError::Command(
                "simulated lost observation after effect boundary".to_string(),
            ));
        }
        Ok(state
            .next_invoke
            .clone()
            .unwrap_or_else(|| PlatformObservation::Succeeded {
                outcome_digest: digest("success"),
            }))
    }

    fn reconcile(
        &self,
        key: &SessionOperationKey,
        _action: PlatformAction,
        _payload_digest: Digest32,
    ) -> Result<PlatformObservation, Self::Error> {
        let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        state.reconcile_count += 1;
        Ok(state
            .reconciliation
            .get(key)
            .cloned()
            .unwrap_or(PlatformObservation::Indeterminate))
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn stable(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("invalid fixture id: {error}"))
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("invalid generation: {error}"))
}

fn signing_key() -> SigningKey {
    SigningKey::from_bytes(&[7_u8; 32])
}

fn verifier() -> TrustedGrantVerifier {
    let key = signing_key();
    TrustedGrantVerifier::new(IssuerRegistration {
        issuer_id: stable("authority.ui.native"),
        key_epoch: generation(4),
        verifying_key: key.verifying_key(),
        revoked: false,
    })
}

fn operation_key(session: &str, gen: u64, operation_id: &StableId) -> SessionOperationKey {
    SessionOperationKey {
        session_id: stable(session),
        session_generation: generation(gen),
        operation_id: operation_id.clone(),
    }
}

fn signed_grant(
    key: &SessionOperationKey,
    payload: &PlatformPayload,
    sequence: u64,
) -> SignedMessage {
    let signing_key = signing_key();
    let claims = SignedMessageClaims {
        issuer_id: stable("authority.ui.native"),
        key_epoch: generation(4),
        message_id: stable(&format!("grant.{sequence}")),
        subject_id: key.operation_id.clone(),
        scope_digest: payload.action().scope_digest(),
        payload_digest: platform_grant_binding_digest(key, payload.action(), payload.digest()),
        sequence,
        expires_at_ms: 50_000,
    };
    let signature = signing_key.sign(&claims.signing_bytes()).to_bytes();
    SignedMessage { claims, signature }
}

fn connect(runtime: &mut NativeShellRuntime<MockPlatform>, session: &str, gen: u64) {
    runtime
        .connect_runtime(
            EndpointManifest {
                endpoint_id: stable("runtime.local"),
                manifest_digest: digest("manifest"),
                protocol_version: 1,
            },
            BackendSessionObservation {
                authenticated: true,
                protocol_version: 1,
                session_id: stable(session),
                generation: generation(gen),
            },
        )
        .unwrap_or_else(|error| panic!("connect failed: {error}"));
    runtime
        .render_runtime_view(RuntimeView {
            session_id: stable(session),
            session_generation: generation(gen),
            generation: 1,
            revision: 1,
            digest: digest("view"),
            modules: vec![stable("runtime.agentd")],
        })
        .unwrap_or_else(|error| panic!("render failed: {error}"));
}

fn unique_journal(name: &str) -> PathBuf {
    let mut path = std::env::temp_dir();
    path.push(format!(
        "hepta-native-shell-{name}-{}-{}.journal",
        std::process::id(),
        now_unix_ms().unwrap_or(1)
    ));
    path
}

#[test]
fn operation_cache_is_fenced_by_session_and_generation() {
    let platform = MockPlatform::default();
    let observer = platform.clone();
    let mut runtime = NativeShellRuntime::new(platform, verifier());
    connect(&mut runtime, "session.a", 1);

    let operation = stable("operation.same");
    let payload = PlatformPayload::Notify {
        title: "Hepta".to_string(),
        body: "first".to_string(),
    };
    let first_key = operation_key("session.a", 1, &operation);
    let first = runtime
        .request_platform_capability_at(
            PlatformCapabilityRequest {
                operation_id: operation.clone(),
                displayed_revision: 1,
                payload: payload.clone(),
                grant: signed_grant(&first_key, &payload, 1),
            },
            1_000,
        )
        .unwrap_or_else(|error| panic!("first request failed: {error}"));
    assert_eq!(first.key.session_id, stable("session.a"));
    assert_eq!(observer.invoke_count(), 1);

    runtime.close();
    connect(&mut runtime, "session.b", 2);
    let second_key = operation_key("session.b", 2, &operation);
    let second = runtime
        .request_platform_capability_at(
            PlatformCapabilityRequest {
                operation_id: operation.clone(),
                displayed_revision: 1,
                payload: payload.clone(),
                grant: signed_grant(&second_key, &payload, 2),
            },
            1_001,
        )
        .unwrap_or_else(|error| panic!("second request failed: {error}"));
    assert_eq!(second.key.session_id, stable("session.b"));
    assert_eq!(second.key.session_generation, generation(2));
    assert_eq!(observer.invoke_count(), 2);
}

#[test]
fn grant_cannot_move_to_replacement_session() {
    let platform = MockPlatform::default();
    let observer = platform.clone();
    let mut runtime = NativeShellRuntime::new(platform, verifier());
    connect(&mut runtime, "session.old", 1);
    let operation = stable("operation.session-bound");
    let payload = PlatformPayload::CopyText {
        text: "bounded".to_string(),
    };
    let old_key = operation_key("session.old", 1, &operation);
    let grant = signed_grant(&old_key, &payload, 3);

    runtime.close();
    connect(&mut runtime, "session.new", 2);
    let result = runtime.request_platform_capability_at(
        PlatformCapabilityRequest {
            operation_id: operation,
            displayed_revision: 1,
            payload,
            grant,
        },
        1_000,
    );
    assert!(matches!(result, Err(ShellError::GrantRejected(_))));
    assert_eq!(observer.invoke_count(), 0);
}

#[test]
fn indeterminate_duplicate_reconciles_instead_of_returning_stale_receipt() {
    let platform = MockPlatform::default();
    platform.set_invoke(PlatformObservation::Indeterminate);
    let observer = platform.clone();
    let mut runtime = NativeShellRuntime::new(platform, verifier());
    connect(&mut runtime, "session.reconcile", 3);
    let operation = stable("operation.reconcile");
    let key = operation_key("session.reconcile", 3, &operation);
    let payload = PlatformPayload::CopyText {
        text: "bounded text".to_string(),
    };
    let first = runtime
        .request_platform_capability_at(
            PlatformCapabilityRequest {
                operation_id: operation.clone(),
                displayed_revision: 1,
                payload: payload.clone(),
                grant: signed_grant(&key, &payload, 10),
            },
            1_000,
        )
        .unwrap_or_else(|error| panic!("first request failed: {error}"));
    assert_eq!(first.status, PlatformDecisionStatus::Indeterminate);
    assert_eq!(observer.invoke_count(), 1);

    observer.set_reconciliation(
        first.key.clone(),
        PlatformObservation::Succeeded {
            outcome_digest: digest("reconciled"),
        },
    );
    let second = runtime
        .request_platform_capability_at(
            PlatformCapabilityRequest {
                operation_id: operation.clone(),
                displayed_revision: 1,
                payload: payload.clone(),
                // Duplicate reconciliation does not consume another grant.
                grant: signed_grant(&key, &payload, 10),
            },
            1_001,
        )
        .unwrap_or_else(|error| panic!("reconciliation failed: {error}"));
    assert_eq!(second.status, PlatformDecisionStatus::Succeeded);
    assert!(second.terminal_observed);
    assert_eq!(observer.invoke_count(), 1);
    assert_eq!(observer.reconcile_count(), 1);
}

#[test]
fn crash_window_reopens_from_journal_and_reconciles_without_redispatch() {
    let path = unique_journal("restart-reconcile");
    let platform = MockPlatform::default();
    platform.fail_next_invoke();
    let observer = platform.clone();
    let operation = stable("operation.crash-window");
    let key = operation_key("session.restart", 9, &operation);
    let payload = PlatformPayload::CopyText {
        text: "once".to_string(),
    };

    {
        let mut runtime = NativeShellRuntime::open_with_journal(
            platform.clone(),
            verifier(),
            path.clone(),
        )
        .unwrap_or_else(|error| panic!("open journal runtime: {error}"));
        connect(&mut runtime, "session.restart", 9);
        let result = runtime.request_platform_capability_at(
            PlatformCapabilityRequest {
                operation_id: operation,
                displayed_revision: 1,
                payload: payload.clone(),
                grant: signed_grant(&key, &payload, 50),
            },
            1_000,
        );
        assert!(matches!(result, Err(ShellError::Platform(_))));
        assert_eq!(runtime.operation_count(), 1);
        assert_eq!(observer.invoke_count(), 1);
    }

    observer.set_reconciliation(
        key,
        PlatformObservation::Succeeded {
            outcome_digest: digest("observed-after-restart"),
        },
    );
    let mut reopened = NativeShellRuntime::open_with_journal(platform, verifier(), path.clone())
        .unwrap_or_else(|error| panic!("reopen journal runtime: {error}"));
    let reconciled = reopened
        .reconcile_indeterminate()
        .unwrap_or_else(|error| panic!("reconcile recovered: {error}"));
    assert_eq!(reconciled.len(), 1);
    assert_eq!(reconciled[0].status, PlatformDecisionStatus::Succeeded);
    assert_eq!(observer.invoke_count(), 1);
    assert_eq!(observer.reconcile_count(), 1);

    drop(reopened);
    let _ = fs::remove_file(path);
}

#[test]
fn operation_id_reuse_with_changed_payload_fails_closed() {
    let platform = MockPlatform::default();
    let mut runtime = NativeShellRuntime::new(platform, verifier());
    connect(&mut runtime, "session.payload", 5);
    let operation = stable("operation.payload");
    let key = operation_key("session.payload", 5, &operation);
    let first_payload = PlatformPayload::CopyText {
        text: "one".to_string(),
    };
    runtime
        .request_platform_capability_at(
            PlatformCapabilityRequest {
                operation_id: operation.clone(),
                displayed_revision: 1,
                payload: first_payload.clone(),
                grant: signed_grant(&key, &first_payload, 20),
            },
            1_000,
        )
        .unwrap_or_else(|error| panic!("first request failed: {error}"));

    let changed = PlatformPayload::CopyText {
        text: "two".to_string(),
    };
    let result = runtime.request_platform_capability_at(
        PlatformCapabilityRequest {
            operation_id: operation.clone(),
            displayed_revision: 1,
            payload: changed.clone(),
            grant: signed_grant(&key, &changed, 21),
        },
        1_001,
    );
    assert_eq!(result, Err(ShellError::OperationPayloadChanged));
}

#[test]
fn signed_grant_binds_exact_payload_and_scope() {
    let platform = MockPlatform::default();
    let mut runtime = NativeShellRuntime::new(platform, verifier());
    connect(&mut runtime, "session.grant", 7);
    let operation = stable("operation.grant");
    let key = operation_key("session.grant", 7, &operation);
    let granted_payload = PlatformPayload::CopyText {
        text: "approved".to_string(),
    };
    let grant = signed_grant(&key, &granted_payload, 30);
    let actual_payload = PlatformPayload::CopyText {
        text: "changed".to_string(),
    };
    let result = runtime.request_platform_capability_at(
        PlatformCapabilityRequest {
            operation_id: operation,
            displayed_revision: 1,
            payload: actual_payload,
            grant,
        },
        1_000,
    );
    assert!(matches!(result, Err(ShellError::GrantRejected(_))));
}

#[test]
fn stale_view_revision_cannot_issue_platform_effect() {
    let platform = MockPlatform::default();
    let observer = platform.clone();
    let mut runtime = NativeShellRuntime::new(platform, verifier());
    connect(&mut runtime, "session.stale", 8);
    let operation = stable("operation.stale");
    let key = operation_key("session.stale", 8, &operation);
    let payload = PlatformPayload::CopyText {
        text: "text".to_string(),
    };
    let result = runtime.request_platform_capability_at(
        PlatformCapabilityRequest {
            operation_id: operation,
            displayed_revision: 99,
            payload: payload.clone(),
            grant: signed_grant(&key, &payload, 40),
        },
        1_000,
    );
    assert_eq!(result, Err(ShellError::DisplayedRevisionStale));
    assert_eq!(observer.invoke_count(), 0);
}

use base64::Engine as _;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use hepta_native::backend::Backend;
use hepta_native::backend::BackendError;
use hepta_native::journal::OperationJournal;
use hepta_native::now_unix_ms;
use hepta_native::platform::ObservationStatus;
use hepta_native::platform::PlatformAdapter;
use hepta_native::platform::PlatformError;
use hepta_native::platform::PlatformObservation;
use hepta_native::runtime::ShellRuntime;
use hepta_native::security::GrantVerifier;
use hepta_native::security::grant_signing_bytes;
use hepta_native::sha256_hex;
use hepta_native::types::DecisionStatus;
use hepta_native::types::GrantBinding;
use hepta_native::types::NativeSession;
use hepta_native::types::OperationKey;
use hepta_native::types::PlatformAction;
use hepta_native::types::PlatformGrant;
use hepta_native::types::PlatformPayload;
use hepta_native::types::RuntimeManifest;
use hepta_native::types::SignedPlatformGrant;
use std::sync::Arc;
use std::sync::Mutex;

#[derive(Clone)]
struct MockBackend {
    generation: u64,
}

impl Backend for MockBackend {
    fn connect(&mut self, manifest: &RuntimeManifest) -> Result<NativeSession, BackendError> {
        Ok(NativeSession {
            endpoint_id: manifest.endpoint_id.clone(),
            manifest_digest: manifest.manifest_digest.clone(),
            protocol_version: manifest.protocol_version,
            session_id: format!("session.{}", self.generation),
            generation: self.generation,
        })
    }

    fn fetch_runtime(
        &mut self,
        _session: &NativeSession,
    ) -> Result<serde_json::Value, BackendError> {
        Ok(serde_json::json!({
            "state": {
                "runtime_snapshot_generation": self.generation
            },
            "authority": {
                "external_effect": false
            }
        }))
    }
}

#[derive(Default)]
struct PlatformState {
    invokes: usize,
    reconciles: usize,
}

struct MockPlatform {
    state: Arc<Mutex<PlatformState>>,
    terminal_on_invoke: bool,
    terminal_on_reconcile: bool,
}

impl PlatformAdapter for MockPlatform {
    fn invoke(
        &mut self,
        _key: &OperationKey,
        _action: PlatformAction,
        _payload: &PlatformPayload,
    ) -> Result<PlatformObservation, PlatformError> {
        self.state.lock().unwrap().invokes += 1;
        if self.terminal_on_invoke {
            Ok(PlatformObservation::succeeded("mock-invoke"))
        } else {
            Ok(PlatformObservation::indeterminate())
        }
    }

    fn reconcile(
        &mut self,
        _key: &OperationKey,
        _action: PlatformAction,
        _payload: &PlatformPayload,
    ) -> Result<Option<PlatformObservation>, PlatformError> {
        self.state.lock().unwrap().reconciles += 1;
        if self.terminal_on_reconcile {
            Ok(Some(PlatformObservation {
                terminal_observed: true,
                status: Some(ObservationStatus::Succeeded),
                outcome_digest: Some(sha256_hex(b"mock-reconciled")),
            }))
        } else {
            Ok(None)
        }
    }
}

fn manifest() -> RuntimeManifest {
    RuntimeManifest {
        endpoint: "http://127.0.0.1:7373".to_string(),
        endpoint_id: "runtime.test".to_string(),
        manifest_digest: "1".repeat(64),
        protocol_version: 1,
    }
}

fn root(name: &str) -> std::path::PathBuf {
    std::env::temp_dir().join(format!(
        "hepta-native-{name}-{}-{}",
        std::process::id(),
        now_unix_ms().unwrap()
    ))
}

fn verifier(root: &std::path::Path, signing_key: &SigningKey) -> GrantVerifier {
    GrantVerifier::new(
        "authority.test".to_string(),
        "key.test".to_string(),
        signing_key.verifying_key().to_bytes(),
        root.join("nonces.log"),
    )
    .unwrap()
}

fn signed_grant(
    binding: GrantBinding,
    nonce: &str,
    signing_key: &SigningKey,
) -> SignedPlatformGrant {
    let now = now_unix_ms().unwrap();
    let grant = PlatformGrant {
        schema_version: 1,
        signer_id: "authority.test".to_string(),
        key_id: "key.test".to_string(),
        grant_id: format!("grant.{nonce}"),
        nonce: nonce.to_string(),
        binding,
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = signing_key.sign(&grant_signing_bytes(&grant).unwrap());
    SignedPlatformGrant {
        grant,
        signature_b64: base64::engine::general_purpose::STANDARD.encode(signature.to_bytes()),
    }
}

fn shell(
    root: &std::path::Path,
    generation: u64,
    state: Arc<Mutex<PlatformState>>,
    terminal_on_invoke: bool,
    terminal_on_reconcile: bool,
    signing_key: &SigningKey,
) -> ShellRuntime<MockBackend, MockPlatform> {
    ShellRuntime::new(
        MockBackend { generation },
        MockPlatform {
            state,
            terminal_on_invoke,
            terminal_on_reconcile,
        },
        OperationJournal::open(root.join("operations.jsonl")).unwrap(),
        Some(verifier(root, signing_key)),
    )
}

#[test]
fn restart_reconciles_indeterminate_without_replaying_effect() {
    let root = root("restart-reconcile");
    std::fs::create_dir_all(&root).unwrap();
    let key = SigningKey::from_bytes(&[7_u8; 32]);
    let state = Arc::new(Mutex::new(PlatformState::default()));
    let payload = PlatformPayload::Text {
        text: "hello".to_string(),
    };

    let mut first = shell(&root, 9, Arc::clone(&state), false, false, &key);
    first.connect(&manifest()).unwrap();
    let view = first.refresh_view().unwrap();
    let binding = first
        .prepare_binding(
            "operation.1",
            PlatformAction::CopyText,
            "clipboard.primary",
            &payload,
            view.revision,
        )
        .unwrap();
    let grant = signed_grant(binding, "nonce.1", &key);
    first.allow_once(PlatformAction::CopyText);
    let decision = first
        .request_platform_capability(
            "operation.1",
            PlatformAction::CopyText,
            "clipboard.primary",
            &payload,
            view.revision,
            &grant,
        )
        .unwrap();
    assert_eq!(decision.status, DecisionStatus::Indeterminate);
    assert_eq!(state.lock().unwrap().invokes, 1);
    drop(first);

    let mut restarted = shell(&root, 9, Arc::clone(&state), false, true, &key);
    restarted.connect(&manifest()).unwrap();
    let view = restarted.refresh_view().unwrap();
    restarted.allow_once(PlatformAction::CopyText);
    let reconciled = restarted
        .request_platform_capability(
            "operation.1",
            PlatformAction::CopyText,
            "clipboard.primary",
            &payload,
            view.revision,
            &grant,
        )
        .unwrap();
    assert_eq!(reconciled.status, DecisionStatus::Succeeded);
    let counts = state.lock().unwrap();
    assert_eq!(counts.invokes, 1);
    assert_eq!(counts.reconciles, 1);
    drop(counts);

    restarted.allow_once(PlatformAction::CopyText);
    let repeated = restarted
        .request_platform_capability(
            "operation.1",
            PlatformAction::CopyText,
            "clipboard.primary",
            &payload,
            view.revision,
            &grant,
        )
        .unwrap();
    assert_eq!(repeated, reconciled);
    assert_eq!(state.lock().unwrap().invokes, 1);
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn backend_generation_fences_operation_identity() {
    let root = root("generation-fence");
    std::fs::create_dir_all(&root).unwrap();
    let key = SigningKey::from_bytes(&[8_u8; 32]);
    let state = Arc::new(Mutex::new(PlatformState::default()));
    let payload = PlatformPayload::Text {
        text: "same payload".to_string(),
    };

    for (generation, nonce) in [(1, "nonce.a"), (2, "nonce.b")] {
        let mut runtime = shell(&root, generation, Arc::clone(&state), true, false, &key);
        let session = runtime.connect(&manifest()).unwrap();
        let view = runtime.refresh_view().unwrap();
        let binding = runtime
            .prepare_binding(
                "operation.same",
                PlatformAction::CopyText,
                "clipboard.primary",
                &payload,
                view.revision,
            )
            .unwrap();
        assert_eq!(binding.session_generation, generation);
        assert_eq!(binding.session_id, session.session_id);
        let grant = signed_grant(binding, nonce, &key);
        runtime.allow_once(PlatformAction::CopyText);
        let decision = runtime
            .request_platform_capability(
                "operation.same",
                PlatformAction::CopyText,
                "clipboard.primary",
                &payload,
                view.revision,
                &grant,
            )
            .unwrap();
        assert_eq!(decision.status, DecisionStatus::Succeeded);
    }

    assert_eq!(state.lock().unwrap().invokes, 2);
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn reused_operation_with_changed_payload_fails_closed() {
    let root = root("payload-drift");
    std::fs::create_dir_all(&root).unwrap();
    let key = SigningKey::from_bytes(&[9_u8; 32]);
    let state = Arc::new(Mutex::new(PlatformState::default()));
    let mut runtime = shell(&root, 3, state, true, false, &key);
    runtime.connect(&manifest()).unwrap();
    let view = runtime.refresh_view().unwrap();

    let first_payload = PlatformPayload::Text {
        text: "first".to_string(),
    };
    let first_binding = runtime
        .prepare_binding(
            "operation.drift",
            PlatformAction::CopyText,
            "clipboard.primary",
            &first_payload,
            view.revision,
        )
        .unwrap();
    let first_grant = signed_grant(first_binding, "nonce.first", &key);
    runtime.allow_once(PlatformAction::CopyText);
    runtime
        .request_platform_capability(
            "operation.drift",
            PlatformAction::CopyText,
            "clipboard.primary",
            &first_payload,
            view.revision,
            &first_grant,
        )
        .unwrap();

    let second_payload = PlatformPayload::Text {
        text: "changed".to_string(),
    };
    let second_binding = runtime
        .prepare_binding(
            "operation.drift",
            PlatformAction::CopyText,
            "clipboard.primary",
            &second_payload,
            view.revision,
        )
        .unwrap();
    let second_grant = signed_grant(second_binding, "nonce.second", &key);
    runtime.allow_once(PlatformAction::CopyText);
    let error = runtime
        .request_platform_capability(
            "operation.drift",
            PlatformAction::CopyText,
            "clipboard.primary",
            &second_payload,
            view.revision,
            &second_grant,
        )
        .unwrap_err();
    assert!(error.to_string().contains("reused"));
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn tampered_grant_is_terminally_rejected_without_invocation() {
    let root = root("grant-tamper");
    std::fs::create_dir_all(&root).unwrap();
    let key = SigningKey::from_bytes(&[10_u8; 32]);
    let state = Arc::new(Mutex::new(PlatformState::default()));
    let mut runtime = shell(&root, 4, Arc::clone(&state), true, false, &key);
    runtime.connect(&manifest()).unwrap();
    let view = runtime.refresh_view().unwrap();
    let payload = PlatformPayload::Text {
        text: "trusted".to_string(),
    };
    let binding = runtime
        .prepare_binding(
            "operation.tampered",
            PlatformAction::CopyText,
            "clipboard.primary",
            &payload,
            view.revision,
        )
        .unwrap();
    let mut grant = signed_grant(binding, "nonce.tampered", &key);
    grant.grant.binding.payload_digest = "2".repeat(64);
    runtime.allow_once(PlatformAction::CopyText);
    let decision = runtime
        .request_platform_capability(
            "operation.tampered",
            PlatformAction::CopyText,
            "clipboard.primary",
            &payload,
            view.revision,
            &grant,
        )
        .unwrap();
    assert_eq!(decision.status, DecisionStatus::Rejected);
    assert_eq!(state.lock().unwrap().invokes, 0);
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn reused_operation_with_changed_resource_fails_closed() {
    let root = root("resource-drift");
    std::fs::create_dir_all(&root).unwrap();
    let key = SigningKey::from_bytes(&[13_u8; 32]);
    let state = Arc::new(Mutex::new(PlatformState::default()));
    let mut runtime = shell(&root, 5, Arc::clone(&state), true, false, &key);
    runtime.connect(&manifest()).unwrap();
    let view = runtime.refresh_view().unwrap();
    let payload = PlatformPayload::Text {
        text: "same payload".to_string(),
    };

    let first_binding = runtime
        .prepare_binding(
            "operation.resource",
            PlatformAction::CopyText,
            "clipboard.primary",
            &payload,
            view.revision,
        )
        .unwrap();
    let first_grant = signed_grant(first_binding, "nonce.resource.first", &key);
    runtime.allow_once(PlatformAction::CopyText);
    runtime
        .request_platform_capability(
            "operation.resource",
            PlatformAction::CopyText,
            "clipboard.primary",
            &payload,
            view.revision,
            &first_grant,
        )
        .unwrap();

    let second_binding = runtime
        .prepare_binding(
            "operation.resource",
            PlatformAction::CopyText,
            "clipboard.secondary",
            &payload,
            view.revision,
        )
        .unwrap();
    let second_grant = signed_grant(second_binding, "nonce.resource.second", &key);
    runtime.allow_once(PlatformAction::CopyText);
    let error = runtime
        .request_platform_capability(
            "operation.resource",
            PlatformAction::CopyText,
            "clipboard.secondary",
            &payload,
            view.revision,
            &second_grant,
        )
        .unwrap_err();
    assert!(error.to_string().contains("reused"));
    assert_eq!(state.lock().unwrap().invokes, 1);
    let _ = std::fs::remove_dir_all(root);
}

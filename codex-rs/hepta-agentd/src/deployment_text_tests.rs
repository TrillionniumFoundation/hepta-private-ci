use super::*;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use pretty_assertions::assert_eq;

pub(super) fn identity(root: &Path) -> AgentdIdentity {
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let fleet = codex_hepta_paths::HeptaFleetRoot::parse(root.join("fleet")).unwrap();
    let layout = fleet.layout().agent(&agent_id);
    AgentdIdentity {
        agent_id,
        spawn_generation: 1,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace: root.to_path_buf(),
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
        layout,
    }
}

pub(super) fn body() -> AuthBusTextBody {
    AuthBusTextBody {
        spawn_generation: 1,
        thread_id: "thread-one".into(),
        text: "真实输入，保留同一身份".into(),
    }
}

pub(super) fn issuer(path: &Path, owner: &AgentdIdentity) -> DeploymentFinalUseIssuer {
    DeploymentFinalUseIssuer::create(
        path,
        "original-owner".into(),
        vec![DeploymentGrantPolicy {
            subject_id: owner.agent_id.to_string(),
            destination_id: DeploymentFinalUseIssuer::text_destination("thread-one").unwrap(),
            scope_sha256: DeploymentFinalUseIssuer::text_scope(&owner.agent_id),
            lifetime_ms: 30_000,
        }],
        Arc::new(SystemAuthorityClock),
    )
    .unwrap()
}

#[test]
fn retained_text_signature_uses_original_key_store_and_sequence_after_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let owner = identity(directory.path());
    let path = directory.path().join("issuer");
    let original = issuer(&path, &owner);
    let first = original
        .text(&owner, "input:1", body(), TextIssuerOperation::Sign)
        .unwrap();
    let public = original.trust_key().unwrap();
    let status = original.store.load(STATE_OWNER).unwrap();
    assert_eq!(status.sequence, 1);
    drop(original);
    let original = DeploymentFinalUseIssuer::open(&path, Arc::new(SystemAuthorityClock)).unwrap();
    assert_eq!(
        original
            .text(&owner, "input:1", body(), TextIssuerOperation::Lookup)
            .unwrap(),
        first
    );
    assert_eq!(
        original
            .text(&owner, "input:1", body(), TextIssuerOperation::Sign)
            .unwrap(),
        first
    );
    assert_eq!(original.store.load(STATE_OWNER).unwrap().sequence, 1);
    let claims = crate::authbus_text_claims(&owner.agent_id, &first).unwrap();
    let message = SignedMessage {
        claims,
        signature: crate::authbus_trust::hex_bytes(&first.signature_hex).unwrap(),
    };
    let registration = IssuerRegistration {
        issuer_id: StableId::new(&first.issuer_id).unwrap(),
        key_epoch: Generation::new(first.key_epoch).unwrap(),
        verifying_key: VerifyingKey::from_bytes(&public.verifying_key).unwrap(),
        revoked: false,
    };
    assert!(
        message
            .authenticate(
                &registration,
                message.claims.scope_digest,
                message.claims.payload_digest,
                SystemAuthorityClock.now_unix_ms().unwrap()
            )
            .is_ok()
    );
    let second = original
        .text(&owner, "input:2", body(), TextIssuerOperation::Sign)
        .unwrap();
    assert_eq!(second.sequence, first.sequence + 1);
    assert_ne!(second.message_id, first.message_id);
}

#[test]
fn missing_lookup_and_scope_conflict_do_not_sign_or_consume_sequence() {
    let directory = tempfile::tempdir().unwrap();
    let owner = identity(directory.path());
    let issuer = issuer(&directory.path().join("issuer"), &owner);
    assert_eq!(
        issuer
            .text(&owner, "missing:1", body(), TextIssuerOperation::Lookup)
            .unwrap_err()
            .kind(),
        io::ErrorKind::NotFound
    );
    assert_eq!(issuer.store.load(STATE_OWNER).unwrap().sequence, 0);
    let original = issuer
        .text(&owner, "same:1", body(), TextIssuerOperation::Sign)
        .unwrap();
    let mut changed = body();
    changed.text = "different".into();
    assert!(
        issuer
            .text(&owner, "same:1", changed, TextIssuerOperation::Sign)
            .is_err()
    );
    let mut wrong = body();
    wrong.thread_id = "thread-two".into();
    assert!(
        issuer
            .text(&owner, "other:2", wrong, TextIssuerOperation::Sign)
            .is_err()
    );
    let mut newer = owner.clone();
    newer.spawn_generation = 2;
    let mut request = body();
    request.spawn_generation = 2;
    assert_eq!(
        issuer
            .text(&newer, "same:1", request, TextIssuerOperation::Lookup)
            .unwrap(),
        original
    );
    assert_eq!(issuer.store.load(STATE_OWNER).unwrap().sequence, 1);
}

#[test]
fn full_retention_refuses_new_identity_without_eviction_or_new_signature() {
    let directory = tempfile::tempdir().unwrap();
    let owner = identity(directory.path());
    let issuer = issuer(&directory.path().join("issuer"), &owner);
    for number in 1..=MAX_TEXT_SIGNATURES {
        issuer
            .text(
                &owner,
                &format!("input:{number}"),
                body(),
                TextIssuerOperation::Sign,
            )
            .unwrap();
    }
    let retained = issuer
        .text(&owner, "input:1", body(), TextIssuerOperation::Lookup)
        .unwrap();
    assert!(
        issuer
            .text(&owner, "input:33", body(), TextIssuerOperation::Sign)
            .is_err()
    );
    assert_eq!(
        issuer
            .text(&owner, "input:1", body(), TextIssuerOperation::Lookup)
            .unwrap(),
        retained
    );
    assert_eq!(
        issuer.store.load(STATE_OWNER).unwrap().sequence,
        MAX_TEXT_SIGNATURES as u64
    );
}

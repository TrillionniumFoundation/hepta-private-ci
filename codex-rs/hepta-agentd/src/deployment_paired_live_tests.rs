//! Actual temporary Registry/signature CAS and pidfds, synthetic human scope.
//! These controls never authenticate a real human or read training material.
use super::*;
use crate::AuthBusTextBody;
use crate::authority_host_service::SyntheticOriginalHuman;
use crate::deployment_issuer::RootHumanTextRequest;
use pretty_assertions::assert_eq;

pub(super) fn original() -> (
    Fixture,
    AgentdIdentity,
    SyntheticOriginalHuman,
    AuthBusTextIngress,
) {
    let mut f = Fixture::new();
    let route = &f.registration.original_route;
    let fleet = codex_hepta_paths::HeptaFleetRoot::parse(f.directory.path().join("fleet")).unwrap();
    let layout = fleet.layout().agent(&f.writer.registered_agent_id);
    let identity = AgentdIdentity {
        agent_id: f.writer.registered_agent_id.clone(),
        spawn_generation: f.writer.spawn_generation,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace: f.directory.path().to_path_buf(),
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
        home_root: route.codex_home.clone(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: route.control_socket.clone(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
        layout,
    };
    let human = SyntheticOriginalHuman::new(
        route.clone(),
        f.registration.preparation.principal_id.clone(),
        f.registration.permission_revision,
        f.registration.human_expires_at_ms,
    )
    .unwrap();
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    let mut changed = state.clone();
    changed.policies.push(DeploymentGrantPolicy {
        subject_id: identity.agent_id.to_string(),
        destination_id: DeploymentFinalUseIssuer::text_destination(&route.thread_id).unwrap(),
        scope_sha256: DeploymentFinalUseIssuer::text_scope(&identity.agent_id),
        lifetime_ms: 1_000,
    });
    f.issuer
        .store
        .compare_and_set(STATE_OWNER, &state, &changed)
        .unwrap();
    let (binding, namespace) = {
        let held = human
            .lifetime(Instant::now() + Duration::from_secs(2))
            .unwrap();
        (held.binding(), held.namespace())
    };
    let request_id = format!("{namespace}:1");
    let ingress = f
        .issuer
        .registered_writer_human_text(
            &identity,
            RootHumanTextRequest {
                request_id: &request_id,
                body: AuthBusTextBody {
                    spawn_generation: identity.spawn_generation,
                    thread_id: route.thread_id.clone(),
                    text: f
                        .registration
                        .request
                        .original
                        .usage
                        .consent_text(f.registration.preparation.study),
                },
                operation: TextIssuerOperation::Sign,
                human: &binding,
            },
            &f.writer,
            &f.registry.verifier(),
            &f.issuer.retained_writer_authorization(&f.writer).unwrap(),
        )
        .unwrap();
    let message = codex_hepta_authbus::SignedMessage {
        claims: crate::authbus_text_claims(&identity.agent_id, &ingress).unwrap(),
        signature: crate::authbus_trust::hex_bytes(&ingress.signature_hex).unwrap(),
    };
    f.registration.request.original.delivery_id = message.delivery_id();
    let (enrollment, effect, _) = f.registration.bindings(&f.writer).unwrap();
    assert_eq!(
        f.registry
            .read_lease(&f.registration.enrollment_id().unwrap())
            .unwrap()
            .unwrap()
            .lease
            .binding,
        enrollment
    );
    f.registry
        .put_lease(
            AuthorityLease {
                lease_id: f.registration.effect_id(),
                binding: effect,
                expires_at_unix_ms: 15_000,
                ..f.writer.authority_lease.clone()
            },
            /*expected_revision*/ 0,
        )
        .unwrap();
    (f, identity, human, ingress)
}

#[test]
fn paired_root_live_original_signature_and_four_records_are_read_only() {
    let (f, identity, human, ingress) = original();
    let owner = f.open(f.registration.clone()).unwrap();
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    let frontier = f.registry.frontier().unwrap();
    let held = human
        .lifetime(Instant::now() + Duration::from_secs(2))
        .unwrap();
    assert_eq!(
        owner
            .observe_original_human(&identity, &ingress, &held)
            .unwrap(),
        owner.observe().unwrap()
    );
    assert!(f.issuer.store.load(STATE_OWNER).unwrap() == state);
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

#[test]
fn paired_root_live_changed_delivery_or_principal_has_no_new_effect() {
    let (f, mut identity, human, ingress) = original();
    let owner = f.open(f.registration.clone()).unwrap();
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    let frontier = f.registry.frontier().unwrap();
    let held = human
        .lifetime(Instant::now() + Duration::from_secs(2))
        .unwrap();
    let mut changed = ingress.clone();
    changed.body.text.push('!');
    assert!(
        owner
            .observe_original_human(&identity, &changed, &held)
            .is_err()
    );
    changed = ingress.clone();
    let replacement = if changed.signature_hex.starts_with("00") {
        "01"
    } else {
        "00"
    };
    changed.signature_hex.replace_range(..2, replacement);
    assert!(
        owner
            .observe_original_human(&identity, &changed, &held)
            .is_err()
    );
    identity.spawn_generation += 1;
    assert!(
        owner
            .observe_original_human(&identity, &ingress, &held)
            .is_err()
    );
    identity.spawn_generation -= 1;
    let another = SyntheticOriginalHuman::new(
        f.registration.original_route.clone(),
        "another-person".into(),
        /*permission_revision*/ 1,
        f.registration.human_expires_at_ms,
    )
    .unwrap();
    let another = another
        .lifetime(Instant::now() + Duration::from_secs(2))
        .unwrap();
    assert!(
        owner
            .observe_original_human(&identity, &ingress, &another)
            .is_err()
    );
    assert!(f.issuer.store.load(STATE_OWNER).unwrap() == state);
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

#[test]
fn paired_root_live_same_locked_state_rechecks_current_text_policy() {
    let (f, identity, human, ingress) = original();
    let owner = f.open(f.registration.clone()).unwrap();
    let held = human
        .lifetime(Instant::now() + Duration::from_secs(2))
        .unwrap();
    let guard = f.issuer.request_lock.lock().unwrap();
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    assert_eq!(
        state
            .verify_retained_human_text_at(
                &identity,
                &ingress,
                &held.binding(),
                &held.namespace(),
                /*now*/ 10_000
            )
            .unwrap(),
        ingress.expires_at_ms
    );
    let mut changed = state.clone();
    let destination = DeploymentFinalUseIssuer::text_destination(&ingress.body.thread_id).unwrap();
    changed
        .policies
        .retain(|policy| policy.destination_id != destination);
    f.issuer
        .store
        .compare_and_set(STATE_OWNER, &state, &changed)
        .unwrap();
    drop(guard);
    let frontier = f.registry.frontier().unwrap();
    owner.observe().unwrap();
    assert!(
        owner
            .observe_original_human(&identity, &ingress, &held)
            .is_err()
    );
    assert!(f.issuer.store.load(STATE_OWNER).unwrap() == changed);
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

#[test]
fn paired_root_live_retained_signature_expiry_survives_reopen() {
    let (f, identity, human, ingress) = original();
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    let frontier = f.registry.frontier().unwrap();
    f.clock.0.store(ingress.expires_at_ms, Ordering::SeqCst);
    let f = f.reopen();
    let owner = f.open(f.registration.clone()).unwrap();
    owner.observe().unwrap();
    let held = human
        .lifetime(Instant::now() + Duration::from_secs(2))
        .unwrap();
    assert!(
        owner
            .observe_original_human(&identity, &ingress, &held)
            .is_err()
    );
    assert!(f.issuer.store.load(STATE_OWNER).unwrap() == state);
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

#[test]
fn paired_root_live_revoked_enrollment_refuses_retained_human_signature() {
    let (f, identity, human, ingress) = original();
    let owner = f.open(f.registration.clone()).unwrap();
    let held = human
        .lifetime(Instant::now() + Duration::from_secs(2))
        .unwrap();
    owner
        .observe_original_human(&identity, &ingress, &held)
        .unwrap();
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    f.registry
        .revoke(
            &f.registration.enrollment_id().unwrap(),
            /*expected_revision*/ 1,
            [8; 32],
        )
        .unwrap();
    let frontier = f.registry.frontier().unwrap();
    assert!(
        owner
            .observe_original_human(&identity, &ingress, &held)
            .is_err()
    );
    assert!(f.issuer.store.load(STATE_OWNER).unwrap() == state);
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

//! Actual canonical AuthBus Objective signature, retaining the original fixture.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn objective_independent_issuer_revocation_refuses_new_canonical_signature() {
    let mut f = WriterFixture::new();
    let parent = AuthorityLease {
        lease_id: "independent-objective-issuer".into(),
        expires_at_unix_ms: 30_000,
        binding: AuthorityLeaseBinding {
            operation_class: "runtime.agentd.root_issuer".into(),
            destination_id: "canonical-objective-issuer".into(),
            ..f.registration.authority_lease.binding.clone()
        },
        ..f.registration.authority_lease
    };
    f.leases.put_lease(parent.clone(), 0).unwrap();
    // The original registered fixture initially aliases issuer and writer.
    // Retain its same key/store/registry/proof and install a distinct original
    // parent as actual Root's independent issuer/writer configuration does.
    f.base.issuer.lease = Some(
        crate::deployment_issuer::ProtectedLease::new(
            f.leases.verifier(),
            parent.lease_id.clone(),
            parent.revision,
        )
        .unwrap(),
    );
    let signed = f.sign().unwrap();
    let message = signed_message(&f.base, &signed);
    let trust = f.base.issuer.trust_key().unwrap();
    message
        .authenticate(
            &IssuerRegistration {
                issuer_id: message.claims.issuer_id.clone(),
                key_epoch: message.claims.key_epoch,
                verifying_key: VerifyingKey::from_bytes(&trust.verifying_key).unwrap(),
                revoked: false,
            },
            objective_scope(f.base.config.identity()),
            message.claims.payload_digest,
            10_000,
        )
        .unwrap();
    f.leases.revoke(&parent.lease_id, 1, [8; 32]).unwrap();
    assert!(f.base.issuer.with_live_lease(|_| Ok(())).is_err());
    f.registration.with_live(&f.leases.verifier(), |_| Ok(())).unwrap();
    let before = serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = f.leases.frontier().unwrap();
    assert!(
        f.sign().is_err(),
        "AuthBus must not sign a new Objective after its independent canonical issuer was revoked"
    );
    assert_eq!(
        serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(f.leases.frontier().unwrap(), frontier);
}

fn original_registered_text_fixture(parent_id: &str) -> (WriterFixture, AuthorityLease) {
    let mut f = WriterFixture::new();
    let parent = AuthorityLease {
        lease_id: parent_id.into(),
        expires_at_unix_ms: 30_000,
        binding: AuthorityLeaseBinding {
            operation_class: "runtime.agentd.root_issuer".into(),
            destination_id: "canonical-text-issuer".into(),
            ..f.registration.authority_lease.binding.clone()
        },
        ..f.registration.authority_lease
    };
    f.leases.put_lease(parent.clone(), 0).unwrap();
    f.base.issuer.lease = Some(
        crate::deployment_issuer::ProtectedLease::new(
            f.leases.verifier(),
            parent.lease_id.clone(),
            parent.revision,
        )
        .unwrap(),
    );
    // As in the original issuer policy tests, install only this exact test
    // route in the SAME durable owner before entering the production method.
    // This does not substitute a new issuer key, registry, writer or proof.
    let current = f.base.issuer.store.load(STATE_OWNER).unwrap();
    let mut next = current.clone();
    next.policies.push(DeploymentGrantPolicy {
        subject_id: f.base.config.identity().agent_id.to_string(),
        destination_id: DeploymentFinalUseIssuer::text_destination("thread-one").unwrap(),
        scope_sha256: DeploymentFinalUseIssuer::text_scope(&f.base.config.identity().agent_id),
        lifetime_ms: 30_000,
    });
    f.base
        .issuer
        .store
        .compare_and_set(STATE_OWNER, &current, &next)
        .unwrap();
    (f, parent)
}

fn original_text_body(f: &WriterFixture) -> crate::AuthBusTextBody {
    crate::AuthBusTextBody {
        spawn_generation: f.base.config.identity().spawn_generation,
        thread_id: "thread-one".into(),
        text: "original registered text after issuer revocation".into(),
    }
}

fn authenticate_original_text(f: &WriterFixture, signed: &crate::AuthBusTextIngress) {
    let message = SignedMessage {
        claims: crate::authbus_text_claims(&f.base.config.identity().agent_id, signed).unwrap(),
        signature: crate::authbus_trust::hex_bytes(&signed.signature_hex).unwrap(),
    };
    let trust = f.base.issuer.trust_key().unwrap();
    message
        .authenticate(
            &IssuerRegistration {
                issuer_id: message.claims.issuer_id.clone(),
                key_epoch: message.claims.key_epoch,
                verifying_key: VerifyingKey::from_bytes(&trust.verifying_key).unwrap(),
                revoked: false,
            },
            message.claims.scope_digest,
            message.claims.payload_digest,
            10_000,
        )
        .unwrap();
}

#[test]
fn text_independent_issuer_revocation_refuses_new_canonical_signature() {
    use crate::deployment_issuer::TextIssuerOperation;

    let (f, parent) = original_registered_text_fixture("independent-text-issuer");
    let text = |request_id: &str, operation| {
        f.base.issuer.registered_writer_text(
            f.base.config.identity(),
            request_id,
            original_text_body(&f),
            operation,
            crate::deployment_issuer::RegisteredTextWriterAuthority {
                registration: &f.registration,
                leases: &f.leases.verifier(),
                proof: &f.proof,
            },
        )
    };
    let signed = text("followup-text:1", TextIssuerOperation::Sign).unwrap();
    authenticate_original_text(&f, &signed);
    f.leases.revoke(&parent.lease_id, 1, [8; 32]).unwrap();
    assert!(f.base.issuer.with_live_lease(|_| Ok(())).is_err());
    f.registration.with_live(&f.leases.verifier(), |_| Ok(())).unwrap();
    let before = serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = f.leases.frontier().unwrap();
    assert!(
        text("followup-text:2", TextIssuerOperation::Sign).is_err(),
        "Text must not create a new canonical signature after its independent issuer was revoked"
    );
    // An exact retained readback neither signs nor grants new authority.
    assert_eq!(text("followup-text:1", TextIssuerOperation::Lookup).unwrap(), signed);
    assert_eq!(text("followup-text:1", TextIssuerOperation::Sign).unwrap(), signed);
    assert_eq!(
        serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(f.leases.frontier().unwrap(), frontier);
}

#[test]
fn human_text_independent_issuer_revocation_refuses_new_canonical_signature() {
    use crate::deployment_issuer::RootHumanTextRequest;
    use crate::deployment_issuer::TextHumanBinding;
    use crate::deployment_issuer::TextIssuerOperation;

    let (f, parent) = original_registered_text_fixture("independent-human-text-issuer");
    let owner = f.base.config.identity();
    // The original human-text fixture's typed binding, using this SAME
    // registered owner and clock. This unit case does not authenticate a
    // physical login; the production Root UI lane supplies that provenance.
    let human = TextHumanBinding {
        principal_id: "test-human".into(),
        session_id: "test-original-login".into(),
        permission_revision: 1,
        expires_at_ms: 14_000,
        route: crate::text_session::AgentdTextSessionConfig {
            agent_id: owner.agent_id.clone(),
            spawn_generation: owner.spawn_generation,
            control_socket: owner.control_socket.clone(),
            codex_home: owner.home_root.clone(),
            thread_id: "thread-one".into(),
            app_server_session_id: "test-original-session".into(),
        },
    };
    let text = |request_id: &str, operation| {
        f.base.issuer.registered_writer_human_text(
            owner,
            RootHumanTextRequest {
                request_id,
                body: original_text_body(&f),
                operation,
                human: &human,
            },
            &f.registration,
            &f.leases.verifier(),
            &f.proof,
        )
    };
    let signed = text("followup-human:1", TextIssuerOperation::Sign).unwrap();
    authenticate_original_text(&f, &signed);
    f.base
        .issuer
        .verify_retained_human_text(owner, &signed, &human, "followup-human")
        .unwrap();
    assert_eq!(signed.expires_at_ms, human.expires_at_ms);
    f.leases.revoke(&parent.lease_id, 1, [8; 32]).unwrap();
    assert!(f.base.issuer.with_live_lease(|_| Ok(())).is_err());
    f.registration.with_live(&f.leases.verifier(), |_| Ok(())).unwrap();
    let before = serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = f.leases.frontier().unwrap();
    assert!(
        text("followup-human:2", TextIssuerOperation::Sign).is_err(),
        "Human Text must not create a new canonical signature after its independent issuer was revoked"
    );
    assert_eq!(text("followup-human:1", TextIssuerOperation::Lookup).unwrap(), signed);
    assert_eq!(text("followup-human:1", TextIssuerOperation::Sign).unwrap(), signed);
    assert_eq!(
        serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(f.leases.frontier().unwrap(), frontier);
}

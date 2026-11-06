//! Original disk/key/proof fixtures exercise actual final-signature deadlines.
use super::*;
use crate::deployment_issuer::RootHumanTextRequest;
use crate::deployment_issuer::TextHumanBinding;
use crate::deployment_issuer::TextIssuerOperation;
use pretty_assertions::assert_eq;

fn fixture(parent_expiry: u64) -> WriterFixture {
    let mut f = WriterFixture::new();
    let parent = AuthorityLease {
        lease_id: "independent-final-signature-issuer".into(),
        expires_at_unix_ms: parent_expiry,
        binding: AuthorityLeaseBinding {
            operation_class: "runtime.agentd.root_issuer".into(),
            destination_id: "canonical-final-signature-issuer".into(),
            ..f.registration.authority_lease.binding.clone()
        },
        ..f.registration.authority_lease
    };
    f.leases.put_lease(parent.clone(), 0).unwrap();
    f.base.issuer.lease = Some(
        crate::deployment_issuer::ProtectedLease::new(
            f.leases.verifier(),
            parent.lease_id,
            parent.revision,
        )
        .unwrap(),
    );
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
    f
}

fn text(
    f: &WriterFixture,
    human: bool,
    request: &str,
    operation: TextIssuerOperation,
) -> io::Result<crate::AuthBusTextIngress> {
    let owner = f.base.config.identity();
    let body = crate::AuthBusTextBody {
        spawn_generation: owner.spawn_generation,
        thread_id: "thread-one".into(),
        text: "same original signed text identity".into(),
    };
    if !human {
        return f.base.issuer.registered_writer_text(
            owner,
            request,
            body,
            operation,
            crate::deployment_issuer::RegisteredTextWriterAuthority {
                registration: &f.registration,
                leases: &f.leases.verifier(),
                proof: &f.proof,
            },
        );
    }
    // Original typed human fixture only; no physical login is claimed.
    let binding = TextHumanBinding {
        principal_id: "test-human".into(),
        session_id: "test-original-login".into(),
        permission_revision: 1,
        expires_at_ms: 20_000,
        route: crate::text_session::AgentdTextSessionConfig {
            agent_id: owner.agent_id.clone(),
            spawn_generation: owner.spawn_generation,
            control_socket: owner.control_socket.clone(),
            codex_home: owner.home_root.clone(),
            thread_id: body.thread_id.clone(),
            app_server_session_id: "test-original-session".into(),
        },
    };
    f.base.issuer.registered_writer_human_text(
        owner,
        RootHumanTextRequest {
            request_id: request,
            body,
            operation,
            human: &binding,
        },
        &f.registration,
        &f.leases.verifier(),
        &f.proof,
    )
}

fn sign(f: &WriterFixture, route: u8, request: &str) -> io::Result<u64> {
    if route == 0 {
        let signed = f.sign()?;
        let message = signed_message(&f.base, &signed);
        let trust = f.base.issuer.trust_key()?;
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
        Ok(signed.expires_at_ms)
    } else {
        let signed = text(f, route == 2, request, TextIssuerOperation::Sign)?;
        let claims = crate::authbus_text_claims(&f.base.config.identity().agent_id, &signed).unwrap();
        VerifyingKey::from_bytes(&f.base.issuer.trust_key()?.verifying_key)
            .unwrap()
            .verify_strict(
                &claims.signing_bytes(),
                &ed25519_dalek::Signature::from_bytes(
                    &crate::authbus_trust::hex_bytes(&signed.signature_hex).unwrap(),
                ),
            )
            .unwrap();
        Ok(signed.expires_at_ms)
    }
}

#[test]
fn registered_objective_text_and_human_signatures_cap_parent_and_refuse_new_use_after_expiry() {
    for route in 0..3 {
        let f = fixture(12_000);
        assert_eq!(sign(&f, route, "deadline:1").unwrap(), 12_000);
        f.base.clock.now.store(12_000, Ordering::SeqCst);
        assert!(f.base.issuer.with_live_lease(|_| Ok(())).is_err());
        f.registration.with_live(&f.leases.verifier(), |_| Ok(())).unwrap();
        let before = serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
        assert!(sign(&f, route, "deadline:2").is_err());
        assert_eq!(
            serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
            before
        );
    }
}

#[test]
fn original_five_clock_samples_keep_post_io_expiry_consumed_and_text_history_exact() {
    for route in 0..3 {
        let f = fixture(14_900);
        f.base.clock.step.store(1_500, Ordering::SeqCst);
        // Original token verify, same-owner entry, retained proof, pre-sign,
        // post-I/O. Parent is live at 14_500 and expired at 16_000.
        assert!(sign(&f, route, "late:1").is_err());
        assert_eq!(f.base.clock.now.load(Ordering::SeqCst), 17_500);
        assert_eq!(f.base.sequence(), 2);
        if route == 0 {
            continue;
        }
        f.base.clock.step.store(0, Ordering::SeqCst);
        f.base.clock.now.store(14_900, Ordering::SeqCst);
        let before = serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
        let retained = text(&f, route == 2, "late:1", TextIssuerOperation::Lookup).unwrap();
        assert_eq!((retained.sequence, retained.expires_at_ms), (2, 14_900));
        assert_eq!(text(&f, route == 2, "late:1", TextIssuerOperation::Sign).unwrap(), retained);
        assert!(text(&f, route == 2, "late:2", TextIssuerOperation::Sign).is_err());
        assert_eq!(
            serde_json::to_value(f.base.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
            before
        );
    }
}

#[test]
fn protected_objective_compatibility_entry_cannot_bypass_original_writer_registration() {
    let f = WriterFixture::new();
    let before = f.base.sequence();
    assert!(
        f.base.issuer.sign_objective(f.base.config.identity(), f.base.body()).is_err(),
        "A protected issuer must require its original registered Objective entry"
    );
    assert_eq!(f.base.sequence(), before);
    assert_eq!(f.sign().unwrap().sequence, before + 1);
}

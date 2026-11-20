use super::*;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

struct WriterFixture {
    base: Fixture,
    leases: AuthorityLeaseRegistry,
    registration: crate::HostAuthorityWriterRegistration,
    proof: crate::HostSignedWriterAuthorizationV1,
}
impl WriterFixture {
    fn new() -> Self {
        let mut base = Fixture::new();
        let path = base.root.path().join("original-writer-leases");
        std::fs::create_dir(&path).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        let leases = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &path,
            "original-writer-owner".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            base.clock.clone(),
        )
        .unwrap();
        let registration = crate::HostAuthorityWriterRegistration {
            registered_agent_id: base.config.identity().agent_id.clone(),
            spawn_generation: base.config.identity().spawn_generation,
            owner_epoch: 3,
            local_lease_id: "local-writer".into(),
            local_lease_generation: 1,
            authority_lease: AuthorityLease {
                schema_version: 1,
                lease_id: "actual-writer".into(),
                revision: 1,
                authority_epoch: 1,
                binding: AuthorityLeaseBinding {
                    principal_id: base.config.identity().agent_id.to_string(),
                    operation_class: "runtime.agentd.production_writer".into(),
                    destination_id: "original-cognitive-owner".into(),
                    scope_sha256: [4; 32],
                    payload_sha256: [5; 32],
                },
                issued_at_unix_ms: 10_000,
                expires_at_unix_ms: 15_000,
            },
        };
        leases
            .put_lease(registration.authority_lease.clone(), 0)
            .unwrap();
        // Unit fixture only; deployed construction requires the original root factory.
        base.issuer.lease = Some(
            crate::deployment_issuer::ProtectedLease::new(
                leases.verifier(),
                "actual-writer".into(),
                1,
            )
            .unwrap(),
        );
        let proof = base
            .issuer
            .register_writer_authorization(&registration, &leases.verifier())
            .unwrap();
        Self {
            base,
            leases,
            registration,
            proof,
        }
    }
    fn sign(&self) -> io::Result<AuthBusObjectiveIngress> {
        self.base.issuer.sign_registered_writer_objective(
            self.base.config.identity(),
            self.base.body(),
            &self.registration,
            &self.leases.verifier(),
            &self.proof,
        )
    }
}

#[test]
fn deployment_writer_objective_uses_original_claims_and_caps_expiry_to_the_live_lease() {
    let fixture = WriterFixture::new();
    let signed = fixture.sign().unwrap();
    assert_eq!((signed.sequence, signed.expires_at_ms), (2, 15_000));
    let message = signed_message(&fixture.base, &signed);
    let trust = fixture.base.issuer.trust_key().unwrap();
    let registration = IssuerRegistration {
        issuer_id: message.claims.issuer_id.clone(),
        key_epoch: message.claims.key_epoch,
        verifying_key: VerifyingKey::from_bytes(&trust.verifying_key).unwrap(),
        revoked: false,
    };
    assert!(
        message
            .authenticate(
                &registration,
                objective_scope(fixture.base.config.identity()),
                message.claims.payload_digest,
                10_000
            )
            .is_ok()
    );
    assert_eq!(fixture.base.sequence(), 2);
}

#[test]
fn deployment_writer_objective_refuses_revoked_or_changed_exact_lease_before_sequence() {
    let fixture = WriterFixture::new();
    fixture
        .leases
        .put_lease(
            AuthorityLease {
                revision: 2,
                expires_at_unix_ms: 14_000,
                ..fixture.registration.authority_lease.clone()
            },
            1,
        )
        .unwrap();
    assert!(fixture.sign().is_err());
    assert_eq!(fixture.base.sequence(), 1);
    let fixture = WriterFixture::new();
    fixture.leases.revoke("actual-writer", 1, [8; 32]).unwrap();
    assert!(fixture.sign().is_err());
    assert_eq!(fixture.base.sequence(), 1);
}

#[test]
fn deployment_writer_objective_discards_post_io_expiry_without_reusing_sequence() {
    let fixture = WriterFixture::new();
    // Original verify/dispatch, proof read, pre-sign sample, post-reservation.
    fixture.base.clock.step.store(1_500, Ordering::SeqCst);
    assert!(fixture.sign().is_err());
    assert_eq!(fixture.base.sequence(), 2);
    fixture.base.clock.now.store(10_000, Ordering::SeqCst);
    fixture.base.clock.step.store(0, Ordering::SeqCst);
    assert_eq!(fixture.sign().unwrap().sequence, 3);
}

#[test]
fn deployment_writer_objective_refuses_wrong_proof_or_spawn_before_sequence() {
    let mut fixture = WriterFixture::new();
    let changed = if fixture.proof.signature_hex.starts_with("00") {
        "01"
    } else {
        "00"
    };
    fixture.proof.signature_hex.replace_range(..2, changed);
    assert!(fixture.sign().is_err());
    assert_eq!(fixture.base.sequence(), 1);
    let mut fixture = WriterFixture::new();
    fixture.registration.spawn_generation += 1;
    assert!(fixture.sign().is_err());
    assert_eq!(fixture.base.sequence(), 1);
}

//! Synthetic scope and content, real retained signatures, Registry CAS and
//! pidfd-bound test sockets. Only the production-entry refusal tests Root UID;
//! positive component controls do not claim a physical human or Core turn.
use super::*;
use crate::RootPairedTrainingPlanV1;
use crate::deployment_issuer::OriginalPairedTrainingAdmission;
use crate::deployment_issuer::RootHumanTextRequest;
use crate::paired_preparation::material_protocol::PairedTrainingReadRequest;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;

#[derive(Clone, Copy)]
enum Entry {
    Component,
    ActualRootFactory,
    ExpiredFrame,
}

fn fresh() -> TrainingFixture {
    let mut f = TrainingFixture::new();
    let held = f
        .human
        .lifetime(Instant::now() + Duration::from_secs(2))
        .unwrap();
    let binding = held.binding();
    let request_id = format!("{}:2", held.namespace());
    f.ingress = f
        .original
        .issuer
        .registered_writer_human_text(
            &f.identity,
            RootHumanTextRequest {
                request_id: &request_id,
                body: f.ingress.body.clone(),
                operation: TextIssuerOperation::Sign,
                human: &binding,
            },
            &f.original.writer,
            &f.original.registry.verifier(),
            &f.original
                .issuer
                .retained_writer_authorization(&f.original.writer)
                .unwrap(),
        )
        .unwrap();
    let message = codex_hepta_authbus::SignedMessage {
        claims: crate::authbus_text_claims(&f.identity.agent_id, &f.ingress).unwrap(),
        signature: crate::authbus_trust::hex_bytes(&f.ingress.signature_hex).unwrap(),
    };
    f.original.registration.request.original.delivery_id = message.delivery_id();
    f.original.registration.effect_revision = 1;
    assert!(
        f.original
            .registry
            .read_lease(&f.original.registration.effect_id())
            .unwrap()
            .is_none()
    );
    f
}

fn plan(f: &TrainingFixture) -> RootPairedTrainingPlanV1 {
    RootPairedTrainingPlanV1 {
        training: crate::PairedTrainingPlanV1 {
            preparation: f.original.registration.preparation.clone(),
            manifest: f.manifest.clone(),
            operation: f.original.registration.request.operation,
        },
        enrollment_revision: f.original.registration.enrollment_revision,
        effect_lifetime_ms: f.original.registration.effect_lifetime_ms,
    }
}

fn attempt(
    f: &TrainingFixture,
    plan: &RootPairedTrainingPlanV1,
    raw: &[u8],
    entry: Entry,
) -> io::Result<RegisteredRootPaired> {
    let (mut server, _client) = f.channel(raw);
    let mut outcome = None;
    let exchange = server.exchange_with_original_response(|raw, response| {
        let request = PairedTrainingReadRequest::decode(raw)
            .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
        let held = f
            .human
            .lifetime(response.current().deadline())
            .map_err(|_| HostIssuerTransportError::Unavailable)?;
        if matches!(entry, Entry::ExpiredFrame) {
            std::thread::sleep(Duration::from_millis(1_050));
        }
        let original = OriginalPairedTrainingAdmission {
            identity: &f.identity,
            request: &request,
            held: &held,
            response,
        };
        outcome = Some(match entry {
            Entry::ActualRootFactory => plan.admit_original_training(
                Arc::clone(&f.original.issuer),
                Arc::clone(&f.original.registry),
                f.original.writer.clone(),
                original,
            ),
            Entry::Component | Entry::ExpiredFrame => plan.admit_checked(
                Arc::clone(&f.original.issuer),
                Arc::clone(&f.original.registry),
                f.original.writer.clone(),
                original,
            ),
        });
        response.write_response(b"{}", || Ok(()))
    });
    if !matches!(entry, Entry::ExpiredFrame) {
        assert!(exchange.unwrap());
    }
    outcome.unwrap_or_else(|| Err(io::Error::other("component request was not entered")))
}

#[test]
fn late_original_effect_is_created_once_and_does_not_read_material() {
    let f = fresh();
    let plan = plan(&f);
    let raw = f.request_bytes();
    let mut accesses = support::ReadWatch::new(f.original.directory.path());
    let before = f.original.registry.frontier().unwrap();
    let owner = attempt(&f, &plan, &raw, Entry::Component).unwrap();
    assert_eq!(owner.registration, f.original.registration);
    assert!(owner.training_materials.is_none());
    let effect = f
        .original
        .registry
        .read_lease(&f.original.registration.effect_id())
        .unwrap()
        .unwrap()
        .lease;
    assert_eq!(effect.revision, 1);
    assert!(effect.expires_at_unix_ms <= f.ingress.expires_at_ms);
    let after = f.original.registry.frontier().unwrap();
    assert!(after.store_revision > before.store_revision);
    drop(owner);
    attempt(&f, &plan, &raw, Entry::Component).unwrap();
    assert_eq!(f.original.registry.frontier().unwrap(), after);
    assert_eq!(accesses.content_accesses(), (false, false));
}

#[test]
fn late_effect_prune_reopen_and_replay_never_recreates_the_identity() {
    let f = fresh();
    let plan = plan(&f);
    let raw = f.request_bytes();
    drop(attempt(&f, &plan, &raw, Entry::Component).unwrap());
    let mut effect = f
        .original
        .registry
        .read_lease(&f.original.registration.effect_id())
        .unwrap()
        .unwrap()
        .lease;
    f.original
        .clock
        .0
        .store(effect.expires_at_unix_ms, Ordering::SeqCst);
    assert_eq!(f.original.registry.prune_expired_leases(8).unwrap(), 1);
    let f = f.reopen();
    let before = f.original.registry.frontier().unwrap();
    assert!(attempt(&f, &plan, &raw, Entry::Component).is_err());
    effect.issued_at_unix_ms = effect.expires_at_unix_ms;
    effect.expires_at_unix_ms += 1_000;
    assert!(matches!(
        f.original
            .registry
            .put_lease(effect, /*expected_revision*/ 0),
        Err(AuthorityLeaseError::RevisionMismatch)
    ));
    assert_eq!(f.original.registry.frontier().unwrap(), before);
    assert!(
        f.original
            .registry
            .read_lease(&f.original.registration.effect_id())
            .unwrap()
            .is_none()
    );
}

#[test]
fn changed_frozen_plan_or_forged_original_request_cannot_create_an_effect() {
    let f = fresh();
    let expected = plan(&f);
    let raw = f.request_bytes();
    let before = f.original.registry.frontier().unwrap();
    for changed in [
        RootPairedTrainingPlanV1 {
            enrollment_revision: expected.enrollment_revision + 1,
            ..expected.clone()
        },
        RootPairedTrainingPlanV1 {
            effect_lifetime_ms: 10_001,
            ..expected.clone()
        },
        RootPairedTrainingPlanV1 {
            training: crate::PairedTrainingPlanV1 {
                operation: Digest32::of_bytes(b"another operation"),
                ..expected.training.clone()
            },
            ..expected.clone()
        },
    ] {
        assert!(attempt(&f, &changed, &raw, Entry::Component).is_err());
    }
    for field in ["signature_hex", "payload_json"] {
        let mut changed: serde_json::Value = serde_json::from_slice(&raw).unwrap();
        if field == "signature_hex" {
            changed["ingress"][field] = "00".repeat(f.ingress.signature_hex.len() / 2).into();
        } else {
            changed[field] = "{}".into();
        }
        assert!(
            attempt(
                &f,
                &expected,
                &serde_json::to_vec(&changed).unwrap(),
                Entry::Component
            )
            .is_err()
        );
    }
    assert_eq!(f.original.registry.frontier().unwrap(), before);
    assert!(
        f.original
            .registry
            .read_lease(&f.original.registration.effect_id())
            .unwrap()
            .is_none()
    );
}

#[test]
fn revoked_parent_or_expired_original_frame_cannot_admit_a_late_effect() {
    for parent in ["issuer", "writer", "enrollment"] {
        let f = fresh();
        let (id, revision) = match parent {
            "issuer" => ("synthetic-paired-issuer".to_owned(), 1),
            "writer" => (f.original.writer.authority_lease.lease_id.clone(), 1),
            "enrollment" => (
                f.original.registration.enrollment_id().unwrap(),
                f.original.registration.enrollment_revision,
            ),
            _ => unreachable!(),
        };
        f.original.registry.revoke(&id, revision, [7; 32]).unwrap();
        let before = f.original.registry.frontier().unwrap();
        assert!(attempt(&f, &plan(&f), &f.request_bytes(), Entry::Component).is_err());
        assert_eq!(f.original.registry.frontier().unwrap(), before);
    }
    let f = fresh();
    let before = f.original.registry.frontier().unwrap();
    assert!(attempt(&f, &plan(&f), &f.request_bytes(), Entry::ExpiredFrame).is_err());
    assert_eq!(f.original.registry.frontier().unwrap(), before);
}

#[test]
fn production_late_factory_refuses_actual_non_root_without_mutation() {
    // Ordinary controls deliberately run as non-Root; do not silently skip.
    assert_ne!(unsafe { libc::geteuid() }, 0);
    let f = fresh();
    let before = f.original.registry.frontier().unwrap();
    let refused = attempt(&f, &plan(&f), &f.request_bytes(), Entry::ActualRootFactory);
    assert!(refused.is_err());
    assert_eq!(f.original.registry.frontier().unwrap(), before);
}

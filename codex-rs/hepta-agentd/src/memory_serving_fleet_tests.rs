//! Real signature verification with fixture keys; not deployed-node evidence.
use super::*;
use codex_hepta_contracts::*;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}
struct Fixture {
    fleet: FleetRevocationCoordinator,
    clock: Arc<Clock>,
    distributor: SigningKey,
    node: SigningKey,
}
impl Fixture {
    fn new() -> Self {
        let distributor = SigningKey::from_bytes(&[61; 32]);
        let node = SigningKey::from_bytes(&[62; 32]);
        let feed = FinalUseRevocationFeedVerifier::new(
            "distributor".into(),
            distributor.verifying_key().to_bytes(),
        )
        .expect("feed");
        let convergence =
            FinalUseRevocationConvergenceVerifier::new([FinalUseRevocationNodeTrust {
                node_id: "node".into(),
                keys: vec![FinalUseTrustKey {
                    key_id: "node-key".into(),
                    verifying_key: node.verifying_key().to_bytes(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 9,
                }],
            }])
            .expect("node trust");
        let clock = Arc::new(Clock(AtomicU64::new(1100)));
        let fleet = FleetRevocationCoordinator::new(
            feed,
            convergence,
            clock.clone(),
            /*convergence_sla_ms*/ 500,
        )
        .expect("coordinator");
        Self {
            fleet,
            clock,
            distributor,
            node,
        }
    }
    fn update(&self, revision: u64) -> SignedFinalUseRevocationUpdate {
        let update = FinalUseRevocationUpdate::new(
            "distributor".into(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision,
                revoked_grant_ids: BTreeSet::from(["revoked.1".into()]),
            },
            /*issued_at_unix_ms*/ 1000,
            /*expires_at_unix_ms*/ 2000,
        );
        let signature = self
            .distributor
            .sign(&update.signing_bytes().expect("update"))
            .to_bytes()
            .to_vec();
        SignedFinalUseRevocationUpdate { update, signature }
    }
    fn ack(&self, update: &SignedFinalUseRevocationUpdate) -> SignedFinalUseRevocationAck {
        let mut bytes = b"hepta.kernel.authority.revocation-update-digest.v1\0".to_vec();
        bytes.extend_from_slice(&update.update.signing_bytes().expect("update payload"));
        let ack = FinalUseRevocationAck {
            schema_version: 1,
            node_id: "node".into(),
            distributor_id: "distributor".into(),
            authority_epoch: 1,
            revision: update.update.head.revision,
            update_sha256: *Digest32::of_bytes(&bytes).as_array(),
            applied_at_unix_ms: 1100,
        };
        let signature = self
            .node
            .sign(&ack.signing_bytes().expect("ack"))
            .to_bytes()
            .to_vec();
        SignedFinalUseRevocationAck { ack, signature }
    }
}

#[test]
fn serving_requires_current_node_ack_not_loaded_weights_or_an_old_ack() {
    let mut f = Fixture::new();
    assert!(require_current_memory_fleet_v1(&f.fleet, "node").is_err());
    let update = f.update(1);
    f.fleet.install_update(update.clone()).expect("install");
    assert!(require_current_memory_fleet_v1(&f.fleet, "node").is_err());
    let ack = f.ack(&update);
    f.fleet.record_ack(ack.clone()).expect("ack");
    let old = require_current_memory_fleet_v1(&f.fleet, "node").expect("ready");
    assert!(require_current_memory_fleet_v1(&f.fleet, "other-node").is_err());
    let next = f.update(2);
    f.fleet.install_update(next.clone()).expect("new head");
    assert!(require_current_memory_fleet_v1(&f.fleet, "node").is_err());
    assert!(f.fleet.record_ack(ack).is_err());
    f.fleet.record_ack(f.ack(&next)).expect("new ack");
    assert_ne!(
        old,
        require_current_memory_fleet_v1(&f.fleet, "node").expect("new ready")
    );
}

#[test]
fn fresh_ack_does_not_survive_stale_feed_or_backward_clock() {
    let mut f = Fixture::new();
    let update = f.update(1);
    f.fleet.install_update(update.clone()).expect("install");
    f.fleet.record_ack(f.ack(&update)).expect("ack");
    for time in [900, 2000] {
        f.clock.0.store(time, Ordering::SeqCst);
        assert!(require_current_memory_fleet_v1(&f.fleet, "node").is_err());
    }
}

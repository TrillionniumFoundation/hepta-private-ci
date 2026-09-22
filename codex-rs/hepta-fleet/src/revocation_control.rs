//! Fleet-side revocation convergence and node-admission control.
//!
//! This module owns no network transport. It turns authenticated kernel.authority
//! revocation updates and signed node acknowledgements into one bounded,
//! fail-closed fleet state machine. Wire fanout may be implemented by any host,
//! but a node is not authority-ready until it has acknowledged the exact current
//! update and that update is still fresh.

use std::collections::BTreeSet;
use std::fmt;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseControlError;
use codex_hepta_contracts::FinalUseRevocationAck;
use codex_hepta_contracts::FinalUseRevocationConvergenceReport;
use codex_hepta_contracts::FinalUseRevocationConvergenceVerifier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::MAX_REVOCATION_FEED_LIFETIME_MS;
use codex_hepta_contracts::SignedFinalUseRevocationAck;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;

pub const MAX_FLEET_REVOCATION_NODES: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FleetNodeRevocationState {
    Ready,
    CatchingUp,
    Quarantined,
    FeedStale,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetRevocationStatus {
    pub authority_epoch: u64,
    pub revision: u64,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub convergence_deadline_unix_ms: u64,
    pub acknowledged_nodes: Vec<String>,
    pub missing_nodes: Vec<String>,
    pub converged: bool,
    pub feed_fresh: bool,
}

struct Current {
    update: SignedFinalUseRevocationUpdate,
    acknowledgements: Vec<SignedFinalUseRevocationAck>,
    expected_nodes: BTreeSet<String>,
    convergence_deadline_unix_ms: u64,
}

/// Bounded fleet control plane for one independently authenticated revocation
/// feed and one closed enrolled-node set.
///
/// Missing or stale revocation knowledge never becomes authority. Before the
/// convergence deadline a missing node is catching up. At/after the deadline it
/// is quarantined until it acknowledges the exact current update. A stale feed
/// quarantines every node regardless of prior convergence.
pub struct FleetRevocationCoordinator {
    feed_verifier: FinalUseRevocationFeedVerifier,
    convergence_verifier: FinalUseRevocationConvergenceVerifier,
    clock: Arc<dyn AuthorityClock>,
    convergence_sla_ms: u64,
    current: Option<Current>,
}

impl fmt::Debug for FleetRevocationCoordinator {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("FleetRevocationCoordinator")
            .field("convergence_sla_ms", &self.convergence_sla_ms)
            .field("has_current_update", &self.current.is_some())
            .finish()
    }
}

impl FleetRevocationCoordinator {
    pub fn new(
        feed_verifier: FinalUseRevocationFeedVerifier,
        convergence_verifier: FinalUseRevocationConvergenceVerifier,
        clock: Arc<dyn AuthorityClock>,
        convergence_sla_ms: u64,
    ) -> Result<Self, FleetRevocationError> {
        if convergence_sla_ms == 0 || convergence_sla_ms > MAX_REVOCATION_FEED_LIFETIME_MS {
            return Err(FleetRevocationError::InvalidSla);
        }
        clock
            .now_unix_ms()
            .map_err(|_| FleetRevocationError::ClockUnavailable)?;
        Ok(Self {
            feed_verifier,
            convergence_verifier,
            clock,
            convergence_sla_ms,
            current: None,
        })
    }

    /// Install one fresh distributor-signed head. Exact transport replay is
    /// idempotent; a reused epoch/revision with different semantics conflicts.
    /// Newer heads reset acknowledgement state and force every enrolled node to
    /// catch up again.
    pub fn install_update(
        &mut self,
        update: SignedFinalUseRevocationUpdate,
    ) -> Result<FleetRevocationStatus, FleetRevocationError> {
        let now = self.now()?;
        let authenticated = self
            .convergence_verifier
            .verify(&self.feed_verifier, &update, &[], now)
            .map_err(FleetRevocationError::Control)?;

        if authenticated.expected_nodes.is_empty()
            || authenticated.expected_nodes.len() > MAX_FLEET_REVOCATION_NODES
        {
            return Err(FleetRevocationError::InvalidNodeSet);
        }

        if let Some(current) = &self.current {
            let old = &current.update.update;
            let new = &update.update;
            if new.head.authority_epoch < old.head.authority_epoch
                || (new.head.authority_epoch == old.head.authority_epoch
                    && new.head.revision < old.head.revision)
            {
                return Err(FleetRevocationError::StaleUpdate);
            }
            if new.head.authority_epoch == old.head.authority_epoch
                && !new
                    .head
                    .revoked_grant_ids
                    .is_superset(&old.head.revoked_grant_ids)
            {
                return Err(FleetRevocationError::ConflictingUpdate);
            }
            if new.head.authority_epoch == old.head.authority_epoch
                && new.head.revision == old.head.revision
            {
                if same_update(&current.update, &update) {
                    return self.status();
                }
                return Err(FleetRevocationError::ConflictingUpdate);
            }
        }

        let deadline = update
            .update
            .issued_at_unix_ms
            .checked_add(self.convergence_sla_ms)
            .ok_or(FleetRevocationError::InvalidSla)?
            .min(update.update.expires_at_unix_ms);
        self.current = Some(Current {
            update,
            acknowledgements: Vec::new(),
            expected_nodes: authenticated.expected_nodes.into_iter().collect(),
            convergence_deadline_unix_ms: deadline,
        });
        self.status()
    }

    /// Add one signed acknowledgement for the exact current update. An exact
    /// duplicate is idempotent; a second different acknowledgement from the
    /// same node conflicts instead of replacing evidence.
    pub fn record_ack(
        &mut self,
        signed: SignedFinalUseRevocationAck,
    ) -> Result<FleetRevocationStatus, FleetRevocationError> {
        let duplicate = {
            let current = self
                .current
                .as_mut()
                .ok_or(FleetRevocationError::NoCurrentUpdate)?;

            if !current.expected_nodes.contains(&signed.ack.node_id) {
                return Err(FleetRevocationError::UnknownNode);
            }
            if let Some(existing) = current
                .acknowledgements
                .iter()
                .find(|candidate| candidate.ack.node_id == signed.ack.node_id)
            {
                if existing != &signed {
                    return Err(FleetRevocationError::ConflictingAck);
                }
                true
            } else {
                current.acknowledgements.push(signed);
                if current.acknowledgements.len() > current.expected_nodes.len() {
                    current.acknowledgements.pop();
                    return Err(FleetRevocationError::InvalidNodeSet);
                }
                false
            }
        };

        if duplicate {
            return self.status();
        }

        if let Err(error) = self.current_report() {
            if let Some(current) = self.current.as_mut() {
                current.acknowledgements.pop();
            }
            return Err(error);
        }
        self.status()
    }

    pub fn node_state(
        &self,
        node_id: &str,
    ) -> Result<FleetNodeRevocationState, FleetRevocationError> {
        let current = self
            .current
            .as_ref()
            .ok_or(FleetRevocationError::NoCurrentUpdate)?;
        if !current.expected_nodes.contains(node_id) {
            return Err(FleetRevocationError::UnknownNode);
        }
        let now = self.now()?;
        if now >= current.update.update.expires_at_unix_ms {
            return Ok(FleetNodeRevocationState::FeedStale);
        }
        if current
            .acknowledgements
            .iter()
            .any(|candidate| candidate.ack.node_id == node_id)
        {
            return Ok(FleetNodeRevocationState::Ready);
        }
        if now >= current.convergence_deadline_unix_ms {
            Ok(FleetNodeRevocationState::Quarantined)
        } else {
            Ok(FleetNodeRevocationState::CatchingUp)
        }
    }

    pub fn status(&self) -> Result<FleetRevocationStatus, FleetRevocationError> {
        let current = self
            .current
            .as_ref()
            .ok_or(FleetRevocationError::NoCurrentUpdate)?;
        let now = self.now()?;
        if now >= current.update.update.expires_at_unix_ms {
            let acknowledged: BTreeSet<String> = current
                .acknowledgements
                .iter()
                .map(|candidate| candidate.ack.node_id.clone())
                .collect();
            let acknowledged_nodes: Vec<String> = acknowledged.iter().cloned().collect();
            let missing_nodes: Vec<String> = current
                .expected_nodes
                .iter()
                .filter(|node| !acknowledged.contains(*node))
                .cloned()
                .collect();
            return Ok(FleetRevocationStatus {
                authority_epoch: current.update.update.head.authority_epoch,
                revision: current.update.update.head.revision,
                issued_at_unix_ms: current.update.update.issued_at_unix_ms,
                expires_at_unix_ms: current.update.update.expires_at_unix_ms,
                convergence_deadline_unix_ms: current.convergence_deadline_unix_ms,
                acknowledged_nodes,
                missing_nodes,
                converged: false,
                feed_fresh: false,
            });
        }
        let report = self.current_report()?;
        Ok(FleetRevocationStatus {
            authority_epoch: current.update.update.head.authority_epoch,
            revision: current.update.update.head.revision,
            issued_at_unix_ms: current.update.update.issued_at_unix_ms,
            expires_at_unix_ms: current.update.update.expires_at_unix_ms,
            convergence_deadline_unix_ms: current.convergence_deadline_unix_ms,
            acknowledged_nodes: report.acknowledged_nodes,
            missing_nodes: report.missing_nodes,
            converged: report.converged(),
            feed_fresh: true,
        })
    }

    fn current_report(&self) -> Result<FinalUseRevocationConvergenceReport, FleetRevocationError> {
        let current = self
            .current
            .as_ref()
            .ok_or(FleetRevocationError::NoCurrentUpdate)?;
        self.convergence_verifier
            .verify(
                &self.feed_verifier,
                &current.update,
                &current.acknowledgements,
                self.now()?,
            )
            .map_err(FleetRevocationError::Control)
    }

    fn now(&self) -> Result<u64, FleetRevocationError> {
        self.clock
            .now_unix_ms()
            .map_err(|_| FleetRevocationError::ClockUnavailable)
    }
}

fn same_update(
    left: &SignedFinalUseRevocationUpdate,
    right: &SignedFinalUseRevocationUpdate,
) -> bool {
    left.signature == right.signature
        && left.update.schema_version == right.update.schema_version
        && left.update.distributor_id == right.update.distributor_id
        && left.update.head.authority_epoch == right.update.head.authority_epoch
        && left.update.head.revision == right.update.head.revision
        && left.update.head.revoked_grant_ids == right.update.head.revoked_grant_ids
        && left.update.issued_at_unix_ms == right.update.issued_at_unix_ms
        && left.update.expires_at_unix_ms == right.update.expires_at_unix_ms
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FleetRevocationError {
    InvalidSla,
    InvalidNodeSet,
    NoCurrentUpdate,
    StaleUpdate,
    ConflictingUpdate,
    UnknownNode,
    ConflictingAck,
    ClockUnavailable,
    Control(FinalUseControlError),
}

impl fmt::Display for FleetRevocationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for FleetRevocationError {}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_contracts::AuthorityTrustError;
    use codex_hepta_contracts::FinalUseRevocationNodeTrust;
    use codex_hepta_contracts::FinalUseRevocationUpdate;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::FinalUseTrustKey;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use sha2::Digest;
    use sha2::Sha256;
    use std::collections::BTreeSet;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    #[derive(Debug)]
    struct ManualClock(AtomicU64);

    impl ManualClock {
        fn new(now: u64) -> Self {
            Self(AtomicU64::new(now))
        }

        fn set(&self, now: u64) {
            self.0.store(now, Ordering::SeqCst);
        }
    }

    impl AuthorityClock for ManualClock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(self.0.load(Ordering::SeqCst))
        }
    }

    fn setup() -> (
        FleetRevocationCoordinator,
        Arc<ManualClock>,
        SigningKey,
        SigningKey,
        SignedFinalUseRevocationUpdate,
    ) {
        let distributor = SigningKey::from_bytes(&[41; 32]);
        let node = SigningKey::from_bytes(&[42; 32]);
        let feed = FinalUseRevocationFeedVerifier::new(
            "revocation-distributor".into(),
            distributor.verifying_key().to_bytes(),
        )
        .unwrap();
        let convergence =
            FinalUseRevocationConvergenceVerifier::new([FinalUseRevocationNodeTrust {
                node_id: "node-a".into(),
                keys: vec![FinalUseTrustKey {
                    key_id: "node-key".into(),
                    verifying_key: node.verifying_key().to_bytes(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 99,
                }],
            }])
            .unwrap();
        let clock = Arc::new(ManualClock::new(1_100));
        let coordinator =
            FleetRevocationCoordinator::new(feed, convergence, clock.clone(), 500).unwrap();
        let update = FinalUseRevocationUpdate::new(
            "revocation-distributor".into(),
            FinalUseRevocations {
                authority_epoch: 7,
                revision: 2,
                revoked_grant_ids: BTreeSet::from(["grant-a".into()]),
            },
            1_000,
            2_000,
        );
        let signed_update = SignedFinalUseRevocationUpdate {
            signature: distributor
                .sign(&update.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            update,
        };
        (coordinator, clock, distributor, node, signed_update)
    }

    fn ack_digest(update: &FinalUseRevocationUpdate) -> [u8; 32] {
        let mut hash = Sha256::new();
        hash.update(b"hepta.kernel.authority.revocation-update-digest.v1\0");
        hash.update(update.signing_bytes().unwrap());
        hash.finalize().into()
    }

    fn signed_ack(
        node: &SigningKey,
        update: &SignedFinalUseRevocationUpdate,
        applied_at_unix_ms: u64,
    ) -> SignedFinalUseRevocationAck {
        let ack = FinalUseRevocationAck {
            schema_version: 1,
            node_id: "node-a".into(),
            distributor_id: update.update.distributor_id.clone(),
            authority_epoch: update.update.head.authority_epoch,
            revision: update.update.head.revision,
            update_sha256: ack_digest(&update.update),
            applied_at_unix_ms,
        };
        SignedFinalUseRevocationAck {
            signature: node.sign(&ack.signing_bytes().unwrap()).to_bytes().to_vec(),
            ack,
        }
    }

    #[test]
    fn missing_node_moves_from_catchup_to_quarantine_and_stale() {
        let (mut coordinator, clock, _distributor, _node, update) = setup();
        let status = coordinator.install_update(update).unwrap();
        assert!(!status.converged);
        assert_eq!(
            coordinator.node_state("node-a").unwrap(),
            FleetNodeRevocationState::CatchingUp
        );
        clock.set(1_500);
        assert_eq!(
            coordinator.node_state("node-a").unwrap(),
            FleetNodeRevocationState::Quarantined
        );
        clock.set(2_000);
        assert_eq!(
            coordinator.node_state("node-a").unwrap(),
            FleetNodeRevocationState::FeedStale
        );
        let stale = coordinator.status().unwrap();
        assert!(!stale.feed_fresh);
        assert!(!stale.converged);
    }

    #[test]
    fn exact_ack_makes_node_ready_and_duplicate_is_idempotent() {
        let (mut coordinator, _clock, _distributor, node, update) = setup();
        coordinator.install_update(update.clone()).unwrap();
        let ack = signed_ack(&node, &update, 1_200);
        let first = coordinator.record_ack(ack.clone()).unwrap();
        let retry = coordinator.record_ack(ack).unwrap();
        assert_eq!(first, retry);
        assert!(retry.converged);
        assert_eq!(
            coordinator.node_state("node-a").unwrap(),
            FleetNodeRevocationState::Ready
        );
    }

    #[test]
    fn new_head_forces_catchup_and_same_revision_drift_conflicts() {
        let (mut coordinator, clock, distributor, node, update) = setup();
        coordinator.install_update(update.clone()).unwrap();
        coordinator
            .record_ack(signed_ack(&node, &update, 1_200))
            .unwrap();

        let mut drifted = update.clone();
        drifted
            .update
            .head
            .revoked_grant_ids
            .insert("grant-b".into());
        drifted.signature = distributor
            .sign(&drifted.update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        assert_eq!(
            coordinator.install_update(drifted).unwrap_err(),
            FleetRevocationError::ConflictingUpdate
        );

        clock.set(1_300);
        let mut removed = update.clone();
        removed.update.head.revision = 3;
        removed.update.head.revoked_grant_ids.clear();
        removed.update.issued_at_unix_ms = 1_250;
        removed.update.expires_at_unix_ms = 2_100;
        removed.signature = distributor
            .sign(&removed.update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        assert_eq!(
            coordinator.install_update(removed).unwrap_err(),
            FleetRevocationError::ConflictingUpdate
        );

        let mut newer = update;
        newer.update.head.revision = 3;
        newer.update.issued_at_unix_ms = 1_250;
        newer.update.expires_at_unix_ms = 2_100;
        newer.signature = distributor
            .sign(&newer.update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        coordinator.install_update(newer).unwrap();
        assert_eq!(
            coordinator.node_state("node-a").unwrap(),
            FleetNodeRevocationState::CatchingUp
        );
    }
}

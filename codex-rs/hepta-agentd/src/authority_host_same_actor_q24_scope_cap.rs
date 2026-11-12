//! Root's one-use typed authorization for the post-A scoped enrollment.
//! No daemon message can construct this capability or supply replacement
//! CURRENT, model reservation, issuer trust or participant identities.

use super::*;

const PREPARED: u8 = 0;
const ACTIVE: u8 = 1;
const CONSUMED: u8 = 2;

pub(super) struct ScopeSubmission {
    pub(super) profile: crate::HostAuthorityLearningProfileV1,
    pub(super) acknowledgement: std::sync::mpsc::SyncSender<Result<RootSameActorScopedEnrollmentV1, String>>,
}

pub(super) struct ScopeRuntime {
    pub(super) receiver: std::sync::mpsc::Receiver<ScopeSubmission>,
    pub(super) phase: Arc<std::sync::atomic::AtomicU8>,
}

pub struct RootSameActorScopeEnrollmentCapabilityV1 {
    sender: std::sync::mpsc::SyncSender<ScopeSubmission>,
    phase: Arc<std::sync::atomic::AtomicU8>,
    root: codex_hepta_memory::CognitiveCheckpointPeerLifetime,
    gate: Arc<SameActorPhaseGate>,
}

/// Retain both the actual one-shot owner offer and the Root-only publication
/// capability until the original handoff has completed. Dropping an unsent
/// response closes the common phase instead of allowing a replacement offer.
pub struct RootSameActorScopedEnrollmentV1 {
    pub(crate) offer: crate::root_production_handoff::same_actor_phase::RootSameActorScopedOfferV1,
    pub(crate) publication: generation_publication::RootSameActorPublicationEnrollmentCapabilityV1,
    pub(crate) gate: Arc<SameActorPhaseGate>,
    pub(crate) closing: CloseSameActorPhaseOnDrop,
}

impl ScopeRuntime {
    pub(super) fn mint(
        root: codex_hepta_memory::CognitiveCheckpointPeerLifetime,
        gate: &Arc<SameActorPhaseGate>,
    ) -> (Self, RootSameActorScopeEnrollmentCapabilityV1) {
        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        let phase = Arc::new(std::sync::atomic::AtomicU8::new(PREPARED));
        (
            Self { receiver, phase: Arc::clone(&phase) },
            RootSameActorScopeEnrollmentCapabilityV1 {
                sender, phase, root, gate: Arc::clone(gate),
            },
        )
    }

    pub(super) fn activate(&self) -> io::Result<()> {
        self.phase.compare_exchange(
            PREPARED, ACTIVE, std::sync::atomic::Ordering::AcqRel,
            std::sync::atomic::Ordering::Acquire,
        ).map_err(|_| io::Error::other("original phase scope was already activated"))?;
        Ok(())
    }
}

impl RootSameActorScopeEnrollmentCapabilityV1 {
    /// Authorize the actual Prepared profile supplied by trusted Root. The
    /// daemon must independently prove its retained original capability at
    /// the same-purpose join; this profile alone supplies no business evidence.
    pub fn register(
        self,
        profile: crate::HostAuthorityLearningProfileV1,
    ) -> io::Result<RootSameActorScopedEnrollmentV1> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        self.gate.require_open()?;
        crate::authority_host_service::generation_initial::original_root()?;
        if self.root.uid != 0
            || self.root.pid != std::process::id()
            || self.root.boot_id != std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim()
            || self.root.process_start_ticks != original_root_start()?
            || self.phase.compare_exchange(
                ACTIVE, CONSUMED, std::sync::atomic::Ordering::AcqRel,
                std::sync::atomic::Ordering::Acquire,
            ).is_err()
        {
            return Err(io::Error::other("original Root phase capability is unavailable"));
        }
        let (acknowledgement, receiver) = std::sync::mpsc::sync_channel(1);
        self.sender.try_send(ScopeSubmission { profile, acknowledgement })
            .map_err(|_| io::Error::other("original phase scope handoff unavailable"))?;
        self.gate.notify_original_waiters();
        let enrolled = loop {
            let epoch = self.gate.original_wait_epoch()?;
            match receiver.try_recv() {
                Ok(result) => break result.map_err(io::Error::other)?,
                Err(std::sync::mpsc::TryRecvError::Empty) => self.gate.wait_original_change(epoch)?,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    return Err(io::Error::other("original phase scope acknowledgement uncertain"));
                }
            }
        };
        self.gate.require_open()?;
        if !Arc::ptr_eq(&enrolled.gate, &self.gate) {
            return Err(io::Error::other("original phase scope acknowledgement changed its gate"));
        }
        closing.disarm();
        Ok(enrolled)
    }
}

fn original_root_start() -> io::Result<u64> {
    std::fs::read_to_string("/proc/self/stat")?
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value != 0)
        .ok_or_else(|| io::Error::other("actual Root incarnation missing"))
}

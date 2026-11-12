//! The publication enrollment capability with the original phase's fixed ends.
//! The normal publication capability and its existing behavior are unchanged.

use super::*;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

pub struct RootSameActorPublicationEnrollmentCapabilityV1 {
    original: RootGenerationPublicationEnrollmentCapabilityV1,
    gate: Arc<SameActorPhaseGate>,
}

impl RootGenerationPublicationEnrollmentCapabilityV1 {
    pub(in super::super) fn into_same_actor_phase(
        self,
        gate: &Arc<SameActorPhaseGate>,
    ) -> RootSameActorPublicationEnrollmentCapabilityV1 {
        RootSameActorPublicationEnrollmentCapabilityV1 {
            original: self,
            gate: Arc::clone(gate),
        }
    }
}

impl RootSameActorPublicationEnrollmentCapabilityV1 {
    pub fn register(
        self,
        inputs: crate::RootGenerationPublicationEnrollmentV1,
    ) -> io::Result<RootGenerationPublicationRegistrationV1> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        let _admission = self.gate.enter_original_lane()?;
        crate::authority_host_service::generation_publication::original_root()?;
        if inputs.mode != crate::RootGenerationPublicationModeV1::Reserve
            || std::process::id() != self.original.root_pid
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim()
                != self.original.boot_id
            || root_start()? != self.original.process_start_ticks
            || self.original.phase.compare_exchange(
                ACTIVE, CONSUMED, Ordering::AcqRel, Ordering::Acquire,
            ).is_err()
        {
            return Err(io::Error::other("original live phase publication admission required"));
        }
        let (acknowledgement, receiver) = mpsc::sync_channel(1);
        self.original.sender.try_send(Submission { inputs, acknowledgement })
            .map_err(|_| io::Error::other("original phase publication channel unavailable"))?;
        self.gate.notify_original_waiters();
        let binding = loop {
            let epoch = self.gate.original_wait_epoch()?;
            match receiver.try_recv() {
                Ok(reply) => break reply.map_err(io::Error::other)?,
                Err(mpsc::TryRecvError::Empty) => self.gate.wait_original_change(epoch)?,
                Err(mpsc::TryRecvError::Disconnected) => {
                    return Err(io::Error::other("original phase publication acknowledgement uncertain"));
                }
            }
        };
        self.gate.require_open()?;
        if self.original.phase.load(Ordering::Acquire) != CONSUMED {
            return Err(io::Error::other("original phase publication session ended during enrollment"));
        }
        closing.disarm();
        Ok(RootGenerationPublicationRegistrationV1 { binding })
    }
}

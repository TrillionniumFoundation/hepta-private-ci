//! The initial enrollment capability with the original phase's fixed ends.
//! The normal initial capability and its existing behavior are unchanged.

use super::*;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;

pub struct RootSameActorInitialEnrollmentCapabilityV1 {
    original: RootGenerationInitialEnrollmentCapabilityV1,
    gate: Arc<SameActorPhaseGate>,
    current_directory: Arc<codex_hepta_contracts::RootAuthorityDirectory>,
}

impl RootGenerationInitialEnrollmentCapabilityV1 {
    pub(in super::super) fn into_same_actor_phase(
        self,
        gate: &Arc<SameActorPhaseGate>,
        current_directory: &Arc<codex_hepta_contracts::RootAuthorityDirectory>,
    ) -> RootSameActorInitialEnrollmentCapabilityV1 {
        RootSameActorInitialEnrollmentCapabilityV1 {
            original: self,
            gate: Arc::clone(gate),
            current_directory: Arc::clone(current_directory),
        }
    }
}

impl RootSameActorInitialEnrollmentCapabilityV1 {
    pub fn register(
        self,
        inputs: crate::RootGenerationInitialEnrollmentV1,
    ) -> io::Result<RootGenerationInitialRegistrationV1> {
        let mut closing = CloseSameActorPhaseOnDrop::new(&self.gate);
        let _admission = self.gate.enter_original_lane()?;
        crate::authority_host_service::generation_initial::original_root()?;
        if inputs.mode != crate::RootGenerationInitialModeV1::Reserve
            || !Arc::ptr_eq(&inputs.current_directory, &self.current_directory)
            || std::process::id() != self.original.root_pid
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim()
                != self.original.boot_id
            || root_start()? != self.original.process_start_ticks
            || self
                .original
                .phase
                .compare_exchange(ACTIVE, CONSUMED, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
        {
            return Err(io::Error::other(
                "original live phase Initial admission required",
            ));
        }
        let (acknowledgement, receiver) = mpsc::sync_channel(1);
        self.original
            .sender
            .try_send(Submission {
                inputs,
                acknowledgement,
            })
            .map_err(|_| io::Error::other("original phase Initial channel unavailable"))?;
        self.gate.notify_original_waiters();
        let binding = loop {
            let epoch = self.gate.original_wait_epoch()?;
            match receiver.try_recv() {
                Ok(reply) => break reply.map_err(io::Error::other)?,
                Err(mpsc::TryRecvError::Empty) => self.gate.wait_original_change(epoch)?,
                Err(mpsc::TryRecvError::Disconnected) => {
                    return Err(io::Error::other(
                        "original phase Initial acknowledgement uncertain",
                    ));
                }
            }
        };
        self.gate.require_open()?;
        if self.original.phase.load(Ordering::Acquire) != CONSUMED {
            return Err(io::Error::other(
                "original phase Initial session ended during enrollment",
            ));
        }
        closing.disarm();
        Ok(RootGenerationInitialRegistrationV1 { binding })
    }
}

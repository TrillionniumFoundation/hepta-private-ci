//! Explicit ordinary-peer readiness consumes only the original Root-held
//! deployment. It cannot supply inputs or call a capability that waits on itself.

use super::super::ACTIVE;
use super::super::CONSUMED;
use super::super::PREPARED;
use super::RootGenerationInitialDeploymentV1;
use crate::PreparedHostAuthoritySession;
use crate::RootGenerationInitialEnrollmentV1;
use std::io;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Instant;

impl PreparedHostAuthoritySession {
    /// Select peer readiness for this original deployment before serving.
    /// The ordinary peer only starts validation; every input remains held by Root.
    pub fn enable_original_initial_peer_ready(
        &mut self,
        deployment: RootGenerationInitialDeploymentV1,
    ) -> io::Result<()> {
        crate::authority_host_service::generation_initial::original_root()?;
        let initial = self
            .initial_publication
            .as_ref()
            .ok_or_else(|| io::Error::other("original Initial route must be enabled first"))?;
        if initial.peer_deployment.is_some()
            || !Arc::ptr_eq(&initial.phase, &deployment.capability.phase)
            || !Arc::ptr_eq(&initial.original_end, &deployment.capability.original_end)
            || initial.phase.load(Ordering::Acquire) != PREPARED
            || initial.deployment != deployment.files.deployment
        {
            return Err(io::Error::other(
                "different or consumed original Initial session",
            ));
        }
        self.service.with_initial_publication_context(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            |proof| {
                if proof != initial.writer {
                    return Err(io::Error::other("original Initial writer changed"));
                }
                deployment.files.require_original_initial_files()
            },
        )?;
        self.initial_publication
            .as_mut()
            .ok_or_else(|| io::Error::other("original Initial route disappeared"))?
            .peer_deployment = Some(deployment);
        Ok(())
    }
}

impl RootGenerationInitialDeploymentV1 {
    pub(in super::super) fn with_original_peer_enrollment<T>(
        &self,
        end: Instant,
        action: impl FnOnce(RootGenerationInitialEnrollmentV1) -> io::Result<T>,
    ) -> io::Result<T> {
        crate::authority_host_service::generation_initial::original_root()?;
        let cap = &self.capability;
        if cap
            .original_end
            .get()
            .is_none_or(|original| end > *original)
            || Instant::now() >= end
            || std::process::id() != cap.root_pid
            || super::super::root_start()? != cap.process_start_ticks
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim() != cap.boot_id
            || cap
                .phase
                .compare_exchange(ACTIVE, CONSUMED, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
        {
            return Err(io::Error::other(
                "original one-shot Initial enrollment required",
            ));
        }
        self.files.require_original_initial_files()?;
        let (inputs, artifacts) = self
            .files
            .inputs
            .initial_enrollment_inputs(&self.files.data, cap.consumer_uid)?;
        let result = action(inputs);
        // Perform the physical and lifetime postchecks even if enrollment
        // failed. Nothing from the peer can substitute these original files.
        let post = (|| {
            self.files.require_original_initial_files()?;
            for file in &artifacts {
                file.require_original_file()?;
            }
            if cap.phase.load(Ordering::Acquire) != CONSUMED
                || Instant::now() >= end
                || std::process::id() != cap.root_pid
                || super::super::root_start()? != cap.process_start_ticks
                || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim() != cap.boot_id
            {
                return Err(io::Error::other(
                    "original Initial registration outcome uncertain",
                ));
            }
            Ok(())
        })();
        let value = result?;
        post?;
        Ok(value)
    }
}

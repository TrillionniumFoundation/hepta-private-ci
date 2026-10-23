//! Trusted, one-attempt installation for this fixed recovered owner.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_memory::InstalledCognitiveMaterial;
use codex_hepta_memory::VerifiedCognitiveMaterial;
use std::sync::atomic::Ordering;

impl HostAuthorityService {
    /// Consume the independently verified last-Current image for this exact
    /// recovered composition. No request selects a layout, cut or generation.
    /// The actual Root producer and captured UID60001 Host must already be
    /// registered. This grants no writer or Session permission.
    ///
    /// Both original Registry and checkpoint locks remain held through the
    /// original physical installer and final proof/head/time/lifetime checks.
    /// Any failed first attempt permanently fences this launch; candidates are
    /// retained for exact reconciliation. A second attempt cannot repair it.
    /// Keep the returned original owner lock until Root finishes its launch
    /// checks, then drop it before releasing the fixed Host's recovery factory.
    pub fn install_recovered_owner_material(
        &self,
        material: VerifiedCognitiveMaterial,
        predecessor: &crate::RetiredCheckpointPublisher,
        successor: &crate::RetainedCheckpointPublisher,
    ) -> io::Result<InstalledCognitiveMaterial> {
        let startup = self.material_startup.as_ref()
            .ok_or_else(|| io::Error::other("required material startup missing"))?;
        let checkpoint = self.checkpoint.as_ref()
            .ok_or_else(|| io::Error::other("registered checkpoint required"))?;
        let recovered = checkpoint.recovered.as_ref()
            .ok_or_else(|| io::Error::other("original recovery composition required"))?;
        startup.begin_install()?;
        if recovered.attempted.swap(true, Ordering::AcqRel) {
            // An earlier successful attempt remains pending until actual Host
            // readiness. A duplicate does not race or alter that launch state.
            startup.installed();
            return Err(io::Error::other("recovered owner install was already attempted"));
        }
        let result = (|| {
            let bootstrap = self.bootstrap.as_ref()
                .ok_or_else(|| io::Error::other("actual Root/Host bootstrap required"))?;
            let writer = self.writer.as_ref()
                .ok_or_else(|| io::Error::other("registered writer required"))?;
            writer.registration.with_live(&writer.leases, |_| {
                // No callback in this scope may re-enter Registry or the
                // checkpoint backend. All retained paths are fixed Root input.
                startup.verify_directory()?;
                bootstrap.verify_processes()?;
                if self.issuer.retained_writer_authorization(&writer.registration)? != writer.proof {
                    return Err(io::Error::other("retained canonical writer proof changed"));
                }
                let head = self.issuer.revocations()?;
                checkpoint.backend.install_recovered_material_for_root(
                    &recovered.previous, predecessor, successor, material, &self.identity.layout,
                    |installed, before, checkpoint_expiry| {
                        let checked = (|| {
                            startup.verify_directory()?;
                            bootstrap.verify_processes()?;
                            installed.verify_unchanged().map_err(io::Error::other)?;
                            if self.issuer.retained_writer_authorization(&writer.registration)? != writer.proof
                                || self.issuer.revocations()? != head
                            {
                                return Err(io::Error::other("canonical writer changed during physical install"));
                            }
                            // All blocking I/O precedes the actual protected
                            // time. Only held lifetime polls follow it.
                            let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
                            validate_observation_lease(&writer.registration.authority_lease, &head, now)?;
                            if now < before || now >= checkpoint_expiry {
                                return Err(io::Error::other("checkpoint expiry crossed physical install"));
                            }
                            bootstrap.check_serving()
                        })();
                        checked.map_err(|_| AuthorityTrustError::Unavailable)
                    },
                ).map_err(io::Error::other)
            })
        })();
        match result {
            Ok(installed) => {
                recovered.installed.store(true, Ordering::Release);
                startup.installed();
                Ok(installed)
            }
            Err(error) => {
                startup.fail();
                checkpoint.backend.close();
                Err(error)
            }
        }
    }
}

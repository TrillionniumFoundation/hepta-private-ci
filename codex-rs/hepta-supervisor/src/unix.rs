//! Unix process driver with final-use runtime.fleet admission at the physical
//! child-process boundary.
//!
//! The established Unix implementation remains in `unix_core.rs`. This wrapper
//! captures one immutable admission profile from the daemon entry point and
//! verifies the exact Agent grant, host/lease fences and durable revocation cut
//! immediately before every spawn or adoption, including automatic recovery and
//! Matrix companion paths.

#[path = "unix_core.rs"]
mod raw;

pub use raw::UnixManagedProcess;

use std::future::Future;

use codex_hepta_contracts::AgentId;

use crate::AdoptSpec;
use crate::Adoption;
use crate::FleetStartAdmission;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::SpawnSpec;
use crate::SpawnedProcess;

tokio::task_local! {
    static FLEET_START_ADMISSION: FleetStartAdmission;
}

pub(crate) async fn with_fleet_start_admission<F, T>(admission: FleetStartAdmission, future: F) -> T
where
    F: Future<Output = T>,
{
    FLEET_START_ADMISSION.scope(admission, future).await
}

/// Product-facing Unix driver. Legacy library entry points that do not install
/// a fleet admission scope retain their historical behavior; the named
/// `hepta-supervisord` product always installs one before constructing this
/// driver.
pub struct UnixProcessDriver {
    inner: raw::UnixProcessDriver,
    admission: Option<FleetStartAdmission>,
}

impl UnixProcessDriver {
    pub fn new(log_channel_capacity: usize) -> Result<Self, ProcessDriverError> {
        let inner = raw::UnixProcessDriver::new(log_channel_capacity)?;
        let admission = FLEET_START_ADMISSION.try_with(Clone::clone).ok();
        Ok(Self { inner, admission })
    }

    fn verify_process_effect(&self, agent_id: &AgentId) -> Result<(), ProcessDriverError> {
        let Some(admission) = self.admission.as_ref() else {
            return Ok(());
        };
        admission
            .verify_agent_start(agent_id)
            .map(|_witness| ())
            .map_err(|_error| {
                ProcessDriverError::new(
                    "runtime.fleet final-use admission rejected the process effect",
                )
            })
    }
}

impl ProcessDriver for UnixProcessDriver {
    type Process = raw::UnixManagedProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        self.verify_process_effect(&spec.agent_id)?;
        self.inner.spawn(spec)
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.verify_process_effect(&spec.agent_id)?;
        self.inner.adopt(spec)
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        self.verify_process_effect(&spec.agent_id)?;
        self.inner.spawn_matrixd(spec)
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.verify_process_effect(&spec.agent_id)?;
        self.inner.adopt_matrixd(spec)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::FLEET_START_TRUST_PROFILE_SCHEMA_VERSION;
    use crate::FleetStartNodeTrustV1;
    use crate::FleetStartTrustKeyV1;
    use crate::FleetStartTrustProfileV1;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
    const DISTRIBUTOR_KEY: &str =
        "fa4834147f6e690c3693eff61336046403cd8ae2a14f31b3c407358569239565";
    const NODE_KEY: &str = "197f6b23e16c8532c6abc838facd5ea789be0c76b2920334039bfa8b3d368d61";

    fn trust_profile() -> FleetStartTrustProfileV1 {
        FleetStartTrustProfileV1 {
            schema_version: FLEET_START_TRUST_PROFILE_SCHEMA_VERSION,
            local_node_id: "node-a".into(),
            distributor_id: "revocation-distributor".into(),
            distributor_keys: vec![FleetStartTrustKeyV1 {
                key_id: "distributor-v1".into(),
                verifying_key_hex: DISTRIBUTOR_KEY.into(),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: 99,
            }],
            nodes: vec![FleetStartNodeTrustV1 {
                node_id: "node-a".into(),
                keys: vec![FleetStartTrustKeyV1 {
                    key_id: "node-a-v1".into(),
                    verifying_key_hex: NODE_KEY.into(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 99,
                }],
            }],
        }
    }

    #[tokio::test]
    async fn scoped_driver_rejects_before_process_effect_without_current_grant() {
        let directory = tempfile::tempdir().expect("tempdir");
        let state_root = directory.path().join("state");
        std::fs::create_dir(&state_root).expect("state root");
        let admission =
            FleetStartAdmission::new(&state_root, trust_profile()).expect("start admission");
        let agent_id = AgentId::parse(AGENT_ID).expect("agent id");

        let result = with_fleet_start_admission(admission, async move {
            let driver = UnixProcessDriver::new(8).expect("driver");
            driver.verify_process_effect(&agent_id)
        })
        .await;

        let error = result.expect_err("missing grant must deny process effect");
        assert!(
            error
                .to_string()
                .contains("runtime.fleet final-use admission rejected")
        );
    }
}

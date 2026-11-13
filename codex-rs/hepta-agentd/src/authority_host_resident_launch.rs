//! Normal Root service entry for the original V3 candidate continuation.
//! Configuration describes original inputs; it cannot construct a role owner.

use std::io;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::Arc;

use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use serde::Deserialize;

use crate::CellQ24ModelFilesV1;
use crate::LoadedCellQ24ModelV1;
use crate::RootResidentCandidateServiceV1;
use crate::RootResidentLearningConsumerV3;
use crate::RootResidentLearningReadbackAuthorizationV3;
use crate::RootResidentLearningRegistrationV3;
use crate::authority_host_config::read_root_json;

#[path = "authority_host_resident_launch_inputs.rs"]
mod inputs;
#[path = "authority_host_resident_trust_file.rs"]
mod trust;

/// Each descriptor is inherited from the actual Root supervisor and consumed
/// once. The ten role streams remain in the separate original SCM_RIGHTS
/// handoff, with the original recipient/pidfd/purpose/deadline checks.
pub struct RootResidentCandidateProcessInputsV3 {
    pub stage_handoff: UnixDatagram,
    pub consumer_stream: UnixStream,
    pub original_consumer_pidfd: OwnedFd,
    pub baseline_files: CellQ24ModelFilesV1,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReadbackFile {
    schema_version: u32,
    purpose: String,
    intent: SignedFinalUseGrant,
    lease: AuthorityLease,
}

enum Purpose<'a> {
    Fresh,
    Readback(&'a Path),
}

/// Call inside the resident Tokio runtime, after the original ordinary A has
/// completed and its exact initial request and independent B plan are known.
/// No error promises that a successfully registered Root record was unwritten;
/// uncertainty requires the separate original readback authorization.
pub fn prepare_host_resident_candidate_v3(
    config_file: &Path,
    deployment_file: &Path,
    trusted_evidence_file: &Path,
    original: RootResidentCandidateProcessInputsV3,
) -> io::Result<RootResidentCandidateServiceV1> {
    prepare(
        config_file,
        deployment_file,
        trusted_evidence_file,
        original,
        Purpose::Fresh,
    )
}

/// Open-only recovery consumes the same original deployment and a distinct
/// current readback grant/lease. Neither file can promote recovered custody to
/// fresh execution or recreate a role channel.
pub fn recover_host_resident_candidate_v3(
    config_file: &Path,
    deployment_file: &Path,
    trusted_evidence_file: &Path,
    original: RootResidentCandidateProcessInputsV3,
    readback_file: &Path,
) -> io::Result<RootResidentCandidateServiceV1> {
    prepare(
        config_file,
        deployment_file,
        trusted_evidence_file,
        original,
        Purpose::Readback(readback_file),
    )
}

fn prepare(
    config_file: &Path,
    deployment_file: &Path,
    trusted_evidence_file: &Path,
    original: RootResidentCandidateProcessInputsV3,
    purpose: Purpose<'_>,
) -> io::Result<RootResidentCandidateServiceV1> {
    // SAFETY: geteuid has no pointer or ownership precondition.
    if unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::other("original Root resident process required"));
    }
    let trust = trust::OriginalHostTrust::read(trusted_evidence_file)?;
    let RootResidentCandidateProcessInputsV3 {
        stage_handoff,
        consumer_stream,
        original_consumer_pidfd,
        baseline_files,
    } = original;
    let baseline = Arc::new(
        LoadedCellQ24ModelV1::open_files(baseline_files).map_err(io::Error::other)?,
    );
    let deployment = inputs::OriginalDeployment::read(deployment_file, &trust, baseline)?;
    let readback = match purpose {
        Purpose::Fresh => None,
        Purpose::Readback(path) => {
            let value: ReadbackFile = read_root_json(path)?;
            if value.schema_version != 3
                || value.purpose != "hepta.host-resident-learning.readback-deployment.v3"
            {
                return Err(io::Error::other("original resident readback profile differs"));
            }
            Some(RootResidentLearningReadbackAuthorizationV3::from_original_root(
                &deployment.profile,
                value.intent,
                value.lease,
            )?)
        }
    };
    let handoff = crate::receive_root_candidate_stage_handoff(
        stage_handoff,
        &deployment.profile,
        deployment.handoff_timeout,
    )
    .map_err(io::Error::other)?;
    let registration = match readback {
        Some(authorization) => super::recover_host_resident_learning_v3(
            config_file,
            deployment.profile,
            authorization,
        )?,
        None => super::register_host_resident_learning_v3(config_file, deployment.profile)?,
    };
    let (peer, uid, timeout, lifetime) = deployment.consumer.into_peer();
    RootResidentLearningRegistrationV3::into_candidate_service(
        registration,
        deployment.inputs,
        handoff,
        RootResidentLearningConsumerV3 {
            stream: consumer_stream,
            peer,
            uid,
            original_consumer_pidfd,
            timeout,
            lifetime,
        },
    )
    .map_err(io::Error::other)
}

#[path = "authority_host_resident_enrollment.rs"]
mod enrollment;
pub use enrollment::RootResidentCandidateEnrollmentInputsV3;
pub use enrollment::RootResidentCandidateEnrollmentServiceV3;
pub use enrollment::prepare_host_resident_candidate_enrollment_v3;
pub use enrollment::recover_host_resident_candidate_enrollment_v3;
pub(crate) use enrollment::connect_original_resident_enrollment;
pub(crate) use enrollment::{OriginalTaskResidentInputs, OriginalTaskResidentPaths,
    OriginalTaskResidentPrepared, OriginalTaskResidentPurpose, prepare_original_task_resident,
    OriginalTaskPrefreezeState, prepare_original_task_prefreeze};

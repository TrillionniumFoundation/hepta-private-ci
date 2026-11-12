//! The final complete-task purpose belongs to the existing Root session.
//! Protected deployment data fixes both the current recipient and old inputs;
//! it neither opens a legacy learning checkpoint nor freezes a Dataset scope.

use std::io;
use std::os::fd::OwnedFd;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use serde::Deserialize;

use super::PreparedHostAuthoritySession;
use super::generation_publication::deployment::files::MetadataFile;
use crate::HostAuthorityLearningProfileV1;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityService;
use crate::HostAuthorityServiceConfig;
use crate::RootHistoricalSourceInputsV1;
use crate::authority_host_runtime::RootInitialRunStartFilesV1;
use crate::authority_host_service::generation_initial::cell_retention::RootHistoricalCellInputsV1;
use crate::authority_host_service::generation_initial::historical_source_pin::RootOriginalHistoricalCompleteTaskObservationV1;
use crate::authority_host_service::generation_initial::historical_source_pin::RootOriginalHistoricalTaskReadV1;
use crate::authority_host_service::generation_initial::historical_source_pin::RootRetainedHistoricalCompleteTaskV1;
use crate::authority_host_service::generation_initial::original_root;
use crate::root_historical_task_read_protocol::HistoricalReadOperationV1;
use crate::root_historical_task_read_protocol::HistoricalTaskReadProfileV1;
use crate::root_historical_task_read_protocol::HistoricalTaskReadResponseV1;
use crate::root_historical_task_read_protocol::PURPOSE;
use crate::root_historical_task_read_protocol::SOCKET;
use crate::root_historical_task_read_protocol::WIRE_BOUND;

#[path = "authority_host_historical_learning_trust.rs"]
mod learning_trust;
#[path = "authority_host_post_a_learning.rs"]
mod post_a;
#[path = "authority_host_post_a_files.rs"]
mod post_a_files;
#[path = "authority_host_post_a_freeze.rs"]
mod post_a_freeze;
use crate::root_historical_learning_trust_data::HistoricalLearningTrustResponseV1;
use crate::root_historical_learning_trust_data::TRUST_PURPOSE;
use learning_trust::RootHistoricalLearningTrustV1;
#[path = "authority_host_historical_read_session.rs"]
mod prepared;
#[path = "authority_host_historical_read_runtime.rs"]
mod runtime;
pub(super) use runtime::BoundHistoricalTaskRead;
pub(super) use runtime::serve_optional;

const DEPLOYMENT_PURPOSE: &str = "runtime.learning.historical-task-deployment.v1";
const PREPARED: u8 = 0;
const SEALED: u8 = 1;
const SERVING: u8 = 2;
const STOPPED: u8 = 3;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HistoricalTaskDeploymentData {
    schema_version: u32,
    purpose: String,
    initial: HostAuthorityLearningProfileV1,
    target: CellGenerationOwnerBindingV1,
    source_deployment: PathBuf,
    run_start_deployment: PathBuf,
    ledger_deployment: PathBuf,
    learning_trust_deployment: PathBuf,
}

pub(super) struct HistoricalTaskReadRuntime {
    metadata: MetadataFile,
    deployment: HistoricalTaskDeploymentData,
    profile: HistoricalTaskReadProfileV1,
    task: RootRetainedHistoricalCompleteTaskV1,
    learning_trust: RootHistoricalLearningTrustV1,
    socket: PathBuf,
    phase: AtomicU8,
}

impl HistoricalTaskReadRuntime {
    fn open_original(
        path: &Path,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
    ) -> io::Result<Self> {
        original_root()?;
        let (metadata, bytes) = MetadataFile::open_metadata(path)?;
        let deployment: HistoricalTaskDeploymentData =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if deployment.schema_version != 1
            || deployment.purpose != DEPLOYMENT_PURPOSE
            || deployment.initial.schema_version != 1
            || deployment.initial.update_scope.is_some()
        {
            return Err(io::Error::other(
                "original unfrozen historical deployment required",
            ));
        }
        deployment.target.digest().map_err(io::Error::other)?;
        let identity = registration.registered_identity.identity()?;
        let (profile, task, learning_trust) = service.with_learning_profile(
            config,
            registration,
            owner,
            &deployment.initial,
            |initial, proof| {
                metadata.require_metadata_unchanged()?;
                let learning_trust = RootHistoricalLearningTrustV1::open_original(
                    service,
                    &deployment.learning_trust_deployment,
                    &initial,
                    &deployment.target,
                )?;
                let mut profile: HistoricalTaskReadProfileV1 = HistoricalTaskReadProfileV1 {
                    purpose: PURPOSE.into(),
                    identity: crate::neuron_generation_process_identity_digest_v1(&identity)
                        .map_err(io::Error::other)?
                        .to_string(),
                    writer: proof,
                    initial: codex_hepta_types::Digest32::of_parts(&[
                        b"hepta.root.historical-task-read.initial.v1\0",
                        deployment.initial.encoded_initial().as_bytes(),
                    ])
                    .to_string(),
                    deployment: metadata.digest().to_string(),
                    learning_trust: learning_trust.pin.clone(),
                    binding: String::new(),
                };
                profile.binding = profile.digest()?;
                profile.require_original_context(
                    &identity,
                    &profile.writer,
                    &deployment.initial,
                )?;
                let task = RootRetainedHistoricalCompleteTaskV1::open_existing(
                    RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?,
                    deployment.target.clone(),
                    deployment.ledger_deployment.clone(),
                    || {
                        RootHistoricalCellInputsV1::open_original_cell_deployment(
                            &deployment.source_deployment,
                        )
                    },
                )?;
                metadata.require_metadata_unchanged()?;
                RootHistoricalLearningTrustV1::revalidate(&learning_trust, service, &initial)?;
                Ok((profile, task, learning_trust))
            },
        )?;
        let socket = config
            .sockets
            .observation
            .parent()
            .ok_or_else(|| io::Error::other("original Root socket parent missing"))?
            .join(SOCKET);
        metadata.require_metadata_unchanged()?;
        Ok(Self {
            metadata,
            deployment,
            profile,
            task,
            learning_trust,
            socket,
            phase: AtomicU8::new(PREPARED),
        })
    }

    fn observe_complete_task(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        operation: HistoricalReadOperationV1,
        request_id: u64,
        end: Instant,
    ) -> io::Result<Vec<u8>> {
        self.task
            .with_original_historical_task(service, end, |read| {
                require_end(end)?;
                self.metadata.require_metadata_unchanged()?;
                let (reply, initial) = service.with_learning_profile(
                    config,
                    registration,
                    owner,
                    &self.deployment.initial,
                    |initial, proof| {
                        let expected = self.profile.require_original_context(
                            &registration.registered_identity.identity()?,
                            &proof,
                            &self.deployment.initial,
                        )?;
                        if expected != initial || self.phase.load(Ordering::Acquire) != SERVING {
                            return Err(io::Error::other("original historical recipient changed"));
                        }
                        RootHistoricalLearningTrustV1::revalidate(&self.learning_trust, service, &initial)?;
                        RootOriginalHistoricalTaskReadV1::require_original_target(read, &self.deployment.target)?;
                        let observed: RootOriginalHistoricalCompleteTaskObservationV1 = RootOriginalHistoricalTaskReadV1::observe_original_task(
                            read,
                            |identity| {
                                RootHistoricalSourceInputsV1::open_original_source_deployment(
                                    &self.deployment.source_deployment,
                                    identity,
                                )
                            },
                            || {
                                RootInitialRunStartFilesV1::open_original_deployment(
                                    &self.deployment.run_start_deployment,
                                )
                                .map(Arc::new)
                            },
                        )?;
                        let ledger = RootOriginalHistoricalCompleteTaskObservationV1::ledger_read_data(&observed)?;
                        RootHistoricalLearningTrustV1::require_original_ledger(&self.learning_trust, &ledger)?;
                        let data_cut = RootOriginalHistoricalCompleteTaskObservationV1::data_cut_digest(&observed).to_string();
                        let reply = match operation {
                            HistoricalReadOperationV1::Task => serde_json::to_vec(&HistoricalTaskReadResponseV1 {
                                schema: 1,
                                purpose: PURPOSE.into(),
                                request_id,
                                profile: self.profile.binding.clone(),
                                data_cut,
                                ledger,
                                publication: RootOriginalHistoricalCompleteTaskObservationV1::publication_read_data(&observed),
                            }),
                            HistoricalReadOperationV1::LearningTrust => serde_json::to_vec(&HistoricalLearningTrustResponseV1 {
                                schema: 1,
                                purpose: TRUST_PURPOSE.into(),
                                request_id,
                                profile: self.profile.binding.clone(),
                                data_cut,
                                pin: self.learning_trust.pin.clone(),
                                payload: RootHistoricalLearningTrustV1::read_original_payload(&self.learning_trust, service, &initial, &ledger)?,
                            }),
                        }.map_err(io::Error::other)?;
                        if reply.is_empty() || reply.len() > WIRE_BOUND {
                            return Err(io::Error::other(
                                "complete historical reply exceeds bound",
                            ));
                        }
                        RootHistoricalLearningTrustV1::revalidate(&self.learning_trust, service, &initial)?;
                        require_end(end)?;
                        Ok((reply, initial))
                    },
                )?;
                // Actual current recipient postchecks returned before the complete
                // task's final physical rereads and all refusal Ready transitions.
                self.metadata.require_metadata_unchanged()?;
                RootHistoricalLearningTrustV1::revalidate(&self.learning_trust, service, &initial)?;
                require_end(end)?;
                Ok(reply)
            })
    }
}

fn require_end(end: Instant) -> io::Result<()> {
    original_root()?;
    if Instant::now() >= end {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "original historical read expired",
        ));
    }
    Ok(())
}

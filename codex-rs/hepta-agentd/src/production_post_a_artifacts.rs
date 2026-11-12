//! The ordinary path consumes original Artifact owner and independent Selector
//! signatures. No key or fallback publication is supplied by this composition.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::Digest32;
use tokio_util::sync::CancellationToken;

use super::OriginalFiles;
use super::late_input::OriginalLateInput;
use super::late_input::OriginalLateValue;
use super::post_a_remaining;
use super::refused;
use crate::AgentdError;
use crate::AgentdGenerationSelectionFilesV1;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::OriginalCellQ24ArtifactPublicationDriverV1;
use crate::OriginalCellQ24LearningStageOwnersV1;
use crate::OriginalCellQ24RetainedArtifactForRootV1;
use crate::OriginalCellQ24SelectedArtifactForRootV1;
use crate::OriginalCellQ24SelectionInputsV1;
use crate::authority_host_runtime::PublicationInputData;
use crate::authority_host_runtime::publication_data::CurrentData;
use crate::authority_host_runtime::publication_data::Mode;
use crate::authority_host_runtime::publication_data::SelectionData;
use crate::cell_q24_publication_driver::validation::Decision;
use crate::root_generation_publication_inputs::OriginalPreparedPublicationRoute;

#[path = "production_post_a_artifact_data.rs"]
mod data;
#[path = "production_post_a_artifact_request.rs"]
mod request;
pub(super) use data::ArtifactFilesData;

pub(super) struct OriginalArtifactPlan {
    lease: OriginalLateInput,
    head: OriginalLateInput,
    selection: OriginalLateInput,
    end: Instant,
}

pub(super) struct OriginalSelectedArtifacts {
    pub(super) selected: OriginalCellQ24SelectedArtifactForRootV1,
    pub(super) signed: SignedArtifactSelectionV1,
    pub(super) custody: OriginalArtifactCustody,
}

pub(super) struct OriginalArtifactCustody {
    lease: OriginalLateValue,
    head: Option<OriginalLateValue>,
    selection: OriginalLateValue,
    end: Instant,
}

impl OriginalArtifactCustody {
    pub(super) fn require_original(&self) -> Result<(), AgentdError> {
        post_a_remaining(self.end)?;
        self.lease.require_unchanged()?;
        if let Some(head) = &self.head {
            head.require_unchanged()?;
        }
        self.selection.require_unchanged()?;
        post_a_remaining(self.end)?;
        Ok(())
    }
}

impl OriginalArtifactPlan {
    pub(super) fn open_original(
        data: ArtifactFilesData,
        files: &mut OriginalFiles,
        end: Instant,
    ) -> Result<Self, AgentdError> {
        Ok(Self {
            lease: OriginalLateInput::open_original(data.writer_lease, files, end)?,
            head: OriginalLateInput::open_original(data.candidate_head, files, end)?,
            selection: OriginalLateInput::open_original(data.independent_selection, files, end)?,
            end,
        })
    }

    pub(super) async fn publish_and_select_original(
        self,
        route: &OriginalPreparedPublicationRoute,
        owners: Arc<OriginalCellQ24LearningStageOwnersV1>,
        snapshot: LearningIterationSnapshotV1,
        final_use: Arc<FinalUseAuthority>,
        clock: Arc<dyn AuthorityClock>,
        files: &mut OriginalFiles,
        cancelled: &CancellationToken,
    ) -> Result<OriginalSelectedArtifacts, AgentdError> {
        route.require_current()?;
        let lease = self.lease.wait_original_value(cancelled).await?;
        let writer_lease = lease.with_original_bytes(|bytes| {
            let data: data::WriterLeaseData = serde_json::from_slice(bytes)?;
            data.original_signed_lease()
        })?;
        if writer_lease.producer_id != snapshot.owners.trainer {
            return Err(refused(
                "Artifact lease belongs to another original Trainer",
            ));
        }
        let (authority, mode) = route.with_original_data(|fixed| {
            lease.require_unchanged()?;
            let inputs = &fixed.inputs;
            let withdrawal_registry = withdrawal_floor(inputs, files)?;
            let now = clock.now_unix_ms().map_err(refused)?;
            let artifacts =
                LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                    root: inputs.artifact_root.clone(),
                    trust: inputs.owner_trust.original_owner_trust()?,
                    writer_lease,
                    required_current_head: Some(inputs.retained_current.original_current()?),
                    withdrawal_registry,
                    storage_binding: Digest32::from_array(inputs.storage_binding),
                    now,
                })
                .map_err(refused)?;
            let authority = AgentdGenerationUpdateAuthoritiesV1::new(
                Arc::new(Mutex::new(artifacts)),
                final_use,
                clock,
            )?;
            lease.require_unchanged()?;
            Ok((authority, inputs.mode))
        })?;
        let decision = Decision::new(snapshot.clone()).map_err(refused)?;
        decision.require_root_publication().map_err(refused)?;
        let (published, retained, head) = if decision.adopts() {
            let driver = OriginalCellQ24ArtifactPublicationDriverV1::for_qualified_adoption(
                Arc::clone(&owners),
                snapshot,
                authority.clone(),
            )
            .await
            .map_err(refused)?;
            let (published, head) = match mode {
                Mode::Reserve => {
                    let head = self.head.wait_original_value(cancelled).await?;
                    route.require_current()?;
                    lease.require_unchanged()?;
                    let signed = head.with_original_bytes(|bytes| {
                        let data: CurrentData = serde_json::from_slice(bytes)?;
                        Ok(data.original_current()?)
                    })?;
                    let request = {
                        let locked = authority.artifacts.writer()?.lock().map_err(refused)?;
                        request::original_request(
                            &decision,
                            driver
                                .candidate_manifest()
                                .ok_or_else(|| refused("actual B manifest absent"))?,
                            signed,
                            &locked,
                            authority.now()?,
                        )?
                    };
                    let published = OriginalCellQ24ArtifactPublicationDriverV1::publish_candidate(
                        driver, request,
                    )
                    .await
                    .map_err(refused)?;
                    head.require_unchanged()?;
                    (published, Some(head))
                }
                Mode::Recover => (
                    OriginalCellQ24ArtifactPublicationDriverV1::recover_published(driver)
                        .await
                        .map_err(refused)?,
                    None,
                ),
            };
            (Some(published), None, head)
        } else {
            let retained = OriginalCellQ24RetainedArtifactForRootV1::from_original_result(
                owners,
                snapshot,
                authority.clone(),
            )
            .await
            .map_err(refused)?;
            (None, Some(retained), None)
        };
        route.require_current()?;
        lease.require_unchanged()?;
        let selection = self.selection.wait_original_value(cancelled).await?;
        let signed = selection.with_original_bytes(|bytes| {
            let data: SelectionData = serde_json::from_slice(bytes)?;
            Ok(data.original_selection()?)
        })?;
        let input = route.with_original_data(|fixed| {
            selection.require_unchanged()?;
            let inputs = &fixed.inputs;
            let trust = inputs.owner_trust.original_owner_trust()?;
            let verifier = inputs.selector_trust.original_selector(&trust)?;
            let floor = withdrawal_floor(inputs, files)?;
            let now = authority.now()?;
            // SAFETY: geteuid reads only this process's actual kernel owner.
            let uid = unsafe { libc::geteuid() };
            let reader = LearningArtifactReadViewV1::open_original(
                inputs.artifact_root.clone(),
                uid,
                trust,
                inputs.retained_current.original_current()?,
                now,
            )
            .map_err(refused)?
            .with_original_withdrawal_floor(Digest32::from_array(inputs.storage_binding), floor)
            .map_err(refused)?;
            let paths = reader
                .locate_selected_original_files(&verifier, &signed, now)
                .map_err(refused)?;
            let input = OriginalCellQ24SelectionInputsV1 {
                verifier: verifier.clone(),
                signed: signed.clone(),
                files: AgentdGenerationSelectionFilesV1 {
                    registry_snapshot: files.read(&paths.0)?,
                    payload: files.read(&paths.1)?,
                },
            };
            if reader
                .locate_selected_original_files(&verifier, &signed, now)
                .map_err(refused)?
                != paths
            {
                return Err(refused("actual independent selection files changed"));
            }
            selection.require_unchanged()?;
            Ok(input)
        })?;
        let selected = match (published, retained) {
            (Some(published), None) => {
                crate::OriginalCellQ24PublishedArtifactForRootV1::accept_selection(published, input)
                    .await
                    .map_err(refused)?
            }
            (None, Some(retained)) => {
                OriginalCellQ24RetainedArtifactForRootV1::accept_selection(retained, input)
                    .await
                    .map_err(refused)?
            }
            _ => return Err(refused("exact original Artifact branch required")),
        };
        let custody = OriginalArtifactCustody {
            lease,
            head,
            selection,
            end: self.end,
        };
        custody.require_original()?;
        route.require_current()?;
        Ok(OriginalSelectedArtifacts {
            selected,
            signed,
            custody,
        })
    }
}

fn withdrawal_floor(
    inputs: &PublicationInputData,
    files: &mut OriginalFiles,
) -> Result<DatasetWithdrawalRegistry, AgentdError> {
    let data = &inputs.withdrawal;
    read_dataset_withdrawal_snapshot(
        files.read(&inputs.withdrawal_file)?,
        DatasetWithdrawalSnapshotReceiptV1 {
            binding: Digest32::from_array(data.binding),
            scope_digest: Digest32::from_array(data.scope),
            head_digest: Digest32::from_array(data.head),
            file_digest: Digest32::from_array(data.file_digest),
            records: data.records,
            encoded_bytes: data.encoded_bytes,
        },
    )
    .map_err(refused)
}

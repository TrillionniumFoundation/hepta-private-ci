//! An immutable first Root acceptance, protected by a separate durable refusal
//! attempt before every primary read. Missing facts are never inferred from a
//! terminal checkpoint. The complete original Root operation finishes before
//! first initialization and before the independent attempt can become Ready.

use std::io;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::require_end;
use crate::HostAuthorityLearningProfileV1;
use crate::authority_host_service::generation_initial::RootCompletedLearningRefusalV1;

const PURPOSE: &str = "runtime.learning.completed-acceptance.v1";

/// DATA only. Constructing or deserializing this record grants no historical
/// receipt, new execution, checkpoint owner or current model authority.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RootCompletedLearningAcceptanceDataV1 {
    pub(super) schema: u8,
    pub(super) purpose: String,
    pub(super) initial: String,
    pub(super) target: String,
    pub(super) deployment: String,
    pub(super) original_profile: String,
    pub(super) frozen_scope: String,
    pub(super) terminal_head: String,
    pub(super) checkpoint: String,
    pub(super) root_verified_at_seconds: u64,
    pub(super) original_task: String,
    pub(super) journals: [String; 7],
    pub(super) signatures: [String; 7],
    pub(super) independent_b: String,
    pub(super) publication: String,
}

impl RootCompletedLearningAcceptanceDataV1 {
    pub(crate) fn data_digest(&self) -> io::Result<Digest32> {
        let bytes = serde_json::to_vec(self).map_err(io::Error::other)?;
        if bytes.len() > 12 * 1024 {
            return Err(io::Error::other(
                "bounded original completed acceptance required",
            ));
        }
        Ok(Digest32::of_parts(&[
            b"hepta.root.completed-learning.acceptance.v1\0",
            &bytes,
        ]))
    }

    fn require_original(
        &self,
        initial: &LearningIterationSnapshotV1,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<()> {
        if self.schema != 1
            || self.purpose != PURPOSE
            || self.root_verified_at_seconds == 0
            || self.initial != initial.head_digest.to_string()
            || self.target
                != Digest32::from_array(target.digest().map_err(io::Error::other)?).to_string()
        {
            return Err(io::Error::other(
                "original completed acceptance binding differs",
            ));
        }
        for field in [
            &self.initial,
            &self.target,
            &self.deployment,
            &self.frozen_scope,
            &self.terminal_head,
            &self.checkpoint,
            &self.original_task,
            &self.independent_b,
            &self.publication,
        ]
        .into_iter()
        .chain(self.journals.iter())
        .chain(self.signatures.iter())
        {
            let digest: Digest32 = field.parse().map_err(io::Error::other)?;
            if digest.is_zero() || digest.to_string() != *field {
                return Err(io::Error::other(
                    "canonical completed acceptance digest required",
                ));
            }
        }
        let profile: HostAuthorityLearningProfileV1 =
            serde_json::from_str(&self.original_profile).map_err(io::Error::other)?;
        if serde_json::to_string(&profile).map_err(io::Error::other)? != self.original_profile
            || profile.original_initial_data()? != *initial
            || profile.require_cell_scope(initial)?.binding().to_string() != self.frozen_scope
        {
            return Err(io::Error::other(
                "original completed frozen profile differs",
            ));
        }
        self.data_digest()?;
        Ok(())
    }
}

pub(super) struct CompletedLearningRecord;

impl CompletedLearningRecord {
    pub(super) fn accept<T>(
        original: &RootCompletedLearningRefusalV1,
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
        initial: &LearningIterationSnapshotV1,
        end: Instant,
        action: impl FnOnce() -> io::Result<(RootCompletedLearningAcceptanceDataV1, T)>,
    ) -> io::Result<(Digest32, T)> {
        require_end(end)?;
        RootCompletedLearningRefusalV1::accept_registered(original, || {
            // Every live Root and physical postcheck in action has returned
            // before this first record exists. An error leaves Armed.
            let (accepted, value) = action()?;
            accepted.require_original(initial, target)?;
            require_end(end)?;
            let owner = completed_learning_acceptance_owner(initial);
            let store =
                HostAuthorityFrontierStore::initialize(root, owner.clone(), accepted.clone())
                    .map_err(io::Error::other)?;
            if store.load(&owner).map_err(io::Error::other)? != accepted {
                return Err(io::Error::other(
                    "original terminal acceptance acknowledgement differs",
                ));
            }
            require_end(end)?;
            Ok((accepted.data_digest()?, value))
        })
    }

    pub(super) fn read<T>(
        root: Arc<RootAuthorityDirectory>,
        target: &CellGenerationOwnerBindingV1,
        initial: &LearningIterationSnapshotV1,
        end: Instant,
        action: impl FnOnce(&RootCompletedLearningAcceptanceDataV1) -> io::Result<T>,
    ) -> io::Result<(Digest32, T)> {
        require_end(end)?;
        RootCompletedLearningRefusalV1::read_original(
            Arc::clone(&root),
            target,
            initial.head_digest,
            || {
                let owner = completed_learning_acceptance_owner(initial);
                let store: HostAuthorityFrontierStore<RootCompletedLearningAcceptanceDataV1> =
                    HostAuthorityFrontierStore::open(root, owner.clone())
                        .map_err(io::Error::other)?;
                let accepted = store.load(&owner).map_err(io::Error::other)?;
                accepted.require_original(initial, target)?;
                let value = action(&accepted);
                // Even a swallowed callback failure cannot skip the physical
                // primary readback. Nothing in recovery writes this record.
                if store.load(&owner).map_err(io::Error::other)? != accepted {
                    return Err(io::Error::other("original terminal acceptance changed"));
                }
                require_end(end)?;
                Ok((accepted.data_digest()?, value?))
            },
        )
    }
}

pub(crate) fn completed_learning_acceptance_owner(initial: &LearningIterationSnapshotV1) -> String {
    format!(
        "completed-learning/{}",
        Digest32::of_parts(&[
            b"hepta.root.completed-learning.owner.v1\0",
            initial.request.operation_id.as_str().as_bytes(),
        ])
    )
}

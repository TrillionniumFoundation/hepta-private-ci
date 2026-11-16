//! Schema 3 uses the original protected Root CAS, with no idempotent execution.
//! Old schema 1/2 owners never construct, mutate, or resume this record.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use super::profile::RootResidentLearningProfileV3;
use super::profile::invalid;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ResidentRecordV3 {
    schema: u8,
    binding: String,
    snapshot: Option<String>,
    dispatch: Option<ResidentDispatchV3>,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ResidentDispatchV3 {
    head: String,
    stage: u8,
}

/// Data readback is never an execution token, even for the exact initial cut.
pub(crate) struct ResidentSnapshotV3 {
    pub(crate) snapshot: Option<LearningIterationSnapshotV1>,
    pub(crate) dispatch_pending: bool,
}

pub(crate) struct ResidentCheckpointV3 {
    store: HostAuthorityFrontierStore<ResidentRecordV3>,
    owner_id: String,
    profile: RootResidentLearningProfileV3,
    fresh_registration: bool,
    admission_attempted: AtomicBool,
}

/// No Clone, deserialization, caller constructor, or recovery conversion.
/// Only the actual successful vacant-to-initial CAS creates this value.
pub(crate) struct FreshResidentCheckpointV3 {
    owner_id: String,
    current: ResidentRecordV3,
}

impl ResidentCheckpointV3 {
    pub(super) fn register(
        root: Arc<RootAuthorityDirectory>,
        profile: RootResidentLearningProfileV3,
    ) -> io::Result<Self> {
        let owner_id = profile.owner_id();
        let store =
            HostAuthorityFrontierStore::initialize(root, owner_id.clone(), Self::vacant(&profile))
                .map_err(io::Error::other)?;
        let owner = Self {
            store,
            owner_id,
            profile,
            fresh_registration: true,
            admission_attempted: AtomicBool::new(false),
        };
        owner.read()?;
        Ok(owner)
    }

    pub(super) fn recover(
        root: Arc<RootAuthorityDirectory>,
        profile: RootResidentLearningProfileV3,
    ) -> io::Result<Self> {
        let owner_id = profile.owner_id();
        let store =
            HostAuthorityFrontierStore::open(root, owner_id.clone()).map_err(io::Error::other)?;
        let owner = Self {
            store,
            owner_id,
            profile,
            fresh_registration: false,
            admission_attempted: AtomicBool::new(true),
        };
        owner.read()?;
        Ok(owner)
    }

    fn vacant(profile: &RootResidentLearningProfileV3) -> ResidentRecordV3 {
        ResidentRecordV3 {
            schema: 3,
            binding: profile.binding.to_string(),
            snapshot: None,
            dispatch: None,
        }
    }

    pub(super) fn read(&self) -> io::Result<ResidentSnapshotV3> {
        let (record, snapshot) = self.load()?;
        Ok(ResidentSnapshotV3 {
            snapshot,
            dispatch_pending: record.dispatch.is_some(),
        })
    }

    pub(super) fn admit(&self) -> io::Result<Option<FreshResidentCheckpointV3>> {
        if !self.fresh_registration || self.admission_attempted.swap(true, Ordering::AcqRel) {
            return Ok(None);
        }
        let (current, snapshot) = self.load()?;
        if snapshot.is_some() || current != Self::vacant(&self.profile) {
            return Ok(None);
        }
        let next = ResidentRecordV3 {
            schema: 3,
            binding: self.profile.binding.to_string(),
            snapshot: Some(self.profile.encoded_initial()?),
            dispatch: None,
        };
        // No equality shortcut is permission. A conflict or lost durability ACK
        // returns no fresh token; any later entry can only read the same owner.
        self.store
            .compare_and_set(&self.owner_id, &current, &next)
            .map_err(io::Error::other)?;
        Ok(Some(FreshResidentCheckpointV3 {
            owner_id: self.owner_id.clone(),
            current: next,
        }))
    }

    pub(super) fn begin_dispatch(
        &self,
        token: &mut FreshResidentCheckpointV3,
        predecessor: &LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> io::Result<()> {
        self.require_token(token)?;
        let encoded = encode(predecessor)?;
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(predecessor.clone())
            .map_err(io::Error::other)?;
        if token.current.snapshot.as_ref() != Some(&encoded)
            || token.current.dispatch.is_some()
            || coordinator.next_stage() != Some(stage)
        {
            return Err(invalid("resident dispatch predecessor or stage differs"));
        }
        let mut next = token.current.clone();
        next.dispatch = Some(ResidentDispatchV3 {
            head: predecessor.head_digest.to_string(),
            stage: stage_code(stage),
        });
        self.store
            .compare_and_set(&self.owner_id, &token.current, &next)
            .map_err(io::Error::other)?;
        token.current = next;
        Ok(())
    }

    pub(super) fn require_dispatch(
        &self,
        token: &FreshResidentCheckpointV3,
        predecessor: &LearningIterationSnapshotV1,
    ) -> io::Result<()> {
        self.require_token(token)?;
        self.profile
            .scope
            .validate_snapshot(predecessor)
            .map_err(io::Error::other)?;
        let stage = LearningIterationCoordinatorV1::from_snapshot(predecessor.clone())
            .map_err(io::Error::other)?
            .next_stage()
            .ok_or_else(|| invalid("resident completed cut has no dispatch"))?;
        let dispatch = ResidentDispatchV3 {
            head: predecessor.head_digest.to_string(),
            stage: stage_code(stage),
        };
        if token.current.snapshot.as_ref() != Some(&encode(predecessor)?)
            || token.current.dispatch.as_ref() != Some(&dispatch)
        {
            return Err(invalid(
                "resident effect does not match the same active continuation",
            ));
        }
        Ok(())
    }

    pub(super) fn checkpoint(
        &self,
        token: &mut FreshResidentCheckpointV3,
        predecessor: &LearningIterationSnapshotV1,
        next: &LearningIterationSnapshotV1,
    ) -> io::Result<()> {
        self.require_dispatch(token, predecessor)?;
        self.profile
            .scope
            .validate_snapshot(next)
            .map_err(io::Error::other)?;
        LearningIterationCoordinatorV1::from_snapshot(next.clone()).map_err(io::Error::other)?;
        if next.request != predecessor.request
            || next.owners != predecessor.owners
            || next.receipts.len() != predecessor.receipts.len() + 1
            || !next.receipts.starts_with(&predecessor.receipts)
            || next.receipts.last().is_none_or(|receipt| {
                receipt.predecessor != predecessor.head_digest
                    || token.current.dispatch.as_ref().is_none_or(|dispatch| {
                        stage_code(receipt.observation.stage()) != dispatch.stage
                    })
            })
        {
            return Err(invalid(
                "resident checkpoint is not the dispatched single successor",
            ));
        }
        let record = ResidentRecordV3 {
            schema: 3,
            binding: self.profile.binding.to_string(),
            snapshot: Some(encode(next)?),
            dispatch: None,
        };
        self.store
            .compare_and_set(&self.owner_id, &token.current, &record)
            .map_err(io::Error::other)?;
        token.current = record;
        Ok(())
    }

    fn require_token(&self, token: &FreshResidentCheckpointV3) -> io::Result<()> {
        if token.owner_id != self.owner_id || self.load()?.0 != token.current {
            return Err(invalid(
                "resident original CURRENT differs from the fresh continuation",
            ));
        }
        Ok(())
    }

    fn load(&self) -> io::Result<(ResidentRecordV3, Option<LearningIterationSnapshotV1>)> {
        let record = self.store.load(&self.owner_id).map_err(io::Error::other)?;
        if record.schema != 3 || record.binding != self.profile.binding.to_string() {
            return Err(invalid("resident Root record profile differs"));
        }
        let Some(encoded) = &record.snapshot else {
            if record.dispatch.is_some() {
                return Err(invalid("vacant resident record contains a dispatch"));
            }
            return Ok((record, None));
        };
        if encoded.len() > 10_924 {
            return Err(invalid(
                "resident snapshot exceeds the original codec bound",
            ));
        }
        let bytes = STANDARD_NO_PAD.decode(encoded).map_err(io::Error::other)?;
        let snapshot = decode_original_owner_snapshot_v1(&bytes).map_err(io::Error::other)?;
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
            .map_err(io::Error::other)?;
        self.profile
            .scope
            .validate_snapshot(&snapshot)
            .map_err(io::Error::other)?;
        if STANDARD_NO_PAD.encode(&bytes) != *encoded
            || snapshot.request != self.profile.initial.request
            || snapshot.owners != self.profile.initial.owners
        {
            return Err(invalid("resident snapshot canonical context differs"));
        }
        if let Some(dispatch) = &record.dispatch {
            let stage = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())
                .map_err(io::Error::other)?
                .next_stage()
                .ok_or_else(|| invalid("completed resident record still has dispatch intent"))?;
            if dispatch.head != snapshot.head_digest.to_string()
                || dispatch.stage != stage_code(stage)
            {
                return Err(invalid(
                    "resident dispatch does not match durable predecessor",
                ));
            }
        }
        Ok((record, Some(snapshot)))
    }
}

fn encode(snapshot: &LearningIterationSnapshotV1) -> io::Result<String> {
    Ok(STANDARD_NO_PAD
        .encode(encode_original_owner_snapshot_v1(snapshot).map_err(io::Error::other)?))
}

fn stage_code(stage: LearningIterationStageV1) -> u8 {
    match stage {
        LearningIterationStageV1::Experience => 0,
        LearningIterationStageV1::Dataset => 1,
        LearningIterationStageV1::Training => 2,
        LearningIterationStageV1::Evaluation => 3,
        LearningIterationStageV1::Proposal => 4,
        LearningIterationStageV1::Selection => 5,
        LearningIterationStageV1::NextUse => 6,
    }
}

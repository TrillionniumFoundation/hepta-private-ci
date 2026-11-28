//! Explicit late Evaluator binding from original owned records to two existing
//! terminal episodes. Text and success flags never become action or value labels.
//! This is a constant-state tabular consumer, not representation or SFT training.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::TryLockError;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_bellman_operator::freeze_terminal_cell_from_owner_v1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_memory::SharedExperiencePurposeV1;
use codex_hepta_memory::SharedExperienceUseV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::Semaphore;

use crate::AgentdSharedReplayHostV1;
use crate::PairedRecordIdentityV1;
use crate::PairedRecordPinsV1;
use crate::PairedTrainingPlanV1;
use crate::TerminalLearningErrorV1;
use crate::TerminalLearningRequestV1;
use crate::identify_original_paired_records_v1;
use crate::paired_preparation::training::consumer::OriginalPairedTrainingDelivery;

use super::AgentdTerminalLearningOwnerV1;
use super::Job;
use super::anchored_snapshot;
use super::check_deadline;
use super::owner_error;
use super::projected_now;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct PairedTerminalEventPairV1 {
    pub(crate) decision: Digest32,
    pub(crate) outcome: Digest32,
}

/// Trusted composition metadata; its fields do not grant Replay or training.
#[derive(Clone, Debug)]
pub(crate) struct PairedTerminalBindingPlanV1 {
    pub(crate) original: PairedTrainingPlanV1,
    pub(crate) records: PairedRecordPinsV1,
    pub(crate) training: TerminalLearningRequestV1,
    pub(crate) failure: PairedTerminalEventPairV1,
    pub(crate) correction: PairedTerminalEventPairV1,
}

/// No Clone, Deserialize or caller-built constructor. The required intake owner
/// retains this value while the existing Evaluator signs the observed delivery.
pub(crate) struct PreparedPairedTerminalV1 {
    records: PairedRecordIdentityV1,
    plan: PairedTerminalBindingPlanV1,
    source: SharedExperienceUseV1,
    dataset: DatasetSnapshotReceiptV3,
    ledger: Arc<Mutex<LedgerWriter>>,
    replay: Arc<AgentdSharedReplayHostV1>,
    jobs: Arc<Mutex<BTreeMap<StableId, Job>>>,
    compute: Arc<Semaphore>,
    payload: Vec<u8>,
    prepared_at: u64,
    end: tokio::time::Instant,
}

impl PreparedPairedTerminalV1 {
    pub(crate) fn signing_payload(&self) -> &[u8] {
        &self.payload
    }

    pub(crate) fn original_records(&self) -> &PairedRecordIdentityV1 {
        &self.records
    }

    pub(crate) fn prepared_at(&self) -> u64 {
        self.prepared_at
    }
}

impl AgentdTerminalLearningOwnerV1 {
    /// No fit or ledger append. `end` is the original supervised intake deadline;
    /// preparing or waiting for a signature never extends it.
    pub(crate) async fn prepare_paired_original_v1(
        &self,
        delivery: OriginalPairedTrainingDelivery,
        plan: PairedTerminalBindingPlanV1,
        now: u64,
        end: tokio::time::Instant,
    ) -> Result<PreparedPairedTerminalV1, TerminalLearningErrorV1> {
        plan.training
            .job_digest(&self.agent_id, &self.producer_id)?;
        check_deadline(&plan.training, now)?;
        let end = end.min(
            tokio::time::Instant::now()
                + Duration::from_millis(plan.training.budget.maximum_wall_milliseconds),
        );
        if tokio::time::Instant::now() >= end {
            return Err(TerminalLearningErrorV1::DeadlineExceeded);
        }
        let expected = plan
            .original
            .request_for_original(
                delivery.request.original.turn_id.clone(),
                delivery.request.original.delivery_id,
            )
            .map_err(owner_error)?;
        if delivery.request != expected {
            return Err(TerminalLearningErrorV1::Conflict);
        }
        let records = identify_original_paired_records_v1(
            delivery.result.map_err(owner_error)?,
            &delivery.request,
            plan.records,
        )
        .map_err(owner_error)?;
        let started = Instant::now();
        let (source, dataset) = tokio::time::timeout_at(end, self.paired_context(&plan, now))
            .await
            .map_err(|_| TerminalLearningErrorV1::DeadlineExceeded)??;
        let prepared_at = projected_now(now, started);
        check_deadline(&plan.training, prepared_at)?;
        let payload = binding_payload(self, &plan, &records, &source, &dataset)?;
        if tokio::time::Instant::now() >= end {
            return Err(TerminalLearningErrorV1::DeadlineExceeded);
        }
        Ok(PreparedPairedTerminalV1 {
            records,
            plan,
            source,
            dataset,
            payload,
            prepared_at,
            end,
            ledger: Arc::clone(&self.ledger),
            replay: Arc::clone(&self.replay),
            jobs: Arc::clone(&self.jobs),
            compute: Arc::clone(&self.compute),
        })
    }

    async fn paired_context(
        &self,
        plan: &PairedTerminalBindingPlanV1,
        now: u64,
    ) -> Result<(SharedExperienceUseV1, DatasetSnapshotReceiptV3), TerminalLearningErrorV1> {
        let started = Instant::now();
        check_deadline(&plan.training, now)?;
        let source = self
            .replay
            .training_source(&plan.training.source_policy_id)
            .await
            .map_err(owner_error)?;
        if source.source_support_digest().as_str()
            != plan.training.expected_source_support_digest.to_string()
        {
            return Err(TerminalLearningErrorV1::Conflict);
        }
        let ledger = self.ledger.try_lock().map_err(|error| match error {
            TryLockError::WouldBlock => TerminalLearningErrorV1::Busy,
            TryLockError::Poisoned(_) => TerminalLearningErrorV1::Unavailable,
        })?;
        anchored_snapshot(&ledger, plan.training.budget.maximum_ledger_records)?;
        let now = projected_now(now, started);
        check_deadline(&plan.training, now)?;
        let dataset = ledger
            .freeze_dataset(
                plan.training.dataset_plan.clone(),
                &plan.training.dataset_evidence,
                now,
            )
            .map_err(owner_error)?;
        if dataset.snapshot.dataset_digest != plan.training.expected_dataset_digest
            || dataset.snapshot.source_record_digests.len()
                > plan.training.budget.maximum_dataset_records as usize
        {
            return Err(TerminalLearningErrorV1::Conflict);
        }
        let expected = [
            plan.failure.decision,
            plan.failure.outcome,
            plan.correction.decision,
            plan.correction.outcome,
        ];
        if expected.iter().any(|digest| digest.is_zero())
            || expected.into_iter().collect::<BTreeSet<_>>().len() != 4
        {
            return Err(TerminalLearningErrorV1::InvalidRequest);
        }
        let mut episodes = [None, None, None, None];
        for record in ledger
            .read_dataset_records(&dataset, now)
            .map_err(owner_error)?
        {
            let episode = match &record.event {
                LedgerEvent::AuthenticatedDecisionV2(value) => {
                    if value.support_digest != plan.training.expected_source_support_digest {
                        return Err(TerminalLearningErrorV1::Conflict);
                    }
                    (&value.episode_id, 0)
                }
                LedgerEvent::AuthenticatedOutcomeV2(value) => (&value.episode_id, 1),
                _ => continue,
            };
            let index = expected
                .iter()
                .position(|digest| *digest == record.event_digest)
                .ok_or(TerminalLearningErrorV1::Conflict)?;
            if index % 2 != episode.1 || episodes[index].is_some() {
                return Err(TerminalLearningErrorV1::Conflict);
            }
            episodes[index] = Some(episode.0.clone());
        }
        if episodes.iter().any(Option::is_none)
            || episodes[0] != episodes[1]
            || episodes[2] != episodes[3]
            || episodes[0] == episodes[2]
        {
            return Err(TerminalLearningErrorV1::Conflict);
        }
        // Reuse the unchanged native profile validator; no values are inferred.
        freeze_terminal_cell_from_owner_v1(&ledger, &dataset, plan.training.profile.clone(), now)
            .map_err(owner_error)?;
        Ok((source, dataset))
    }
}

fn binding_payload(
    owner: &AgentdTerminalLearningOwnerV1,
    plan: &PairedTerminalBindingPlanV1,
    records: &PairedRecordIdentityV1,
    source: &SharedExperienceUseV1,
    dataset: &DatasetSnapshotReceiptV3,
) -> Result<Vec<u8>, TerminalLearningErrorV1> {
    let request = records.original_request();
    let registration = &plan.original.preparation;
    let manifest = &plan.original.manifest;
    let SharedExperiencePurposeV1::Replay {
        parameter_scope,
        artifact_consumer,
    } = source.purpose()
    else {
        return Err(TerminalLearningErrorV1::WrongScope);
    };
    let mut bytes = b"hepta.agentd.paired-terminal-owner-binding.v1\0".to_vec();
    for value in [
        owner.agent_id.as_str(),
        owner.producer_id.as_str(),
        request.original.turn_id.as_str(),
        registration.principal_id.as_str(),
        source.owner_id().as_str(),
        source.policy_id().as_str(),
        parameter_scope.as_str(),
        artifact_consumer.as_str(),
    ] {
        bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
        bytes.extend_from_slice(value.as_bytes());
    }
    for value in [
        registration.study,
        registration.enrollment,
        registration.frozen_materials,
        request.operation,
        request.original.delivery_id,
        manifest.failure_sha256,
        manifest.correction_sha256,
        records.failure_record().record_digest,
        records.correction_record().record_digest,
        plan.training
            .job_digest(&owner.agent_id, &owner.producer_id)?,
        dataset.snapshot.dataset_digest,
        plan.training.expected_source_support_digest,
        plan.failure.decision,
        plan.failure.outcome,
        plan.correction.decision,
        plan.correction.outcome,
    ] {
        bytes.extend_from_slice(value.as_array());
    }
    for value in [
        registration.policy_generation.get(),
        manifest.failure_bytes,
        manifest.correction_bytes,
        source.policy_revision(),
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(bytes)
}

//! The daemon retains an original Root reader, never B's runner, key or file
//! writers. Completion is data-only until the current Root verifies the actual
//! original Trainer signature against its own retained Training checkpoint.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::Digest32;

use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalRootBEvaluationConnectionV1;
use crate::learning_owner_evidence;
use crate::root_generation_current_client::OriginalPublicationStream;
use crate::root_independent_b_protocol::*;

#[path = "root_independent_b_client_connect.rs"]
mod connect;
#[path = "root_independent_b_training.rs"]
mod training;

struct Lane {
    stream: OriginalPublicationStream,
    sequence: u64,
}

pub(crate) struct OriginalRootIndependentBEvaluationClientV1 {
    bootstrap: Bootstrap,
    connection: OriginalRootBEvaluationConnectionV1,
    lane: Mutex<Lane>,
    refused: AtomicBool,
}

/// Only the original client constructs this readonly observation. Its getters
/// are data: later Model/CURRENT actions must enter the actual Root owner again.
pub(crate) struct OriginalRootIndependentBEvaluationReadbackV1 {
    data: CompletedData,
    receipt: LearningIterationReceiptV1,
    attestation: SignedLearningEvidenceV1,
    binding: Digest32,
}

impl OriginalRootIndependentBEvaluationReadbackV1 {
    pub(crate) fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.receipt
    }
    pub(crate) fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.attestation
    }
    pub(crate) fn manifest(&self) -> &CellBackendManifestV2 {
        &self.data.manifest
    }
    pub(crate) fn comparison_json(&self) -> &str {
        &self.data.comparison
    }
    pub(crate) fn original_binding(&self) -> Digest32 {
        self.binding
    }
    pub(crate) fn same_original_observation(&self, other: &Self) -> bool {
        self.binding == other.binding && self.data == other.data
    }
}

impl OriginalRootIndependentBEvaluationClientV1 {
    pub(crate) fn original_binding(&self) -> Result<Digest32, Error> {
        digest(&self.bootstrap.binding).map_err(unavailable)
    }

    pub(crate) fn require_initial(
        &self,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        self.connection.require_original().map_err(unavailable)?;
        scope.validate_request(&initial.request, &initial.owners)?;
        let actual =
            LearningIterationCoordinatorV1::new(initial.request.clone(), initial.owners.clone())?;
        if actual.snapshot().head_digest.to_string() != self.bootstrap.initial
            || scope.binding().to_string() != self.bootstrap.scope
        {
            return Err(Error::WrongScope);
        }
        if self.refused.load(Ordering::Acquire) {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }

    fn original_training(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
        signed: &SignedLearningEvidenceV1,
        mode: TrainingMode,
    ) -> Result<OriginalRootIndependentBEvaluationReadbackV1, Error> {
        let result = (|| {
            self.require_initial(snapshot, scope)?;
            let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
            if coordinator.next_stage() != Some(LearningIterationStageV1::Evaluation) {
                return Err(Error::WrongScope);
            }
            let candidate = coordinator
                .candidate()
                .ok_or(Error::WrongScope)?
                .digest()
                .map_err(|_| Error::WrongScope)?;
            let training = snapshot.receipts.last().ok_or(Error::WrongScope)?;
            let payload = learning_iteration_receipt_signing_bytes_v1(training)?;
            if signed.role != LearningEvidenceRoleV1::Generator
                || signed.principal_id != snapshot.owners.trainer
                || signed.trust_digest != snapshot.owners.evidence_trust_digest
                || signed.payload_digest != Digest32::of_bytes(&payload)
            {
                return Err(Error::WrongScope);
            }
            let command = match mode {
                TrainingMode::Complete => Command::Complete {
                    training_head: snapshot.head_digest.to_string(),
                    training_attestation: learning_owner_evidence::encode(&payload, signed)
                        .map_err(unavailable)?,
                },
                TrainingMode::Readback => Command::Readback {
                    training_head: snapshot.head_digest.to_string(),
                },
            };
            let Observation::Completed(data) = self.exchange(command)? else {
                return Err(Error::CommitUncertain);
            };
            let receipt = data.receipt.data().map_err(unavailable)?;
            let (original, attestation) =
                learning_owner_evidence::decode(&data.attestation).map_err(unavailable)?;
            if data.training_head != snapshot.head_digest.to_string()
                || receipt.predecessor != snapshot.head_digest
                || receipt.actor_id != snapshot.owners.evaluator
                || data.manifest.bundle_digest != candidate.into_array()
                || attestation.role != LearningEvidenceRoleV1::Evaluator
                || attestation.principal_id != snapshot.owners.evaluator
                || attestation.trust_digest != snapshot.owners.evidence_trust_digest
                || original != learning_iteration_receipt_signing_bytes_v1(&receipt)?
                || data.comparison.is_empty()
                || data.comparison.len() > 8_192
            {
                return Err(Error::WrongScope);
            }
            digest(&data.plan_digest).map_err(unavailable)?;
            digest(&data.execution_digest).map_err(unavailable)?;
            scope.validate_observation(&receipt.observation)?;
            coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
            self.require_initial(snapshot, scope)?;
            Ok(OriginalRootIndependentBEvaluationReadbackV1 {
                data: *data,
                receipt,
                attestation,
                binding: self.original_binding()?,
            })
        })();
        if result.is_err() {
            self.refused.store(true, Ordering::Release);
        }
        result
    }

    fn exchange(&self, command: Command) -> Result<Observation, Error> {
        self.connection.require_original().map_err(unavailable)?;
        let mut lane = self
            .lane
            .try_lock()
            .map_err(|_| Error::OwnerUnavailable("original B lane busy"))?;
        if self.refused.swap(true, Ordering::AcqRel) {
            return Err(Error::CommitUncertain);
        }
        let request = Request {
            schema: 1,
            purpose: PURPOSE.into(),
            sequence: lane.sequence,
            binding: self.bootstrap.binding.clone(),
            command,
        };
        let raw = lane
            .stream
            .exchange(&serde_json::to_vec(&request).map_err(unavailable)?)
            .map_err(unavailable)?;
        let response: Response = serde_json::from_slice(&raw).map_err(unavailable)?;
        if serde_json::to_vec(&response).map_err(unavailable)? != raw
            || response.schema != 1
            || response.purpose != PURPOSE
            || response.sequence != lane.sequence
            || response.binding != self.bootstrap.binding
        {
            return Err(Error::CommitUncertain);
        }
        lane.sequence = lane.sequence.checked_add(1).ok_or(Error::CommitUncertain)?;
        self.connection.require_original().map_err(unavailable)?;
        self.refused.store(false, Ordering::Release);
        Ok(response.result)
    }
}

enum TrainingMode {
    Complete,
    Readback,
}

fn unavailable(_: impl std::fmt::Display) -> Error {
    Error::OwnerUnavailable("original independent B observation")
}

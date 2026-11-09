//! Serialize-only historical bytes from the original generation journal actor.
//! This is neither a learning attestation nor a portable CURRENT/FinalUse grant.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellGenerationIntentV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use serde::Serialize;

use crate::AgentdError;
use crate::neuron_generation_update_bootstrap::GenerationLearningReadbackV1;

const SCHEMA: &str = "hepta.agentd.learning-use-readback.v1";
const DOMAIN: &[u8] = b"hepta.agentd.learning-use-readback.v1\0";
const MAX_JSON_BYTES: usize = 8 * 1024 * 1024;

/// Exact compact serde bytes and their domain-separated SHA-256. The private
/// constructor requires the original journal/publication; there is deliberately
/// no Deserialize implementation. Export preserves unresolved output and costs.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AgentdGenerationLearningUseReadbackV1 {
    schema: &'static str,
    payload_json: String,
    payload_digest: [u8; 32],
}

impl AgentdGenerationLearningUseReadbackV1 {
    pub fn payload_json(&self) -> &str {
        &self.payload_json
    }

    pub const fn digest(&self) -> [u8; 32] {
        self.payload_digest
    }

    pub const fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Serialize)]
struct UseIntent<'a> {
    operation_id: &'a str,
    task_digest: [u8; 32],
    source_frontier: [u8; 32],
    predecessor_digest: [u8; 32],
    input_digest: [u8; 32],
    deadline_micros: u64,
}

#[derive(Serialize)]
struct UseObservation {
    kind: &'static str,
    bundle_digest: [u8; 32],
    state_partition_digest: [u8; 32],
    checkpoint_digest: [u8; 32],
    selection_digest: [u8; 32],
    committed_step_receipt: [u8; 32],
    state_cutover_receipt: Option<[u8; 32]>,
    task_owner_publication: Option<[u8; 32]>,
}

#[derive(Serialize)]
struct UsePayload<'a> {
    disposition: &'static str,
    learning_operation_id: &'a str,
    learning_head: [u8; 32],
    learning_decision_head: [u8; 32],
    source_run_id: &'a str,
    source_task_receipt: [u8; 32],
    source_selected_artifact: [u8; 32],
    source_selected_bundle: [u8; 32],
    observation: UseObservation,
    intent: UseIntent<'a>,
    manifest_json: String,
    previous_manifest_json: Option<String>,
    publication_json: String,
    step_receipt_json: String,
    generation_observation_json: String,
    authority: &'static str,
    current_permission: &'static str,
}

impl<W: AnchorWitnessStore> GenerationLearningReadbackV1<'_, W> {
    pub(crate) fn export_next_use(
        &self,
        coordinator: &LearningIterationCoordinatorV1,
        previous_manifest: Option<&CellBackendManifestV2>,
        intent: &CellGenerationIntentV2,
    ) -> Result<AgentdGenerationLearningUseReadbackV1, AgentdError> {
        // Reuse the exact native checks; callers supply no receipt/checkpoint,
        // grant, observer identity, successful-stage flag or current assertion.
        let observation = match previous_manifest {
            Some(previous) => self.read_updated_next_use(coordinator, previous, intent)?,
            None => self.read_next_use(coordinator, intent)?,
        };
        let (disposition, observation) = match observation {
            LearningIterationObservationV1::NextUse {
                candidate_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                state_cutover_receipt,
            } => (
                "adopted_model_reset",
                UseObservation {
                    kind: "next_use",
                    bundle_digest: candidate_bundle.into_array(),
                    state_partition_digest: state_partition.digest().into_array(),
                    checkpoint_digest: checkpoint_digest.into_array(),
                    selection_digest: selection_digest.into_array(),
                    committed_step_receipt: committed_step_receipt.into_array(),
                    state_cutover_receipt: Some(state_cutover_receipt.into_array()),
                    task_owner_publication: None,
                },
            ),
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                task_owner_publication,
            } => (
                "retained_model",
                UseObservation {
                    kind: "retained_model_next_use",
                    bundle_digest: retained_bundle.into_array(),
                    state_partition_digest: state_partition.digest().into_array(),
                    checkpoint_digest: checkpoint_digest.into_array(),
                    selection_digest: selection_digest.into_array(),
                    committed_step_receipt: committed_step_receipt.into_array(),
                    state_cutover_receipt: None,
                    task_owner_publication: Some(task_owner_publication.into_array()),
                },
            ),
            LearningIterationObservationV1::Experience { .. }
            | LearningIterationObservationV1::Dataset { .. }
            | LearningIterationObservationV1::Training { .. }
            | LearningIterationObservationV1::Evaluation { .. }
            | LearningIterationObservationV1::Proposal { .. }
            | LearningIterationObservationV1::Selection { .. } => {
                return Err(invalid("owner did not return a committed learning use"));
            }
        };
        let receipt = self
            .journal
            .receipt_for_intent(intent)
            .map_err(invalid)?
            .ok_or_else(|| invalid("original step receipt disappeared"))?;
        let observed = self.journal.observe_generation().map_err(invalid)?;
        let step_receipt_json = bounded_json(&receipt)?;
        if observed.owner_checkpoint().as_array() != &observation.checkpoint_digest
            || Digest32::of_parts(&[
                b"hepta.agentd.learning-next-use-receipt.v1\0",
                step_receipt_json.as_bytes(),
            ])
            .as_array()
                != &observation.committed_step_receipt
        {
            return Err(invalid("original learning use changed during export"));
        }
        let snapshot = coordinator.snapshot();
        let decision = snapshot
            .receipts
            .last()
            .ok_or_else(|| invalid("missing original learning selection"))?
            .predecessor;
        let payload_json = bounded_json(&UsePayload {
            disposition,
            learning_operation_id: snapshot.request.operation_id.as_str(),
            learning_head: snapshot.head_digest.into_array(),
            learning_decision_head: decision.into_array(),
            source_run_id: snapshot.request.source_run_id.as_str(),
            source_task_receipt: snapshot.request.completed_task_receipt.into_array(),
            source_selected_artifact: snapshot.request.selected_artifact_digest.into_array(),
            source_selected_bundle: snapshot
                .request
                .selected_bundle
                .digest()
                .map_err(invalid)?
                .into_array(),
            observation,
            intent: UseIntent {
                operation_id: &intent.operation_id,
                task_digest: intent.task_digest,
                source_frontier: intent.source_frontier,
                predecessor_digest: intent.predecessor_digest,
                input_digest: intent.input_digest,
                deadline_micros: intent.deadline_micros,
            },
            manifest_json: bounded_json(self.journal.manifest())?,
            previous_manifest_json: previous_manifest.map(bounded_json).transpose()?,
            publication_json: self.publication.publication_json()?,
            step_receipt_json,
            generation_observation_json: bounded_json(&observed)?,
            authority: "DENY_ALL",
            current_permission: "NOT_EXPORTED",
        })?;
        let payload_digest = Digest32::of_parts(&[DOMAIN, payload_json.as_bytes()]).into_array();
        // A successful historical read is not a lease after this last live
        // check. No actor dispatch, checkpoint, nonce or authority is created.
        self.journal.require_current().map_err(invalid)?;
        Ok(AgentdGenerationLearningUseReadbackV1 {
            schema: SCHEMA,
            payload_json,
            payload_digest,
        })
    }
}

fn bounded_json(value: &impl Serialize) -> Result<String, AgentdError> {
    struct Output(Vec<u8>);
    impl std::io::Write for Output {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            if bytes.len() > MAX_JSON_BYTES.saturating_sub(self.0.len()) {
                return Err(std::io::Error::other("learning readback byte limit"));
            }
            self.0.extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut output = Output(Vec::new());
    serde_json::to_writer(&mut output, value).map_err(invalid)?;
    String::from_utf8(output.0).map_err(invalid)
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}

#[cfg(test)]
#[path = "neuron_generation_learning_readback_test_support.rs"]
pub(crate) mod test_support;

//! Bind a real frozen-encoder ridge result to the existing candidate-only port.
//! These checks establish equation/identity consistency, not independent task gain.

use std::collections::BTreeMap;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellExecutionError;
use crate::CellUpdateCandidateV1;
use crate::CellUpdateOutcomeV1;
use crate::CellUpdatePortV1;
use crate::CellUpdateRequestV1;
use crate::HcsnRecoveryBindingV2;
use crate::HcsnStreamingStateV1;
use crate::hcsn_streaming::Tensor;

/// Retain this mapping independently of worker output. Peak working bytes must
/// come from the host's process measurement, not tensor size or a zero placeholder.
#[derive(Clone, Debug)]
pub struct HcsnStreamingUpdateAdmissionV1 {
    pub request: CellUpdateRequestV1,
    pub research_binding: HcsnRecoveryBindingV2,
    pub base_parameters_digest: Digest32,
    pub observed_peak_working_bytes: u64,
}

/// One-use candidate adapter. The immutable parameter payload is available for
/// the existing artifact owner; no call here adopts it or changes a live state.
#[derive(Debug)]
pub struct HcsnStreamingUpdatePortV1 {
    admitted: CellUpdateRequestV1,
    outcome: Option<CellUpdateOutcomeV1>,
    artifact: Vec<u8>,
    lineage: [Digest32; 8],
}

/// Exact full request binding retained before dispatch. Parameter order and all
/// resource caps are part of the identity; another nonzero request cannot reuse it.
pub fn hcsn_streaming_request_digest_v1(request: &CellUpdateRequestV1) -> Digest32 {
    let mut bytes = b"hepta.hcsn.streaming-update-request.v1\0".to_vec();
    bytes.extend_from_slice(&(request.proposal_id.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(request.proposal_id.as_str().as_bytes());
    for digest in [
        request.scope.digest(),
        request.base_bundle_digest,
        request.source_frontier,
        request.dataset_digest,
        request.credit_profile_digest,
        request.trainable_mask_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        request.dataset_bytes,
        request.from_generation.get(),
        request.candidate_generation.get(),
        request.budget.maximum_dataset_bytes,
        request.budget.maximum_steps,
        request.budget.maximum_elapsed_micros,
        request.budget.maximum_working_bytes,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&(request.trainable_parameters.len() as u64).to_be_bytes());
    for name in &request.trainable_parameters {
        bytes.extend_from_slice(&(name.as_str().len() as u32).to_be_bytes());
        bytes.extend_from_slice(name.as_str().as_bytes());
    }
    Digest32::of_bytes(&bytes)
}

impl HcsnStreamingUpdatePortV1 {
    pub fn prepare(
        admission: HcsnStreamingUpdateAdmissionV1,
        state: &HcsnStreamingStateV1,
        candidate_readout: &[u8],
    ) -> Result<Self, CellExecutionError> {
        let invalid = CellExecutionError::InvalidInput;
        // Reconstruct costs and numerical metadata from the clock-sealed snapshot;
        // caller-controlled mirrors can never refund work or replace lineage.
        let verified = state.revalidate().map_err(|_| invalid.clone())?;
        let state = &verified;
        let request = &admission.request;
        let mut mask = b"hepta.cell.trainable-mask.v1".to_vec();
        let mut names = Vec::new();
        for name in ["readout.bias", "readout.weight"] {
            mask.extend_from_slice(&(name.len() as u32).to_be_bytes());
            mask.extend_from_slice(name.as_bytes());
            names.push(StableId::new(name).map_err(|_| invalid.clone())?);
        }
        if state.snapshot.binding != admission.research_binding
            || state.snapshot.binding.request_digest != hcsn_streaming_request_digest_v1(request)
            || state.clock_identity().scope_digest != request.scope.digest()
            || state.clock_identity().generation != request.from_generation
            || Digest32::of_bytes(&state.snapshot.parameters) != admission.base_parameters_digest
            || state.snapshot.binding.dataset_digest != request.dataset_digest
            || request.base_bundle_digest.is_zero()
            || request.source_frontier.is_zero()
            || request.credit_profile_digest.is_zero()
            || request.dataset_bytes == 0
            || request.dataset_bytes > request.budget.maximum_dataset_bytes
            || request.from_generation.get().checked_add(1)
                != Some(request.candidate_generation.get())
            || request.trainable_parameters != names
            || request.trainable_mask_digest != Digest32::of_bytes(&mask)
            || state.controller.examples == 0
            || state.controller.solves == 0
            || state.cost().charged_proposals > request.budget.maximum_steps
            || state.cost().elapsed_micros > request.budget.maximum_elapsed_micros
            || admission.observed_peak_working_bytes == 0
            || admission.observed_peak_working_bytes > request.budget.maximum_working_bytes
            || candidate_readout.is_empty()
            || candidate_readout.len() > 1_048_576
        {
            return Err(invalid);
        }
        let candidate: BTreeMap<String, Tensor> =
            serde_json::from_slice(candidate_readout).map_err(|_| invalid.clone())?;
        if candidate.len() != 2 {
            return Err(invalid);
        }
        let weight = candidate
            .get("weight")
            .ok_or(invalid.clone())?
            .values(&[state.outputs, state.features])
            .map_err(|_| invalid.clone())?;
        let bias = candidate
            .get("bias")
            .ok_or(invalid.clone())?
            .values(&[state.outputs])
            .map_err(|_| invalid.clone())?;
        let width = state.features + 1;
        // Check the actual regularized normal equation in FP64. This bounded
        // residual check is not a proof of a global optimum or downstream gain.
        for (output, bias_value) in bias.iter().enumerate() {
            for row in 0..width {
                let mut result = 0.0;
                let mut scale = state.cross[row * state.outputs + output].abs() + 1.0;
                for col in 0..width {
                    let parameter = if col == state.features {
                        *bias_value
                    } else {
                        weight[output * state.features + col]
                    };
                    let coefficient = state.gram[row * width + col]
                        + if row == col && col != state.features {
                            state.controller.ridge
                        } else {
                            0.0
                        };
                    result += coefficient * parameter;
                    scale += (coefficient * parameter).abs();
                }
                if !result.is_finite()
                    || !scale.is_finite()
                    || (result - state.cross[row * state.outputs + output]).abs() > 1e-10 * scale
                {
                    return Err(invalid);
                }
            }
        }
        let mut parameters = state.parameters.clone();
        let mut changed = Vec::new();
        for (name, parameter) in &candidate {
            if parameters.readout.get(name) != Some(parameter) {
                changed
                    .push(StableId::new(format!("readout.{name}")).map_err(|_| invalid.clone())?);
            }
        }
        parameters.readout = candidate;
        let artifact = serde_json::to_vec(&parameters).map_err(|_| invalid.clone())?;
        let artifact_digest = Digest32::of_bytes(&artifact);
        let outcome = if changed.is_empty() {
            CellUpdateOutcomeV1::NoUpdate
        } else {
            CellUpdateOutcomeV1::Candidate(Box::new(CellUpdateCandidateV1 {
                proposal_id: request.proposal_id.clone(),
                base_bundle_digest: request.base_bundle_digest,
                dataset_digest: request.dataset_digest,
                credit_profile_digest: request.credit_profile_digest,
                trainable_mask_digest: request.trainable_mask_digest,
                candidate_generation: request.candidate_generation,
                candidate_artifact_digest: artifact_digest,
                changed_parameters: changed,
                executed_steps: state.cost().charged_proposals,
                elapsed_micros: state.cost().elapsed_micros,
                peak_working_bytes: admission.observed_peak_working_bytes,
                authority: AuthorityPosture::DENY_ALL,
            }))
        };
        Ok(Self {
            admitted: admission.request,
            outcome: Some(outcome),
            artifact,
            lineage: [
                state.snapshot.binding.base_checkpoint_digest,
                admission.base_parameters_digest,
                Digest32::of_bytes(&state.encode().map_err(|_| invalid)?),
                state.cost().journal_tail,
                Digest32::of_bytes(candidate_readout),
                state.snapshot.binding.request_digest,
                state.clock_digest(),
                artifact_digest,
            ],
        })
    }

    pub fn artifact_bytes(&self) -> &[u8] {
        &self.artifact
    }

    pub fn lineage(&self) -> &[Digest32; 8] {
        &self.lineage
    }
}

impl CellUpdatePortV1 for HcsnStreamingUpdatePortV1 {
    fn propose(
        &mut self,
        request: &CellUpdateRequestV1,
    ) -> Result<CellUpdateOutcomeV1, CellExecutionError> {
        if request != &self.admitted {
            return Err(CellExecutionError::OperationConflict);
        }
        self.outcome
            .take()
            .ok_or(CellExecutionError::OperationConflict)
    }
}

#[cfg(test)]
#[path = "hcsn_streaming_update_tests.rs"]
mod tests;

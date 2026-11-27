//! Owner-admitted task obligations and monotonic budget for the v4 generator.
//! The caller cannot provide a replacement committed prefix or remaining budget.

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::CellGenerationErrorV2;
use crate::CellGenerationRequestV2;
use crate::cell_joint_protocol::JointGenerationActionV1;
use crate::cell_joint_protocol::JointGenerationCommandV1;
use crate::cell_joint_protocol::JointGenerationModalityV1;
use crate::cell_joint_protocol::JointGenerationSamplerV1;

/// Immutable delivery contract carried in the original journal-admitted input.
/// Its deadline uses the same host monotonic epoch as Cell request admission.
/// Every v2 request uses this task deadline so observed and executable remaining
/// time have the same meaning; per-request shortened deadlines are rejected.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JointGenerationDeliveryContractV2 {
    pub required_mask: u8,
    pub optional_mask: u8,
    pub budget_total_micros: u64,
    pub task_deadline_micros: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum JointGenerationCommandV2 {
    Init {
        seed: u64,
        sampler: JointGenerationSamplerV1,
    },
    Advance {
        action: JointGenerationActionV1,
    },
    Auto,
    Commit {
        modality: JointGenerationModalityV1,
        units: u32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JointGenerationInputV2 {
    pub public_digest: [u8; 32],
    pub delivery: JointGenerationDeliveryContractV2,
    pub command: JointGenerationCommandV2,
}

pub(crate) fn request_bytes(
    request: &CellGenerationRequestV2,
    input: &JointGenerationInputV2,
    weights: &[u8],
    public: &[u8],
    now_micros: u64,
) -> Result<Vec<u8>, CellGenerationErrorV2> {
    let contract = &input.delivery;
    if contract.required_mask & contract.optional_mask != 0
        || contract.required_mask | contract.optional_mask == 0
        || (contract.required_mask | contract.optional_mask) & !15 != 0
        || contract.budget_total_micros == 0
        || contract.task_deadline_micros < contract.budget_total_micros
        || now_micros < request.admitted_at_micros
        || request.admitted_at_micros < contract.task_deadline_micros - contract.budget_total_micros
        || request.deadline_micros != contract.task_deadline_micros
        || request.task_digest == [0; 32]
    {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    if now_micros >= request.deadline_micros || now_micros >= contract.task_deadline_micros {
        return Err(CellGenerationErrorV2::Deadline);
    }
    let remaining = contract.task_deadline_micros - now_micros;
    if remaining > contract.budget_total_micros {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    let remaining_millionths =
        (u128::from(remaining) * 1_000_000 / u128::from(contract.budget_total_micros)) as u32;
    let command = match input.command {
        JointGenerationCommandV2::Init { seed, sampler } => {
            JointGenerationCommandV1::Init { seed, sampler }
        }
        JointGenerationCommandV2::Advance { action } => {
            JointGenerationCommandV1::Advance { action }
        }
        JointGenerationCommandV2::Auto => JointGenerationCommandV1::Auto {
            remaining_millionths,
        },
        JointGenerationCommandV2::Commit { modality, units } => {
            JointGenerationCommandV1::Commit { modality, units }
        }
    };
    // A later caller cannot move the deadline while keeping the task identity.
    // The actual task digest remains bound in the complete request digest.
    let contract_digest = Digest32::of_parts(&[
        b"hepta.joint.owner-delivery-contract.v2\0",
        &request.task_digest,
        &[contract.required_mask, contract.optional_mask],
        &contract.budget_total_micros.to_le_bytes(),
        &contract.task_deadline_micros.to_le_bytes(),
    ]);
    let legacy = crate::cell_joint_protocol::request_bytes_with_text_limit(
        request.digest()?,
        weights,
        public,
        &request.predecessor.state,
        &request.predecessor.prefix,
        &command,
        /*text_limit*/ 128,
    )?;
    let mut bytes = b"HJREQV02".to_vec();
    bytes.extend(&legacy[8..40]);
    bytes.extend([contract.required_mask, contract.optional_mask]);
    bytes.extend(contract.budget_total_micros.to_le_bytes());
    bytes.extend(remaining.to_le_bytes());
    bytes.extend(contract_digest.as_array());
    bytes.extend(&legacy[40..]);
    Ok(bytes)
}

#[cfg(test)]
#[path = "cell_joint_observed_tests.rs"]
mod tests;

//! Opt-in research outcomes. These types grant no publication or adoption power.
//! V1 task-BP handoffs remain unchanged; optimizer API usage is not a rule label.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_PARAMETERS: usize = 1_024;
const MAX_PARAMETER_BYTES: usize = 64 * 1_024 * 1_024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnLearningRuleV2 {
    TaskBp,
    ClosedFormReadout,
    ProgrammaticWeightEdit,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnParameterRoleV2 {
    Dynamics,
    Encoder,
    Readout,
    Controller,
}

/// Full named parameter bytes, including frozen parameters, in increasing ID order.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnParameterV2 {
    pub id: StableId,
    pub role: HcsnParameterRoleV2,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HcsnResearchBindingV2 {
    pub request_digest: Digest32,
    pub base_checkpoint_digest: Digest32,
    pub code_digest: Digest32,
    pub dataset_digest: Digest32,
    pub runtime_digest: Digest32,
    pub backend_state_schema_digest: Digest32,
    pub base_parameters_digest: Digest32,
    pub parameter_mask_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnResearchRequestV2 {
    pub binding: HcsnResearchBindingV2,
    pub rule: HcsnLearningRuleV2,
    pub trainable_parameters: Vec<StableId>,
    pub maximum_elapsed_micros: u64,
    pub maximum_peak_working_bytes: u64,
}

/// Work is measured separately for discovery, application and evaluation.
/// In particular, program discovery may use gradients; its cost cannot disappear.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct HcsnResearchCostV2 {
    pub elapsed_micros: u64,
    pub forward_calls: u64,
    pub backward_calls: u64,
    pub optimizer_steps: u64,
    pub peak_working_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnRuleEvidenceV2 {
    TaskBp {
        gradient_digest: Digest32,
    },
    ClosedFormReadout {
        solve_receipt_digest: Digest32,
    },
    ProgrammaticWeightEdit {
        program_digest: Digest32,
        discovery_receipt_digest: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnResearchOutcomeV2 {
    pub binding: HcsnResearchBindingV2,
    pub evidence: HcsnRuleEvidenceV2,
    pub discovery: HcsnResearchCostV2,
    pub application: HcsnResearchCostV2,
    pub evaluation: HcsnResearchCostV2,
    pub receipt_digest: Digest32,
}

impl HcsnResearchBindingV2 {
    fn digests(self) -> [Digest32; 8] {
        [
            self.request_digest,
            self.base_checkpoint_digest,
            self.code_digest,
            self.dataset_digest,
            self.runtime_digest,
            self.backend_state_schema_digest,
            self.base_parameters_digest,
            self.parameter_mask_digest,
        ]
    }
}

impl HcsnResearchOutcomeV2 {
    /// Canonical worker evidence to authenticate before validation. Includes all
    /// method and cost claims and the complete result-parameter digest; excludes
    /// `receipt_digest`, which must hash the returned bytes.
    pub fn encode_receipt(&self, parameters_digest: Digest32) -> Vec<u8> {
        let mut bytes = b"hepta.hcsn.research-receipt.v2\0".to_vec();
        for digest in self.binding.digests() {
            bytes.extend_from_slice(digest.as_array());
        }
        match self.evidence {
            HcsnRuleEvidenceV2::TaskBp { gradient_digest } => {
                bytes.push(0);
                bytes.extend_from_slice(gradient_digest.as_array());
            }
            HcsnRuleEvidenceV2::ClosedFormReadout {
                solve_receipt_digest,
            } => {
                bytes.push(1);
                bytes.extend_from_slice(solve_receipt_digest.as_array());
            }
            HcsnRuleEvidenceV2::ProgrammaticWeightEdit {
                program_digest,
                discovery_receipt_digest,
            } => {
                bytes.push(2);
                bytes.extend_from_slice(program_digest.as_array());
                bytes.extend_from_slice(discovery_receipt_digest.as_array());
            }
        }
        for cost in [self.discovery, self.application, self.evaluation] {
            for value in [
                cost.elapsed_micros,
                cost.forward_calls,
                cost.backward_calls,
                cost.optimizer_steps,
                cost.peak_working_bytes,
            ] {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        bytes.extend_from_slice(parameters_digest.as_array());
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum HcsnResearchDispositionV2 {
    NoUpdate,
    Candidate {
        parameters_digest: Digest32,
        changed_parameters: Vec<StableId>,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnResearchErrorV2 {
    Binding,
    Parameters,
    Mask,
    Rule,
    Cost,
    Receipt,
}

/// Digests actual bytes rather than trusting a producer's changed-parameter list.
pub fn hcsn_parameters_digest_v2(
    parameters: &[HcsnParameterV2],
) -> Result<Digest32, HcsnResearchErrorV2> {
    if parameters.is_empty() || parameters.len() > MAX_PARAMETERS {
        return Err(HcsnResearchErrorV2::Parameters);
    }
    let mut total = 0_usize;
    let mut previous: Option<&str> = None;
    let mut bytes = b"hepta.hcsn.parameters.v2\0".to_vec();
    for parameter in parameters {
        let id = parameter.id.as_str();
        total = total
            .checked_add(parameter.bytes.len())
            .ok_or(HcsnResearchErrorV2::Parameters)?;
        if previous.is_some_and(|value| value >= id)
            || parameter.bytes.is_empty()
            || total > MAX_PARAMETER_BYTES
        {
            return Err(HcsnResearchErrorV2::Parameters);
        }
        previous = Some(id);
        bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(id.as_bytes());
        bytes.push(match parameter.role {
            HcsnParameterRoleV2::Dynamics => 0,
            HcsnParameterRoleV2::Encoder => 1,
            HcsnParameterRoleV2::Readout => 2,
            HcsnParameterRoleV2::Controller => 3,
        });
        bytes.extend_from_slice(&(parameter.bytes.len() as u64).to_be_bytes());
        bytes.extend_from_slice(Digest32::of_bytes(&parameter.bytes).as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn hcsn_parameter_mask_digest_v2(mask: &[StableId]) -> Result<Digest32, HcsnResearchErrorV2> {
    if mask.is_empty() || mask.len() > MAX_PARAMETERS {
        return Err(HcsnResearchErrorV2::Mask);
    }
    let mut bytes = b"hepta.hcsn.parameter-mask.v2\0".to_vec();
    let mut previous: Option<&str> = None;
    for id in mask {
        if previous.is_some_and(|value| value >= id.as_str()) {
            return Err(HcsnResearchErrorV2::Mask);
        }
        previous = Some(id.as_str());
        bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// The caller retains the admitted request and authenticates the worker receipt.
/// Validation binds evidence and parameter bytes; it does not prove task utility
/// or independently execute/verify a claimed numerical method.
pub fn validate_hcsn_research_outcome_v2(
    request: &HcsnResearchRequestV2,
    outcome: &HcsnResearchOutcomeV2,
    before: &[HcsnParameterV2],
    after: &[HcsnParameterV2],
    receipt: &[u8],
) -> Result<HcsnResearchDispositionV2, HcsnResearchErrorV2> {
    let binding = request.binding;
    if binding != outcome.binding
        || binding.digests().into_iter().any(Digest32::is_zero)
        || hcsn_parameters_digest_v2(before)? != binding.base_parameters_digest
    {
        return Err(HcsnResearchErrorV2::Binding);
    }
    if hcsn_parameter_mask_digest_v2(&request.trainable_parameters)?
        != binding.parameter_mask_digest
        || request
            .trainable_parameters
            .iter()
            .any(|id| !before.iter().any(|p| p.id == *id))
    {
        return Err(HcsnResearchErrorV2::Mask);
    }
    let parameters_digest = hcsn_parameters_digest_v2(after)?;
    if before.len() != after.len() {
        return Err(HcsnResearchErrorV2::Parameters);
    }
    let mut changed_parameters = Vec::new();
    for (old, new) in before.iter().zip(after) {
        if old.id != new.id || old.role != new.role || old.bytes.len() != new.bytes.len() {
            return Err(HcsnResearchErrorV2::Parameters);
        }
        if old.bytes != new.bytes {
            if !request.trainable_parameters.contains(&old.id) {
                return Err(HcsnResearchErrorV2::Mask);
            }
            if request.rule == HcsnLearningRuleV2::ClosedFormReadout
                && old.role != HcsnParameterRoleV2::Readout
            {
                return Err(HcsnResearchErrorV2::Rule);
            }
            changed_parameters.push(old.id.clone());
        }
    }
    let mut elapsed = 0_u64;
    for cost in [outcome.discovery, outcome.application, outcome.evaluation] {
        elapsed = elapsed
            .checked_add(cost.elapsed_micros)
            .ok_or(HcsnResearchErrorV2::Cost)?;
        if cost.peak_working_bytes > request.maximum_peak_working_bytes {
            return Err(HcsnResearchErrorV2::Cost);
        }
    }
    if request.maximum_elapsed_micros == 0
        || request.maximum_peak_working_bytes == 0
        || elapsed > request.maximum_elapsed_micros
        || receipt.is_empty()
        || receipt.len() > 1_024 * 1_024
    {
        return Err(HcsnResearchErrorV2::Cost);
    }
    if Digest32::of_bytes(receipt) != outcome.receipt_digest
        || receipt != outcome.encode_receipt(parameters_digest)
    {
        return Err(HcsnResearchErrorV2::Receipt);
    }
    let changed = !changed_parameters.is_empty();
    let apply = outcome.application;
    let rule = match outcome.evidence {
        HcsnRuleEvidenceV2::TaskBp { gradient_digest } => {
            if gradient_digest.is_zero() != (apply.backward_calls == 0)
                || (apply.optimizer_steps > 0 && apply.backward_calls == 0)
                || (changed && (apply.backward_calls == 0 || apply.optimizer_steps == 0))
            {
                return Err(HcsnResearchErrorV2::Rule);
            }
            HcsnLearningRuleV2::TaskBp
        }
        HcsnRuleEvidenceV2::ClosedFormReadout {
            solve_receipt_digest,
        } => {
            if (changed && solve_receipt_digest.is_zero())
                || apply.backward_calls != 0
                || apply.optimizer_steps != 0
            {
                return Err(HcsnResearchErrorV2::Rule);
            }
            HcsnLearningRuleV2::ClosedFormReadout
        }
        HcsnRuleEvidenceV2::ProgrammaticWeightEdit {
            program_digest,
            discovery_receipt_digest,
        } => {
            if program_digest.is_zero()
                || discovery_receipt_digest.is_zero()
                || outcome.discovery.elapsed_micros == 0
                || apply.backward_calls != 0
                || apply.optimizer_steps != 0
            {
                return Err(HcsnResearchErrorV2::Rule);
            }
            HcsnLearningRuleV2::ProgrammaticWeightEdit
        }
    };
    if rule != request.rule {
        return Err(HcsnResearchErrorV2::Rule);
    }
    if changed {
        Ok(HcsnResearchDispositionV2::Candidate {
            parameters_digest,
            changed_parameters,
        })
    } else {
        Ok(HcsnResearchDispositionV2::NoUpdate)
    }
}

#[cfg(test)]
#[path = "hcsn_research_tests.rs"]
mod tests;

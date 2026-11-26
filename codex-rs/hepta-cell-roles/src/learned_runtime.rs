//! Runtime input/output bridge for learned role owners.
//!
//! The role adapters in this crate intentionally project an already executed
//! runtime receipt.  This module makes that boundary explicit and reusable:
//! callers provide the exact runtime output and the exact successor state
//! bytes, while this bridge invokes the role adapter and fences the resulting
//! step to the state digest.  It never derives state bytes from a frontier
//! digest and it never manufactures resource or evidence receipts.

use codex_hepta_bellman_operator::WorldModelPredictionV1;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_ndu::NduEvaluationReceiptV2;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::Digest32;

use crate::CellAdapterContextV1;
use crate::CellRoleAdapterErrorV1;
use crate::CellRoleStepV1;
use crate::DecisionAdapterErrorV1;
use crate::DecisionAdapterV1;
use crate::DecisionExecutionBindingV1;
use crate::DecisionResultV1;
use crate::EvaluatorAdapterV1;
use crate::EvaluatorResultV1;
use crate::PredictorAdapterV1;
use crate::PredictorResultV1;
use crate::RepresentationAdapterV1;
use crate::RepresentationResultV1;
use crate::ValueAdapterV1;
use crate::ValueResultV1;

/// Runtime output supplied by the owner of one learned role.
///
/// The values are intentionally concrete owner receipts instead of input
/// digests.  The owner must obtain them from the corresponding runtime before
/// calling [`LearnedRoleRuntimeInputV1::adapt`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearnedRoleRuntimeInputV1 {
    Representation(Box<NeuronRuntimeOutputV1>),
    Predictor(WorldModelPredictionV1),
    Value(NduEvaluationReceiptV2),
    Decision(Box<LearnedRoleDecisionInputV1>),
    Evaluator {
        intuition: CalibratedIntuitionReceiptV1,
        uncertainty_ppm: u32,
        ood_ppm: u32,
    },
}

/// Calibrated intuition plus the owner-supplied policy/evidence binding for a
/// Decision step. It is boxed inside [`LearnedRoleRuntimeInputV1`] because a
/// decision receipt is materially larger than the other role inputs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedRoleDecisionInputV1 {
    pub intuition: CalibratedIntuitionReceiptV1,
    pub binding: DecisionExecutionBindingV1,
}

impl LearnedRoleRuntimeInputV1 {
    #[must_use]
    pub const fn role(&self) -> CellRoleV1 {
        match self {
            Self::Representation(_) => CellRoleV1::Representation,
            Self::Predictor(_) => CellRoleV1::Predictor,
            Self::Value(_) => CellRoleV1::Value,
            Self::Decision(_) => CellRoleV1::Decision,
            Self::Evaluator { .. } => CellRoleV1::Evaluator,
        }
    }

    /// Adapt the concrete runtime output and bind its successor to exact
    /// checkpoint bytes.  The adapters' projection-only successor is replaced
    /// only after the caller supplies those bytes; no bytes are synthesized.
    pub fn adapt(
        &self,
        context: &CellAdapterContextV1,
        state_bytes: &[u8],
    ) -> Result<LearnedRoleRuntimeExecutionV1, LearnedRoleRuntimeErrorV1> {
        if state_bytes.is_empty() {
            return Err(LearnedRoleRuntimeErrorV1::EmptyState);
        }
        let state_successor_digest = Digest32::of_bytes(state_bytes);
        let mut output = match self {
            Self::Representation(value) => LearnedRoleRuntimeOutputV1::Representation(
                RepresentationAdapterV1::adapt(context, value)?,
            ),
            Self::Predictor(value) => {
                LearnedRoleRuntimeOutputV1::Predictor(PredictorAdapterV1::adapt(context, value)?)
            }
            Self::Value(value) => {
                LearnedRoleRuntimeOutputV1::Value(ValueAdapterV1::adapt(context, value)?)
            }
            Self::Decision(value) => {
                let intuition = &value.intuition;
                let binding = &value.binding;
                if binding.state_successor_digest != state_successor_digest {
                    return Err(LearnedRoleRuntimeErrorV1::StateBinding);
                }
                LearnedRoleRuntimeOutputV1::Decision(Box::new(DecisionAdapterV1::adapt(
                    context, intuition, binding,
                )?))
            }
            Self::Evaluator {
                intuition,
                uncertainty_ppm,
                ood_ppm,
            } => LearnedRoleRuntimeOutputV1::Evaluator(EvaluatorAdapterV1::adapt(
                context,
                intuition,
                *uncertainty_ppm,
                *ood_ppm,
            )?),
        };
        if output.role() != self.role() {
            return Err(LearnedRoleRuntimeErrorV1::RoleBinding);
        }
        if output.receipt().state_predecessor_digest != context.state_predecessor_digest {
            return Err(LearnedRoleRuntimeErrorV1::StateBinding);
        }
        match &mut output {
            LearnedRoleRuntimeOutputV1::Representation(value) => {
                value.receipt.state_successor_digest = state_successor_digest;
            }
            LearnedRoleRuntimeOutputV1::Predictor(value) => {
                value.receipt.state_successor_digest = state_successor_digest;
            }
            LearnedRoleRuntimeOutputV1::Value(value) => {
                value.receipt.state_successor_digest = state_successor_digest;
            }
            LearnedRoleRuntimeOutputV1::Decision(value) => {
                value.receipt.state_successor_digest = state_successor_digest;
            }
            LearnedRoleRuntimeOutputV1::Evaluator(value) => {
                value.receipt.state_successor_digest = state_successor_digest;
            }
        }
        let receipt = output.receipt().clone();
        receipt.validate()?;
        Ok(LearnedRoleRuntimeExecutionV1 { output, receipt })
    }
}

/// Typed result returned by an adapter invocation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearnedRoleRuntimeOutputV1 {
    Representation(CellRoleStepV1<RepresentationResultV1>),
    Predictor(CellRoleStepV1<PredictorResultV1>),
    Value(CellRoleStepV1<ValueResultV1>),
    Decision(Box<CellRoleStepV1<DecisionResultV1>>),
    Evaluator(CellRoleStepV1<EvaluatorResultV1>),
}

impl LearnedRoleRuntimeOutputV1 {
    #[must_use]
    pub const fn role(&self) -> CellRoleV1 {
        match self {
            Self::Representation(_) => CellRoleV1::Representation,
            Self::Predictor(_) => CellRoleV1::Predictor,
            Self::Value(_) => CellRoleV1::Value,
            Self::Decision(_) => CellRoleV1::Decision,
            Self::Evaluator(_) => CellRoleV1::Evaluator,
        }
    }

    #[must_use]
    pub fn receipt(&self) -> &CellStepReceiptV1 {
        match self {
            Self::Representation(value) => &value.receipt,
            Self::Predictor(value) => &value.receipt,
            Self::Value(value) => &value.receipt,
            Self::Decision(value) => &value.receipt,
            Self::Evaluator(value) => &value.receipt,
        }
    }
}

/// Concrete typed output and the state-fenced receipt that must be committed.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearnedRoleRuntimeExecutionV1 {
    pub output: LearnedRoleRuntimeOutputV1,
    pub receipt: CellStepReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearnedRoleRuntimeErrorV1 {
    Adapter(CellRoleAdapterErrorV1),
    Decision(DecisionAdapterErrorV1),
    Contract(CellRoleContractErrorV1),
    EmptyState,
    RoleBinding,
    StateBinding,
}

impl std::fmt::Display for LearnedRoleRuntimeErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LearnedRoleRuntimeErrorV1 {}

impl From<CellRoleAdapterErrorV1> for LearnedRoleRuntimeErrorV1 {
    fn from(value: CellRoleAdapterErrorV1) -> Self {
        Self::Adapter(value)
    }
}

impl From<DecisionAdapterErrorV1> for LearnedRoleRuntimeErrorV1 {
    fn from(value: DecisionAdapterErrorV1) -> Self {
        Self::Decision(value)
    }
}

impl From<CellRoleContractErrorV1> for LearnedRoleRuntimeErrorV1 {
    fn from(value: CellRoleContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

#[cfg(test)]
#[path = "learned_runtime_tests.rs"]
mod tests;

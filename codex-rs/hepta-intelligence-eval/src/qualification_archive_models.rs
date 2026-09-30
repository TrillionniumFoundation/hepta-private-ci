//! Exact typed qualification payloads; no Debug, JSON coercion or host callback.
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::FixedQ32;

use super::ArchivedTiming;
use super::codec::*;
use crate::CrossFoldPlanReceiptV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::EvaluationIntervalV1;
use crate::HoldoutUseDispositionV1;
use crate::IndependentEvaluationBundleV1;
use crate::LongitudinalTimeEvidenceV1;
use crate::MetricGateV1;
use crate::MetricRoleContractV2;
use crate::MetricRoleV2;
use crate::ObservedFutureWindowV1;
use crate::SignedEvaluationEvidenceV1;

structure!(AuthenticatedPrincipalV1 {
    principal_id,
    credential_chain_digest,
    signing_key_digest,
    scope_digest,
    authority_epoch,
    authenticated_at,
    expires_at,
});
structure!(SignedLearningEvidenceV1 {
    evidence_id,
    principal_id,
    role,
    trust_digest,
    scope_digest,
    objective_digest,
    authority_epoch,
    issued_at,
    expires_at,
    payload_digest,
    signature,
});
structure!(SignedEvaluationEvidenceV1 {
    generator_plan,
    evaluator_bundle
});
structure!(MetricRoleContractV2 { metric_id, role });
structure!(EvaluationIntervalV1 { lower, upper });
structure!(MetricGateV1 {
    metric_id,
    direction,
    candidate,
    baseline,
    safety_floor,
    support_digest
});
structure!(ObservedFutureWindowV1 {
    window_id,
    snapshot_id,
    starts_unix_micros,
    ends_unix_micros,
    observation_count,
    observed_source_cut,
});
structure!(LongitudinalTimeEvidenceV1 {
    frozen_unix_micros,
    windows,
    observer
});
structure!(IndependentEvaluationBundleV1 {
    evaluation_id,
    candidate_id,
    baseline_id,
    claim_scope,
    generator,
    evaluator,
    frozen_plan,
    holdout_use,
    objective_digest,
    dataset_digest,
    estimand_digest,
    estimate_receipt_digest,
    support_audit_digest,
    confidence_receipt_digest,
    retention_receipt_digests,
    unlearning_receipt_digest,
    snapshot_ids,
    future_window_ids,
    family_alpha_ppm,
    simultaneous_comparisons,
    metrics,
});

impl Wire for CrossFoldPlanReceiptV1 {
    fn write(&self, output: &mut Writer) -> Result<()> {
        crate::closure::encode_holdout_plan(self)?.write(output)
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        Ok(crate::closure::decode_holdout_plan(&Vec::<u8>::read(
            input,
        )?)?)
    }
}

impl Wire for EvaluationClaimScopeV1 {
    fn write(&self, output: &mut Writer) -> Result<()> {
        match self {
            Self::Qualification => 0_u8.write(output),
            Self::SystemLongitudinal => 1_u8.write(output),
        }
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        match u8::read(input)? {
            0 => Ok(Self::Qualification),
            1 => Ok(Self::SystemLongitudinal),
            _ => Err(invalid()),
        }
    }
}

impl Wire for EvaluationDirectionV1 {
    fn write(&self, output: &mut Writer) -> Result<()> {
        match self {
            Self::Maximize => 0_u8.write(output),
            Self::Minimize => 1_u8.write(output),
        }
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        match u8::read(input)? {
            0 => Ok(Self::Maximize),
            1 => Ok(Self::Minimize),
            _ => Err(invalid()),
        }
    }
}

impl Wire for HoldoutUseDispositionV1 {
    fn write(&self, output: &mut Writer) -> Result<()> {
        match self {
            Self::Recorded => 0_u8.write(output),
            Self::IdempotentReplay => 1_u8.write(output),
        }
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        match u8::read(input)? {
            0 => Ok(Self::Recorded),
            1 => Ok(Self::IdempotentReplay),
            _ => Err(invalid()),
        }
    }
}

impl Wire for LearningEvidenceRoleV1 {
    fn write(&self, output: &mut Writer) -> Result<()> {
        match self {
            Self::Generator => 0_u8.write(output),
            Self::Evaluator => 1_u8.write(output),
            Self::Observer => 2_u8.write(output),
            _ => Err(invalid()),
        }
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        match u8::read(input)? {
            0 => Ok(Self::Generator),
            1 => Ok(Self::Evaluator),
            2 => Ok(Self::Observer),
            _ => Err(invalid()),
        }
    }
}

impl Wire for MetricRoleV2 {
    fn write(&self, output: &mut Writer) -> Result<()> {
        match self {
            Self::PrimarySuperiority {
                minimum_improvement,
            } => {
                0_u8.write(output)?;
                minimum_improvement.write(output)
            }
            Self::NonInferiority { maximum_regression } => {
                1_u8.write(output)?;
                maximum_regression.write(output)
            }
            Self::AbsoluteConstraint => 2_u8.write(output),
        }
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        match u8::read(input)? {
            0 => Ok(Self::PrimarySuperiority {
                minimum_improvement: FixedQ32::read(input)?,
            }),
            1 => Ok(Self::NonInferiority {
                maximum_regression: FixedQ32::read(input)?,
            }),
            2 => Ok(Self::AbsoluteConstraint),
            _ => Err(invalid()),
        }
    }
}

impl Wire for ArchivedTiming {
    fn write(&self, output: &mut Writer) -> Result<()> {
        match self {
            Self::Qualification => 0_u8.write(output),
            Self::SystemLongitudinal {
                timing,
                minimum_window_micros,
            } => {
                1_u8.write(output)?;
                timing.write(output)?;
                minimum_window_micros.write(output)
            }
        }
    }
    fn read(input: &mut Reader<'_>) -> Result<Self> {
        match u8::read(input)? {
            0 => Ok(Self::Qualification),
            1 => Ok(Self::SystemLongitudinal {
                timing: LongitudinalTimeEvidenceV1::read(input)?,
                minimum_window_micros: u64::read(input)?,
            }),
            _ => Err(invalid()),
        }
    }
}

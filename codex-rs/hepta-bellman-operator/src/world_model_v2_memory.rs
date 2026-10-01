//! Conservative peak-memory preflight for the world-model fitting profile.

use codex_hepta_types::StableId;

use crate::OperatorWorkErrorV1;
use crate::WorldModelSampleV1;
use crate::checked_add;
use crate::checked_mul;
use crate::checked_u64;

use super::Group;
use super::TransitionBranchV2;
use super::TransitionEstimateV2;
use super::WorldModelPlanV2;

pub(super) fn estimate_fit_bytes(plan: &WorldModelPlanV2) -> Result<u64, OperatorWorkErrorV1> {
    let samples = checked_u64(plan.samples.len())?;
    let mut id_bytes = checked_u64(plan.model_id.as_str().len())?;
    for sample in &plan.samples {
        for value in [
            &sample.sample_id,
            &sample.state_id,
            &sample.action_id,
            &sample.next_state_id,
        ] {
            id_bytes = checked_add(id_bytes, checked_u64(value.as_str().len())?)?;
        }
    }
    // Conservatively cover input capacity, stable-sort scratch, BTree nodes,
    // growing evidence vectors, temporary branch rows, Vec-to-Arc overlap and
    // digest preimages. Identifier storage is heap-owned, not part of size_of.
    let sample_structs = checked_mul(
        checked_add(checked_u64(plan.samples.capacity())?, samples)?,
        u64::try_from(std::mem::size_of::<WorldModelSampleV1>())
            .map_err(|_| OperatorWorkErrorV1::Arithmetic)?,
    )?;
    let grouping = checked_mul(
        samples,
        checked_add(
            u64::try_from(
                std::mem::size_of::<Group>() + std::mem::size_of::<(StableId, StableId)>(),
            )
            .map_err(|_| OperatorWorkErrorV1::Arithmetic)?,
            /*right*/ 512,
        )?,
    )?;
    let estimates = checked_mul(
        samples,
        checked_mul(
            u64::try_from(std::mem::size_of::<TransitionEstimateV2>())
                .map_err(|_| OperatorWorkErrorV1::Arithmetic)?,
            /*right*/ 2,
        )?,
    )?;
    let evidence = checked_mul(samples, /*right*/ 160)?;
    let branches = checked_mul(
        samples,
        checked_add(
            checked_mul(
                u64::try_from(std::mem::size_of::<TransitionBranchV2>())
                    .map_err(|_| OperatorWorkErrorV1::Arithmetic)?,
                /*right*/ 2,
            )?,
            u64::try_from(
                std::mem::size_of::<(StableId, u32, u64, u128)>()
                    + std::mem::size_of::<usize>()
                    + 512,
            )
            .map_err(|_| OperatorWorkErrorV1::Arithmetic)?,
        )?,
    )?;
    let digests = checked_mul(samples, /*right*/ 128)?;
    let mut total = 4_096;
    for amount in [
        sample_structs,
        grouping,
        estimates,
        evidence,
        branches,
        digests,
        checked_mul(id_bytes, /*right*/ 3)?,
    ] {
        total = checked_add(total, amount)?;
    }
    Ok(total)
}

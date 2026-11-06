//! Explicit HCSN interval planning; this is not a numerical kernel or a writer.
//!
//! V1 clocks use integer microseconds in one host-attested monotonic epoch;
//! numerical backends use seconds. Input and its conditioned boundary are sampled
//! at the interval's left edge, input is held over [start, end), and output is at
//! end. The forecast horizon describes the task target, not elapsed integration
//! time or the HX financial maturity. Owners publish state only after execution.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde::Serialize;

const MAX_DELTA_MICROS: u64 = (1_u64 << 53) - 1;
const MAX_SUBSTEPS: u32 = 4_096;
const MAX_BATCH_INTERVALS: usize = 256;
const MAX_CHECKPOINT_BYTES: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum HcsnIntegrationV1 {
    ValueKernel,
    PopulationGrid { step_micros: u64, max_substeps: u32 },
}

/// Separate opt-in profile; existing sparse Q24 profiles retain their semantics.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HcsnTimeProfileV1 {
    pub maximum_gap_micros: u64,
    pub forecast_horizon_micros: u64,
    pub integration: HcsnIntegrationV1,
}

impl HcsnTimeProfileV1 {
    pub fn digest(&self) -> Result<Digest32, HcsnTimeError> {
        if !(1..=MAX_DELTA_MICROS).contains(&self.maximum_gap_micros)
            || !(1..=MAX_DELTA_MICROS).contains(&self.forecast_horizon_micros)
        {
            return Err(HcsnTimeError::InvalidProfile);
        }
        let mut bytes =
            b"hepta.neuron.hcsn-time-profile.v1.seconds.zoh-left.sample-boundary.right-output"
                .to_vec();
        bytes.extend_from_slice(&self.maximum_gap_micros.to_be_bytes());
        bytes.extend_from_slice(&self.forecast_horizon_micros.to_be_bytes());
        match self.integration {
            HcsnIntegrationV1::ValueKernel => bytes.push(0),
            HcsnIntegrationV1::PopulationGrid {
                step_micros,
                max_substeps,
            } => {
                if !(1..=self.maximum_gap_micros).contains(&step_micros)
                    || !(1..=MAX_SUBSTEPS).contains(&max_substeps)
                {
                    return Err(HcsnTimeError::InvalidProfile);
                }
                bytes.push(1);
                bytes.extend_from_slice(&step_micros.to_be_bytes());
                bytes.extend_from_slice(&max_substeps.to_be_bytes());
            }
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// The host supplies a clock epoch and the exact model/parameter artifact identity.
/// These bindings are not credentials; owner authorization remains external.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HcsnClockIdentityV1 {
    pub clock_epoch: Digest32,
    pub scope_digest: Digest32,
    pub generation: Generation,
    pub writer_epoch: u64,
    pub model_digest: Digest32,
}

impl HcsnClockIdentityV1 {
    fn validate(&self) -> Result<(), HcsnTimeError> {
        if self.clock_epoch.is_zero()
            || self.scope_digest.is_zero()
            || self.model_digest.is_zero()
            || self.writer_epoch == 0
        {
            return Err(HcsnTimeError::InvalidIdentity);
        }
        Ok(())
    }
}

/// Clock metadata binds the backend's complete state digest, not tensor contents.
/// It does not by itself persist, restore, or validate those backend tensors.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HcsnClockCheckpointV1 {
    profile_digest: Digest32,
    identity: HcsnClockIdentityV1,
    last_micros: u64,
    sequence: u64,
    state_digest: Digest32,
    predecessor_digest: Digest32,
    digest: Digest32,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ClockCheckpointDto {
    schema_version: u32,
    profile_digest: String,
    clock_epoch: String,
    scope_digest: String,
    generation: u64,
    writer_epoch: u64,
    model_digest: String,
    last_micros: u64,
    sequence: u64,
    state_digest: String,
    predecessor_digest: String,
}

impl HcsnClockCheckpointV1 {
    pub fn initial(
        profile: &HcsnTimeProfileV1,
        identity: HcsnClockIdentityV1,
        last_micros: u64,
        state_digest: Digest32,
    ) -> Result<Self, HcsnTimeError> {
        identity.validate()?;
        if state_digest.is_zero() {
            return Err(HcsnTimeError::InvalidState);
        }
        let mut checkpoint = Self {
            profile_digest: profile.digest()?,
            identity,
            last_micros,
            sequence: 0,
            state_digest,
            predecessor_digest: Digest32::ZERO,
            digest: Digest32::ZERO,
        };
        checkpoint.digest = checkpoint.calculate_digest();
        Ok(checkpoint)
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn last_micros(&self) -> u64 {
        self.last_micros
    }

    pub fn sequence(&self) -> u64 {
        self.sequence
    }

    pub fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    fn calculate_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.neuron.hcsn-clock-checkpoint.v1".to_vec();
        for digest in [
            self.profile_digest,
            self.identity.clock_epoch,
            self.identity.scope_digest,
            self.identity.model_digest,
            self.state_digest,
            self.predecessor_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            self.identity.generation.get(),
            self.identity.writer_epoch,
            self.last_micros,
            self.sequence,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn encode(&self) -> Result<Vec<u8>, HcsnTimeError> {
        serde_json::to_vec(&ClockCheckpointDto {
            schema_version: 1,
            profile_digest: self.profile_digest.to_string(),
            clock_epoch: self.identity.clock_epoch.to_string(),
            scope_digest: self.identity.scope_digest.to_string(),
            generation: self.identity.generation.get(),
            writer_epoch: self.identity.writer_epoch,
            model_digest: self.identity.model_digest.to_string(),
            last_micros: self.last_micros,
            sequence: self.sequence,
            state_digest: self.state_digest.to_string(),
            predecessor_digest: self.predecessor_digest.to_string(),
        })
        .map_err(|_| HcsnTimeError::CheckpointFormat)
    }

    /// The expected digest must come from the owner's independently retained
    /// acknowledged state, never from the checkpoint being recovered. A new
    /// boot/clock epoch requires explicit state migration, not timestamp rebasing.
    pub fn restore(
        profile: &HcsnTimeProfileV1,
        identity: HcsnClockIdentityV1,
        bytes: &[u8],
        expected_checkpoint_digest: Digest32,
    ) -> Result<Self, HcsnTimeError> {
        if bytes.len() > MAX_CHECKPOINT_BYTES {
            return Err(HcsnTimeError::CheckpointTooLarge);
        }
        let dto: ClockCheckpointDto =
            serde_json::from_slice(bytes).map_err(|_| HcsnTimeError::CheckpointFormat)?;
        let parse = |raw: &str| raw.parse().map_err(|_| HcsnTimeError::CheckpointFormat);
        let mut checkpoint = Self {
            profile_digest: parse(&dto.profile_digest)?,
            identity: HcsnClockIdentityV1 {
                clock_epoch: parse(&dto.clock_epoch)?,
                scope_digest: parse(&dto.scope_digest)?,
                generation: Generation::new(dto.generation)
                    .map_err(|_| HcsnTimeError::InvalidIdentity)?,
                writer_epoch: dto.writer_epoch,
                model_digest: parse(&dto.model_digest)?,
            },
            last_micros: dto.last_micros,
            sequence: dto.sequence,
            state_digest: parse(&dto.state_digest)?,
            predecessor_digest: parse(&dto.predecessor_digest)?,
            digest: Digest32::ZERO,
        };
        checkpoint.identity.validate()?;
        identity.validate()?;
        if checkpoint.identity != identity {
            return Err(HcsnTimeError::IdentityMismatch);
        }
        if checkpoint.profile_digest != profile.digest()? {
            return Err(HcsnTimeError::ProfileMismatch);
        }
        checkpoint.digest = checkpoint.calculate_digest();
        if dto.schema_version != 1
            || checkpoint.state_digest.is_zero()
            || (checkpoint.sequence == 0) != checkpoint.predecessor_digest.is_zero()
            || expected_checkpoint_digest.is_zero()
            || checkpoint.digest != expected_checkpoint_digest
        {
            return Err(HcsnTimeError::CheckpointMismatch);
        }
        Ok(checkpoint)
    }
}

/// Integer wire plan. A backend must verify its bindings before executing; a
/// deserialized plan alone provides neither execution evidence nor authority.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HcsnIntervalPlanV1 {
    pub schema_version: u32,
    pub start_micros: u64,
    pub end_micros: u64,
    pub elapsed_micros: u64,
    pub substep_micros: u64,
    pub substeps: u32,
    pub forecast_horizon_micros: u64,
    pub profile_digest: String,
    pub checkpoint_before: String,
}

pub fn plan_hcsn_interval_v1(
    profile: &HcsnTimeProfileV1,
    identity: HcsnClockIdentityV1,
    previous: &HcsnClockCheckpointV1,
    end_micros: u64,
) -> Result<HcsnIntervalPlanV1, HcsnTimeError> {
    plan_interval_from_start(
        profile,
        identity,
        previous,
        previous.last_micros,
        end_micros,
    )
}

/// Plan one coarse worker block from a real, already committed clock anchor.
/// All entries retain that same `checkpoint_before`; only an integer cursor
/// advances internally. No intermediate state digest is invented or committed.
pub fn plan_hcsn_batch_v1(
    profile: &HcsnTimeProfileV1,
    identity: HcsnClockIdentityV1,
    initial: &HcsnClockCheckpointV1,
    ends: &[u64],
) -> Result<Vec<HcsnIntervalPlanV1>, HcsnTimeError> {
    if !(1..=MAX_BATCH_INTERVALS).contains(&ends.len()) {
        return Err(HcsnTimeError::InvalidBatch);
    }
    let mut start = initial.last_micros;
    let mut plans = Vec::with_capacity(ends.len());
    for end in ends {
        plans.push(plan_interval_from_start(
            profile, identity, initial, start, *end,
        )?);
        start = *end;
    }
    Ok(plans)
}

fn plan_interval_from_start(
    profile: &HcsnTimeProfileV1,
    identity: HcsnClockIdentityV1,
    previous: &HcsnClockCheckpointV1,
    start_micros: u64,
    end_micros: u64,
) -> Result<HcsnIntervalPlanV1, HcsnTimeError> {
    identity.validate()?;
    let profile_digest = profile.digest()?;
    if previous.identity != identity {
        return Err(HcsnTimeError::IdentityMismatch);
    }
    if previous.profile_digest != profile_digest {
        return Err(HcsnTimeError::ProfileMismatch);
    }
    previous
        .sequence
        .checked_add(1)
        .ok_or(HcsnTimeError::Arithmetic)?;
    let elapsed = end_micros
        .checked_sub(start_micros)
        .filter(|elapsed| *elapsed > 0)
        .ok_or(HcsnTimeError::NonIncreasingTime)?;
    if elapsed > profile.maximum_gap_micros {
        return Err(HcsnTimeError::GapExceeded);
    }
    end_micros
        .checked_add(profile.forecast_horizon_micros)
        .ok_or(HcsnTimeError::Arithmetic)?;
    let (substep_micros, substeps) = match profile.integration {
        HcsnIntegrationV1::ValueKernel => (elapsed, 1),
        HcsnIntegrationV1::PopulationGrid {
            step_micros,
            max_substeps,
        } => {
            if !elapsed.is_multiple_of(step_micros) {
                return Err(HcsnTimeError::GridMisaligned);
            }
            let steps = elapsed / step_micros;
            if steps > u64::from(max_substeps) {
                return Err(HcsnTimeError::SubstepLimit);
            }
            (step_micros, steps as u32)
        }
    };
    Ok(HcsnIntervalPlanV1 {
        schema_version: 1,
        start_micros,
        end_micros,
        elapsed_micros: elapsed,
        substep_micros,
        substeps,
        forecast_horizon_micros: profile.forecast_horizon_micros,
        profile_digest: profile_digest.to_string(),
        checkpoint_before: previous.digest.to_string(),
    })
}

/// Produce clock metadata after the caller validates real backend execution.
/// This pure function does not acknowledge, write or promote the candidate.
pub fn commit_hcsn_interval_v1(
    profile: &HcsnTimeProfileV1,
    identity: HcsnClockIdentityV1,
    previous: &HcsnClockCheckpointV1,
    plan: &HcsnIntervalPlanV1,
    state_digest: Digest32,
) -> Result<HcsnClockCheckpointV1, HcsnTimeError> {
    if *plan != plan_hcsn_interval_v1(profile, identity, previous, plan.end_micros)? {
        return Err(HcsnTimeError::PlanMismatch);
    }
    advance_clock(previous, plan.end_micros, state_digest)
}

/// Commit metadata once after the entire admitted block has completed. The
/// owner must bind `state_digest` to the verified final backend tensors; partial
/// execution, cancellation and UNKNOWN results leave the original anchor intact.
pub fn commit_hcsn_batch_v1(
    profile: &HcsnTimeProfileV1,
    identity: HcsnClockIdentityV1,
    initial: &HcsnClockCheckpointV1,
    plans: &[HcsnIntervalPlanV1],
    state_digest: Digest32,
) -> Result<HcsnClockCheckpointV1, HcsnTimeError> {
    if !(1..=MAX_BATCH_INTERVALS).contains(&plans.len()) {
        return Err(HcsnTimeError::InvalidBatch);
    }
    let ends: Vec<_> = plans.iter().map(|plan| plan.end_micros).collect();
    if plans != plan_hcsn_batch_v1(profile, identity, initial, &ends)?.as_slice() {
        return Err(HcsnTimeError::PlanMismatch);
    }
    let last = plans.last().ok_or(HcsnTimeError::InvalidBatch)?;
    advance_clock(initial, last.end_micros, state_digest)
}

fn advance_clock(
    previous: &HcsnClockCheckpointV1,
    end_micros: u64,
    state_digest: Digest32,
) -> Result<HcsnClockCheckpointV1, HcsnTimeError> {
    if state_digest.is_zero() {
        return Err(HcsnTimeError::InvalidState);
    }
    let mut next = HcsnClockCheckpointV1 {
        profile_digest: previous.profile_digest,
        identity: previous.identity,
        last_micros: end_micros,
        sequence: previous
            .sequence
            .checked_add(1)
            .ok_or(HcsnTimeError::Arithmetic)?,
        state_digest,
        predecessor_digest: previous.digest,
        digest: Digest32::ZERO,
    };
    next.digest = next.calculate_digest();
    Ok(next)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HcsnTimeError {
    InvalidProfile,
    InvalidBatch,
    InvalidIdentity,
    InvalidState,
    IdentityMismatch,
    ProfileMismatch,
    NonIncreasingTime,
    GapExceeded,
    GridMisaligned,
    SubstepLimit,
    Arithmetic,
    PlanMismatch,
    CheckpointFormat,
    CheckpointTooLarge,
    CheckpointMismatch,
}

impl fmt::Display for HcsnTimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for HcsnTimeError {}

#[cfg(test)]
#[path = "continuous_time_tests.rs"]
mod tests;

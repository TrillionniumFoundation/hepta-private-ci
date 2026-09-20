#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

const MAX_OCCURRENCES: usize = 1_024;
const MAX_STEPS_PER_OCCURRENCE: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Occurrence {
    pub occurrence_id: String,
    pub schedule_id: String,
    pub schedule_revision: u64,
    pub scheduled_unix_ms: u64,
    pub graph_generation: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Claim {
    pub occurrence_id: String,
    pub fence: u64,
    pub claimant_id: String,
    pub expires_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StepIntent {
    pub step_id: String,
    pub operation_id: String,
    pub authority_epoch: u64,
    pub semantic_digest: String,
    pub final_payload_digest: String,
    pub grant_payload_digest: String,
    pub deadline_ms: u64,
    pub dependencies: Vec<String>,
    pub compensation_for: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EffectObservation {
    pub terminal_observed: bool,
    pub succeeded: bool,
    pub outcome_digest: Option<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StepState {
    Pending,
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StepReceipt {
    pub occurrence_id: String,
    pub step_id: String,
    pub operation_id: String,
    pub state: StepState,
    pub outcome_digest: Option<String>,
    pub terminal_observed: bool,
    pub idempotent: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidOccurrence,
    CapacityExceeded,
    OccurrenceNotFound,
    ClaimRequired,
    ClaimExpired,
    StaleFence,
    PayloadMismatch,
    OperationConflict,
    DependencyNotTerminal,
    StepCapacity,
    Driver(String),
    TerminalOutcomeMissing,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub trait EffectDriver {
    fn dispatch(
        &mut self,
        occurrence: &Occurrence,
        claim: &Claim,
        intent: &StepIntent,
    ) -> Result<EffectObservation, Error>;
}

#[derive(Debug)]
struct StepRecord {
    semantic_digest: String,
    receipt: StepReceipt,
}

#[derive(Debug)]
struct OccurrenceRecord {
    occurrence: Occurrence,
    claim: Option<Claim>,
    steps: BTreeMap<String, StepRecord>,
}

#[derive(Debug)]
pub struct TaskFlowExecutor<D: EffectDriver> {
    driver: D,
    occurrences: BTreeMap<String, OccurrenceRecord>,
}

impl<D: EffectDriver> TaskFlowExecutor<D> {
    pub fn new(driver: D) -> Self {
        Self {
            driver,
            occurrences: BTreeMap::new(),
        }
    }

    pub fn register_occurrence(&mut self, occurrence: Occurrence) -> Result<(), Error> {
        validate_occurrence(&occurrence)?;
        if let Some(current) = self.occurrences.get(&occurrence.occurrence_id) {
            if current.occurrence == occurrence {
                return Ok(());
            }
            return Err(Error::OperationConflict);
        }
        if self.occurrences.len() >= MAX_OCCURRENCES {
            return Err(Error::CapacityExceeded);
        }
        self.occurrences.insert(
            occurrence.occurrence_id.clone(),
            OccurrenceRecord {
                occurrence,
                claim: None,
                steps: BTreeMap::new(),
            },
        );
        Ok(())
    }

    pub fn claim_occurrence(&mut self, now_ms: u64, claim: Claim) -> Result<(), Error> {
        validate_claim(now_ms, &claim)?;
        let record = self
            .occurrences
            .get_mut(&claim.occurrence_id)
            .ok_or(Error::OccurrenceNotFound)?;
        if let Some(current) = &record.claim {
            if current == &claim {
                return Ok(());
            }
            if claim.fence <= current.fence {
                return Err(Error::StaleFence);
            }
        }
        record.claim = Some(claim);
        Ok(())
    }

    pub fn execute_step(
        &mut self,
        now_ms: u64,
        occurrence_id: &str,
        expected_fence: u64,
        intent: StepIntent,
    ) -> Result<StepReceipt, Error> {
        validate_identity(occurrence_id, "occurrence")?;
        validate_intent(now_ms, &intent)?;
        let record = self
            .occurrences
            .get_mut(occurrence_id)
            .ok_or(Error::OccurrenceNotFound)?;
        let claim = record.claim.as_ref().ok_or(Error::ClaimRequired)?;
        if claim.fence != expected_fence {
            return Err(Error::StaleFence);
        }
        if now_ms >= claim.expires_at_ms {
            return Err(Error::ClaimExpired);
        }
        if intent.final_payload_digest != intent.grant_payload_digest {
            return Err(Error::PayloadMismatch);
        }
        if let Some(current) = record.steps.get(&intent.operation_id) {
            if current.semantic_digest != intent.semantic_digest {
                return Err(Error::OperationConflict);
            }
            let mut receipt = current.receipt.clone();
            receipt.idempotent = true;
            return Ok(receipt);
        }
        if record.steps.len() >= MAX_STEPS_PER_OCCURRENCE {
            return Err(Error::StepCapacity);
        }
        for dependency in &intent.dependencies {
            let state = record
                .steps
                .values()
                .find(|step| step.receipt.step_id == *dependency)
                .map(|step| step.receipt.state);
            if state != Some(StepState::Succeeded) {
                return Err(Error::DependencyNotTerminal);
            }
        }
        if let Some(compensation_for) = &intent.compensation_for {
            let target = record
                .steps
                .values()
                .find(|step| step.receipt.operation_id == *compensation_for)
                .ok_or(Error::DependencyNotTerminal)?;
            if target.receipt.state == StepState::Pending {
                return Err(Error::DependencyNotTerminal);
            }
        }

        let observation = self.driver.dispatch(&record.occurrence, claim, &intent)?;
        let (state, outcome_digest, terminal_observed) = if !observation.terminal_observed {
            (StepState::Indeterminate, None, false)
        } else {
            let outcome = observation
                .outcome_digest
                .as_ref()
                .ok_or(Error::TerminalOutcomeMissing)?;
            validate_digest(outcome, "outcome")?;
            (
                if observation.succeeded {
                    StepState::Succeeded
                } else {
                    StepState::Failed
                },
                observation.outcome_digest,
                true,
            )
        };
        let receipt = StepReceipt {
            occurrence_id: occurrence_id.to_string(),
            step_id: intent.step_id,
            operation_id: intent.operation_id.clone(),
            state,
            outcome_digest,
            terminal_observed,
            idempotent: false,
        };
        record.steps.insert(
            intent.operation_id,
            StepRecord {
                semantic_digest: intent.semantic_digest,
                receipt: receipt.clone(),
            },
        );
        Ok(receipt)
    }

    pub fn step(&self, occurrence_id: &str, operation_id: &str) -> Option<&StepReceipt> {
        self.occurrences
            .get(occurrence_id)?
            .steps
            .get(operation_id)
            .map(|record| &record.receipt)
    }
}

fn validate_occurrence(value: &Occurrence) -> Result<(), Error> {
    validate_identity(&value.occurrence_id, "occurrence")?;
    validate_identity(&value.schedule_id, "schedule")?;
    if value.schedule_revision == 0 || value.graph_generation == 0 {
        return Err(Error::InvalidOccurrence);
    }
    Ok(())
}

fn validate_claim(now_ms: u64, value: &Claim) -> Result<(), Error> {
    validate_identity(&value.occurrence_id, "occurrence")?;
    validate_identity(&value.claimant_id, "claimant")?;
    if value.fence == 0 || value.expires_at_ms <= now_ms {
        return Err(Error::ClaimExpired);
    }
    Ok(())
}

fn validate_intent(now_ms: u64, value: &StepIntent) -> Result<(), Error> {
    validate_identity(&value.step_id, "step")?;
    validate_identity(&value.operation_id, "operation")?;
    validate_digest(&value.semantic_digest, "semantic")?;
    validate_digest(&value.final_payload_digest, "payload")?;
    validate_digest(&value.grant_payload_digest, "grant payload")?;
    if value.authority_epoch == 0 || value.deadline_ms <= now_ms {
        return Err(Error::ClaimExpired);
    }
    if value.dependencies.len() > MAX_STEPS_PER_OCCURRENCE {
        return Err(Error::StepCapacity);
    }
    for dependency in &value.dependencies {
        validate_identity(dependency, "dependency")?;
    }
    if let Some(operation) = &value.compensation_for {
        validate_identity(operation, "compensation operation")?;
    }
    Ok(())
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(Error::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), Error> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(Error::InvalidDigest(field));
    }
    Ok(())
}

#[cfg(test)]
#[path = "effect_executor_tests.rs"]
mod tests;

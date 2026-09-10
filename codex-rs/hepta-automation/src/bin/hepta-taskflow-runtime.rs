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
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StepReceipt {
    pub occurrence_id: String,
    pub step_id: String,
    pub operation_id: String,
    pub claim_fence: u64,
    pub authority_epoch: u64,
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
    StepIdentityConflict,
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
    intent: StepIntent,
    claim: Claim,
    receipt: StepReceipt,
}

#[derive(Debug)]
struct OccurrenceRecord {
    occurrence: Occurrence,
    claim: Option<Claim>,
    steps: BTreeMap<String, StepRecord>,
    step_operations: BTreeMap<String, String>,
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
                step_operations: BTreeMap::new(),
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
            if current.intent != intent || current.claim != *claim {
                return Err(Error::OperationConflict);
            }
            let mut receipt = current.receipt.clone();
            receipt.idempotent = true;
            return Ok(receipt);
        }
        if let Some(existing_operation) = record.step_operations.get(&intent.step_id) {
            if existing_operation != &intent.operation_id {
                return Err(Error::StepIdentityConflict);
            }
        }
        if record.steps.len() >= MAX_STEPS_PER_OCCURRENCE {
            return Err(Error::StepCapacity);
        }

        for dependency in &intent.dependencies {
            let dependency_operation = record
                .step_operations
                .get(dependency)
                .ok_or(Error::DependencyNotTerminal)?;
            let dependency_record = record
                .steps
                .get(dependency_operation)
                .ok_or(Error::DependencyNotTerminal)?;
            if dependency_record.receipt.state != StepState::Succeeded
                || !dependency_record.receipt.terminal_observed
            {
                return Err(Error::DependencyNotTerminal);
            }
        }
        if let Some(compensation_for) = &intent.compensation_for {
            let target = record
                .steps
                .get(compensation_for)
                .ok_or(Error::DependencyNotTerminal)?;
            if !target.receipt.terminal_observed {
                return Err(Error::DependencyNotTerminal);
            }
        }

        let observation = self
            .driver
            .dispatch(&record.occurrence, claim, &intent)?;
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
            step_id: intent.step_id.clone(),
            operation_id: intent.operation_id.clone(),
            claim_fence: claim.fence,
            authority_epoch: intent.authority_epoch,
            state,
            outcome_digest,
            terminal_observed,
            idempotent: false,
        };
        record
            .step_operations
            .insert(intent.step_id.clone(), intent.operation_id.clone());
        record.steps.insert(
            intent.operation_id.clone(),
            StepRecord {
                intent,
                claim: claim.clone(),
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
    if value.schedule_revision == 0
        || value.scheduled_unix_ms == 0
        || value.graph_generation == 0
    {
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
        if dependency == &value.step_id {
            return Err(Error::DependencyNotTerminal);
        }
    }
    if !value
        .dependencies
        .windows(2)
        .all(|window| window[0] < window[1])
    {
        return Err(Error::OperationConflict);
    }
    if let Some(operation) = &value.compensation_for {
        validate_identity(operation, "compensation operation")?;
        if operation == &value.operation_id {
            return Err(Error::OperationConflict);
        }
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

#[derive(Debug)]
struct NoProductEffectDriver;

impl EffectDriver for NoProductEffectDriver {
    fn dispatch(
        &mut self,
        _occurrence: &Occurrence,
        _claim: &Claim,
        _intent: &StepIntent,
    ) -> Result<EffectObservation, Error> {
        Err(Error::Driver(
            "no product effect driver is enrolled in this source kernel".to_string(),
        ))
    }
}

fn main() {
    let mut arguments = std::env::args().skip(1);
    match (arguments.next().as_deref(), arguments.next()) {
        (Some("--describe"), None) => {
            println!(
                "{{\"kind\":\"hepta.taskflow.kernel.v1\",\"productEffectDriverEnrolled\":false,\"authorityGranted\":false}}"
            );
        }
        (Some("--self-test"), None) => {
            let mut executor = TaskFlowExecutor::new(NoProductEffectDriver);
            executor
                .register_occurrence(Occurrence {
                    occurrence_id: "self-test.occurrence".to_string(),
                    schedule_id: "self-test.schedule".to_string(),
                    schedule_revision: 1,
                    scheduled_unix_ms: 1,
                    graph_generation: 1,
                })
                .expect("bounded self-test occurrence");
            executor
                .claim_occurrence(
                    1,
                    Claim {
                        occurrence_id: "self-test.occurrence".to_string(),
                        fence: 1,
                        claimant_id: "self-test.scheduler".to_string(),
                        expires_at_ms: 2,
                    },
                )
                .expect("bounded self-test claim");
            println!(
                "{{\"status\":\"PASS_HEPTA_TASKFLOW_KERNEL_SELF_TEST\",\"productEffectDriverEnrolled\":false}}"
            );
        }
        _ => {
            eprintln!("usage: hepta-taskflow-runtime --describe|--self-test");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug)]
    struct Driver {
        terminal: bool,
        succeeded: bool,
        calls: usize,
    }

    impl EffectDriver for Driver {
        fn dispatch(
            &mut self,
            _occurrence: &Occurrence,
            _claim: &Claim,
            _intent: &StepIntent,
        ) -> Result<EffectObservation, Error> {
            self.calls += 1;
            Ok(EffectObservation {
                terminal_observed: self.terminal,
                succeeded: self.succeeded,
                outcome_digest: self.terminal.then(|| "9".repeat(64)),
            })
        }
    }

    fn occurrence() -> Occurrence {
        Occurrence {
            occurrence_id: "occurrence.1".to_string(),
            schedule_id: "schedule.1".to_string(),
            schedule_revision: 1,
            scheduled_unix_ms: 1_000,
            graph_generation: 2,
        }
    }

    fn claim(fence: u64) -> Claim {
        Claim {
            occurrence_id: "occurrence.1".to_string(),
            fence,
            claimant_id: "scheduler.1".to_string(),
            expires_at_ms: 10_000,
        }
    }

    fn intent(operation: &str, step: &str) -> StepIntent {
        StepIntent {
            step_id: step.to_string(),
            operation_id: operation.to_string(),
            authority_epoch: 4,
            semantic_digest: "1".repeat(64),
            final_payload_digest: "2".repeat(64),
            grant_payload_digest: "2".repeat(64),
            deadline_ms: 9_000,
            dependencies: Vec::new(),
            compensation_for: None,
        }
    }

    fn executor(terminal: bool, succeeded: bool) -> TaskFlowExecutor<Driver> {
        let mut executor = TaskFlowExecutor::new(Driver {
            terminal,
            succeeded,
            calls: 0,
        });
        executor
            .register_occurrence(occurrence())
            .expect("occurrence");
        executor.claim_occurrence(100, claim(7)).expect("claim");
        executor
    }

    #[test]
    fn current_fence_executes_once() {
        let mut executor = executor(true, true);
        let input = intent("operation.1", "step.1");
        let first = executor
            .execute_step(100, "occurrence.1", 7, input.clone())
            .expect("execute");
        assert_eq!(first.state, StepState::Succeeded);
        let second = executor
            .execute_step(100, "occurrence.1", 7, input)
            .expect("idempotent");
        assert!(second.idempotent);
        assert_eq!(executor.driver.calls, 1);
    }

    #[test]
    fn replay_binds_every_step_and_claim_field() {
        let mut executor = executor(true, true);
        let original = intent("operation.1", "step.1");
        executor
            .execute_step(100, "occurrence.1", 7, original.clone())
            .expect("execute");

        let mut mutations = Vec::new();
        let mut changed = original.clone();
        changed.step_id = "step.changed".to_string();
        mutations.push(changed);
        let mut changed = original.clone();
        changed.authority_epoch = 5;
        mutations.push(changed);
        let mut changed = original.clone();
        changed.semantic_digest = "3".repeat(64);
        mutations.push(changed);
        let mut changed = original.clone();
        changed.final_payload_digest = "4".repeat(64);
        changed.grant_payload_digest = "4".repeat(64);
        mutations.push(changed);
        let mut changed = original.clone();
        changed.deadline_ms = 8_000;
        mutations.push(changed);
        let mut changed = original.clone();
        changed.compensation_for = Some("operation.prior".to_string());
        mutations.push(changed);

        for changed in mutations {
            assert_eq!(
                executor.execute_step(100, "occurrence.1", 7, changed),
                Err(Error::OperationConflict)
            );
        }
        assert_eq!(executor.driver.calls, 1);
    }

    #[test]
    fn duplicate_step_identity_is_rejected() {
        let mut executor = executor(true, true);
        executor
            .execute_step(100, "occurrence.1", 7, intent("operation.1", "step.1"))
            .expect("first");
        assert_eq!(
            executor.execute_step(100, "occurrence.1", 7, intent("operation.2", "step.1")),
            Err(Error::StepIdentityConflict)
        );
    }

    #[test]
    fn stale_fence_and_unknown_effect_fail_closed() {
        let mut executor = executor(false, false);
        assert_eq!(
            executor.execute_step(100, "occurrence.1", 2, intent("operation.1", "step.1")),
            Err(Error::StaleFence)
        );
        let result = executor
            .execute_step(100, "occurrence.1", 7, intent("operation.1", "step.1"))
            .expect("execute");
        assert_eq!(result.state, StepState::Indeterminate);
        let mut dependent = intent("operation.2", "step.2");
        dependent.dependencies.push("step.1".to_string());
        assert_eq!(
            executor.execute_step(100, "occurrence.1", 7, dependent),
            Err(Error::DependencyNotTerminal)
        );
        let mut compensation = intent("operation.3", "step.3");
        compensation.compensation_for = Some("operation.1".to_string());
        assert_eq!(
            executor.execute_step(100, "occurrence.1", 7, compensation),
            Err(Error::DependencyNotTerminal)
        );
    }
}

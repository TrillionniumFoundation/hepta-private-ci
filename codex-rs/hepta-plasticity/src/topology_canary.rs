//! Bounded structural-canary state machine for independently admitted topology.
//!
//! This controller observes a canary run; it never applies topology. Any safety,
//! regression, lineage or rollback failure aborts and the controller cannot return
//! to an accepting state.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StructuralCanaryStateV1 {
    Prepared,
    Running,
    Accepted,
    Aborted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StructuralCanaryPlanV1 {
    pub topology_admission_digest: Digest32,
    pub rollback_plan_digest: Digest32,
    pub writer_handoff_set_digest: Digest32,
    pub baseline_health_digest: Digest32,
    pub maximum_steps: u32,
    pub maximum_regressions: u32,
    pub minimum_successful_steps: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StructuralCanaryObservationV1 {
    pub sequence: u32,
    pub health_digest: Digest32,
    pub evidence_digest: Digest32,
    pub regression_count: u32,
    pub safety_violation: bool,
    pub lineage_mismatch: bool,
    pub rollback_verified: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StructuralCanaryReceiptV1 {
    pub state: StructuralCanaryStateV1,
    pub plan_digest: Digest32,
    pub observed_steps: u32,
    pub successful_steps: u32,
    pub last_observation_digest: Digest32,
    pub observation_chain_digest: Digest32,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StructuralCanaryErrorV1 {
    InvalidPlan,
    Terminal,
    Sequence,
    Observation,
    InsufficientEvidence,
}

impl fmt::Display for StructuralCanaryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for StructuralCanaryErrorV1 {}

pub struct StructuralCanaryControllerV1 {
    plan: StructuralCanaryPlanV1,
    plan_digest: Digest32,
    state: StructuralCanaryStateV1,
    observed_steps: u32,
    successful_steps: u32,
    last_observation_digest: Digest32,
    observation_chain_digest: Digest32,
}

impl StructuralCanaryControllerV1 {
    pub fn new(plan: StructuralCanaryPlanV1) -> Result<Self, StructuralCanaryErrorV1> {
        if plan.topology_admission_digest.is_zero()
            || plan.rollback_plan_digest.is_zero()
            || plan.writer_handoff_set_digest.is_zero()
            || plan.baseline_health_digest.is_zero()
            || plan.maximum_steps == 0
            || plan.maximum_steps > 1_024
            || plan.minimum_successful_steps == 0
            || plan.minimum_successful_steps > plan.maximum_steps
        {
            return Err(StructuralCanaryErrorV1::InvalidPlan);
        }
        let plan_digest = digest_plan(&plan);
        Ok(Self {
            plan,
            plan_digest,
            state: StructuralCanaryStateV1::Prepared,
            observed_steps: 0,
            successful_steps: 0,
            last_observation_digest: Digest32::ZERO,
            observation_chain_digest: Digest32::ZERO,
        })
    }

    pub const fn state(&self) -> StructuralCanaryStateV1 {
        self.state
    }

    pub fn observe(
        &mut self,
        observation: StructuralCanaryObservationV1,
    ) -> Result<StructuralCanaryReceiptV1, StructuralCanaryErrorV1> {
        if matches!(
            self.state,
            StructuralCanaryStateV1::Accepted | StructuralCanaryStateV1::Aborted
        ) {
            return Err(StructuralCanaryErrorV1::Terminal);
        }
        let expected = self
            .observed_steps
            .checked_add(1)
            .ok_or(StructuralCanaryErrorV1::Sequence)?;
        if observation.sequence != expected
            || observation.sequence > self.plan.maximum_steps
            || observation.regression_count > observation.sequence
        {
            return Err(StructuralCanaryErrorV1::Sequence);
        }
        if observation.health_digest.is_zero() || observation.evidence_digest.is_zero() {
            return Err(StructuralCanaryErrorV1::Observation);
        }

        let previous_chain_digest = self.observation_chain_digest;
        let mut bytes = b"hepta.plasticity.structural-canary-observation.v2\0".to_vec();
        bytes.extend_from_slice(self.plan_digest.as_array());
        bytes.extend_from_slice(previous_chain_digest.as_array());
        bytes.extend_from_slice(&observation.sequence.to_be_bytes());
        bytes.extend_from_slice(observation.health_digest.as_array());
        bytes.extend_from_slice(observation.evidence_digest.as_array());
        bytes.extend_from_slice(&observation.regression_count.to_be_bytes());
        bytes.push(u8::from(observation.safety_violation));
        bytes.push(u8::from(observation.lineage_mismatch));
        bytes.push(u8::from(observation.rollback_verified));
        self.last_observation_digest = Digest32::of_bytes(&bytes);

        let mut chain = b"hepta.plasticity.structural-canary-chain.v1\0".to_vec();
        chain.extend_from_slice(self.plan_digest.as_array());
        chain.extend_from_slice(previous_chain_digest.as_array());
        chain.extend_from_slice(self.last_observation_digest.as_array());
        self.observation_chain_digest = Digest32::of_bytes(&chain);
        self.observed_steps = observation.sequence;

        if observation.safety_violation
            || observation.lineage_mismatch
            || observation.regression_count > self.plan.maximum_regressions
            || !observation.rollback_verified
        {
            self.state = StructuralCanaryStateV1::Aborted;
            return Ok(self.receipt());
        }

        self.successful_steps = self
            .successful_steps
            .checked_add(1)
            .ok_or(StructuralCanaryErrorV1::Sequence)?;
        self.state = StructuralCanaryStateV1::Running;
        Ok(self.receipt())
    }

    pub fn finish(&mut self) -> Result<StructuralCanaryReceiptV1, StructuralCanaryErrorV1> {
        if matches!(
            self.state,
            StructuralCanaryStateV1::Aborted | StructuralCanaryStateV1::Accepted
        ) {
            return Ok(self.receipt());
        }
        if self.successful_steps < self.plan.minimum_successful_steps
            || self.last_observation_digest.is_zero()
            || self.observation_chain_digest.is_zero()
        {
            return Err(StructuralCanaryErrorV1::InsufficientEvidence);
        }
        self.state = StructuralCanaryStateV1::Accepted;
        Ok(self.receipt())
    }

    fn receipt(&self) -> StructuralCanaryReceiptV1 {
        let mut bytes = b"hepta.plasticity.structural-canary-receipt.v2\0".to_vec();
        bytes.extend_from_slice(self.plan_digest.as_array());
        bytes.push(match self.state {
            StructuralCanaryStateV1::Prepared => 0,
            StructuralCanaryStateV1::Running => 1,
            StructuralCanaryStateV1::Accepted => 2,
            StructuralCanaryStateV1::Aborted => 3,
        });
        bytes.extend_from_slice(&self.observed_steps.to_be_bytes());
        bytes.extend_from_slice(&self.successful_steps.to_be_bytes());
        bytes.extend_from_slice(self.last_observation_digest.as_array());
        bytes.extend_from_slice(self.observation_chain_digest.as_array());
        StructuralCanaryReceiptV1 {
            state: self.state,
            plan_digest: self.plan_digest,
            observed_steps: self.observed_steps,
            successful_steps: self.successful_steps,
            last_observation_digest: self.last_observation_digest,
            observation_chain_digest: self.observation_chain_digest,
            receipt_digest: Digest32::of_bytes(&bytes),
        }
    }
}

fn digest_plan(plan: &StructuralCanaryPlanV1) -> Digest32 {
    let mut bytes = b"hepta.plasticity.structural-canary-plan.v1\0".to_vec();
    bytes.extend_from_slice(plan.topology_admission_digest.as_array());
    bytes.extend_from_slice(plan.rollback_plan_digest.as_array());
    bytes.extend_from_slice(plan.writer_handoff_set_digest.as_array());
    bytes.extend_from_slice(plan.baseline_health_digest.as_array());
    bytes.extend_from_slice(&plan.maximum_steps.to_be_bytes());
    bytes.extend_from_slice(&plan.maximum_regressions.to_be_bytes());
    bytes.extend_from_slice(&plan.minimum_successful_steps.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn plan() -> StructuralCanaryPlanV1 {
        StructuralCanaryPlanV1 {
            topology_admission_digest: digest(b"admission"),
            rollback_plan_digest: digest(b"rollback"),
            writer_handoff_set_digest: digest(b"handoffs"),
            baseline_health_digest: digest(b"baseline"),
            maximum_steps: 4,
            maximum_regressions: 0,
            minimum_successful_steps: 2,
        }
    }

    #[test]
    fn canary_accepts_only_after_bounded_success_and_verified_rollback() {
        let mut controller = StructuralCanaryControllerV1::new(plan()).expect("controller");
        let first = controller
            .observe(StructuralCanaryObservationV1 {
                sequence: 1,
                health_digest: digest(b"h1"),
                evidence_digest: digest(b"e1"),
                regression_count: 0,
                safety_violation: false,
                lineage_mismatch: false,
                rollback_verified: true,
            })
            .expect("first");
        assert_eq!(first.state, StructuralCanaryStateV1::Running);
        let second = controller
            .observe(StructuralCanaryObservationV1 {
                sequence: 2,
                health_digest: digest(b"h2"),
                evidence_digest: digest(b"e2"),
                regression_count: 0,
                safety_violation: false,
                lineage_mismatch: false,
                rollback_verified: true,
            })
            .expect("second");
        assert_eq!(second.state, StructuralCanaryStateV1::Running);
        let accepted = controller.finish().expect("finish");
        assert_eq!(accepted.state, StructuralCanaryStateV1::Accepted);
        assert_eq!(accepted.observed_steps, 2);
        assert_eq!(accepted.successful_steps, 2);
        assert!(!accepted.plan_digest.is_zero());
        assert!(!accepted.observation_chain_digest.is_zero());
    }

    #[test]
    fn any_safety_violation_aborts_terminally() {
        let mut controller = StructuralCanaryControllerV1::new(plan()).expect("controller");
        let receipt = controller
            .observe(StructuralCanaryObservationV1 {
                sequence: 1,
                health_digest: digest(b"h1"),
                evidence_digest: digest(b"e1"),
                regression_count: 0,
                safety_violation: true,
                lineage_mismatch: false,
                rollback_verified: true,
            })
            .expect("observation");
        assert_eq!(receipt.state, StructuralCanaryStateV1::Aborted);
    }

    #[test]
    fn receipt_binds_the_full_plan_and_observation_history() {
        let mut left = StructuralCanaryControllerV1::new(plan()).expect("left");
        let mut changed_plan = plan();
        changed_plan.rollback_plan_digest = digest(b"other-rollback");
        let mut right = StructuralCanaryControllerV1::new(changed_plan).expect("right");

        let observation = StructuralCanaryObservationV1 {
            sequence: 1,
            health_digest: digest(b"h1"),
            evidence_digest: digest(b"e1"),
            regression_count: 0,
            safety_violation: false,
            lineage_mismatch: false,
            rollback_verified: true,
        };
        let left_receipt = left.observe(observation.clone()).expect("left observation");
        let right_receipt = right.observe(observation).expect("right observation");
        assert_ne!(left_receipt.plan_digest, right_receipt.plan_digest);
        assert_ne!(
            left_receipt.observation_chain_digest,
            right_receipt.observation_chain_digest
        );
        assert_ne!(left_receipt.receipt_digest, right_receipt.receipt_digest);

        let second = left
            .observe(StructuralCanaryObservationV1 {
                sequence: 2,
                health_digest: digest(b"h2"),
                evidence_digest: digest(b"e2"),
                regression_count: 0,
                safety_violation: false,
                lineage_mismatch: false,
                rollback_verified: true,
            })
            .expect("second observation");
        assert_ne!(
            left_receipt.observation_chain_digest,
            second.observation_chain_digest
        );
        assert_eq!(second.state, StructuralCanaryStateV1::Running);
    }
}

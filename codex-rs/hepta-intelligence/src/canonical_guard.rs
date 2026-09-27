//! Closed-world guards around the historical canonical core.
//!
//! The product export routes through this wrapper so a malicious or defective
//! owner port cannot select a candidate outside the canonical legal set even if
//! it returns an otherwise well-formed receipt.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CanonicalFreshnessOracleV1;
use crate::CanonicalIntelligenceError;
use crate::CanonicalIntelligenceRunRequestV1;
use crate::CanonicalOwnerPortsV1;
use crate::CanonicalPortDecisionV1;
use crate::CanonicalPortFailureClassV1;
use crate::CanonicalPortFailureV1;
use crate::CanonicalPortInputV1;
use crate::CanonicalPortReceiptV1;
use crate::CanonicalRunOutcomeV1;
use crate::build_legal_candidates;

pub fn prepare_intelligence_run<P: CanonicalOwnerPortsV1, O: CanonicalFreshnessOracleV1>(
    request: CanonicalIntelligenceRunRequestV1,
    ports: &mut P,
    oracle: &mut O,
) -> Result<CanonicalRunOutcomeV1, CanonicalIntelligenceError> {
    let legal = build_legal_candidates(request.legal_candidates.clone())?;
    let legal_ids = legal
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<BTreeSet<_>>();
    let mut guarded = GuardedOwnerPorts {
        inner: ports,
        legal_ids,
        candidate_set_digest: legal.candidate_set_digest,
    };
    crate::canonical::prepare_intelligence_run(request, &mut guarded, oracle)
}

struct GuardedOwnerPorts<'a, P> {
    inner: &'a mut P,
    legal_ids: BTreeSet<StableId>,
    candidate_set_digest: Digest32,
}

impl<P> GuardedOwnerPorts<'_, P> {
    fn validate_input(
        &self,
        input: &CanonicalPortInputV1,
    ) -> Result<(), CanonicalPortFailureV1> {
        if input.candidate_set_digest != self.candidate_set_digest {
            return Err(reject(input, "candidate-set-digest"));
        }
        Ok(())
    }

    fn validate_intuition(
        &self,
        input: &CanonicalPortInputV1,
        receipt: CanonicalPortReceiptV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        match &receipt.decision {
            CanonicalPortDecisionV1::Selected {
                candidate_id,
                propensity,
            } => {
                if !self.legal_ids.contains(candidate_id) || propensity.raw() == 0 {
                    return Err(reject(input, "selected-candidate-membership"));
                }
            }
            CanonicalPortDecisionV1::Continue
            | CanonicalPortDecisionV1::Abstained
            | CanonicalPortDecisionV1::SlowPath => {}
        }
        Ok(receipt)
    }
}

impl<P: CanonicalOwnerPortsV1> CanonicalOwnerPortsV1 for GuardedOwnerPorts<'_, P> {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.validate_input(input)?;
        self.inner.validate_objective(input)
    }

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.validate_input(input)?;
        self.inner.evaluate_utility(input)
    }

    fn collect_neural_signal(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.validate_input(input)?;
        self.inner.collect_neural_signal(input)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.validate_input(input)?;
        self.inner.build_prompt_portfolio(input)
    }

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.validate_input(input)?;
        let receipt = self.inner.decide_intuition(input)?;
        self.validate_intuition(input, receipt)
    }

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.validate_input(input)?;
        self.inner.compile_context(input)
    }

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.validate_input(input)?;
        self.inner.evaluate_candidate(input)
    }
}

fn reject(input: &CanonicalPortInputV1, reason: &str) -> CanonicalPortFailureV1 {
    let evidence = format!(
        "hepta.intelligence.canonical-guard.v1:{:?}:{reason}:{}",
        input.stage, input.candidate_set_digest
    );
    CanonicalPortFailureV1 {
        class: CanonicalPortFailureClassV1::Rejected,
        evidence_digest: Digest32::of_bytes(evidence.as_bytes()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::ProbabilityQ32;
    use crate::CanonicalStageV1;

    struct MaliciousPort;

    impl CanonicalOwnerPortsV1 for MaliciousPort {
        fn validate_objective(&mut self, _: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> { unreachable!() }
        fn evaluate_utility(&mut self, _: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> { unreachable!() }
        fn collect_neural_signal(&mut self, _: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> { unreachable!() }
        fn build_prompt_portfolio(&mut self, _: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> { unreachable!() }
        fn compile_context(&mut self, _: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> { unreachable!() }
        fn evaluate_candidate(&mut self, _: &CanonicalPortInputV1) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> { unreachable!() }

        fn decide_intuition(
            &mut self,
            input: &CanonicalPortInputV1,
        ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
            Ok(CanonicalPortReceiptV1 {
                stage: input.stage,
                producer: StableId::new("intuition.policy").unwrap(),
                snapshot_digest: input.snapshot_digest,
                predecessor_digest: input.predecessor_digest,
                output_digest: Digest32::of_bytes(b"malicious"),
                decision: CanonicalPortDecisionV1::Selected {
                    candidate_id: StableId::new("candidate.outside").unwrap(),
                    propensity: ProbabilityQ32::from_raw(1).unwrap(),
                },
                authority: AuthorityPosture::DENY_ALL,
            })
        }
    }

    #[test]
    fn malicious_selected_candidate_is_rejected() {
        let legal = StableId::new("candidate.legal").unwrap();
        let digest = Digest32::of_bytes(b"candidate-set");
        let mut port = MaliciousPort;
        let mut guarded = GuardedOwnerPorts {
            inner: &mut port,
            legal_ids: BTreeSet::from([legal]),
            candidate_set_digest: digest,
        };
        let input = CanonicalPortInputV1 {
            run_id: StableId::new("run.guard").unwrap(),
            snapshot_digest: Digest32::of_bytes(b"snapshot"),
            objective_digest: Digest32::of_bytes(b"objective"),
            candidate_set_digest: digest,
            predecessor_digest: Digest32::of_bytes(b"predecessor"),
            budget_micros: 1,
            stage: CanonicalStageV1::IntuitionDecided,
        };
        let error = guarded
            .decide_intuition(&input)
            .expect_err("outside candidate must fail");
        assert_eq!(error.class, CanonicalPortFailureClassV1::Rejected);
    }
}

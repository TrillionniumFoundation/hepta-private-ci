use crate::CompositionCancellationV3;
use crate::CompositionClockV3;
use crate::CompositionDispositionV3;
use crate::CompositionErrorV3;
use crate::IntelligenceHostEnvelopeInputV1;
use crate::IntelligenceHostEnvelopeV1;
use crate::LaneFCompositionPortsV3;
use crate::LaneFCompositionReceiptV3;
use crate::LaneFCompositionRequestV3;
use crate::LaneFStageV3;
use crate::PortDecisionV1;
use crate::composition_v3_engine::Runner;
use crate::composition_v3_engine::Step;
use crate::composition_v3_validate::digest_trace_prefix_v3;

pub fn run_composition_v3<P, C, X>(
    request: LaneFCompositionRequestV3,
    ports: &mut P,
    clock: &mut C,
    cancellation: &X,
) -> Result<LaneFCompositionReceiptV3, CompositionErrorV3>
where
    P: LaneFCompositionPortsV3,
    C: CompositionClockV3,
    X: CompositionCancellationV3,
{
    request.budget.validate()?;
    if request.request_digest.is_zero() {
        return Err(CompositionErrorV3::EmptyDigest("request"));
    }
    request
        .legal_candidates
        .validate()
        .map_err(CompositionErrorV3::Contract)?;
    if request.legal_candidates.state_digest != request.snapshot.digest() {
        return Err(CompositionErrorV3::CandidateSnapshotMismatch);
    }
    validate_capabilities(&request)?;

    let started = clock.now_micros();
    let total_deadline = started
        .checked_add(request.budget.total_micros)
        .ok_or(CompositionErrorV3::Arithmetic)?;
    let mut runner = Runner::new(request, total_deadline, clock, cancellation);

    if let Step::Terminal(receipt) = runner.required(LaneFStageV3::ObjectiveValidated, |input| {
        ports.validate_objective(input)
    })? {
        return Ok(receipt);
    }
    if let Some(receipt) = runner.internal_legal_set()? {
        return Ok(receipt);
    }
    let utility = match runner.required(LaneFStageV3::UtilityEvaluated, |input| {
        ports.evaluate_utility(input)
    })? {
        Step::Continue(receipt) => receipt,
        Step::Terminal(receipt) => return Ok(receipt),
    };
    let evaluation = match runner.required(LaneFStageV3::EvaluationAdmitted, |input| {
        ports.admit_evaluation(input)
    })? {
        Step::Continue(receipt) => receipt,
        Step::Terminal(receipt) => return Ok(receipt),
    };
    if let Some(receipt) = runner.optional(
        LaneFStageV3::NeuralSignalCollected,
        "neural.signal",
        |input| ports.collect_neural_signal(input),
    )? {
        return Ok(receipt);
    }
    if let Some(receipt) = runner.optional(
        LaneFStageV3::PromptPortfolioBuilt,
        "prompt.portfolio",
        |input| ports.build_prompt_portfolio(input),
    )? {
        return Ok(receipt);
    }
    let intuition = match runner.advisory(|input| ports.decide_intuition(input))? {
        Step::Continue(receipt) => receipt,
        Step::Terminal(receipt) => return Ok(receipt),
    };
    let disposition = match intuition.decision {
        PortDecisionV1::Continue => CompositionDispositionV3::DispatchProposed,
        PortDecisionV1::Abstain => CompositionDispositionV3::Abstained,
        PortDecisionV1::SlowPath => CompositionDispositionV3::SlowPath,
    };

    if intuition.decision == PortDecisionV1::Continue {
        let context = match runner.required(LaneFStageV3::ContextCompiled, |input| {
            ports.compile_context(input)
        })? {
            Step::Continue(receipt) => receipt,
            Step::Terminal(receipt) => return Ok(receipt),
        };
        let envelope = IntelligenceHostEnvelopeV1::new(IntelligenceHostEnvelopeInputV1 {
            run_id: runner.run_id().clone(),
            request_digest: runner.request_digest(),
            snapshot_digest: runner.snapshot_digest(),
            objective_digest: runner.objective_digest(),
            legal_candidate_set_digest: runner.candidate_set_digest(),
            utility_digest: utility.output_digest,
            evaluation_digest: evaluation.output_digest,
            intuition_digest: intuition.output_digest,
            context_digest: context.output_digest,
            composition_trace_digest: digest_trace_prefix_v3(
                runner.run_id(),
                runner.request_digest(),
                runner.snapshot_digest(),
                runner.objective_digest(),
                runner.candidate_set_digest(),
                runner.stages(),
            ),
        })
        .map_err(CompositionErrorV3::Contract)?;
        if let Some(receipt) = runner.internal_host_envelope(envelope.clone())? {
            return Ok(receipt);
        }
        let dispatch_envelope = envelope.clone();
        runner.set_host_envelope(envelope);
        if let Step::Terminal(receipt) = runner.required(LaneFStageV3::DispatchProposed, |input| {
            ports.propose_dispatch(input, &dispatch_envelope)
        })? {
            return Ok(receipt);
        }
    }

    if let Step::Terminal(receipt) = runner.required(LaneFStageV3::LearningRecorded, |input| {
        ports.record_learning(input)
    })? {
        return Ok(receipt);
    }
    runner.finish(disposition)
}

fn validate_capabilities(request: &LaneFCompositionRequestV3) -> Result<(), CompositionErrorV3> {
    for (capability, owner) in [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("learning.evaluation", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.envelope", "intelligence.control"),
        ("dispatch.proposal", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ] {
        match request.snapshot.bound_owner(capability) {
            None => return Err(CompositionErrorV3::MissingCapability(capability)),
            Some(actual) if actual != owner => {
                return Err(CompositionErrorV3::OwnerMismatch(capability));
            }
            Some(_) => {}
        }
    }
    for (capability, owner) in [
        ("neural.signal", "neuron.runtime"),
        ("prompt.portfolio", "prompt.optimizer"),
    ] {
        if let Some(actual) = request.snapshot.bound_owner(capability)
            && actual != owner
        {
            return Err(CompositionErrorV3::OwnerMismatch(capability));
        }
    }
    Ok(())
}

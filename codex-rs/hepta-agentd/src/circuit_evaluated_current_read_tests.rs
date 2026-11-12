//! Exercises the private read wire using actual opaque Evaluator results from
//! the host fixture. This is mechanism evidence, not deployed qualification.

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;

pub(crate) fn check_evaluated_profiles(
    fresh: OriginalCircuitEvaluatedRetentionContextV1,
    cold: OriginalCircuitEvaluatedRetentionContextV1,
) -> anyhow::Result<()> {
    let mut fresh = ReadContext::from_evaluated(fresh)?;
    let cold = ReadContext::from_evaluated(cold)?;
    let at = now()?;
    let binding = wire::context_binding(&fresh, at)?;
    let cold_binding = wire::context_binding(&cold, at)?;
    assert_ne!(binding, cold_binding);
    assert_eq!(wire::mode(&fresh)?, wire::Mode::Selection);
    assert_eq!(wire::mode(&cold)?, wire::Mode::Selection);
    assert_eq!(wire::decision(&fresh)?.snapshot(), &fresh.prefix);
    assert_eq!(fresh.prefix, cold.prefix);

    let request = wire::Request::new(&fresh, binding, /*request_id*/ 1)?;
    request.require_context(&fresh, binding, /*request_id*/ 1)?;
    assert!(
        request
            .require_context(&cold, cold_binding, /*request_id*/ 1)
            .is_err()
    );
    let mut injected = serde_json::to_value(&request)?;
    injected["execute"] = serde_json::json!(true);
    assert!(serde_json::from_value::<wire::Request>(injected).is_err());

    let legacy: ReadContext = OriginalCircuitLearningReadContextV1 {
        prefix: fresh.prefix.clone(),
        scope: fresh.scope.clone(),
        verifier: fresh.verifier.clone(),
        training_evidence: fresh.training_evidence.clone(),
        selection_evidence: None,
    }
    .into();
    assert!(wire::context_binding(&legacy, at).is_err());
    // Neither a fifth-cut hint nor a Selector signature opens NextUse here.
    fresh.selection_evidence = Some(fresh.training_evidence.clone());
    assert!(wire::context_binding(&fresh, at).is_err());
    fresh.selection_evidence = None;
    fresh.prefix.request.source_run_id = codex_hepta_types::StableId::new("other-source-run")?;
    assert!(wire::context_binding(&fresh, at).is_err());
    fresh.prefix = cold.prefix.clone();
    fresh.training_evidence.expires_at -= 1;
    assert!(wire::context_binding(&fresh, at).is_err());
    let proof = cold.evaluated.as_ref().unwrap().original_read_proof(at)?;
    let expired = proof
        .training
        .expires_at
        .max(proof.evaluation.expires_at)
        .saturating_add(1);
    assert!(wire::context_binding(&cold, expired).is_err());
    Ok(())
}

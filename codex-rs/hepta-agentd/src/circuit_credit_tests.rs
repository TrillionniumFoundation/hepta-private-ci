use pretty_assertions::assert_eq;

use std::collections::BTreeMap;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CreditAllocationBatchV1;
use codex_hepta_learning_ledger::CreditAllocationV1;
use codex_hepta_types::FixedQ32;

use super::*;
use crate::circuit_credit::CircuitCreditErrorV1;
use crate::circuit_credit::CircuitCreditTargetV1;

#[tokio::test]
async fn terminal_credit_requires_both_owners_and_exact_original_inputs() {
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    let inputs = BTreeMap::from([(dispatch.activation_id, request.clone())]);
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, /*now_ms*/ 13).await;
    let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = model.calls.clone();
    let owner = native_owner(&bindings);
    let registry = checked(CircuitCellRegistryV1::new(definition.clone(), bindings.clone()));
    let mut runtime = AgentdCircuitCellOwnerV1::new(registry, owner, model, Encoder);
    let executed = checked(runtime.execute(admission, request, time));
    assert!(matches!(
        runtime.terminal_credit_support(&store, "run-1", &inputs).await,
        Err(CircuitCreditErrorV1::Binding("circuit is not settled"))
    ));
    apply(&store, "complete", /*now_ms*/ 22, CircuitEventV2::Complete {
        completion: executed.completion,
    }).await;
    apply(&store, "exit", /*now_ms*/ 23, CircuitEventV2::Advance { quantum: 1 }).await;
    let support = checked(runtime.terminal_credit_support(&store, "run-1", &inputs).await);
    let definition_digest = checked(bindings[0].cell.semantic_digest());
    assert_eq!(support.targets(), &[CircuitCreditTargetV1 {
        target_id: id(&format!("circuit-cell-version:{definition_digest}")),
        cell_id: bindings[0].cell.cell_id.clone(),
        bundle_digest: bindings[0].cell.bundle_digest,
        definition_digest,
        activation_ids: vec![dispatch.activation_id],
    }]);
    assert_eq!(
        checked(runtime.terminal_credit_support(&store, "run-1", &inputs).await),
        support
    );
    let mut changed = inputs.clone();
    changed.get_mut(&dispatch.activation_id).expect("input").objective_digest = d("other-objective");
    assert!(matches!(
        runtime.terminal_credit_support(&store, "run-1", &changed).await,
        Err(CircuitCreditErrorV1::Binding("original computation claim"))
    ));
    changed = inputs.clone();
    changed.insert(dispatch.activation_id + 99, input("run-1"));
    assert!(runtime.terminal_credit_support(&store, "run-1", &changed).await.is_err());
    assert!(runtime.terminal_credit_support(&store, "run-1", &BTreeMap::new()).await.is_err());
    let mut foreign = inputs.clone();
    foreign.get_mut(&dispatch.activation_id).expect("input").scope.run_id = id("other-run");
    assert!(runtime.terminal_credit_support(&store, "run-1", &foreign).await.is_err());

    let empty_owner = native_owner(&bindings);
    let empty = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition.clone(), bindings.clone())),
        empty_owner,
        Model::new(/*latency*/ 20, /*lose_response*/ false),
        Encoder,
    );
    assert!(matches!(
        empty.terminal_credit_support(&store, "run-1", &inputs).await,
        Err(CircuitCreditErrorV1::Binding("missing committed Cell decision"))
    ));

    let mut changed_definition = definition;
    changed_definition.version += 1;
    changed_definition.predecessor_digest = Some(checked(runtime.registry().definition().definition_digest()));
    let changed_runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(changed_definition, bindings.clone())),
        native_owner(&bindings),
        Model::new(/*latency*/ 20, /*lose_response*/ false),
        Encoder,
    );
    assert!(matches!(
        changed_runtime.terminal_credit_support(&store, "run-1", &inputs).await,
        Err(CircuitCreditErrorV1::Circuit(_))
    ));

    // Structural preflight only: this fixture is neither signed nor admitted.
    let mut credit = CreditAllocationBatchV1 {
        batch_id: id("batch"), episode_id: id("episode"), outcome_id: id("outcome"),
        allocator: AuthenticatedPrincipalV1 {
            principal_id: id("allocator"), credential_chain_digest: d("chain"),
            signing_key_digest: d("key"), scope_digest: d("scope"),
            authority_epoch: 1, authenticated_at: 0, expires_at: 100,
        },
        terminal_outcome: FixedQ32::ONE,
        allocations: vec![CreditAllocationV1 {
            target_id: support.targets()[0].target_id.clone(), credit: FixedQ32::ONE,
        }],
        conservation_residual: FixedQ32::ZERO,
        support_digest: support.digest(), finalized: true,
    };
    checked(support.validate_credit(&credit));
    credit.allocations[0].target_id = id("unexecuted-cell");
    assert!(support.validate_credit(&credit).is_err());
    credit.allocations[0].target_id = support.targets()[0].target_id.clone();
    credit.support_digest = d("another-trace");
    assert!(support.validate_credit(&credit).is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    store.close().await;
}

#[tokio::test]
async fn circuit_credit_rejects_completion_bytes_without_matching_cell_readback() {
    for changed_field in ["output", "receipt", "route", "cost", "outcome"] {
        let (definition, bindings) = configuration();
        let (_directory, store, dispatch) = create_run(&definition).await;
        let mut request = request(&dispatch);
        if changed_field == "outcome" {
            for candidate in &mut request.candidates {
                candidate.allowed = candidate.candidate_id == id("abstain");
            }
        }
        let inputs = BTreeMap::from([(dispatch.activation_id, request.clone())]);
        let admission = claim(&store, &dispatch, &bindings[0].cell, &request, /*now_ms*/ 13).await;
        let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
        let calls = model.calls.clone();
        let owner = native_owner(&bindings);
        let registry = checked(CircuitCellRegistryV1::new(definition, bindings));
        let mut runtime = AgentdCircuitCellOwnerV1::new(registry, owner, model, Encoder);
        let mut completion = checked(runtime.execute(admission, request, time)).completion;
        match changed_field {
            "output" => completion.output_digest = Sha256Digest::for_bytes(b"different-output"),
            "receipt" => completion.receipt_digest = Sha256Digest::for_bytes(b"different-receipt"),
            "route" => completion.selected_edges = vec!["slow".to_string()],
            "cost" => completion.actual_work += 1,
            "outcome" => {
                completion.outcome = CircuitExitV2::Failed;
            }
            _ => unreachable!("fixture variant"),
        }
        let completed = apply(&store, "complete", /*now_ms*/ 22, CircuitEventV2::Complete { completion }).await;
        if completed.run.outcome().is_none() {
            apply(&store, "exit", /*now_ms*/ 23, CircuitEventV2::Advance { quantum: 1 }).await;
        }
        assert!(matches!(
            runtime.terminal_credit_support(&store, "run-1", &inputs).await,
            Err(CircuitCreditErrorV1::Binding("Cell/Circuit completion mismatch"))
        ));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        store.close().await;
    }
}

//! Actual original journal/issuer boundary controls, not model execution.
use super::super::settled::verify_record;
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn completed_read_join_uses_original_settlement_and_cold_reopen_without_mutation() {
    let directory = tempfile::tempdir().unwrap();
    let runtime = runtime();
    let issuer = Arc::new(TestIssuer::open(&directory.path().join("authority")));
    let path = directory.path().join("inference.control");
    let control = Arc::new(Mutex::new(DurableInferenceControl::open(&path, 8).unwrap()));
    let mut context = ControlContext {
        control: control.clone(),
        authorizer: issuer.clone(),
        runtime: runtime.handle().clone(),
        owner_id: owner(),
        body_generation: 1,
        worker_id: "controlled-neural-worker".to_owned(),
        grant: grant(),
        model_digest: Digest32::of_bytes(b"model").to_string(),
    };
    let scope = Digest32::of_bytes(b"explicit journal-only fixture scope");
    let payload = Digest32::of_bytes(b"explicit original control payload fixture");
    let output = Digest32::of_bytes(b"explicit original control output fixture");
    let mut completed = Vec::new();
    for tokens in [0, 1] {
        let admitted = context.admit(payload, 2000).unwrap();
        drop(
            context
                .enter(
                    &admitted,
                    scope,
                    &codex_hepta_agentd::NeuralCognitiveExecutionV1::bounded_read(),
                )
                .unwrap(),
        );
        context
            .settle(&admitted, Some(output), true, tokens)
            .unwrap();
        completed.push((admitted, tokens));
    }
    let before = fs::read(&path).unwrap();
    let nonces = issuer.authority.capacity().unwrap().used_nonces;
    let held = control.lock().unwrap();
    for (admitted, tokens) in &completed {
        let ids = (
            admitted.request_id.as_str(),
            admitted.reservation_id.as_str(),
        );
        verify_record(&context, &held, ids, payload, output, *tokens).unwrap();
        let other = Digest32::of_bytes(b"wrong observation");
        assert!(verify_record(&context, &held, ids, other, output, *tokens).is_err());
        assert!(verify_record(&context, &held, ids, payload, other, *tokens).is_err());
        assert!(verify_record(&context, &held, ids, payload, output, 1 - tokens).is_err());
        assert!(
            verify_record(
                &context,
                &held,
                ("missing", ids.1),
                payload,
                output,
                *tokens
            )
            .is_err()
        );
        assert!(
            verify_record(
                &context,
                &held,
                (ids.0, "wrong-reservation"),
                payload,
                output,
                *tokens
            )
            .is_err()
        );
        context.owner_id = AgentId::parse("00000000-0000-4000-8000-000000000220").unwrap();
        assert!(verify_record(&context, &held, ids, payload, output, *tokens).is_err());
        context.owner_id = owner();
        context.grant.authority_epoch += 1;
        assert!(verify_record(&context, &held, ids, payload, output, *tokens).is_err());
        context.grant.authority_epoch -= 1;
        context.grant.generation += 1;
        assert!(verify_record(&context, &held, ids, payload, output, *tokens).is_err());
        context.grant.generation -= 1;
        let model = std::mem::replace(&mut context.model_digest, other.to_string());
        assert!(verify_record(&context, &held, ids, payload, output, *tokens).is_err());
        context.model_digest = model;
    }
    let records = completed
        .iter()
        .map(|(admitted, _)| held.get(&admitted.request_id).unwrap().clone())
        .collect::<Vec<_>>();
    // A second live writer must refuse; releasing only its MutexGuard is not
    // a cold close. Preserve immutable original context facts for the reopen.
    assert!(matches!(
        DurableInferenceControl::open(&path, 8),
        Err(codex_hepta_infer_core::durable_control::Error::WriterUnavailable)
    ));
    let (owner_id, body_generation, worker_id, original_grant, model_digest) = (
        context.owner_id.clone(),
        context.body_generation,
        context.worker_id.clone(),
        context.grant.clone(),
        context.model_digest.clone(),
    );
    drop(held);
    drop(context);
    drop(control);
    let reopened = Arc::new(Mutex::new(DurableInferenceControl::open(&path, 8).unwrap()));
    let context = ControlContext {
        control: reopened.clone(),
        authorizer: issuer.clone(),
        runtime: runtime.handle().clone(),
        owner_id,
        body_generation,
        worker_id,
        grant: original_grant,
        model_digest,
    };
    let held = reopened.lock().unwrap();
    for (record, (admitted, tokens)) in records.iter().zip(&completed) {
        assert_eq!(held.get(&admitted.request_id), Some(record));
        verify_record(
            &context,
            &held,
            (&admitted.request_id, &admitted.reservation_id),
            payload,
            output,
            *tokens,
        )
        .unwrap();
    }
    assert_eq!(fs::read(&path).unwrap(), before);
    assert_eq!(issuer.authority.capacity().unwrap().used_nonces, nonces);
}

#[test]
fn original_failed_and_unknown_records_are_not_completed_read_evidence() {
    let directory = tempfile::tempdir().unwrap();
    let runtime = runtime();
    let issuer = Arc::new(TestIssuer::open(&directory.path().join("authority")));
    let path = directory.path().join("inference.control");
    let control = Arc::new(Mutex::new(DurableInferenceControl::open(&path, 8).unwrap()));
    let context = ControlContext {
        control: control.clone(),
        authorizer: issuer.clone(),
        runtime: runtime.handle().clone(),
        owner_id: owner(),
        body_generation: 1,
        worker_id: "controlled-neural-worker".to_owned(),
        grant: grant(),
        model_digest: Digest32::of_bytes(b"model").to_string(),
    };
    let payload = Digest32::of_bytes(b"explicit failed/unknown fixture payload");
    let output = Digest32::of_bytes(b"not an observed model output");
    for terminal in [true, false] {
        let admitted = context.admit(payload, 2000).unwrap();
        drop(
            context
                .enter(
                    &admitted,
                    Digest32::of_bytes(b"scope"),
                    &codex_hepta_agentd::NeuralCognitiveExecutionV1::bounded_read(),
                )
                .unwrap(),
        );
        context.settle(&admitted, None, terminal, 0).unwrap();
        let before = fs::read(&path).unwrap();
        let held = control.lock().unwrap();
        let record = held.get(&admitted.request_id).unwrap().clone();
        assert_eq!(
            record.state,
            if terminal {
                RequestState::Failed
            } else {
                RequestState::Indeterminate
            }
        );
        assert!(
            verify_record(
                &context,
                &held,
                (&admitted.request_id, &admitted.reservation_id),
                payload,
                output,
                0
            )
            .is_err()
        );
        assert_eq!(held.get(&admitted.request_id), Some(&record));
        assert_eq!(fs::read(&path).unwrap(), before);
    }
    assert_eq!(issuer.authority.capacity().unwrap().used_nonces, 2);
}

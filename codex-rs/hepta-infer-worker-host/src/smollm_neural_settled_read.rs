//! Same-owner settlement joins before an initial or evaluated read returns.
//! This private check reads the existing journal. Its historical observation
//! grants no installation, CURRENT, FinalUse or terminal-resource qualification.
use super::*;
use codex_hepta_agentd::CognitiveNeuralExecutionV1;
use codex_hepta_agentd::CognitiveNeuralSourceV1;
use codex_hepta_contracts::Sha256Digest;

// Borrowed original-owner inputs only. This is not a selection, receipt or
// conversion between initial and evaluated admission.
pub(super) enum ReadSource<'a> {
    Evaluated(&'a NeuralCognitiveRequestV1),
    SelectedInitial {
        identity: &'a SmolLmRuntimeIdentityV1,
        query: &'a str,
    },
}

pub(super) fn verify(
    context: &ControlContext,
    source: ReadSource<'_>,
    payload: Digest32,
    receipt: Digest32,
    load: &SmolLmMeasuredLoadV1,
    forward: Option<&SmolLmMeasuredForwardV1>,
) -> Result<CognitiveNeuralExecutionV1, String> {
    let (identity, query, load_domain, source): (_, _, &[u8], _) = match source {
        ReadSource::Evaluated(request) => {
            if request.owner_id != context.owner_id
                || request.body_generation != context.body_generation
                || request.query_digest != Digest32::of_bytes(request.query.as_bytes())
            {
                return Err("completed read differs from its original request/load".to_owned());
            }
            (
                SmolLmRuntimeIdentityV1::from(&request.pin),
                request.query.as_str(),
                b"hepta.smollm-load.v1\0",
                CognitiveNeuralSourceV1::EvaluatedChild,
            )
        }
        ReadSource::SelectedInitial { identity, query } => {
            if identity.generation.get() != 1 {
                return Err("initial read requires its selected generation-one parent".to_owned());
            }
            (
                identity.clone(),
                query,
                b"hepta.smollm.selected-initial-runtime-load.v1\0",
                CognitiveNeuralSourceV1::SelectedInitial,
            )
        }
    };
    let forward = forward.ok_or("original completed forward is unavailable")?;
    let load_ids = load
        .control_load_ids()
        .ok_or("original settled load IDs are unavailable")?;
    if load.parameter_file_digest() != identity.payload_digest
        || load.generation() != identity.generation.get()
        || forward.ready_digest() != load.ready_digest()
        || forward.response_digest() != receipt
        || payload.is_zero()
        || receipt.is_zero()
    {
        return Err("completed read differs from its original request/load".to_owned());
    }
    let input = serde_json::to_vec(&serde_json::json!({
        "schema":"hepta-smollm-inference-input-v1",
        "request_id":forward.control_ids().0, "prompt":query,
    }))
    .map_err(|error| error.to_string())?;
    if forward.input_digest() != Digest32::of_bytes(&input) {
        return Err("completed read input differs from its actual worker frame".to_owned());
    }
    let load_payload = Digest32::of_parts(&[
        load_domain,
        context.owner_id.as_str().as_bytes(),
        &context.body_generation.to_be_bytes(),
        identity.payload_digest.as_array(),
        identity.execution_profile_digest.as_array(),
    ]);
    // Keep the original worker/mailbox lock order. An observation cannot wait
    // unboundedly behind another control owner or create a new deadline.
    let control = context
        .control
        .try_lock()
        .map_err(|_| "original inference control is busy or poisoned")?;
    let load_output = load
        .settled_load_output_digest()
        .ok_or("original settled load output is unavailable")?;
    verify_record(context, &control, load_ids, load_payload, load_output, 0)?;
    verify_record(
        context,
        &control,
        forward.control_ids(),
        payload,
        receipt,
        1,
    )?;
    let wire = |digest: Digest32| Sha256Digest::parse(digest.to_string());
    let observed = CognitiveNeuralExecutionV1 {
        source,
        owner_id: context.owner_id.clone(),
        body_generation: context.body_generation,
        model_generation: load.generation(),
        parameter_file_digest: wire(load.parameter_file_digest())?,
        adapter_digest: wire(load.adapter_digest())?,
        backbone_digest: wire(load.backbone_digest())?,
        contract_digest: wire(load.contract_digest())?,
        ready_digest: wire(load.ready_digest())?,
        load_request_digest: Sha256Digest::for_bytes(load_ids.0.as_bytes()),
        load_reservation_digest: Sha256Digest::for_bytes(load_ids.1.as_bytes()),
        load_output_digest: wire(load_output)?,
        forward_request_digest: Sha256Digest::for_bytes(forward.control_ids().0.as_bytes()),
        forward_reservation_digest: Sha256Digest::for_bytes(forward.control_ids().1.as_bytes()),
        forward_payload_digest: wire(payload)?,
        input_digest: wire(forward.input_digest())?,
        response_digest: wire(forward.response_digest())?,
        logits_digest: wire(forward.logits_digest())?,
        execution_ns: forward.execution_ns(),
        input_tokens: u64::try_from(forward.input_tokens()).map_err(|error| error.to_string())?,
        observed_rss_bytes: forward.observed_rss_bytes(),
    };
    observed.validate()?;
    Ok(observed)
}

pub(super) fn verify_record(
    context: &ControlContext,
    control: &DurableInferenceControl,
    ids: (&str, &str),
    payload: Digest32,
    output: Digest32,
    tokens: u32,
) -> Result<(), String> {
    let record = control
        .get(ids.0)
        .ok_or("original inference request is absent")?;
    let reservation = record
        .reservation
        .as_ref()
        .ok_or("original inference reservation is absent")?;
    let assignment = record
        .assignment
        .as_ref()
        .ok_or("original inference assignment is absent")?;
    let terminal = Digest32::of_parts(&[
        b"hepta.smollm-observation.v1\0",
        ids.0.as_bytes(),
        output.as_array(),
        &[1],
        &tokens.to_be_bytes(),
    ]);
    let assignment_digest = Digest32::of_parts(&[
        b"hepta.smollm-assignment.v1\0",
        payload.as_array(),
        ids.0.as_bytes(),
    ]);
    if record.state != RequestState::Completed
        || record.request.principal_id != context.owner_id.as_str()
        || record.request.model_digest != context.model_digest
        || record.request.payload_digest != payload.to_string()
        || record.request.semantic_digest != context.grant.semantic_digest
        || record.request.maximum_tokens != 1
        || record.request.deadline_ms > context.grant.expires_at_ms
        || reservation.reservation_id != ids.1
        || reservation.quota_units != 1
        || reservation.maximum_tokens != 1
        || reservation.authority_epoch != context.grant.authority_epoch
        || reservation.valid_until_ms != record.request.deadline_ms
        || assignment.worker_id != context.worker_id
        || assignment.worker_generation != context.grant.generation
        || assignment.assignment_digest != assignment_digest.to_string()
        || record.terminal_observation_digest.as_deref() != Some(terminal.to_string().as_str())
        || record.consumed_tokens != tokens
        || record.usage_units != u64::from(tokens)
    {
        return Err(
            "original inference journal does not prove this completed observation".to_owned(),
        );
    }
    Ok(())
}

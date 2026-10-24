use std::collections::BTreeSet;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::Digest32;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::*;

/// Drive one admitted turn. EOF, unresolved effects and interrupted persistence
/// leave the original owner cursor recoverable; none becomes terminal success.
pub async fn run<C: TurnOwner, I: InferenceOwner, E: EffectOwner>(
    context: &mut C,
    inference: &mut I,
    effects: &mut E,
    binding: &TurnBinding,
    limits: &Limits,
    cancellation: &CancellationToken,
) -> Result<Outcome> {
    if binding.admission_digest.is_zero() {
        return Err(Error::Contract("missing admission"));
    }
    let now_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::Contract("system clock"))?
        .as_millis();
    let remaining_ms = u128::from(binding.deadline_unix_ms).saturating_sub(now_ms);
    let remaining = Duration::from_millis(u64::try_from(remaining_ms).unwrap_or(u64::MAX));
    if remaining.is_zero() {
        return timeout(
            limits.cancellation_timeout,
            cancel(context, inference, effects, binding),
        )
        .await
        .unwrap_or(Ok(Outcome::CancellationPending));
    }
    let result = tokio::select! {
        biased;
        _ = cancellation.cancelled() => None,
        result = timeout(limits.timeout.min(remaining), drive(context, inference, effects, binding, limits)) => {
            result.ok()
        }
    };
    match result {
        Some(Ok(outcome)) => Ok(outcome),
        Some(Err(error @ Error::Owner(_))) => Err(error),
        #[cfg(feature = "responses-api")]
        Some(Err(error @ Error::Responses(_))) => Err(error),
        Some(Err(error)) => {
            // A validation failure can arrive while a provider is still live.
            // Record and request cancellation before returning the original error.
            let _ = timeout(
                limits.cancellation_timeout,
                cancel(context, inference, effects, binding),
            )
            .await;
            Err(error)
        }
        None => timeout(
            limits.cancellation_timeout,
            cancel(context, inference, effects, binding),
        )
        .await
        .unwrap_or(Ok(Outcome::CancellationPending)),
    }
}

async fn drive<C: TurnOwner, I: InferenceOwner, E: EffectOwner>(
    context: &mut C,
    inference: &mut I,
    effects: &mut E,
    binding: &TurnBinding,
    limits: &Limits,
) -> Result<Outcome> {
    let mut frame = context.load(binding).await?;
    loop {
        validate_frame(&frame, binding, limits)?;
        let transition = match &frame.phase {
            Phase::Complete(output) => return Ok(Outcome::Completed(output.clone())),
            Phase::Cancelled => return Ok(Outcome::Cancelled),
            Phase::CancelRequested => return cancel(context, inference, effects, binding).await,
            Phase::Model(request) => {
                let output = match inference.open_or_reconcile(binding, request).await? {
                    ModelSession::Completed(output) => output,
                    ModelSession::Unresolved => return Ok(Outcome::Paused),
                    ModelSession::Stream(mut stream) => {
                        let mut text = String::new();
                        let mut calls = Vec::new();
                        loop {
                            match stream.recv().await {
                                None => return Ok(Outcome::Paused),
                                Some(Err(error)) => return Err(error),
                                Some(Ok(ModelEvent::TextDelta(delta))) => {
                                    if delta.len()
                                        > limits.maximum_output_bytes.saturating_sub(text.len())
                                    {
                                        return Err(Error::Limit("stream bytes"));
                                    }
                                    text.push_str(&delta);
                                }
                                Some(Ok(ModelEvent::ToolCall(call))) => {
                                    calls.push(call);
                                    validate_calls(&calls, limits)?;
                                }
                                Some(Ok(ModelEvent::Completed {
                                    request_id,
                                    continuation_digest,
                                    usage,
                                })) => {
                                    break ModelOutput {
                                        request_id,
                                        continuation_digest,
                                        text,
                                        calls,
                                        usage,
                                    };
                                }
                            }
                        }
                    }
                };
                if output.request_id != request.request_id || output.continuation_digest.is_zero() {
                    return Err(Error::Contract("model completion binding"));
                }
                validate_calls(&output.calls, limits)?;
                if output.text.len() > limits.maximum_output_bytes
                    || output.usage.output_tokens > request.maximum_output_tokens
                    || output.usage.input_tokens > request.maximum_provider_input_tokens
                    || frame
                        .consumed_tokens
                        .checked_add(output.usage.input_tokens)
                        .and_then(|v| v.checked_add(output.usage.output_tokens))
                        .is_none_or(|v| v > limits.maximum_total_tokens)
                {
                    return Err(Error::Limit("model output or usage"));
                }
                Transition::ModelCompleted(output)
            }
            Phase::Tools { calls, next } => {
                validate_calls(calls, limits)?;
                let call = calls.get(*next).ok_or(Error::Contract("tool cursor"))?;
                let key = operation_key(&frame, call);
                match effects.execute_or_observe(binding, key, call).await? {
                    EffectObservation::Unresolved => return Ok(Outcome::Paused),
                    EffectObservation::Completed(output) => {
                        if output.len() > limits.maximum_output_bytes {
                            return Err(Error::Limit("tool output"));
                        }
                        Transition::ToolCompleted {
                            operation_key: key,
                            output,
                        }
                    }
                }
            }
        };
        let next = context.commit(&frame, transition.clone()).await?;
        validate_successor(&frame, &next, &transition)?;
        frame = next;
    }
}

fn validate_successor(previous: &Frame, next: &Frame, transition: &Transition) -> Result<()> {
    let valid = next.binding == previous.binding
        && previous.revision.checked_add(1) == Some(next.revision)
        && match (&previous.phase, transition, &next.phase) {
            (Phase::Model(_), Transition::ModelCompleted(output), phase) => {
                next.round == previous.round
                    && previous
                        .consumed_tokens
                        .checked_add(output.usage.input_tokens)
                        .and_then(|v| v.checked_add(output.usage.output_tokens))
                        == Some(next.consumed_tokens)
                    && if output.calls.is_empty() {
                        *phase == Phase::Complete(output.clone())
                    } else {
                        *phase
                            == Phase::Tools {
                                calls: output.calls.clone(),
                                next: 0,
                            }
                    }
            }
            (Phase::Tools { calls, next: index }, Transition::ToolCompleted { .. }, phase) => {
                next.consumed_tokens == previous.consumed_tokens
                    && if index + 1 == calls.len() {
                        previous.round.checked_add(1) == Some(next.round)
                            && matches!(phase, Phase::Model(_))
                    } else {
                        next.round == previous.round
                            && *phase
                                == Phase::Tools {
                                    calls: calls.clone(),
                                    next: index + 1,
                                }
                    }
            }
            _ => false,
        };
    if valid {
        Ok(())
    } else {
        Err(Error::Contract("invalid owner successor"))
    }
}

async fn cancel<C: TurnOwner, I: InferenceOwner, E: EffectOwner>(
    context: &mut C,
    inference: &mut I,
    effects: &mut E,
    binding: &TurnBinding,
) -> Result<Outcome> {
    let mut frame = context.load_for_cancel(binding).await?;
    if frame.binding != *binding {
        return Err(Error::Contract("cancellation binding"));
    }
    match &frame.phase {
        Phase::Complete(output) => return Ok(Outcome::Completed(output.clone())),
        Phase::Cancelled => return Ok(Outcome::Cancelled),
        Phase::CancelRequested => {}
        Phase::Model(_) | Phase::Tools { .. } => {
            frame = context.commit(&frame, Transition::CancelRequested).await?;
            if frame.binding != *binding || frame.phase != Phase::CancelRequested {
                return Err(Error::Contract("cancellation was not retained"));
            }
        }
    }
    let (model, effect) = tokio::join!(inference.cancel(binding), effects.cancel(binding));
    let model = model?;
    let effect = effect?;
    if model == StopObservation::Unresolved || effect == StopObservation::Unresolved {
        return Ok(Outcome::CancellationPending);
    }
    let stopped = context.commit(&frame, Transition::Cancelled).await?;
    if stopped.binding != *binding || stopped.phase != Phase::Cancelled {
        return Err(Error::Contract("cancellation acknowledgement"));
    }
    Ok(Outcome::Cancelled)
}

pub(crate) fn validate_frame(frame: &Frame, binding: &TurnBinding, limits: &Limits) -> Result<()> {
    if frame.binding != *binding {
        return Err(Error::Contract("turn binding"));
    }
    if frame.round >= limits.maximum_rounds || frame.consumed_tokens > limits.maximum_total_tokens {
        return Err(Error::Limit("rounds or tokens"));
    }
    if let Phase::Model(request) = &frame.phase {
        if request.payload.is_empty()
            || request.input_tokens == 0
            || request.input_tokens > request.maximum_provider_input_tokens
            || request.payload.len() > limits.maximum_context_bytes
            || request.maximum_output_tokens == 0
            || frame
                .consumed_tokens
                .checked_add(request.maximum_provider_input_tokens)
                .and_then(|v| v.checked_add(request.maximum_output_tokens))
                .is_none_or(|v| v > limits.maximum_total_tokens)
        {
            return Err(Error::Limit("prepared context"));
        }
        if request.context_digest != Digest32::of_bytes(request.payload.as_bytes()) {
            return Err(Error::Contract("context bytes"));
        }
    }
    Ok(())
}

pub(crate) fn validate_calls(calls: &[ToolCall], limits: &Limits) -> Result<()> {
    if calls.len() > limits.maximum_calls {
        return Err(Error::Limit("tool count"));
    }
    let mut ids = BTreeSet::new();
    for call in calls {
        if call.arguments.len() > limits.maximum_output_bytes {
            return Err(Error::Limit("tool arguments"));
        }
        if !ids.insert(&call.call_id) {
            return Err(Error::Contract("duplicate tool call"));
        }
    }
    Ok(())
}

pub(crate) fn operation_key(frame: &Frame, call: &ToolCall) -> Digest32 {
    let generation = frame.binding.generation.get().to_be_bytes();
    let round = frame.round.to_be_bytes();
    let parts = [
        frame.binding.run_id.as_str().as_bytes(),
        frame.binding.turn_id.as_str().as_bytes(),
        &generation,
        frame.binding.admission_digest.as_array(),
        &round,
        call.call_id.as_str().as_bytes(),
        call.name.as_str().as_bytes(),
        call.arguments.as_bytes(),
    ];
    let mut encoded = b"hepta.native-agent.effect.v1".to_vec();
    for part in parts {
        encoded.extend_from_slice(&(part.len() as u64).to_be_bytes());
        encoded.extend_from_slice(part);
    }
    Digest32::of_bytes(&encoded)
}

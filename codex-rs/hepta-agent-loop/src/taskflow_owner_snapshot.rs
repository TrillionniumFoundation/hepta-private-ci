use super::*;
use crate::runner::operation_key;
use crate::runner::validate_calls;
use crate::runner::validate_frame;
use codex_hepta_automation::MAX_TASKFLOW_CURSOR_PAYLOAD_BYTES;

const MAX_OBSERVATIONS: usize = 1024;
const CANCELLATION_RESERVE_BYTES: usize = 1024;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RetainedBounds {
    maximum_rounds: u32,
    maximum_total_tokens: u64,
    maximum_context_bytes: usize,
    maximum_output_bytes: usize,
    maximum_calls: usize,
    timeout: std::time::Duration,
    cancellation_timeout: std::time::Duration,
}

impl From<&Limits> for RetainedBounds {
    fn from(value: &Limits) -> Self {
        Self {
            maximum_rounds: value.maximum_rounds,
            maximum_total_tokens: value.maximum_total_tokens,
            maximum_context_bytes: value.maximum_context_bytes,
            maximum_output_bytes: value.maximum_output_bytes,
            maximum_calls: value.maximum_calls,
            timeout: value.timeout,
            cancellation_timeout: value.cancellation_timeout,
        }
    }
}

/// Complete reconstructible Frame plus its full observation history. Initial
/// and prepared model requests occur once each; replay never recompiles them.
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Snapshot {
    schema_version: u32,
    pub(super) bounds: RetainedBounds,
    pub(super) initial: Frame,
    pub(super) history: Vec<RetainedObservation>,
}

impl Snapshot {
    pub(super) fn initial(
        binding: &TurnBinding,
        request: &ModelRequest,
        limits: &Limits,
    ) -> Result<Self> {
        let frame = Frame {
            binding: binding.clone(),
            revision: 0,
            round: 0,
            consumed_tokens: 0,
            phase: Phase::Model(request.clone()),
        };
        validate_frame(&frame, binding, limits)?;
        Ok(Self {
            schema_version: 1,
            bounds: RetainedBounds::from(limits),
            initial: frame,
            history: Vec::new(),
        })
    }

    pub(super) fn replay(&self, limits: &Limits) -> Result<Frame> {
        if self.schema_version != 1
            || self.initial.revision != 0
            || self.initial.round != 0
            || self.initial.consumed_tokens != 0
            || !matches!(self.initial.phase, Phase::Model(_))
            || self.history.len() > MAX_OBSERVATIONS
            || self.bounds != RetainedBounds::from(limits)
        {
            return Err(Error::Contract("TaskFlow native snapshot shape"));
        }
        validate_frame(&self.initial, &self.initial.binding, limits)?;
        let mut frame = self.initial.clone();
        let mut request_ids = std::collections::BTreeSet::new();
        if let Phase::Model(request) = &frame.phase {
            request_ids.insert(request.request_id.clone());
        }
        for row in &self.history {
            if let Some(request) = &row.prepared_next
                && !request_ids.insert(request.request_id.clone())
            {
                return Err(Error::Contract(
                    "TaskFlow successor reuses model request identity",
                ));
            }
            frame = advance(&frame, row, limits)?;
        }
        Ok(frame)
    }

    pub(super) fn encode(&self, cancellation: bool) -> Result<String> {
        let limit = if cancellation {
            MAX_OBSERVATIONS
        } else {
            MAX_OBSERVATIONS - 2
        };
        if self.history.len() > limit {
            return Err(Error::Limit("TaskFlow retained observation count"));
        }
        let text = serde_json::to_string(self)
            .map_err(|_| Error::Contract("TaskFlow native snapshot serialization"))?;
        let bytes = if cancellation {
            MAX_TASKFLOW_CURSOR_PAYLOAD_BYTES
        } else {
            MAX_TASKFLOW_CURSOR_PAYLOAD_BYTES - CANCELLATION_RESERVE_BYTES
        };
        if text.len() > bytes {
            return Err(Error::Limit("TaskFlow retained snapshot bytes"));
        }
        Ok(text)
    }
}

pub(super) fn needs_next_request(previous: &Frame, transition: &Transition) -> Result<bool> {
    match (&previous.phase, transition) {
        (Phase::Tools { calls, next }, Transition::ToolCompleted { .. }) => {
            if *next >= calls.len() {
                return Err(Error::Contract("TaskFlow tool cursor"));
            }
            Ok(next.checked_add(1) == Some(calls.len()))
        }
        _ => Ok(false),
    }
}

pub(super) fn check_tool_completion(
    previous: &Frame,
    transition: &Transition,
    limits: &Limits,
) -> Result<()> {
    let (
        Phase::Tools { calls, next },
        Transition::ToolCompleted {
            operation_key: key,
            output,
        },
    ) = (&previous.phase, transition)
    else {
        return Err(Error::Contract("TaskFlow tool observation phase"));
    };
    validate_calls(calls, limits)?;
    let call = calls
        .get(*next)
        .ok_or(Error::Contract("TaskFlow original tool cursor"))?;
    if operation_key(previous, call) != *key {
        return Err(Error::Contract("TaskFlow original operation key"));
    }
    if output.len() > limits.maximum_output_bytes {
        return Err(Error::Limit("TaskFlow tool observation bytes"));
    }
    Ok(())
}

pub(super) fn advance(
    previous: &Frame,
    row: &RetainedObservation,
    limits: &Limits,
) -> Result<Frame> {
    let mut next = previous.clone();
    next.revision = next
        .revision
        .checked_add(1)
        .ok_or(Error::Contract("TaskFlow native revision overflow"))?;
    match (&previous.phase, &row.transition) {
        (Phase::Model(request), Transition::ModelCompleted(output)) => {
            if row.prepared_next.is_some()
                || output.request_id != request.request_id
                || output.continuation_digest.is_zero()
            {
                return Err(Error::Contract("TaskFlow model completion binding"));
            }
            validate_calls(&output.calls, limits)?;
            if output.text.len() > limits.maximum_output_bytes
                || output.usage.input_tokens > request.maximum_provider_input_tokens
                || output.usage.output_tokens > request.maximum_output_tokens
            {
                return Err(Error::Limit("TaskFlow observed model usage or bytes"));
            }
            next.consumed_tokens = previous
                .consumed_tokens
                .checked_add(output.usage.input_tokens)
                .and_then(|value| value.checked_add(output.usage.output_tokens))
                .ok_or(Error::Limit("TaskFlow observed usage overflow"))?;
            next.phase = if output.calls.is_empty() {
                Phase::Complete(output.clone())
            } else {
                Phase::Tools {
                    calls: output.calls.clone(),
                    next: 0,
                }
            };
        }
        (Phase::Tools { calls, next: index }, Transition::ToolCompleted { .. }) => {
            check_tool_completion(previous, &row.transition, limits)?;
            if index.checked_add(1) == Some(calls.len()) {
                let request = row
                    .prepared_next
                    .clone()
                    .ok_or(Error::Contract("TaskFlow next context was not retained"))?;
                next.round = previous
                    .round
                    .checked_add(1)
                    .ok_or(Error::Limit("TaskFlow rounds overflow"))?;
                next.phase = Phase::Model(request);
            } else {
                if row.prepared_next.is_some() {
                    return Err(Error::Contract("TaskFlow premature next context"));
                }
                next.phase = Phase::Tools {
                    calls: calls.clone(),
                    next: index + 1,
                };
            }
        }
        (Phase::Model(_) | Phase::Tools { .. }, Transition::CancelRequested) => {
            if row.prepared_next.is_some() {
                return Err(Error::Contract("TaskFlow cancellation context"));
            }
            next.phase = Phase::CancelRequested;
        }
        (Phase::CancelRequested, Transition::Cancelled) => {
            if row.prepared_next.is_some() {
                return Err(Error::Contract("TaskFlow cancellation context"));
            }
            next.phase = Phase::Cancelled;
        }
        _ => return Err(Error::Contract("TaskFlow illegal native transition")),
    }
    validate_frame(&next, &previous.binding, limits)?;
    Ok(next)
}

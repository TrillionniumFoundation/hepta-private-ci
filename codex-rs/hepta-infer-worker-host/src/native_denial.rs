//! Durable local denial before awaiting external cancellation or interruption.

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;

/// Preserve every denied nonterminal observation and cancellation intent. Both
/// journal actions are attempted before returning a failure; the caller must
/// still physically interrupt before propagating it. Neither action releases
/// capacity without an exact provider terminal.
pub(super) fn persist_denied_observation(
    control: &mut DurableInferenceControl,
    request_id: &str,
    output: &NativeRunOutput,
) -> Result<(), Error> {
    let observation = control.settle_native(request_id, output.clone());
    let cancellation = control.cancel_native(request_id);
    observation?;
    cancellation?;
    Ok(())
}

#[cfg(test)]
#[path = "native_denial_tests.rs"]
mod tests;

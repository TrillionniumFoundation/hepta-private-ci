//! One authenticated readiness frame followed by the original Initial lane
//! on the same socket. Root enrollment never accepts peer-supplied inputs.

use super::enrollment::InitialEnrollmentContext;
use crate::RootGenerationInitialDeploymentV1;
use crate::authority_host_service::generation_initial::RegisteredGenerationInitial;
use crate::authority_host_service::generation_initial::ready;
use crate::authority_host_service::generation_initial::run_start_retention::RegisteredInitialRunStartRetentionV1;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostIssuerTransportError;
use std::io;
use std::os::unix::net::UnixStream;

pub(super) fn register_original_peer(
    context: &InitialEnrollmentContext<'_>,
    deployment: &RootGenerationInitialDeploymentV1,
    stream: &UnixStream,
) -> io::Result<(
    RegisteredGenerationInitial,
    Option<RegisteredInitialRunStartRetentionV1>,
)> {
    let started = std::time::Instant::now();
    context.trace_phase("ready.channel-before", started, context.end);
    let mut channel = HostAuthorityPeerChannel::from_stream(
        stream.try_clone()?,
        context.peer_policy()?,
        context.owner.try_clone()?,
    )
    .map_err(io::Error::other)?;
    HostAuthorityPeerChannel::limit_original_end(&mut channel, context.end)
        .map_err(io::Error::other)?;
    context.trace_phase("ready.channel-returned", started, context.end);
    let mut enrolled: Option<(
        RegisteredGenerationInitial,
        Option<RegisteredInitialRunStartRetentionV1>,
    )> = None;
    let mut handler_error = None;
    let mut stage = "receive original readiness frame";
    let result = channel.exchange_with_original_deadline(|bytes, request_end| {
        context.trace_phase("ready.frame-received", started, request_end);
        let action: io::Result<Vec<u8>> = (|| {
            stage = "validate original readiness binding";
            ready::require_request(bytes, &context.initial.runtime.ready_binding)?;
            stage = "check original Root context before enrollment";
            context.require_original_context(request_end)?;
            context.trace_phase("ready.context-returned", started, request_end);
            stage = "open original deployment inputs";
            let registration = deployment.with_original_peer_enrollment(request_end, |inputs| {
                stage = "register original Initial inputs and baselines";
                enrolled = Some(context.enroll_original(inputs, request_end)?);
                context.trace_phase("ready.enrollment-returned", started, request_end);
                stage = "check original deployment after enrollment";
                Ok(())
            });
            // Check the original Root context even when enrollment or the
            // fixed-input postcheck failed. Never ACK an uncertain attempt.
            let post = context.require_original_context(request_end);
            context.trace_phase("ready.registration-context-returned", started, request_end);
            registration?;
            stage = "check original Root context after enrollment";
            post?;
            stage = "verify original enrolled profile";
            let (slot, _) = enrolled
                .as_ref()
                .ok_or_else(|| io::Error::other("original Initial registration missing"))?;
            RegisteredGenerationInitial::require_original_enrollment_profile(slot)?;
            stage = "encode original readiness acknowledgement";
            let response = ready::response(
                &context.initial.runtime.ready_binding,
                &slot.profile.binding,
            )?;
            stage = "write acknowledgement and check original peer deadline";
            context.trace_phase("ready.response-encoded", started, request_end);
            Ok(response)
        })();
        action.map_err(|error| {
            handler_error = Some(error);
            HostIssuerTransportError::Unavailable
        })
    });
    context.trace_phase("ready.exchange-returned", started, context.end);
    if !matches!(result, Ok(true)) {
        if let Some((slot, _)) = &enrolled {
            RegisteredGenerationInitial::refuse_original_enrollment(slot)?;
        }
        return Err(io::Error::other(format!(
            "original Initial readiness acknowledgement uncertain: stage={stage}; enrolled={}; transport={result:?}; handler={handler_error:?}",
            enrolled.is_some()
        )));
    }
    // The framing clone is dropped without shutdown; the same original
    // socket now carries Observe. No second accept or renewed deadline exists.
    drop(channel);
    enrolled.ok_or_else(|| io::Error::other("original Initial readiness registration absent"))
}

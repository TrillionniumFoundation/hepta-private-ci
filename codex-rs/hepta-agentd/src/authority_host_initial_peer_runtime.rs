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
    let mut channel = HostAuthorityPeerChannel::from_stream(
        stream.try_clone()?,
        context.peer_policy()?,
        context.owner.try_clone()?,
    )
    .map_err(io::Error::other)?;
    HostAuthorityPeerChannel::limit_original_end(&mut channel, context.end)
        .map_err(io::Error::other)?;
    let mut enrolled: Option<(
        RegisteredGenerationInitial,
        Option<RegisteredInitialRunStartRetentionV1>,
    )> = None;
    let result = channel.exchange_with_original_deadline(|bytes, request_end| {
        let action = (|| {
            ready::require_request(bytes, &context.initial.runtime.ready_binding)?;
            context.require_original_context(request_end)?;
            let registration = deployment.with_original_peer_enrollment(request_end, |inputs| {
                enrolled = Some(context.enroll_original(inputs, request_end)?);
                Ok(())
            });
            // Check the original Root context even when enrollment or the
            // fixed-input postcheck failed. Never ACK an uncertain attempt.
            let post = context.require_original_context(request_end);
            registration?;
            post?;
            let (slot, _) = enrolled
                .as_ref()
                .ok_or_else(|| io::Error::other("original Initial registration missing"))?;
            slot.require_profile()?;
            ready::response(
                &context.initial.runtime.ready_binding,
                &slot.profile.binding,
            )
        })();
        action.map_err(|_| HostIssuerTransportError::Unavailable)
    });
    if !matches!(result, Ok(true)) {
        if let Some((slot, _)) = &enrolled {
            slot.fence()?;
        }
        return Err(io::Error::other(
            "original Initial readiness acknowledgement uncertain",
        ));
    }
    // The framing clone is dropped without shutdown; the same original
    // socket now carries Observe. No second accept or renewed deadline exists.
    drop(channel);
    enrolled.ok_or_else(|| io::Error::other("original Initial readiness registration absent"))
}

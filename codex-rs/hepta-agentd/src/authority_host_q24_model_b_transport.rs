//! Root Model admission borrows the actual B custodian. The sole Model writer
//! remains in the daemon; only canonical data crosses the original factory
//! lane, after both native readbacks and the complete Root context return.

use super::*;
use crate::cell_q24_model_proposal::project_original_root_model;
use crate::root_q24_model_b_protocol as wire;

pub(super) fn serve_original_b_model_request(
    service: &HostAuthorityService,
    factory: &RegisteredQ24ModelFactory,
    config: &HostAuthorityServiceConfig,
    registration: &HostAuthorityRegistration,
    owner_pidfd: &OwnedFd,
    bytes: &[u8],
    next_request_id: &mut u64,
    frame_end: Instant,
) -> io::Result<Vec<u8>> {
    let request: wire::Request = serde_json::from_slice(bytes).map_err(io::Error::other)?;
    if request.schema != 2
        || factory.profile.wire_schema() != 2
        || request.operation != wire::PURPOSE
        || request.binding != factory.profile.binding()
        || request.request_id != *next_request_id
    {
        return Err(io::Error::other(
            "original B Model purpose/scope/sequence differs",
        ));
    }
    let original = factory
        .original_b
        .as_ref()
        .ok_or_else(|| io::Error::other("original B custodian absent"))?;
    if request.original_b != original.original_binding().to_string() {
        return Err(io::Error::other("original Model B custodian differs"));
    }
    let training_head = request
        .training_head
        .parse::<Digest32>()
        .map_err(io::Error::other)?;
    if training_head.is_zero() || training_head.to_string() != request.training_head {
        return Err(io::Error::other("canonical original Training cut required"));
    }
    *next_request_id = next_request_id
        .checked_add(1)
        .ok_or_else(|| io::Error::other("original Model sequence exhausted"))?;

    // This method owns the one complete Root context and independent B
    // durable attempt. Never enter with_learning_profile around this call.
    crate::OriginalRootIndependentBEvaluationFilesV1::with_original_completed_evaluation(
        original,
        service,
        config,
        registration,
        owner_pidfd,
        frame_end,
        training_head,
        |actual| {
            let scope = factory.learning.require_cell_scope(
                crate::OriginalRootBEvaluationBorrowV1::initial_snapshot(&actual),
            )?;
            LiveFactoryProfile::require_context(
                &factory.profile,
                &service.identity,
                crate::OriginalRootBEvaluationBorrowV1::writer_proof(&actual),
                crate::OriginalRootBEvaluationBorrowV1::initial_snapshot(&actual),
                &scope,
            )?;
            let before = factory.current(config)?;
            let lease = original_factory_lease(service, &before)?;
            let now = HostAuthorityService::original_learning_unix_seconds(service)?;
            let projection =
                project_original_root_model(&actual, &scope, now).map_err(io::Error::other)?;
            let command = match request.action {
                wire::Action::Bind {} => Command::Bind {
                    expected: request.expected,
                    material: projection.proposal_binding.clone(),
                },
                wire::Action::Read {} => {
                    if before.material.as_ref() != Some(&projection.proposal_binding) {
                        return Err(io::Error::other("original B Model is not already bound"));
                    }
                    Command::Confirm {
                        expected: request.expected,
                    }
                }
            };
            let (after, reply) = transition(&before, lease, command, now)?;
            if after != before {
                factory
                    .store
                    .compare_and_set(factory.profile.store_owner(), &before, &after)
                    .map_err(io::Error::other)?;
            }
            if factory.current(config)? != after
                || original_factory_lease(service, &after)? != reply.lease
            {
                return Err(io::Error::other(
                    "original B Model outcome or authority changed",
                ));
            }
            if reply.newly_bound
                && HostAuthorityService::original_learning_unix_seconds(service)?
                    >= factory.profile.expiry()
            {
                return Err(io::Error::other("original B Model binding crossed expiry"));
            }
            crate::authority_host_runtime::owner_alive(owner_pidfd, frame_end)?;
            serde_json::to_vec(&wire::Response {
                schema: 2,
                operation: wire::PURPOSE.into(),
                request_id: request.request_id,
                binding: request.binding,
                original_b: request.original_b,
                reply,
                projection,
            })
            .map_err(io::Error::other)
        },
    )
}

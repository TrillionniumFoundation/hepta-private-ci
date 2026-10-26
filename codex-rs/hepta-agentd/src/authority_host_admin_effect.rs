//! Same-service exact Notes revoke and ORIGINAL authenticated-feed confirmation.
//! No unsigned admin response updates a consumer, no replacement is signed.
use super::*;
use crate::authority_host_admin::*;
use crate::deployment_issuer::OriginalNotesRevokeInput;
use std::time::Duration;
use std::time::Instant;

impl HostAuthorityService {
    pub(crate) fn revoke_original_notes_grant(
        &self,
        context: &LiveRootAdminRequest<'_>,
        signed: &SignedFinalUseGrant,
        expected_effect_revision: u64,
        expected_issuer_revision: u64,
        reason_sha256: [u8; 32],
    ) -> io::Result<RootAdminResponse> {
        context.check_for(self)?;
        let notes = self
            .notes
            .as_ref()
            .ok_or_else(|| io::Error::other("original fixed Notes policy required"))?;
        let prepared = notes.prepare_original_grant_revocation(
            &self.issuer,
            OriginalNotesRevokeInput {
                signed,
                expected_effect_revision,
                expected_issuer_revision,
                reason_sha256,
                before: context.before(),
            },
        )?;
        context.check_for(self)?;
        let revoked = prepared.revoke_effect_lease()?;
        let effect_receipt = revoked.receipt().clone();
        context.check_for(self)?;
        let result = revoked.revoke_original_grant();
        context.check_for(self)?;
        let (final_use_head, synchronization) = match result {
            Ok((_, head)) => {
                let sync_end = context
                    .before()
                    .checked_sub(Duration::from_millis(50))
                    .ok_or_else(|| io::Error::other("original admin response budget exhausted"))?;
                let synchronization = loop {
                    context.check_for(self)?;
                    let observed = self.observe_original_consumer_synchronization(&head);
                    if matches!(observed, RootAdminConsumerSynchronization::Confirmed { .. })
                        || Instant::now() >= sync_end
                    {
                        break observed;
                    }
                    let pause = sync_end
                        .saturating_duration_since(Instant::now())
                        .min(Duration::from_millis(10));
                    if pause.is_zero() {
                        break observed;
                    }
                    std::thread::sleep(pause);
                };
                (Some(head), synchronization)
            }
            Err(_) => (
                None,
                RootAdminConsumerSynchronization::Pending {
                    reason: "original_issuer_outcome_unknown",
                },
            ),
        };
        context.check_for(self)?;
        Ok(RootAdminResponse::OriginalNotesGrantRevocation {
            instance: context.instance().clone(),
            original_grant_id: signed.grant.grant_id.clone(),
            effect_lease_receipt: effect_receipt,
            final_use_head,
            synchronization,
        })
    }

    fn observe_original_consumer_synchronization(
        &self,
        head: &FinalUseRevocations,
    ) -> RootAdminConsumerSynchronization {
        let pending = |reason| RootAdminConsumerSynchronization::Pending { reason };
        let Some(consumers) = &self.consumers else {
            return pending("original_consumers_not_registered");
        };
        if self.issuer.revocations().as_ref().ok() != Some(head) {
            return pending("original_issuer_head_changed");
        }
        let (Ok(device), Ok(notes)) = (
            consumers.device.frontier_for_handoff(head),
            consumers.notes.frontier_for_handoff(head),
        ) else {
            return pending("original_consumer_observation_unavailable");
        };
        if self.issuer.revocations().as_ref().ok() != Some(head) {
            return pending("original_issuer_head_changed");
        }
        // These are only the already registered protected stores advanced by
        // the original authenticated observation -> synchronize_consumers path.
        // We never call update_revocations or CAS either frontier here.
        if [device, notes].iter().all(|frontier| {
            frontier.authority_epoch == head.authority_epoch
                && frontier.revocation_revision == head.revision
        }) {
            RootAdminConsumerSynchronization::Confirmed {
                device_frontier: device,
                notes_frontier: notes,
            }
        } else {
            pending("original_authenticated_consumers_have_not_confirmed")
        }
    }
}

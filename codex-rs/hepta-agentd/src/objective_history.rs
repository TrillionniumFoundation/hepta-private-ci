//! Exact-request history through the original journal owner. This path never
//! authenticates new authority, compiles, appends, reconciles or starts a run.

use codex_hepta_learning_ledger::RunStartAnchor;
use codex_hepta_learning_ledger::RunStartStoreError;

use super::*;
use crate::ObjectiveAdmissionOutcome;
use crate::ObjectiveAdmissionPublication;
use crate::ObjectiveAdmissionQuery;
use crate::ObjectiveAdmissionUnknownReason;
use crate::ObjectivePublicationOutcome;

impl ObjectiveRuntimeHost {
    pub(crate) fn admission_history(
        &self,
        identity: &AgentdIdentity,
        query: ObjectiveAdmissionQuery,
    ) -> ObjectiveAdmissionOutcome {
        let result = self
            .state
            .lock()
            .map_err(|_| ObjectiveAdmissionUnknownReason::JournalUnavailable)
            .and_then(|state| state.read_publication(identity, self.profile_digest, query));
        match result {
            Ok(publication) => ObjectiveAdmissionOutcome::Published {
                publication: Box::new(publication),
            },
            Err(reason) => ObjectiveAdmissionOutcome::Unknown { reason },
        }
    }
}

impl ObjectiveHostState {
    pub(super) fn read_publication(
        &self,
        identity: &AgentdIdentity,
        profile_digest: Digest32,
        query: ObjectiveAdmissionQuery,
    ) -> Result<ObjectiveAdmissionPublication, ObjectiveAdmissionUnknownReason> {
        use ObjectiveAdmissionUnknownReason as Unknown;

        // Match the retained historical signature and all original claims. Do
        // not apply today's issuer expiry/revocation as a history-erasure rule.
        // Read access uses the existing owner-only socket and outer spawn fence.
        let claims = codex_hepta_authority_client::historical_authbus_objective_claims(
            identity,
            &query.request,
        )
        .map_err(|_| Unknown::InvalidQuery)?;
        let expected_authentication = RunStartAuthenticationV1 {
            issuer_id: claims.issuer_id,
            key_epoch: claims.key_epoch.get(),
            message_id: claims.message_id,
            sequence: claims.sequence,
            expires_at_ms: claims.expires_at_ms,
            scope_digest: claims.scope_digest,
            signed_body_digest: claims.payload_digest,
            signature: hex_bytes(&query.request.signature_hex)
                .map_err(|_| Unknown::InvalidQuery)?,
        };
        let run_id =
            StableId::new(&query.request.body.run_id).map_err(|_| Unknown::InvalidQuery)?;
        if let Some(anchor) = &query.anchor {
            let chain_digest = parse_digest(&anchor.chain_digest, "history anchor")
                .map_err(|_| Unknown::InvalidQuery)?;
            self.journal
                .verify_anchor(RunStartAnchor {
                    sequence: anchor.sequence,
                    chain_digest,
                })
                .map_err(|error| match error {
                    RunStartStoreError::InvalidAnchor => Unknown::InvalidQuery,
                    RunStartStoreError::AcknowledgedHistoryMissing => Unknown::AnchorMissing,
                    RunStartStoreError::AnchorMismatch => Unknown::AnchorMismatch,
                    _ => Unknown::JournalUnavailable,
                })?;
        }
        let publication = self
            .journal
            .publication(&run_id)
            .map_err(|_| Unknown::JournalUnavailable)?
            .ok_or(Unknown::NoMatchingPublication)?;
        if query
            .anchor
            .as_ref()
            .is_some_and(|anchor| publication.sequence > anchor.sequence)
        {
            return Err(Unknown::PublicationOutsideAnchor);
        }
        let (authentication, recorded_profile_digest, outcome) = if let Some(record) = self
            .journal
            .get(&run_id)
            .map_err(|_| Unknown::JournalUnavailable)?
        {
            let fields = (
                record.snapshot.objective_digest.to_string(),
                record.snapshot.hard_constraint_digest.to_string(),
            );
            let outcome = match record.disposition {
                RunStartObjectiveDispositionV1::Compiled => ObjectivePublicationOutcome::Compiled {
                    objective_digest: fields.0,
                    hard_constraint_digest: fields.1,
                },
                RunStartObjectiveDispositionV1::ExplicitAbstain => {
                    ObjectivePublicationOutcome::ExplicitAbstain {
                        objective_digest: fields.0,
                        hard_constraint_digest: fields.1,
                    }
                }
            };
            (
                &record.authentication,
                record.admission.profile_digest,
                outcome,
            )
        } else {
            let record = self
                .journal
                .get_conflict(&run_id)
                .map_err(|_| Unknown::JournalUnavailable)?
                .ok_or(Unknown::NoMatchingPublication)?;
            (
                &record.authentication,
                record.admission.profile_digest,
                ObjectivePublicationOutcome::Conflict {
                    conflict_digest: record.conflict_digest.to_string(),
                },
            )
        };
        if authentication != &expected_authentication || recorded_profile_digest != profile_digest {
            return Err(Unknown::NoMatchingPublication);
        }
        Ok(ObjectiveAdmissionPublication {
            run_id: run_id.to_string(),
            original_spawn_generation: query.request.body.spawn_generation,
            issuer_id: authentication.issuer_id.to_string(),
            key_epoch: authentication.key_epoch,
            message_id: authentication.message_id.to_string(),
            message_sequence: authentication.sequence,
            expires_at_ms: authentication.expires_at_ms,
            signed_body_digest: authentication.signed_body_digest.to_string(),
            profile_digest: profile_digest.to_string(),
            publication_sequence: publication.sequence,
            publication_digest: publication.record_digest.to_string(),
            chain_digest: publication.chain_digest.to_string(),
            outcome,
        })
    }
}

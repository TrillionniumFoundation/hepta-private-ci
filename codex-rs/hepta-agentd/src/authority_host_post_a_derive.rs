//! Independently derive the V2 rule from Root's actual complete task and the
//! original durable Evaluator freeze. The pure batch carries no Dataset cap.

use std::time::Instant;

use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::freeze_dataset_from_ledger;

use super::super::learning_trust::RootHistoricalLearningTrustV1;
use super::super::require_end;
use super::*;
use crate::AgentdIdentity;
use crate::CircuitTaskSourcePublicationV1;
use crate::HostAuthorityLearningProfileV1;
use crate::HostAuthorityService;
use crate::authority_host_service::generation_initial::historical_source_pin::RootOriginalHistoricalCompleteTaskObservationV1;
use crate::cell_q24_single_head_update_rule_v1;
use crate::circuit_task::RootHistoricalTaskPublicationDataV1;
use crate::learning_owner_evidence;
use crate::original_q24_dataset_freeze_execution_key_v1;
use crate::original_q24_dataset_preparation_identity_v1;
use crate::project_original_q24_dataset_v1;

impl PostALearningRuntime {
    pub(super) fn with_original_derived_profile<T>(
        &self,
        service: &HostAuthorityService,
        identity: &AgentdIdentity,
        proof: &str,
        initial: &LearningIterationSnapshotV1,
        observed: &RootOriginalHistoricalCompleteTaskObservationV1,
        trust: &RootHistoricalLearningTrustV1,
        end: Instant,
        action: impl FnOnce(HostAuthorityLearningProfileV1) -> io::Result<T>,
    ) -> io::Result<T> {
        require_end(end)?;
        self.require_original_metadata()?;
        if initial != &self.initial || trust.pin.mapping != self.learning_trust_mapping {
            return Err(io::Error::other("original post-A recipient changed"));
        }
        let ledger = RootOriginalHistoricalCompleteTaskObservationV1::ledger_read_data(observed)?;
        if Digest32::from_array(ledger.target.digest().map_err(io::Error::other)?).to_string()
            != self.target
        {
            return Err(io::Error::other("original post-A task target differs"));
        }
        let publication_data =
            RootOriginalHistoricalCompleteTaskObservationV1::publication_read_data(observed);
        let (publication, cell) =
            RootHistoricalTaskPublicationDataV1::validate_against(&publication_data, &ledger)
                .map_err(io::Error::other)?;
        self.require_original_task(&publication)?;
        let baseline = PostABaselineFiles::read_model(&self.baseline)?;
        let index = match self.plan.head {
            CellQ24PrivateHeadV1::Drive { index } | CellQ24PrivateHeadV1::Prediction { index } => {
                index
            }
        };
        if baseline.components() != &initial.request.selected_bundle.components
            || baseline.input_width() != usize::from(self.plan.projection.input_width)
            || usize::from(index) >= baseline.output_width()
        {
            return Err(io::Error::other("actual original baseline and head differ"));
        }
        let snapshot = ledger.read_snapshot()?;
        let plan = DatasetFreezePlanV2 {
            snapshot_id: self.plan.snapshot_id.clone(),
            objective_digest: initial.request.envelope.objective_digest,
            inclusion_policy_digest: self
                .plan
                .projection
                .inclusion_policy_digest()
                .map_err(io::Error::other)?,
        };
        let payload =
            dataset_freeze_signing_payload_v2(&snapshot, &plan).map_err(io::Error::other)?;
        let current_trust =
            RootHistoricalLearningTrustV1::read_original_payload(trust, service, initial, &ledger)?;
        let now = HostAuthorityService::original_learning_unix_seconds(service)?;
        if self.register && now >= initial.request.envelope.expiry_unix_seconds {
            return Err(io::Error::other(
                "new post-A enrollment crossed original deadline",
            ));
        }
        let (activated, evaluator) = current_trust.activate_for_recipient(initial, now)?;
        current_trust.require_activation_pin(initial, &activated, &trust.pin)?;
        let preparation = original_q24_dataset_preparation_identity_v1(
            initial.head_digest,
            ledger
                .cut
                .ledger_binding
                .parse()
                .map_err(io::Error::other)?,
            &payload,
            baseline.effective_weights_digest(),
            self.plan.head,
            self.plan.rule,
        );
        let key = original_q24_dataset_freeze_execution_key_v1(
            &initial.request.operation_id,
            preparation,
            activated.verifier().trust_digest(),
            &evaluator,
            self.plan.maximum_signature_lifetime_seconds,
        );
        PostAFreezeFiles::with_original_completion(&self.freeze, &key, end, |saved| {
            let (saved_payload, signed) =
                learning_owner_evidence::decode(saved).map_err(io::Error::other)?;
            let expected_expiry = signed
                .issued_at
                .checked_add(self.plan.maximum_signature_lifetime_seconds)
                .ok_or_else(|| io::Error::other("original freeze expiry overflow"))?
                .min(evaluator.principal.expires_at);
            if saved_payload != payload
                || signed.evidence_id.as_str()
                    != format!("original-dataset-freeze:{}", key.binding_digest)
                || signed.issued_at >= initial.request.envelope.expiry_unix_seconds
                || signed.expires_at != expected_expiry
            {
                return Err(io::Error::other(
                    "original freeze completion identity differs",
                ));
            }
            let now = HostAuthorityService::original_learning_unix_seconds(service)?;
            let verified = activated
                .verifier()
                .verify(LearningEvidenceRoleV1::Evaluator, &signed, &payload, now)
                .map_err(io::Error::other)?;
            if verified.principal() != &evaluator.principal
                || verified.controller_id() != &evaluator.controller_id
            {
                return Err(io::Error::other("original fixed freeze Evaluator differs"));
            }
            let receipt =
                freeze_dataset_from_ledger(&snapshot, plan, verified.principal().clone(), now)
                    .map_err(io::Error::other)?;
            let records = LedgerSnapshot::read_dataset_records(&snapshot, &receipt, now)
                .map_err(io::Error::other)?;
            let batch = project_original_q24_dataset_v1(
                &snapshot,
                &receipt,
                &self.plan.projection,
                &records,
                &[(publication, cell)],
                now,
            )
            .map_err(io::Error::other)?;
            if batch.rows() > initial.request.budget.maximum_dataset_rows
                || batch.encoded().len() as u64 > initial.request.budget.maximum_dataset_bytes
                || u64::from(batch.rows()) * u64::from(self.plan.rule.epochs)
                    > initial.request.budget.maximum_training_steps
            {
                return Err(io::Error::other(
                    "original Dataset and training budget exceeded",
                ));
            }
            let update_rule = cell_q24_single_head_update_rule_v1(
                &initial.request.selected_bundle,
                self.plan.head,
                self.plan.rule.digest(&batch).map_err(io::Error::other)?,
            )
            .map_err(io::Error::other)?;
            let profile = HostAuthorityLearningProfileV1::new_scoped_v2(
                identity,
                *proof
                    .parse::<Digest32>()
                    .map_err(io::Error::other)?
                    .as_array(),
                initial.request.clone(),
                initial.owners.clone(),
                LearningUpdateScopeV2::Cell,
                update_rule,
            )?;
            if profile.require_binding(identity, proof)? != *initial {
                return Err(io::Error::other("derived original initial differs"));
            }
            require_end(end)?;
            let result = action(profile)?;
            // Root writer/pidfd/lease postchecks in action finish before the
            // independent baseline, trust and freeze physical postchecks here.
            self.require_original_metadata()?;
            RootHistoricalLearningTrustV1::revalidate(trust, service, initial)?;
            let after = PostABaselineFiles::read_model(&self.baseline)?;
            if after.components() != baseline.components()
                || after.effective_weights_digest() != baseline.effective_weights_digest()
            {
                return Err(io::Error::other(
                    "original baseline bytes changed during enrollment",
                ));
            }
            activated
                .verifier()
                .verify(
                    LearningEvidenceRoleV1::Evaluator,
                    &signed,
                    &payload,
                    HostAuthorityService::original_learning_unix_seconds(service)?,
                )
                .map_err(io::Error::other)?;
            self.require_original_metadata()?;
            require_end(end)?;
            Ok(result)
        })
    }

    fn require_original_task(
        &self,
        publication: &CircuitTaskSourcePublicationV1,
    ) -> io::Result<()> {
        let input = publication.input();
        let request = &self.initial.request;
        if input.scope.agent_id != request.agent_id
            || input.scope.cell_id != request.cell_id
            || input.scope.run_id != request.source_run_id
            || input.scope.principal_digest.to_string() != request.principal_id.as_str()
            || input.objective_digest != request.envelope.objective_digest
            || publication.original_record().snapshot.run_id != input.scope.run_id
            || publication.original_record().snapshot.objective_digest != input.objective_digest
            || publication.history_digest().as_str() != request.completed_task_receipt.to_string()
            || publication.bundle_digest() != self.plan.projection.baseline_bundle
        {
            return Err(io::Error::other(
                "actual original completed task differs from learning request",
            ));
        }
        Ok(())
    }
}

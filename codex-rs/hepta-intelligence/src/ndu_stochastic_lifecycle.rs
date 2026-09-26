//! Final stochastic artifact composition over independent current, withdrawal,
//! lifecycle, selection, convergence and well-posedness trust domains.

use codex_hepta_learning_artifacts::ArtifactClosureError;
use codex_hepta_learning_artifacts::ArtifactLifecycleJournalSnapshotV2;
use codex_hepta_learning_artifacts::ArtifactLifecycleJournalV2;
use codex_hepta_learning_artifacts::ArtifactLifecycleStateV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistrySnapshotV1;
use codex_hepta_learning_artifacts::LifecycleActorRoleV2;
use codex_hepta_learning_artifacts::RevalidatingCandidate;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::VerifiedArtifactSelectionV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::NduStochasticAdmissionError;
use super::NduStochasticAdmissionReceiptV1;
use super::NduStochasticAdmissionRequestV1;
use super::admit_ndu_stochastic_candidate_v1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct LifecycleSelectionBindingV2 {
    lifecycle_head_digest: Digest32,
    selected_record_digest: Digest32,
    selection_digest: Digest32,
}

impl<'a> NduStochasticAdmissionRequestV1<'a> {
    /// Compose the existing stochastic admission with independently recovered
    /// withdrawal and lifecycle snapshots plus one independently verified,
    /// signed selection. No caller-provided status flag is trusted:
    ///
    /// * CURRENT is revalidated by `VerifiedCurrentRegistryViewV1`;
    /// * withdrawn datasets reject before numeric evidence is considered;
    /// * the latest lifecycle record must be `Selected`, never `Revoked`;
    /// * the lifecycle selection event must bind the exact signed/verified
    ///   selection and the same current registry head, witness and trust;
    /// * convergence and well-posedness remain independently signed and are
    ///   checked by the existing V1 admission.
    ///
    /// The returned receipt remains `DENY_ALL`; this is admission evidence, not
    /// activation, release or external-effect authority.
    pub fn admit_with_artifact_lifecycle_v2(
        self,
        candidate: &mut RevalidatingCandidate,
        current_registry_view: VerifiedCurrentRegistryViewV1,
        withdrawal_snapshot: DatasetWithdrawalRegistrySnapshotV1,
        lifecycle_snapshot: ArtifactLifecycleJournalSnapshotV2,
        signed_selection: &SignedArtifactSelectionV1,
        verified_selection: &VerifiedArtifactSelectionV1,
        now: u64,
    ) -> Result<NduStochasticAdmissionReceiptV1, NduStochasticAdmissionError> {
        if verified_selection.authority().grants_any() {
            return Err(NduStochasticAdmissionError::AuthorityEscalation(
                "artifact_selection",
            ));
        }
        let manifest = &self.artifact_admission.validated_manifest.manifest;
        if verified_selection.artifact_id() != &manifest.artifact_id
            || signed_selection.artifact_id != manifest.artifact_id
            || signed_selection.selector_id != *verified_selection.selector_id()
        {
            return Err(NduStochasticAdmissionError::SelectionMismatch(
                "verified selection identity",
            ));
        }
        let expected_selection_digest = signed_selection_digest(signed_selection);
        if expected_selection_digest != verified_selection.selection_digest() {
            return Err(NduStochasticAdmissionError::SelectionMismatch(
                "signed selection digest",
            ));
        }

        let withdrawal_head = validate_withdrawal_snapshot_v2(
            withdrawal_snapshot,
            self.current_withdrawal_head,
            self.artifact_admission.withdrawal_scope_digest,
            manifest,
            now,
        )?;
        let current_registry_head = current_registry_view.receipt().head_digest;
        let lifecycle = validate_selected_lifecycle_v2(
            lifecycle_snapshot,
            &manifest.artifact_id,
            &manifest.producer_id,
            expected_selection_digest,
            signed_selection,
            current_registry_head,
            current_registry_view.witness_digest(),
            current_registry_view.trust_digest(),
            self.artifact_admission.withdrawal_scope_digest,
            now,
        )?;

        let mut receipt =
            admit_ndu_stochastic_candidate_v1(candidate, current_registry_view, self, now)?;
        receipt.admission_digest = Digest32::of_parts(&[
            b"hepta.intelligence.ndu-stochastic-lifecycle-admission.v2\0",
            receipt.admission_digest.as_array(),
            withdrawal_head.as_array(),
            lifecycle.lifecycle_head_digest.as_array(),
            lifecycle.selected_record_digest.as_array(),
            lifecycle.selection_digest.as_array(),
        ]);
        Ok(receipt)
    }
}

fn validate_withdrawal_snapshot_v2(
    snapshot: DatasetWithdrawalRegistrySnapshotV1,
    expected_head: Digest32,
    expected_scope: Digest32,
    manifest: &codex_hepta_learning_artifacts::LearningArtifactManifestV2,
    now: u64,
) -> Result<Digest32, NduStochasticAdmissionError> {
    let registry = DatasetWithdrawalRegistry::from_snapshot(snapshot)
        .map_err(NduStochasticAdmissionError::WithdrawalSnapshot)?;
    if registry.head_digest() != expected_head || registry.scope_digest() != Some(expected_scope) {
        return Err(NduStochasticAdmissionError::WithdrawalHeadMismatch);
    }
    match registry.admit_manifest(manifest.clone(), now) {
        Ok(_) => Ok(registry.head_digest()),
        Err(ArtifactClosureError::WithdrawnDataset) => {
            Err(NduStochasticAdmissionError::ArtifactWithdrawn)
        }
        Err(error) => Err(NduStochasticAdmissionError::WithdrawalSnapshot(error)),
    }
}

#[allow(clippy::too_many_arguments)]
fn validate_selected_lifecycle_v2(
    snapshot: ArtifactLifecycleJournalSnapshotV2,
    artifact_id: &StableId,
    producer_id: &StableId,
    expected_selection_digest: Digest32,
    signed_selection: &SignedArtifactSelectionV1,
    current_registry_head: Digest32,
    current_witness_digest: Digest32,
    current_trust_digest: Digest32,
    withdrawal_scope_digest: Digest32,
    now: u64,
) -> Result<LifecycleSelectionBindingV2, NduStochasticAdmissionError> {
    if signed_selection_digest(signed_selection) != expected_selection_digest
        || signed_selection.artifact_id != *artifact_id
        || signed_selection.registry_head_digest != current_registry_head
        || signed_selection.current_witness_digest != current_witness_digest
        || signed_selection.current_trust_digest != current_trust_digest
        || signed_selection.withdrawal_scope_digest != withdrawal_scope_digest
        || signed_selection.issued_at > now
        || now > signed_selection.expires_at
    {
        return Err(NduStochasticAdmissionError::SelectionMismatch(
            "current signed selection binding",
        ));
    }

    let journal = ArtifactLifecycleJournalV2::from_snapshot(snapshot, now)
        .map_err(NduStochasticAdmissionError::LifecycleSnapshot)?;
    let latest = journal
        .records()
        .iter()
        .rev()
        .find(|record| record.event.artifact_id == *artifact_id);
    let state = latest.map_or(ArtifactLifecycleStateV1::Proposed, |record| {
        record.event.next_state
    });
    match state {
        ArtifactLifecycleStateV1::Revoked => {
            return Err(NduStochasticAdmissionError::ArtifactRevoked);
        }
        ArtifactLifecycleStateV1::Selected => {}
        other => return Err(NduStochasticAdmissionError::ArtifactNotSelected(other)),
    }
    let record = latest.ok_or(NduStochasticAdmissionError::ArtifactNotSelected(
        ArtifactLifecycleStateV1::Proposed,
    ))?;
    if &record.producer_id != producer_id
        || record.event.evidence_digest != expected_selection_digest
        || record.event.actor_id != signed_selection.selector_id
        || record.event.actor_credential_digest != signed_selection.selector_credential_digest
        || record.event.authority_epoch != signed_selection.authority_epoch
        || record.actor.role != LifecycleActorRoleV2::Selector
        || record.actor.actor_id != signed_selection.selector_id
        || record.actor.credential_digest != signed_selection.selector_credential_digest
        || record.actor.authority_epoch != signed_selection.authority_epoch
        || record.actor.verified_at > now
        || now > record.actor.expires_at
    {
        return Err(NduStochasticAdmissionError::SelectionMismatch(
            "selected lifecycle record",
        ));
    }
    Ok(LifecycleSelectionBindingV2 {
        lifecycle_head_digest: journal.head_digest(),
        selected_record_digest: record.chain_digest,
        selection_digest: expected_selection_digest,
    })
}

fn signed_selection_digest(selection: &SignedArtifactSelectionV1) -> Digest32 {
    let mut bytes = selection.signing_bytes();
    bytes.extend_from_slice(&selection.signature);
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use codex_hepta_learning_artifacts::ArtifactKind;
    use codex_hepta_learning_artifacts::ArtifactLifecycleEventV1;
    use codex_hepta_learning_artifacts::ArtifactLifecycleJournalV2;
    use codex_hepta_learning_artifacts::DatasetWithdrawalNoticeV1;
    use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
    use codex_hepta_learning_artifacts::DatasetWithdrawalScopeV1;
    use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
    use codex_hepta_learning_artifacts::LifecycleActorEvidenceV2;
    use codex_hepta_learning_artifacts::LifecycleActorRoleV2;
    use codex_hepta_learning_artifacts::ProvenanceModeV1;
    use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
    use codex_hepta_types::Generation;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn manifest(dataset: Digest32) -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: id("ndu-coefficients"),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(1).expect("generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![dataset],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: digest("artifact-bytes"),
            encoded_size_bytes: 64,
            training_code_digest: digest("training-code"),
            runtime_tuple_digest: digest("runtime-tuple"),
            device_profile_digest: digest("device"),
            objective_class_digest: digest("objective-class"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: id("artifact-producer"),
            created_at: 10,
            expires_at: 100,
        }
    }

    fn scope() -> DatasetWithdrawalScopeV1 {
        DatasetWithdrawalScopeV1 {
            authority_domain_id: id("dataset-authority"),
            registry_id: id("withdrawal-registry"),
            scope_id: id("ndu-training"),
        }
    }

    fn signed_selection(
        manifest: &LearningArtifactManifestV2,
        registry_head: Digest32,
        witness: Digest32,
        trust: Digest32,
        withdrawal_scope: Digest32,
    ) -> SignedArtifactSelectionV1 {
        SignedArtifactSelectionV1 {
            selection_id: id("selection-v1"),
            artifact_id: manifest.artifact_id.clone(),
            registry_id: id("artifact-registry"),
            withdrawal_scope_digest: withdrawal_scope,
            registry_head_digest: registry_head,
            current_witness_digest: witness,
            current_trust_digest: trust,
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: None,
            content_digest: manifest.bytes_digest,
            objective_digest: digest("objective"),
            support_digest: digest("support"),
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id("independent-selector"),
            selector_credential_digest: digest("selector-credential"),
            signing_key_digest: digest("selector-key"),
            authority_epoch: 4,
            issued_at: 20,
            expires_at: 80,
            signature: [7; 64],
        }
    }

    fn append_transition(
        journal: &mut ArtifactLifecycleJournalV2,
        manifest: &LearningArtifactManifestV2,
        event_id: &str,
        actor_id: StableId,
        role: LifecycleActorRoleV2,
        prior_state: ArtifactLifecycleStateV1,
        next_state: ArtifactLifecycleStateV1,
        evidence: Digest32,
        now: u64,
    ) {
        let credential = digest(&format!("{event_id}-credential"));
        journal
            .append(
                journal.head_digest(),
                &manifest.producer_id,
                LifecycleActorEvidenceV2 {
                    actor_id: actor_id.clone(),
                    credential_digest: credential,
                    role,
                    authority_epoch: 4,
                    verified_at: 10,
                    expires_at: 100,
                },
                ArtifactLifecycleEventV1 {
                    event_id: id(event_id),
                    artifact_id: manifest.artifact_id.clone(),
                    prior_state,
                    next_state,
                    actor_id,
                    actor_credential_digest: credential,
                    evidence_digest: evidence,
                    authority_epoch: 4,
                    occurred_at: now,
                },
                now,
            )
            .expect("lifecycle transition");
    }

    fn selected_journal(
        manifest: &LearningArtifactManifestV2,
        selection: &SignedArtifactSelectionV1,
    ) -> ArtifactLifecycleJournalV2 {
        let mut journal = ArtifactLifecycleJournalV2::new();
        let transitions = [
            (
                "trained",
                manifest.producer_id.clone(),
                LifecycleActorRoleV2::Producer,
                ArtifactLifecycleStateV1::Proposed,
                ArtifactLifecycleStateV1::Trained,
            ),
            (
                "evaluated",
                id("independent-evaluator"),
                LifecycleActorRoleV2::Evaluator,
                ArtifactLifecycleStateV1::Trained,
                ArtifactLifecycleStateV1::Evaluated,
            ),
            (
                "shadow",
                id("shadow-operator"),
                LifecycleActorRoleV2::ShadowOperator,
                ArtifactLifecycleStateV1::Evaluated,
                ArtifactLifecycleStateV1::Shadow,
            ),
            (
                "canary",
                id("canary-operator"),
                LifecycleActorRoleV2::CanaryOperator,
                ArtifactLifecycleStateV1::Shadow,
                ArtifactLifecycleStateV1::Canary,
            ),
            (
                "operator-accepted",
                id("human-operator"),
                LifecycleActorRoleV2::HumanOperator,
                ArtifactLifecycleStateV1::Canary,
                ArtifactLifecycleStateV1::OperatorAccepted,
            ),
        ];
        for (event, actor, role, prior, next) in transitions {
            append_transition(
                &mut journal,
                manifest,
                event,
                actor,
                role,
                prior,
                next,
                digest(&format!("{event}-evidence")),
                50,
            );
        }
        let selection_digest = signed_selection_digest(selection);
        journal
            .append(
                journal.head_digest(),
                &manifest.producer_id,
                LifecycleActorEvidenceV2 {
                    actor_id: selection.selector_id.clone(),
                    credential_digest: selection.selector_credential_digest,
                    role: LifecycleActorRoleV2::Selector,
                    authority_epoch: selection.authority_epoch,
                    verified_at: selection.issued_at,
                    expires_at: selection.expires_at,
                },
                ArtifactLifecycleEventV1 {
                    event_id: id("selected"),
                    artifact_id: manifest.artifact_id.clone(),
                    prior_state: ArtifactLifecycleStateV1::OperatorAccepted,
                    next_state: ArtifactLifecycleStateV1::Selected,
                    actor_id: selection.selector_id.clone(),
                    actor_credential_digest: selection.selector_credential_digest,
                    evidence_digest: selection_digest,
                    authority_epoch: selection.authority_epoch,
                    occurred_at: 50,
                },
                50,
            )
            .expect("selected transition");
        journal
    }

    #[test]
    fn withdrawal_snapshot_distinguishes_current_and_withdrawn_artifacts() {
        let dataset = digest("dataset");
        let manifest = manifest(dataset);
        let mut registry = DatasetWithdrawalRegistry::new_scoped(scope());
        let current_head = registry.head_digest();
        assert_eq!(
            validate_withdrawal_snapshot_v2(
                registry.snapshot(),
                current_head,
                registry.scope_digest().expect("scope"),
                &manifest,
                50,
            ),
            Ok(current_head)
        );
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id("withdrawal"),
                dataset_digest: dataset,
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("dataset-authority"),
                credential_chain_digest: digest("withdrawal-credential"),
                signing_key_digest: digest("withdrawal-key"),
                authority_epoch: 2,
                issued_at: 60,
            })
            .expect("withdrawal append");
        assert_eq!(
            validate_withdrawal_snapshot_v2(
                registry.snapshot(),
                registry.head_digest(),
                registry.scope_digest().expect("scope"),
                &manifest,
                60,
            ),
            Err(NduStochasticAdmissionError::ArtifactWithdrawn)
        );
    }

    #[test]
    fn selected_lifecycle_is_bound_and_revocation_wins() {
        let manifest = manifest(digest("dataset"));
        let registry_head = digest("registry-head");
        let witness = digest("current-witness");
        let trust = digest("current-trust");
        let withdrawal_scope = scope().digest();
        let selection = signed_selection(
            &manifest,
            registry_head,
            witness,
            trust,
            withdrawal_scope,
        );
        let selection_digest = signed_selection_digest(&selection);
        let mut journal = selected_journal(&manifest, &selection);
        let selected = validate_selected_lifecycle_v2(
            journal.snapshot(),
            &manifest.artifact_id,
            &manifest.producer_id,
            selection_digest,
            &selection,
            registry_head,
            witness,
            trust,
            withdrawal_scope,
            50,
        )
        .expect("selected lifecycle");
        assert_eq!(selected.selection_digest, selection_digest);
        assert_eq!(selected.lifecycle_head_digest, journal.head_digest());

        append_transition(
            &mut journal,
            &manifest,
            "revoked",
            id("revocation-authority"),
            LifecycleActorRoleV2::RevocationAuthority,
            ArtifactLifecycleStateV1::Selected,
            ArtifactLifecycleStateV1::Revoked,
            digest("revocation-evidence"),
            60,
        );
        assert_eq!(
            validate_selected_lifecycle_v2(
                journal.snapshot(),
                &manifest.artifact_id,
                &manifest.producer_id,
                selection_digest,
                &selection,
                registry_head,
                witness,
                trust,
                withdrawal_scope,
                60,
            ),
            Err(NduStochasticAdmissionError::ArtifactRevoked)
        );
    }
}

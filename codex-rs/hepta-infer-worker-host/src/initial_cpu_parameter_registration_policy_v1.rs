//! Original whole E1/Root registration/independent Selector trust join.
use super::*;
use codex_hepta_agent_components::learning_ledger::TrustedLearningSignerV1;
use codex_hepta_agent_components::learning_ledger::verify_independent_roles;

pub(super) struct Inputs {
    pub source: Source,
    pub bytes: Vec<u8>,
    pub config: ParameterPreRegisteredSelectorConfigV1,
    pub evaluation: VerifiedParameterPreRegistrationEvaluationV1,
    pub facts: RegisteredArtifactCurrentFactsV3,
    pub head: ValidatedArtifactManifestV2,
    pub verifier: ArtifactSelectionVerifierV1,
    pub selector: TrustedLearningSignerV1,
    pub registry_id: StableId,
    pub expiry: u64,
}
fn read_evaluation(
    sources: &ParameterPreRegistrationEvaluationSourcesV1,
) -> HostResult<VerifiedParameterPreRegistrationEvaluationV1> {
    inspect_parameter_pre_registration_history_v1(
        &sources.configuration.path,
        digest(&sources.configuration.digest)?,
        &sources.report.path,
        digest(&sources.report.digest)?,
    )
}
impl Inputs {
    pub(super) fn read(source: Source, now: u64) -> HostResult<Self> {
        let bytes = source.read(64 * 1024)?;
        let config: ParameterPreRegisteredSelectorConfigV1 = serde_json::from_slice(&bytes)?;
        if config.schema != "hepta.cpu-neuron.parameter-pre-registration-selector-config.v1"
            || config.workload_uid == 0
            || config.selector.uid == config.workload_uid
            || config.selector.uid != 0
            || config.selector.gid != 0
            || config.authority_epoch == 0
            || config.frozen_at_ms == 0
            || config.frozen_at_ms > now
            || now >= config.expires_at_ms
            || config.expires_at_ms.saturating_sub(config.frozen_at_ms) > 86_400_000
        {
            return Err("bounded independent Root Selector pre-registration purpose".into());
        }
        let evaluation = read_evaluation(&config.evaluation)?;
        let plan = evaluation
            .material()
            .ok_or("actual E1 did not qualify a candidate material")?;
        let facts = inspect_registered_artifact_current_material_v3(
            &config.current_registration.path,
            digest(&config.current_registration.digest)?,
            plan,
            evaluation.subject(),
            now,
        )?;
        let enrolled = evaluation
            .trusted_selector(&id(&config.selector.id)?)
            .ok_or("actual original Root Selector roster")?
            .clone();
        if enrolled.principal.credential_chain_digest != digest(&config.selector.credential_digest)?
            || enrolled.verifying_key != public(&config.selector.public_key_hex)?
            || enrolled.principal.signing_key_digest != Digest32::of_bytes(&enrolled.verifying_key)
            || enrolled.principal.authority_epoch != config.authority_epoch
            || enrolled.revoked_at.is_some_and(|at| now >= at)
            || now >= enrolled.principal.expires_at
        {
            return Err("pre-registration S changed original enrolled credential/key/epoch".into());
        }
        enrolled.principal.validate(now)?;
        for actor in [
            evaluation.generator(),
            evaluation.observer(),
            evaluation.evaluator(),
        ] {
            verify_independent_roles(actor.principal(), &enrolled.principal, now)?;
            if actor.controller_id() == &enrolled.controller_id {
                return Err("pre-registration S shares an actual G/O/E controller".into());
            }
        }
        if config.selector.uid == evaluation.evaluator_uid()
            || config.selector.gid == evaluation.evaluator_gid()
        {
            return Err("pre-registration S shares actual E process identity".into());
        }
        let head = inspect_registered_parameter_head_material_v1(
            &config.head_manifest,
            digest(&config.head_admission_digest)?,
            &facts,
            plan,
            &id(&config.head_artifact_id)?,
            now,
        )?;
        let old_model = &facts.manifests()[0].manifest;
        let mut expected_head_predecessor = evaluation.baseline_head_artifact_id().clone();
        let expected_predecessor = match (evaluation.purpose(), &config.candidate_predecessor) {
            (ParameterPreRegistrationPurposeV1::Candidate, None) => {
                evaluation.baseline_artifact_id().clone()
            }
            (ParameterPreRegistrationPurposeV1::ExactRollback, Some(predecessor)) => {
                let previous = read_evaluation(&predecessor.evaluation)?;
                if previous.purpose() != ParameterPreRegistrationPurposeV1::Candidate
                    || previous.round() != evaluation.round()
                    || previous.candidate_id() != evaluation.candidate_id()
                    || previous.subject() != evaluation.subject()
                    || previous.baseline_artifact_id() != evaluation.baseline_artifact_id()
                    || previous.baseline_registry_head() != evaluation.baseline_registry_head()
                {
                    return Err("rollback predecessor is not the exact same original admitted candidate/E1 round".into());
                }
                let previous_plan = previous
                    .material()
                    .ok_or("rollback predecessor E1 rejected")?;
                if previous_plan.runtime.generation.next()? != plan.runtime.generation {
                    return Err("exact candidate-to-rollback model generation".into());
                }
                let previous_facts = inspect_registered_artifact_current_material_v3(
                    &predecessor.registration.path,
                    digest(&predecessor.registration.digest)?,
                    previous_plan,
                    previous.subject(),
                    now,
                )?;
                let previous_head = inspect_registered_parameter_head_material_v1(
                    &predecessor.head_manifest,
                    digest(&predecessor.head_admission_digest)?,
                    &previous_facts,
                    previous_plan,
                    &id(&predecessor.head_artifact_id)?,
                    now,
                )?;
                expected_head_predecessor = previous_head.manifest.artifact_id;
                previous.revalidate_after_registration()?;
                previous_facts.revalidate_current(now)?;
                previous_facts.manifests()[0].manifest.artifact_id.clone()
            }
            _ => return Err("candidate/rollback exact predecessor purpose".into()),
        };
        if old_model.predecessor_ids != vec![expected_predecessor] {
            return Err("new full model manifest has a different original predecessor".into());
        }
        if head.manifest.predecessor_ids != vec![expected_head_predecessor] {
            return Err(
                "new native-head manifest has a different original head predecessor".into(),
            );
        }
        for full in facts.manifests().iter().chain(std::iter::once(&head)) {
            if !full
                .manifest
                .lineage_digests
                .contains(&evaluation.evaluation_publication_digest())
                || !full
                    .manifest
                    .lineage_digests
                    .contains(&evaluation.authentication_digest())
                || evaluation
                    .source_dataset_digests()
                    .iter()
                    .any(|cut| !full.manifest.source_dataset_digests.contains(cut))
            {
                return Err("registered full manifest lacks actual E1 whole signed publication/data lineage".into());
            }
        }
        let owner_trust = decode_artifact_public_trust_v1(
            &config
                .artifact_public_trust
                .read(MAX_ARTIFACT_PUBLIC_TRUST_BYTES_V1 as u64)?,
        )?;
        let registry_id = owner_trust.registry_id.clone();
        let verifier = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: registry_id.clone(),
                withdrawal_scope_digest: owner_trust.withdrawal_scope_digest,
                minimum_authority_epoch: config.authority_epoch,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id(&config.selector.id)?,
                    verifying_key: enrolled.verifying_key,
                    minimum_authority_epoch: config.authority_epoch,
                    maximum_authority_epoch: config.authority_epoch,
                    valid_from: config.frozen_at_ms,
                    expires_at: config.expires_at_ms,
                    revoked_at: enrolled.revoked_at,
                }],
            },
            &owner_trust,
        )?;
        if ArtifactOwnerVerifierV1::new(owner_trust)?.trust_digest()
            != facts.current_view().trust_digest()
        {
            return Err(
                "pre-registration S public owner trust differs from actual Root CURRENT".into(),
            );
        }
        let expiry = config
            .expires_at_ms
            .min(evaluation.expires_at())
            .min(facts.expires_at())
            .min(enrolled.principal.expires_at)
            .min(enrolled.revoked_at.unwrap_or(u64::MAX))
            .min(evaluation.round().deadline_ms);
        if now >= expiry {
            return Err("actual pre-registration S authority expired".into());
        }
        Ok(Self {
            source,
            bytes,
            config,
            evaluation,
            facts,
            head,
            verifier,
            selector: enrolled,
            registry_id,
            expiry,
        })
    }
    pub(super) fn body(&self, issued_at_ms: u64) -> HostResult<Body> {
        let plan = self.evaluation.material().ok_or("qualified E1 material")?;
        let view = self.facts.current_view();
        Ok(Body {
            schema: "hepta.cpu-neuron.parameter-pre-registered-selections.v1".into(),
            configuration_digest: self.source.digest.clone(),
            evaluation_digest: self.evaluation.authentication_digest().to_string(),
            original_round: self.evaluation.round().clone(),
            purpose: self.evaluation.purpose(),
            candidate_id: self.evaluation.candidate_id().to_string(),
            subject: self.evaluation.subject().to_string(),
            material_digest: Digest32::of_bytes(&material_bytes(plan)?).to_string(),
            model_generation: plan.runtime.generation.get(),
            execution_profile_digest: plan.runtime.execution_profile_digest_v1()?.to_string(),
            native_digest: plan.native.digest()?.to_string(),
            body_digest: plan.body.semantic_digest()?.to_string(),
            original_baseline_artifact: self.evaluation.baseline_artifact_id().to_string(),
            original_baseline_head: self.evaluation.baseline_registry_head().to_string(),
            original_baseline_operation: self
                .evaluation
                .baseline_publication_operation()
                .to_string(),
            artifact_ids: self
                .facts
                .manifests()
                .each_ref()
                .map(|m| m.manifest.artifact_id.to_string()),
            manifest_digests: self
                .facts
                .manifests()
                .each_ref()
                .map(|m| m.manifest_digest.to_string()),
            payload_digests: self
                .facts
                .manifests()
                .each_ref()
                .map(|m| m.manifest.bytes_digest.to_string()),
            current_registry_head: view.receipt().head_digest.to_string(),
            current_witness: view.witness_digest().to_string(),
            current_trust: view.trust_digest().to_string(),
            current_withdrawal_scope: self
                .facts
                .current_head()
                .withdrawal_scope_digest
                .to_string(),
            publication_operation: self.facts.acknowledgement().operation_id.to_string(),
            head_artifact_id: self.head.manifest.artifact_id.to_string(),
            head_manifest_digest: self.head.manifest_digest.to_string(),
            head_payload_digest: self.head.manifest.bytes_digest.to_string(),
            selector_id: self.config.selector.id.clone(),
            selector_controller: self.selector.controller_id.to_string(),
            selector_program_digest: self.config.selector_program.digest.clone(),
            selector_uid: self.config.selector.uid,
            selector_gid: self.config.selector.gid,
            authority_epoch: self.config.authority_epoch,
            issued_at_ms,
            expires_at_ms: self.expiry,
        })
    }
    pub(super) fn selection(
        &self,
        body: &Body,
        index: usize,
        signature: [u8; 64],
    ) -> HostResult<SignedArtifactSelectionV1> {
        let full = if index == 3 {
            &self.head
        } else {
            &self.facts.manifests()[index]
        };
        let view = self.facts.current_view();
        let manifest = view
            .eligible_manifest(&full.manifest.artifact_id)
            .ok_or("actual pre-registered artifact withdrawn")?;
        Ok(SignedArtifactSelectionV1 {
            selection_id: id(&format!(
                "parameter.selected:{index}:{}",
                Digest32::of_bytes(&body.signing_bytes()?)
            ))?,
            artifact_id: manifest.artifact_id.clone(),
            registry_id: self.registry_id.clone(),
            withdrawal_scope_digest: digest(&body.current_withdrawal_scope)?,
            registry_head_digest: view.receipt().head_digest,
            current_witness_digest: view.witness_digest(),
            current_trust_digest: view.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: manifest.predecessor_id.clone(),
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id(&self.config.selector.id)?,
            selector_credential_digest: digest(&self.config.selector.credential_digest)?,
            signing_key_digest: self.selector.principal.signing_key_digest,
            authority_epoch: self.config.authority_epoch,
            issued_at: body.issued_at_ms,
            expires_at: body.expires_at_ms,
            signature,
        })
    }
    pub(super) fn revalidate(&self, now: u64) -> HostResult<()> {
        self.evaluation.revalidate_after_registration()?;
        self.facts.revalidate_current(now)?;
        let current_head = inspect_registered_parameter_head_material_v1(
            &self.config.head_manifest,
            digest(&self.config.head_admission_digest)?,
            &self.facts,
            self.evaluation.material().ok_or("qualified E1 material")?,
            &id(&self.config.head_artifact_id)?,
            now,
        )?;
        if current_head != self.head {
            return Err("S actual registered parameter head changed".into());
        }
        if self.source.read(64 * 1024)? != self.bytes {
            return Err("pre-registration S Root configuration changed".into());
        }
        verify_registered_operational_program_v3(
            &self.config.selector_program.path,
            digest(&self.config.selector_program.digest)?,
        )?;
        if now >= self.expiry {
            return Err("actual pre-registration S authority expired".into());
        }
        Ok(())
    }
}

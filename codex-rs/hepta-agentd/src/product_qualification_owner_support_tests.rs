//! Synthetic observations and credentials, with the actual original Evaluator,
//! exclusive source files and independent publication witness. No real B-data,
//! ordinary stage-owner route, external custody or new-process claim is made.

use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;
use crate::OriginalCellEvaluationExecutionOwnerV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use crate::OriginalProductQualificationErrorV1;
use crate::OriginalProductQualificationOwnerV1;
use crate::OriginalProductQualificationSourceV1;

pub(super) fn clock() -> u64 {
    checked(SystemTime::now().duration_since(UNIX_EPOCH)).as_secs()
}

/// Reopening cannot silently create an absent original file.
pub(super) fn existing(path: &Path) -> File {
    checked(OpenOptions::new().read(true).write(true).open(path))
}

pub(super) fn witness(file: File) -> FileAnchorWitnessStore {
    checked(FileAnchorWitnessStore::open(
        file,
        JournalScope {
            scope_digest: digest("qualification-test-scope"),
            objective_digest: digest("objective"),
        },
        checked(Generation::new(1)),
        /*max_records*/ 64,
    ))
}

pub(super) struct OriginalQualificationFixture {
    pub runner: CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    pub cell_plan: CellEvaluationPlanV1,
    pub candidate: Journal,
    pub fixed: Journal,
    pub executions: LockedFileProductEvaluationExecutionStoreV1,
    pub plan: ProductFrozenEvaluationPlanV1,
    pub candidate_plan: TemporalEvaluationPlan,
    pub baseline_plan: TemporalEvaluationPlan,
    pub context: ProductQualificationContextV1,
    pub evidence: SignedEvaluationEvidenceV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub trust: LearningEvidenceTrustV1,
    pub directory: tempfile::TempDir,
    pub provider_calls: (u32, u32),
}

impl OriginalQualificationFixture {
    pub(super) fn new() -> Self {
        let mut original = Fixture::new(Costs::Complete);
        let plan = checked(original.freeze());
        let time = clock();
        let principals = [
            (
                "qualification-generator",
                41,
                LearningEvidenceRoleV1::Generator,
            ),
            (
                "qualification-evaluator",
                42,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ]
        .map(|(name, byte, role)| {
            let key = SigningKey::from_bytes(&[byte; 32]);
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(name),
                    credential_chain_digest: digest(&format!("{name}-credential")),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    scope_digest: digest("qualification-test-scope"),
                    authority_epoch: 7,
                    authenticated_at: time - 10,
                    expires_at: time + 900,
                },
                controller_id: id(name),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![role],
                revoked_at: None,
            }
        });
        let trust = LearningEvidenceTrustV1 {
            scope_digest: digest("qualification-test-scope"),
            objective_digest: plan.product_plan().frozen_plan.objective_digest,
            authority_epoch: 7,
            signers: principals.to_vec(),
        };
        let verifier = checked(LearningEvidenceVerifierV1::new(trust.clone()));
        let context = ProductQualificationContextV1 {
            generator: principals[0].principal.clone(),
            evaluator: principals[1].principal.clone(),
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
        };
        let config = OriginalCellEvaluationSigningConfigV1 {
            plan: plan.product_plan().clone(),
            execution_namespace: digest("binding"),
            signer: principals[1].clone(),
            verifier: verifier.clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        let path = original.directory.path();
        let mut signer = checked(OriginalCellEvaluationExecutionOwnerV1::create(
            file(&path.join("original-evaluator")),
            witness(file(&path.join("original-evaluator-witness"))),
            config.clone(),
            SigningKey::from_bytes(&[42; 32]),
        ));
        let mut executions = checked(LockedFileProductEvaluationExecutionStoreV1::create(
            file(&path.join("executions")),
            digest("execution-file"),
        ));
        checked(original.runner.evaluate_or_readback(
            &plan,
            CellEvaluationJournalsV1 {
                candidate: &original.candidate,
                fixed_expert: &original.fixed,
            },
            &ProductEvaluationExecutionRequestV1 {
                plan: plan.product_plan(),
                candidate_plan: &original.candidate_temporal,
                baseline_plan: &original.baseline_temporal,
                evaluator: &config.signer.principal,
                verifier: &verifier,
                clock: &|| Ok(clock()),
            },
            &mut original.provider,
            &mut executions,
            &mut signer,
        ));
        // Publication and recovery have no execution signer or provider object.
        drop(signer);
        let mut value = Self {
            runner: original.runner,
            cell_plan: plan.clone(),
            candidate: original.candidate,
            fixed: original.fixed,
            executions,
            plan: plan.product_plan().clone(),
            candidate_plan: original.candidate_temporal,
            baseline_plan: original.baseline_temporal,
            context,
            evidence: SignedEvaluationEvidenceV1 {
                generator_plan: placeholder(&principals[0].principal, &verifier),
                evaluator_bundle: placeholder(&principals[1].principal, &verifier),
            },
            verifier,
            trust,
            directory: original.directory,
            provider_calls: (original.provider.calls, original.provider.releases),
        };
        value.sign_context();
        value
    }

    pub(super) fn material(&mut self) -> ProductEvaluationExecutionMaterialV1 {
        checked(self.runner.product.readback_temporal_comparison_material(
            &ProductEvaluationExecutionRequestV1 {
                plan: &self.plan,
                candidate_plan: &self.candidate_plan,
                baseline_plan: &self.baseline_plan,
                evaluator: &self.context.evaluator,
                verifier: &self.verifier,
                clock: &|| Ok(clock()),
            },
            &mut self.executions,
        ))
    }

    pub(super) fn sign_context(&mut self) {
        let material = self.material();
        let bundle = checked(
            self.runner
                .product
                .qualification_bundle(material.execution(), &self.context),
        );
        let time = clock();
        let sign = |principal: &AuthenticatedPrincipalV1,
                    byte: u8,
                    role: LearningEvidenceRoleV1,
                    payload: &[u8]| {
            let mut value = placeholder(principal, &self.verifier);
            value.role = role;
            value.objective_digest = bundle.objective_digest;
            value.issued_at = time - 1;
            value.expires_at = time + 300;
            value.payload_digest = Digest32::of_bytes(payload);
            value.signature = SigningKey::from_bytes(&[byte; 32])
                .sign(&value.signing_bytes())
                .to_bytes();
            value
        };
        self.evidence = SignedEvaluationEvidenceV1 {
            generator_plan: sign(
                &self.context.generator,
                /*byte*/ 41,
                LearningEvidenceRoleV1::Generator,
                bundle.frozen_plan.plan_digest.as_array(),
            ),
            evaluator_bundle: sign(
                &self.context.evaluator,
                /*byte*/ 42,
                LearningEvidenceRoleV1::Evaluator,
                &checked(evaluation_signing_payload_v2(
                    &bundle,
                    &self.plan.metric_roles,
                )),
            ),
        };
    }

    pub(super) fn publish<W: AnchorWitnessStore>(
        &mut self,
        owner: &mut OriginalProductQualificationOwnerV1<W>,
    ) -> Result<ProductQualificationReceiptV1, OriginalProductQualificationErrorV1> {
        owner.publish(
            &mut self.runner.product,
            &mut self.executions,
            &OriginalProductQualificationSourceV1 {
                plan: &self.plan,
                candidate_plan: &self.candidate_plan,
                baseline_plan: &self.baseline_plan,
                evaluator: &self.context.evaluator,
                verifier: &self.verifier,
            },
            &self.context,
            &self.evidence,
        )
    }

    pub(super) fn readback<W: AnchorWitnessStore>(
        &mut self,
        owner: &mut OriginalProductQualificationOwnerV1<W>,
    ) -> Result<ProductQualificationReceiptV1, OriginalProductQualificationErrorV1> {
        owner.readback(
            &mut self.runner.product,
            &mut self.executions,
            &OriginalProductQualificationSourceV1 {
                plan: &self.plan,
                candidate_plan: &self.candidate_plan,
                baseline_plan: &self.baseline_plan,
                evaluator: &self.trust.signers[1].principal,
                verifier: &self.verifier,
            },
        )
    }

    pub(super) fn reopen_sources(self) -> Self {
        self.snapshot_source_bytes().0
    }

    /// Release both original exclusive source owners before opening their files
    /// by path. Reacquire only those same files, namespace, fence and anchors.
    pub(super) fn snapshot_source_bytes(self) -> (Self, Vec<Vec<u8>>) {
        let holdout_anchor = self.runner.product.holdout_anchor();
        let execution_anchor = self.executions.anchor();
        drop(self.runner);
        drop(self.executions);
        let bytes = [
            "holdout",
            "executions",
            "original-evaluator",
            "original-evaluator-witness",
        ]
        .into_iter()
        .map(|name| checked(std::fs::read(self.directory.path().join(name))))
        .collect();
        let holdout = checked(LockedFileFinalHoldoutCasStoreV1::recover(
            existing(&self.directory.path().join("holdout")),
            digest("binding"),
            Some(holdout_anchor),
        ));
        let runner = ProductEvaluationRunnerV1::new(checked(FencedFinalHoldoutOwnerV1::recover(
            holdout,
            digest("binding"),
            fence(),
        )));
        let executions = checked(LockedFileProductEvaluationExecutionStoreV1::recover(
            existing(&self.directory.path().join("executions")),
            digest("execution-file"),
            execution_anchor,
        ));
        (
            Self {
                runner: CellEvaluationRunnerV1::new(runner),
                executions,
                ..self
            },
            bytes,
        )
    }
}

/// Initialize once, then relinquish both publication locks before the baseline
/// path reads. Tests subsequently recover this exact owner rather than create.
pub(super) fn initialize_publication(path: &Path) -> [Vec<u8>; 2] {
    let owner = checked(OriginalProductQualificationOwnerV1::create(
        file(&path.join("publication")),
        witness(file(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ));
    drop(owner);
    publication_bytes(path)
}

/// Caller must have relinquished the actual publication and witness owner.
pub(super) fn publication_bytes(path: &Path) -> [Vec<u8>; 2] {
    ["publication", "publication-witness"].map(|name| checked(std::fs::read(path.join(name))))
}

pub(super) fn recover_publication(
    path: &Path,
) -> OriginalProductQualificationOwnerV1<FileAnchorWitnessStore> {
    checked(OriginalProductQualificationOwnerV1::recover(
        existing(&path.join("publication")),
        witness(existing(&path.join("publication-witness"))),
        digest("publication-namespace"),
    ))
}

pub(super) fn snapshot_publication(
    owner: OriginalProductQualificationOwnerV1<FileAnchorWitnessStore>,
    path: &Path,
) -> (
    OriginalProductQualificationOwnerV1<FileAnchorWitnessStore>,
    [Vec<u8>; 2],
) {
    drop(owner);
    let bytes = publication_bytes(path);
    (recover_publication(path), bytes)
}

fn placeholder(
    principal: &AuthenticatedPrincipalV1,
    verifier: &LearningEvidenceVerifierV1,
) -> SignedLearningEvidenceV1 {
    SignedLearningEvidenceV1 {
        evidence_id: principal.principal_id.clone(),
        principal_id: principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: Digest32::ZERO,
        authority_epoch: principal.authority_epoch,
        issued_at: 0,
        expires_at: 0,
        payload_digest: Digest32::ZERO,
        signature: [0; 64],
    }
}

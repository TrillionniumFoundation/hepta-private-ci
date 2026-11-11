//! Real evaluator execution and original signature/holdout files, over explicit
//! synthetic test observations and credentials. These tests establish durability
//! and source binding, not ordinary experiment results or production custody.

use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Generation;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::LearningOriginalOwnerErrorV1;
use crate::OriginalCellEvaluationExecutionOwnerV1;
use crate::OriginalCellEvaluationSigningConfigV1;

fn clock() -> u64 {
    checked(SystemTime::now().duration_since(UNIX_EPOCH)).as_secs()
}

fn signing_config(plan: &CellEvaluationPlanV1) -> OriginalCellEvaluationSigningConfigV1 {
    let key = SigningKey::from_bytes(&[78; 32]);
    let signer = TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id("original-evaluator"),
            credential_chain_digest: digest("evaluator-test-credential"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("evaluator-test-scope"),
            authority_epoch: 7,
            authenticated_at: clock() - 1,
            expires_at: clock() + 900,
        },
        controller_id: id("evaluator-test-controller"),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![LearningEvidenceRoleV1::Evaluator],
        revoked_at: None,
    };
    let verifier = checked(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: signer.principal.scope_digest,
        objective_digest: plan.product_plan().frozen_plan.objective_digest,
        authority_epoch: 7,
        signers: vec![signer.clone()],
    }));
    OriginalCellEvaluationSigningConfigV1 {
        plan: plan.product_plan().clone(),
        execution_namespace: digest("binding"),
        signer,
        verifier,
        maximum_signature_lifetime_seconds: 300,
    }
}

fn witness(path: &Path) -> FileAnchorWitnessStore {
    checked(FileAnchorWitnessStore::open(
        file(&path.join("original-evaluator-witness")),
        JournalScope {
            scope_digest: digest("evaluator-test-scope"),
            objective_digest: digest("objective"),
        },
        checked(Generation::new(1)),
        /*max_records*/ 64,
    ))
}

fn execute<W: AnchorWitnessStore>(
    fixture: &mut Fixture,
    plan: &CellEvaluationPlanV1,
    config: &OriginalCellEvaluationSigningConfigV1,
    executions: &mut LockedFileProductEvaluationExecutionStoreV1,
    signer: &mut OriginalCellEvaluationExecutionOwnerV1<W>,
) -> Result<CellEvaluationReceiptV1, CellEvaluationErrorV1> {
    fixture.runner.evaluate_or_readback(
        plan,
        CellEvaluationJournalsV1 {
            candidate: &fixture.candidate,
            fixed_expert: &fixture.fixed,
        },
        &ProductEvaluationExecutionRequestV1 {
            plan: plan.product_plan(),
            candidate_plan: &fixture.candidate_temporal,
            baseline_plan: &fixture.baseline_temporal,
            evaluator: &config.signer.principal,
            verifier: &config.verifier,
            clock: &|| Ok(clock()),
        },
        &mut fixture.provider,
        executions,
        signer,
    )
}

#[test]
fn original_evaluator_signs_actual_execution_once_and_reopens_exact_bytes() {
    let mut fixture = Fixture::new(Costs::Complete);
    let plan = checked(fixture.freeze());
    let config = signing_config(&plan);
    let path = fixture.directory.path().to_path_buf();
    let mut signer = checked(OriginalCellEvaluationExecutionOwnerV1::create(
        file(&path.join("original-evaluator")),
        witness(&path),
        config.clone(),
        SigningKey::from_bytes(&[78; 32]),
    ));
    let empty = checked(std::fs::read(path.join("original-evaluator")));
    let mut executions = checked(LockedFileProductEvaluationExecutionStoreV1::create(
        file(&path.join("executions")),
        digest("execution-file"),
    ));
    let first = checked(execute(
        &mut fixture,
        &plan,
        &config,
        &mut executions,
        &mut signer,
    ));
    let original = checked(signer.readback());
    assert_eq!(
        checked(config.verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &original.1,
            &original.0,
            clock()
        ))
        .principal(),
        &config.signer.principal,
    );
    let bytes = checked(std::fs::read(path.join("original-evaluator")));
    assert_ne!(bytes, empty);
    let original_calls = (fixture.provider.calls, fixture.provider.releases);
    let execution_anchor = executions.anchor();
    drop(signer);
    drop(executions);
    let mut signer = checked(OriginalCellEvaluationExecutionOwnerV1::recover(
        file(&path.join("original-evaluator")),
        witness(&path),
        config.clone(),
        SigningKey::from_bytes(&[78; 32]),
    ));
    let mut executions = checked(LockedFileProductEvaluationExecutionStoreV1::recover(
        file(&path.join("executions")),
        digest("execution-file"),
        execution_anchor,
    ));
    assert_eq!(checked(signer.readback()), original);
    assert_eq!(
        checked(execute(
            &mut fixture,
            &plan,
            &config,
            &mut executions,
            &mut signer
        )),
        first
    );
    assert_eq!(
        (fixture.provider.calls, fixture.provider.releases),
        original_calls
    );
    assert_eq!(
        checked(std::fs::read(path.join("original-evaluator"))),
        bytes
    );
    drop(signer);
    checked(std::fs::write(path.join("original-evaluator"), empty));
    assert!(
        OriginalCellEvaluationExecutionOwnerV1::recover(
            file(&path.join("original-evaluator")),
            witness(&path),
            config,
            SigningKey::from_bytes(&[78; 32]),
        )
        .is_err()
    );
}

#[derive(Clone, Copy)]
enum Fault {
    BeforeWrite,
    AfterWrite,
}

struct LostAckWitness {
    inner: FileAnchorWitnessStore,
    sequence: u64,
    fault: Fault,
}
impl AnchorWitnessStore for LostAckWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }
    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        if next.sequence == self.sequence {
            if matches!(self.fault, Fault::AfterWrite) {
                self.inner.compare_and_swap(expected, next)?;
            }
            return Err(WitnessStoreError::Indeterminate);
        }
        self.inner.compare_and_swap(expected, next)
    }
}

#[test]
fn original_evaluator_uncertain_claim_never_resigns_and_complete_ack_reads_original() {
    for sequence in [2, 3] {
        for fault in [Fault::BeforeWrite, Fault::AfterWrite] {
            let mut fixture = Fixture::new(Costs::Complete);
            let plan = checked(fixture.freeze());
            let config = signing_config(&plan);
            let path = fixture.directory.path().to_path_buf();
            let mut signer = checked(OriginalCellEvaluationExecutionOwnerV1::create(
                file(&path.join("original-evaluator")),
                LostAckWitness {
                    inner: witness(&path),
                    sequence,
                    fault,
                },
                config.clone(),
                SigningKey::from_bytes(&[78; 32]),
            ));
            let mut executions = checked(LockedFileProductEvaluationExecutionStoreV1::create(
                file(&path.join("executions")),
                digest("execution-file"),
            ));
            assert!(execute(&mut fixture, &plan, &config, &mut executions, &mut signer).is_err());
            assert!(matches!(
                signer.readback(),
                Err(LearningOriginalOwnerErrorV1::CommitUncertain)
            ));
            drop(signer);
            let mut reopened = checked(OriginalCellEvaluationExecutionOwnerV1::recover(
                file(&path.join("original-evaluator")),
                witness(&path),
                config.clone(),
                SigningKey::from_bytes(&[78; 32]),
            ));
            if sequence == 2 {
                assert!(matches!(
                    reopened.readback(),
                    Err(LearningOriginalOwnerErrorV1::Pending)
                ));
            } else {
                let original = checked(reopened.readback());
                assert_eq!(checked(reopened.readback()), original);
            }
            let before = checked(std::fs::read(path.join("original-evaluator")));
            let calls = (fixture.provider.calls, fixture.provider.releases);
            assert!(matches!(
                execute(&mut fixture, &plan, &config, &mut executions, &mut reopened),
                Err(CellEvaluationErrorV1::Execution(
                    ProductEvaluationExecutionErrorV1::Pending
                )),
            ));
            assert_eq!(
                checked(std::fs::read(path.join("original-evaluator"))),
                before
            );
            assert_eq!((fixture.provider.calls, fixture.provider.releases), calls);
        }
    }
}

#[test]
fn original_evaluator_rejects_substituted_key_controller_plan_and_namespace() {
    let fixture = Fixture::new(Costs::Complete);
    let plan = checked(fixture.freeze());
    let config = signing_config(&plan);
    let path = fixture.directory.path();
    for changed_field in 0..3 {
        let mut changed = config.clone();
        let key = match changed_field {
            0 => SigningKey::from_bytes(&[79; 32]),
            1 => {
                changed.signer.controller_id = id("different-controller");
                SigningKey::from_bytes(&[78; 32])
            }
            2 => {
                changed.plan.frozen_plan.objective_digest = digest("different-objective");
                SigningKey::from_bytes(&[78; 32])
            }
            _ => unreachable!(),
        };
        assert!(
            OriginalCellEvaluationExecutionOwnerV1::create(
                file(&path.join("original-evaluator")),
                witness(path),
                changed,
                key,
            )
            .is_err()
        );
        assert_eq!(
            checked(file(&path.join("original-evaluator")).metadata()).len(),
            0
        );
    }
    let owner = checked(OriginalCellEvaluationExecutionOwnerV1::create(
        file(&path.join("original-evaluator")),
        witness(path),
        config.clone(),
        SigningKey::from_bytes(&[78; 32]),
    ));
    drop(owner);
    let mut changed = config;
    changed.execution_namespace = digest("different-original-namespace");
    assert!(
        OriginalCellEvaluationExecutionOwnerV1::recover(
            file(&path.join("original-evaluator")),
            witness(path),
            changed,
            SigningKey::from_bytes(&[78; 32]),
        )
        .is_err()
    );
}

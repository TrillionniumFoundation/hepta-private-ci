//! Local deterministic fixture keys are not external authority.
use super::*;
use crate::FinalHoldoutCasStoreError;
use crate::LockedFileFinalHoldoutCasStoreV1;
use crate::paired_data::tests::fixture;
use crate::paired_owner_tests::MemoryCas;
use crate::paired_owner_tests::d;
use crate::paired_owner_tests::fence;
use crate::paired_owner_tests::id;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::cell::Cell;
use std::rc::Rc;

fn trust(shared_controller: bool) -> LearningEvidenceVerifierV1 {
    let roles = [
        LearningEvidenceRoleV1::Generator,
        LearningEvidenceRoleV1::Observer,
        LearningEvidenceRoleV1::Evaluator,
    ];
    let signers = roles
        .iter()
        .enumerate()
        .map(|(i, role)| {
            let key = SigningKey::from_bytes(&[i as u8 + 1; 32])
                .verifying_key()
                .to_bytes();
            let name = format!("fixture-role-{i}");
            TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(&name),
                    credential_chain_digest: d(&name),
                    signing_key_digest: Digest32::of_bytes(&key),
                    scope_digest: d("local-engineering-fixture"),
                    authority_epoch: 1,
                    authenticated_at: 10,
                    expires_at: 100,
                },
                controller_id: id(if shared_controller {
                    "shared-controller"
                } else {
                    &name
                }),
                verifying_key: key,
                roles: vec![*role],
                revoked_at: None,
            }
        })
        .collect();
    LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: d("local-engineering-fixture"),
        objective_digest: d("objective"),
        authority_epoch: 1,
        signers,
    })
    .expect("local fixture trust")
}
fn sign(
    verifier: &LearningEvidenceVerifierV1,
    index: u8,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let roles = [
        LearningEvidenceRoleV1::Generator,
        LearningEvidenceRoleV1::Observer,
        LearningEvidenceRoleV1::Evaluator,
    ];
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence-{index}")),
        principal_id: id(&format!("fixture-role-{index}")),
        role: roles[index as usize],
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: 1,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[index + 1; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}
struct Provider {
    plan: FrozenPairedPlanV1,
    data: PairedDataV1,
    evidence: SignedLearningEvidenceV1,
    releases: Rc<Cell<u32>>,
    inspect_cas: Option<MemoryCas>,
}
impl PairedFinalHoldoutProviderV1 for Provider {
    fn identities(&mut self) -> Result<(Digest32, Digest32), ProductProviderErrorV1> {
        Ok((
            self.plan.spec().holdout_digest,
            self.plan.spec().outcome_bundle_digest,
        ))
    }
    fn release_after_consumption(
        &mut self,
        receipt: &PairedHoldoutJournalReceiptV1,
    ) -> Result<(PairedDataV1, SignedLearningEvidenceV1), ProductProviderErrorV1> {
        receipt
            .validate(&self.plan)
            .map_err(|_| ProductProviderErrorV1::Rejected)?;
        if let Some(store) = &self.inspect_cas {
            assert!(
                store
                    .state
                    .borrow()
                    .as_ref()
                    .expect("CAS committed before release")
                    .journal
                    .records
                    .iter()
                    .any(|r| r.record_digest == receipt.record_digest)
            );
        }
        self.releases.set(self.releases.get() + 1);
        Ok((self.data.clone(), self.evidence.clone()))
    }
}
#[derive(Default)]
struct MemorySink {
    count: usize,
}
impl PairedEvaluationEvidenceSinkV1 for MemorySink {
    fn persist_paired(
        &mut self,
        decision: &SignedPairedEvaluationV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        self.count += 1;
        Ok(decision.evaluation.execution_digest)
    }
}
fn provider(verifier: &LearningEvidenceVerifierV1, store: Option<MemoryCas>) -> Provider {
    let (plan, data) = fixture();
    let evidence = sign(
        verifier,
        1,
        &paired_observation_signing_payload_v1(&plan).expect("payload"),
    );
    Provider {
        plan,
        data,
        evidence,
        releases: Rc::new(Cell::new(0)),
        inspect_cas: store,
    }
}

fn execute(
    owner: &mut FencedFinalHoldoutOwnerV1<MemoryCas>,
    plan: &FrozenPairedPlanV1,
    provider: &mut Provider,
    verifier: &LearningEvidenceVerifierV1,
    sink: &mut MemorySink,
    allow_evaluator: bool,
) -> Result<PublishedPairedEvaluationV1, PairedEvaluationError> {
    let generator = sign(
        verifier,
        0,
        &paired_plan_signing_payload_v1(plan).expect("payload"),
    );
    let manifest = provider.data.manifest.clone();
    evaluate_paired_full_information_v1(
        owner,
        plan,
        &manifest,
        provider,
        &generator,
        verifier,
        |r| {
            assert!(
                allow_evaluator,
                "invalid/unconsumed evidence never reaches evaluator"
            );
            Ok(sign(
                verifier,
                2,
                &paired_evaluation_signing_payload_v1(r).expect("derived"),
            ))
        },
        sink,
        50,
    )
}

#[test]
fn cas_or_evidence_errors_never_publish_and_release_requires_a_successful_cas() {
    for mode in 0..5 {
        let verifier = trust(mode == 4);
        let store = MemoryCas::default();
        let mut owner =
            FencedFinalHoldoutOwnerV1::initialize(store.clone(), d("binding"), fence(1))
                .expect("owner");
        *store.fault.borrow_mut() = match mode {
            0 => Some(FinalHoldoutCasStoreError::Rejected),
            1 => Some(FinalHoldoutCasStoreError::Conflict),
            2 => Some(FinalHoldoutCasStoreError::Indeterminate),
            _ => None,
        };
        let mut provider = provider(&verifier, Some(store));
        if mode == 3 {
            provider.data.observations[0].joint_loss = codex_hepta_types::FixedQ32::ZERO;
        }
        let plan = provider.plan.clone();
        let mut sink = MemorySink::default();
        let failure = execute(
            &mut owner,
            &plan,
            &mut provider,
            &verifier,
            &mut sink,
            false,
        )
        .expect_err("blocked");
        assert_eq!(
            matches!(failure, PairedEvaluationError::Holdout(_)),
            mode < 3
        );
        assert_eq!(provider.releases.get(), u32::from(mode >= 3));
        assert_eq!(owner.is_poisoned(), mode == 1 || mode == 2);
        assert_eq!(sink.count, 0);
    }
}

#[test]
fn mixed_owner_retries_same_frozen_data_but_rejects_changed_plan_before_release() {
    let verifier = trust(false);
    let store = MemoryCas::default();
    let mut owner = FencedFinalHoldoutOwnerV1::initialize(store.clone(), d("binding"), fence(1))
        .expect("owner");
    let mut provider = provider(&verifier, Some(store));
    let plan = provider.plan.clone();
    let mut sink = MemorySink::default();
    let mut digests = Vec::new();
    for _ in 0..2 {
        let done =
            execute(&mut owner, &plan, &mut provider, &verifier, &mut sink, true).expect("publish");
        assert!(!done.decision.evaluation.grants_qualification_or_promotion());
        assert!(!done.decision.evaluation.authority.grants_any());
        digests.push(done.decision.evaluation.execution_digest);
    }
    assert_eq!(digests[0], digests[1]);
    assert_eq!(owner.anchor().record_count, 1);
    let mut changed = plan.spec().clone();
    changed.metric_digest = d("changed metric");
    let changed = crate::freeze_paired_plan_v1(changed).expect("different plan");
    assert!(
        execute(
            &mut owner,
            &changed,
            &mut provider,
            &verifier,
            &mut sink,
            false
        )
        .is_err()
    );
    assert_eq!(provider.releases.get(), 2);
}

#[test]
fn actual_locked_journal_and_durable_file_sink_receive_only_owner_derived_signed_evidence() {
    use std::fs::OpenOptions;
    use std::fs::{self};
    use std::io::Write;
    struct FileSink(std::path::PathBuf);
    impl PairedEvaluationEvidenceSinkV1 for FileSink {
        fn persist_paired(
            &mut self,
            decision: &SignedPairedEvaluationV1,
        ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
            let bytes = format!("{decision:?}").into_bytes();
            let mut file = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&self.0)
                .map_err(|_| ProductEvidenceSinkErrorV1::Rejected)?;
            file.write_all(&bytes)
                .and_then(|()| file.sync_all())
                .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
            Ok(Digest32::of_bytes(&bytes))
        }
    }
    let prefix =
        std::env::temp_dir().join(format!("hepta-paired-evaluation-{}", std::process::id()));
    let journal_path = prefix.with_extension("journal");
    let evidence_path = prefix.with_extension("evidence");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&journal_path)
        .expect("new journal");
    let store =
        LockedFileFinalHoldoutCasStoreV1::create(file, d("binding")).expect("actual locked store");
    let owner =
        FencedFinalHoldoutOwnerV1::initialize(store, d("binding"), fence(1)).expect("actual owner");
    let verifier = trust(false);
    let mut provider = provider(&verifier, None);
    let plan = provider.plan.clone();
    let manifest = provider.data.manifest.clone();
    let generator = sign(
        &verifier,
        0,
        &paired_plan_signing_payload_v1(&plan).expect("payload"),
    );
    let mut sink = FileSink(evidence_path.clone());
    let mut runner = crate::ProductEvaluationRunnerV1::new(owner);
    let done = runner
        .evaluate_paired_profile(
            &plan,
            &manifest,
            &mut provider,
            &generator,
            &verifier,
            |r| {
                Ok(sign(
                    &verifier,
                    2,
                    &paired_evaluation_signing_payload_v1(r).expect("derived"),
                ))
            },
            &mut sink,
            50,
        )
        .expect("published fixture");
    done.validate(&verifier, 50)
        .expect("receiver revalidates signed published receipt");
    let mut altered = done.clone();
    altered.publication_digest = d("changed publication");
    assert!(altered.validate(&verifier, 50).is_err());
    let mut altered = done.clone();
    altered.decision.evaluator_receipt.signature[0] ^= 1;
    assert!(altered.validate(&verifier, 50).is_err());
    assert_eq!(
        done.publication_digest,
        Digest32::of_bytes(&fs::read(&evidence_path).expect("actual persisted bytes"))
    );
    let anchor = runner.holdout_anchor();
    drop(runner);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&journal_path)
        .expect("reopen");
    let store = LockedFileFinalHoldoutCasStoreV1::recover(file, d("binding"), Some(anchor))
        .expect("journal recovery");
    let owner =
        FencedFinalHoldoutOwnerV1::recover(store, d("binding"), fence(2)).expect("fenced recovery");
    assert_eq!(owner.anchor().record_count, 1);
    drop(owner);
    fs::remove_file(journal_path).expect("cleanup journal");
    fs::remove_file(evidence_path).expect("cleanup evidence");
}

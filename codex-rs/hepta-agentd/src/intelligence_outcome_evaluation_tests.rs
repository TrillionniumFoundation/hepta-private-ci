//! Cross-owner regressions use an actually estimated, signed and published
//! multi-outcome receipt. No public struct is used to forge eligibility.
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::AnchoredProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1;
use codex_hepta_intelligence_eval::HoldoutWriterFenceV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
use codex_hepta_types::Generation;

use super::*;

#[path = "../../hepta-intelligence-eval/tests/selected_host_recovery_support/eligible_model.rs"]
mod model;
// This shared fixture's cold-process helpers are exercised by the evaluator's
// integration tests. This consumer test only needs its file-backed anchor.
#[allow(dead_code)]
#[path = "../../hepta-intelligence-eval/tests/selected_host_recovery_support/cold_trust.rs"]
mod host;
#[allow(dead_code)]
#[path = "../../hepta-intelligence-eval/tests/selected_host_recovery_support/cold_storage.rs"]
mod storage;

static NEXT_ROOT: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    root: PathBuf,
    receipt: ProductOutcomeQualificationReceiptV1,
    trust: ActivatedLearningTrustV1,
    owner: CurrentOwnerStateV1,
    binding: AgentdEvaluationBindingV1,
    use_attestation: SignedLearningEvidenceV1,
}

impl Fixture {
    fn new() -> Self {
        Self::with_trust(host::activate(), 85)
    }

    fn with_trust(trust: ActivatedLearningTrustV1, qualification_now: u64) -> Self {
        let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-agentd-outcome-use-{}-{ordinal}",
            std::process::id()
        ));
        fs::create_dir(&root).expect("test root");
        let namespace = host::digest("agentd-test-holdout-namespace");
        let store = LockedFileFinalHoldoutCasStoreV1::create(
            storage::create(&root.join("holdout.cas")),
            namespace,
        )
        .expect("holdout store");
        let holdout = FencedFinalHoldoutOwnerV1::initialize(
            store,
            namespace,
            HoldoutWriterFenceV1 {
                owner_id: host::id("agentd-test-owner"),
                generation: 1,
                lease_digest: host::digest("agentd-test-lease"),
            },
        )
        .expect("holdout owner");
        let mut runner = RecordedProductEvaluationRunnerV1::new(holdout);
        let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
            storage::create(&root.join("attempt.journal")),
            host::digest("agentd-test-attempt-binding"),
            storage::DiskAnchor::new(&root.join("anchor"), None),
        )
        .expect("anchored journal");
        let attempt_id = host::id("agentd-test-attempt");
        let (plan, mut provider, roles) = model::fixture();
        let evaluated = runner
            .evaluate_outcome_comparison(attempt_id.clone(), &plan, &mut provider, &mut journal)
            .expect("actual native multi-outcome evaluation");
        let context = host::context();
        let bundle = runner
            .outcome_qualification_bundle(&evaluated, &context)
            .expect("native bundle");
        let evidence = host::evidence(&bundle, &roles, None);
        let mut clock = host::clock(qualification_now);
        let receipt = runner
            .qualify_outcomes_and_persist_on_selected_host(
                &attempt_id,
                &evaluated,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &trust,
                &mut clock,
                &mut journal,
                root.join("artifacts"),
                root.join("publications"),
                host::digest("agentd-test-selected-host"),
            )
            .expect("signed durable qualification");
        assert_eq!(
            receipt.decision().decision.disposition,
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        );
        assert_eq!(receipt.objective_digest(), host::digest("objective"));
        assert_eq!(receipt.dataset_digest(), host::digest("dataset"));
        assert_eq!(receipt.snapshot_ids(), &[host::id("snapshot")]);
        assert!(!receipt.authority().grants_any());
        let owner = CurrentOwnerStateV1 {
            owner_id: host::id("learning.eval"),
            generation: Generation::new(7).expect("generation"),
            implementation_digest: host::digest("eval-code"),
            key_digest: receipt.evaluator().signing_key_digest,
            key_epoch: 1,
            authority_epoch: 9,
            revocation_frontier_digest: host::digest("current-revocation-frontier"),
        };
        let binding = AgentdEvaluationBindingV1 {
            run_id: host::id("actual-run"),
            objective_digest: host::digest("objective"),
            snapshot_digest: host::digest("actual-runtime-snapshot"),
            context_receipt_digest: host::digest("actual-context-receipt"),
            candidate_set_digest: host::digest("actual-candidate-set"),
            selected_candidate_id: host::id("candidate"),
        };
        let payload = binding
            .outcome_qualification_use_payload_v1(&receipt, &owner, &trust)
            .expect("exact-use signing payload");
        let use_attestation = host::sign(LearningEvidenceRoleV1::Evaluator, &payload, 82);
        drop((journal, runner));
        Self {
            root,
            receipt,
            trust,
            owner,
            binding,
            use_attestation,
        }
    }

    fn consume(
        &self,
        binding: &AgentdEvaluationBindingV1,
        owner: &CurrentOwnerStateV1,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<Digest32, AgentdIntelligenceEvaluationError> {
        binding.consume_outcome_qualification_v1(
            &self.receipt,
            &self.receipt.decision().decision.evaluation_id,
            self.receipt.execution_digest(),
            self.receipt.publication_digest(),
            owner,
            evidence,
            &self.trust,
            now,
        )
    }
}

#[test]
fn multi_outcome_consumer_rejects_expired_distribution_with_live_use_signature() {
    use codex_hepta_learning_ledger::LearningTrustDistributionV1;
    use codex_hepta_learning_ledger::LearningTrustRootV1;
    use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
    use codex_hepta_learning_ledger::activate_learning_trust;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: host::id("cold-root"),
        scope_digest: host::digest("cold-scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 300,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: host::id("cold-distribution"),
            generation: 1,
            effective_at: 10,
            trust: host::definition(/*revoked*/ false),
        },
        root_id: root.root_id.clone(),
        issued_at: 5,
        expires_at: 84,
        signature: [0; 64],
    };
    signed.signature = root_key
        .sign(&signed.signing_bytes().expect("distribution"))
        .to_bytes();
    let trust = activate_learning_trust(&root, signed, None, 83).expect("live distribution");
    let fixture = Fixture::with_trust(trust, 83);
    let payload = fixture
        .binding
        .outcome_qualification_use_payload_v1(&fixture.receipt, &fixture.owner, &fixture.trust)
        .expect("bound use");
    assert!(!fixture.trust.is_current_at(85));
    assert!(
        fixture
            .trust
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &fixture.use_attestation,
                &payload,
                85,
            )
            .is_ok(),
        "use signature must remain independently valid"
    );
    assert!(matches!(
        fixture.consume(
            &fixture.binding,
            &fixture.owner,
            &fixture.use_attestation,
            85,
        ),
        Err(AgentdIntelligenceEvaluationError::Binding)
    ));
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn multi_outcome_consumer_rejects_context_owner_and_signature_substitution() {
    let fixture = Fixture::new();
    let first = fixture
        .consume(
            &fixture.binding,
            &fixture.owner,
            &fixture.use_attestation,
            85,
        )
        .expect("exact bound use");
    assert!(!first.is_zero());
    assert_eq!(
        fixture
            .consume(
                &fixture.binding,
                &fixture.owner,
                &fixture.use_attestation,
                85,
            )
            .expect("same semantic use"),
        first
    );
    for field in 0..6 {
        let mut changed = fixture.binding.clone();
        match field {
            0 => changed.run_id = host::id("different-run"),
            1 => changed.objective_digest = host::digest("different-objective"),
            2 => changed.snapshot_digest = host::digest("different-runtime-snapshot"),
            3 => changed.context_receipt_digest = host::digest("different-context"),
            4 => changed.candidate_set_digest = host::digest("different-candidate-set"),
            _ => changed.selected_candidate_id = host::id("different-candidate"),
        }
        assert!(
            fixture
                .consume(&changed, &fixture.owner, &fixture.use_attestation, 85)
                .is_err(),
            "binding field {field} must not be silently rehashed into a valid use"
        );
    }
    for field in 0..7 {
        let mut changed = fixture.owner.clone();
        match field {
            0 => changed.owner_id = host::id("other-owner"),
            1 => changed.generation = Generation::new(8).expect("generation"),
            2 => changed.implementation_digest = host::digest("other-code"),
            3 => changed.key_digest = host::digest("other-key"),
            4 => changed.key_epoch = 2,
            5 => changed.authority_epoch = 10,
            _ => changed.revocation_frontier_digest = host::digest("other-frontier"),
        }
        assert!(
            fixture
                .consume(&fixture.binding, &changed, &fixture.use_attestation, 85,)
                .is_err(),
            "owner field {field} requires a freshly authenticated use"
        );
    }
    assert!(
        fixture
            .consume(
                &fixture.binding,
                &fixture.owner,
                &fixture.use_attestation,
                91,
            )
            .is_err(),
        "expired use signatures must fail"
    );
    let mut forged = fixture.use_attestation.clone();
    forged.signature[0] ^= 1;
    assert!(
        fixture
            .consume(&fixture.binding, &fixture.owner, &forged, 85)
            .is_err()
    );
    let payload = fixture
        .binding
        .outcome_qualification_use_payload_v1(&fixture.receipt, &fixture.owner, &fixture.trust)
        .expect("payload");
    let wrong_role = host::sign(LearningEvidenceRoleV1::Generator, &payload, 82);
    assert!(
        fixture
            .consume(&fixture.binding, &fixture.owner, &wrong_role, 85)
            .is_err()
    );
    for field in 0..3 {
        let mut evaluation = fixture.receipt.decision().decision.evaluation_id.clone();
        let mut execution = fixture.receipt.execution_digest();
        let mut publication = fixture.receipt.publication_digest();
        match field {
            0 => evaluation = host::id("other-evaluation"),
            1 => execution = host::digest("other-execution"),
            _ => publication = host::digest("other-publication"),
        }
        assert!(
            fixture
                .binding
                .consume_outcome_qualification_v1(
                    &fixture.receipt,
                    &evaluation,
                    execution,
                    publication,
                    &fixture.owner,
                    &fixture.use_attestation,
                    &fixture.trust,
                    85,
                )
                .is_err()
        );
    }
    assert_eq!(
        fs::read_dir(fixture.root.join("publications"))
            .expect("publications")
            .count(),
        1,
        "consumer validation must not cause another qualification publication"
    );
}

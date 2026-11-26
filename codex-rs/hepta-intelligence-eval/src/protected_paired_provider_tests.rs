//! Protected Root-file qualification uses synthetic records/signing fixtures.
//! It is not scientific data, installed role evidence, or production activation.
use super::*;
use crate::FencedFinalHoldoutOwnerV1;
use crate::LockedFileProductEvidenceSinkV1;
use crate::NamedTempFile;
use crate::ProductPublicationRecoveryV1;
use crate::fixed_holdout_custody::PreparedHoldoutCounts;
use crate::fixed_holdout_custody::Witness;
use crate::fixed_holdout_custody::initialize_private_holdout;
use crate::freeze_paired_supervised_plan_v1;
use crate::paired_observer_transport::encode_signed_paired_observation_transport_v1;
use crate::paired_supervised_host_clock::PairedHostClockV1;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::digest;
use crate::paired_supervised_test_support::inputs;
use crate::product_runner::ProductEvaluationRunnerV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::os::unix::fs::PermissionsExt;

struct Fixture {
    directory: PathBuf,
    cas: PathBuf,
    witness: PathBuf,
    cut: PathBuf,
    plan: crate::PairedSupervisedPlanV1,
    signing: SigningFixture,
    runner: ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
}
impl Fixture {
    fn new() -> Self {
        assert!(
            std::fs::read_to_string("/proc/self/status")
                .unwrap()
                .lines()
                .any(|line| line.split_whitespace().collect::<Vec<_>>()
                    == ["Uid:", "0", "0", "0", "0"])
        );
        let temp = NamedTempFile::new().unwrap();
        let directory = temp.path().with_extension("protected-paired-owner");
        std::fs::create_dir(&directory).unwrap();
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
        let witness = directory.join("witness.json");
        let gold = b"synthetic-native-custody-only-no-scientific-data";
        initialize_private_holdout(
            &directory,
            &witness,
            digest("native-config"),
            gold,
            b"[]",
            PreparedHoldoutCounts {
                eligible_claims: 8,
                eligible_components: 8,
                labeled_pairs: 8,
                excluded_shared_claims: 0,
                unjudged_pairs_not_scored: 0,
            },
        )
        .unwrap();
        let witnessed: Witness = serde_json::from_slice(&std::fs::read(&witness).unwrap()).unwrap();
        let binding = witnessed.binding.parse().unwrap();
        let cas = directory.join("holdout-cas.bin");
        let minimum = FinalHoldoutCasAnchorV1 {
            fence_generation: witnessed.fence_generation,
            record_count: witnessed.record_count,
            state_digest: witnessed.state_digest.parse().unwrap(),
        };
        let mut store = LockedFileFinalHoldoutCasStoreV1::recover(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&cas)
                .unwrap(),
            binding,
            Some(minimum),
        )
        .unwrap();
        let state = crate::FinalHoldoutCasStoreV1::load(&mut store, binding)
            .unwrap()
            .unwrap();
        let owner = FencedFinalHoldoutOwnerV1::recover(store, binding, state.fence).unwrap();
        let mut inputs = inputs(8);
        inputs.base_plan.final_holdout_digest = Digest32::of_bytes(gold);
        let plan = freeze_paired_supervised_plan_v1(inputs).unwrap();
        Self {
            cut: directory.join("original-observer-cut.json"),
            directory,
            cas,
            witness,
            plan,
            signing: SigningFixture::new(false),
            runner: ProductEvaluationRunnerV1::new(owner),
        }
    }
    fn provider(&self) -> ProtectedPairedObservationProviderV1 {
        self.runner
            .holdout
            .protected_observer_provider(
                &self.cas,
                &self.witness,
                &self.cut,
                &self.signing.register(&self.plan),
            )
            .unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.directory);
    }
}

#[test]
#[ignore = "requires an actual Root-owned protected fixture namespace"]
fn protected_original_provider_commits_consumption_and_original_evidence_sink() {
    let mut fixture = Fixture::new();
    let original = fixture.signing.cut(&fixture.plan);
    let transport = encode_signed_paired_observation_transport_v1(&original).unwrap();
    crate::fixed_holdout_custody::create_private(&fixture.cut, &transport).unwrap();
    let mut provider = fixture.provider();
    let registration = fixture.signing.register(&fixture.plan);
    let execution = fixture
        .runner
        .evaluate_paired_with_clock(
            &registration,
            &mut provider,
            &fixture.signing.trust,
            &mut PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    let context = fixture.signing.context();
    let evidence = fixture.signing.evaluation(&execution, &context);
    let request = serde_json::to_vec(&serde_json::json!({
        "original_observer_transport":serde_json::from_slice::<serde_json::Value>(&transport).unwrap(),
        "original_evaluator_evidence":ReviewEvidenceWireV1::from_native(&evidence.evaluator_bundle),
    })).unwrap();
    let evidence_file = NamedTempFile::new().unwrap();
    let mut sink = LockedFileProductEvidenceSinkV1::open(
        evidence_file.reopen().unwrap(),
        execution.execution_digest(),
        &request,
        ProductPublicationRecoveryV1::Unacknowledged,
    )
    .unwrap();
    let qualification = fixture
        .runner
        .qualify_paired_with_clock(
            &execution,
            &context,
            &evidence,
            &fixture.signing.trust,
            &mut sink,
            &mut PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    qualification.validate_integrity().unwrap();
    assert_eq!(fixture.runner.holdout_anchor().record_count, 1);
    let original_cas = std::fs::read(&fixture.cas).unwrap();
    let original_publication = std::fs::read(evidence_file.path()).unwrap();
    assert_eq!(
        Digest32::of_bytes(&original_publication),
        qualification.publication_digest
    );
    assert!(!qualification.authority.grants_any());
    let mut reopened_provider = fixture.provider();
    assert!(
        fixture
            .runner
            .evaluate_paired_with_clock(
                &registration,
                &mut reopened_provider,
                &fixture.signing.trust,
                &mut PairedHostClockV1::fixture(&[30])
            )
            .is_err()
    );
    assert_eq!(std::fs::read(&fixture.cas).unwrap(), original_cas);
    assert_eq!(
        std::fs::read(evidence_file.path()).unwrap(),
        original_publication
    );
}

#[test]
#[ignore = "requires an actual Root-owned protected fixture namespace"]
fn unavailable_original_cut_keeps_consumed_obligation_and_forbids_reexecution() {
    let mut fixture = Fixture::new();
    let mut provider = fixture.provider();
    let registration = fixture.signing.register(&fixture.plan);
    assert!(
        fixture
            .runner
            .evaluate_paired_with_clock(
                &registration,
                &mut provider,
                &fixture.signing.trust,
                &mut PairedHostClockV1::fixture(&[30])
            )
            .is_err()
    );
    assert_eq!(fixture.runner.holdout_anchor().record_count, 1);
    let original_cas = std::fs::read(&fixture.cas).unwrap();
    let original = fixture.signing.cut(&fixture.plan);
    crate::fixed_holdout_custody::create_private(
        &fixture.cut,
        &encode_signed_paired_observation_transport_v1(&original).unwrap(),
    )
    .unwrap();
    let mut reopened_provider = fixture.provider();
    assert!(
        fixture
            .runner
            .evaluate_paired_with_clock(
                &registration,
                &mut reopened_provider,
                &fixture.signing.trust,
                &mut PairedHostClockV1::fixture(&[30])
            )
            .is_err()
    );
    assert_eq!(std::fs::read(&fixture.cas).unwrap(), original_cas);
}

#[test]
#[ignore = "requires an actual Root-owned protected fixture namespace"]
fn actual_custody_manifest_does_not_echo_the_callers_registration() {
    let mut fixture = Fixture::new();
    let mut inputs = inputs(8);
    inputs.base_plan.final_holdout_digest = digest("caller-substituted-cohort");
    let wrong_plan = freeze_paired_supervised_plan_v1(inputs).unwrap();
    let registration = fixture.signing.register(&wrong_plan);
    let mut provider = fixture
        .runner
        .holdout
        .protected_observer_provider(&fixture.cas, &fixture.witness, &fixture.cut, &registration)
        .unwrap();
    let before = std::fs::read(&fixture.cas).unwrap();
    assert!(
        fixture
            .runner
            .evaluate_paired_with_clock(
                &registration,
                &mut provider,
                &fixture.signing.trust,
                &mut PairedHostClockV1::fixture(&[30])
            )
            .is_err()
    );
    assert_eq!(fixture.runner.holdout_anchor().record_count, 0);
    assert!(!provider.attempted);
    assert_eq!(std::fs::read(&fixture.cas).unwrap(), before);
}

#[test]
#[ignore = "requires an actual Root-owned protected fixture namespace"]
fn uncertain_committed_cas_is_indeterminate_and_does_not_open_transport() {
    let mut fixture = Fixture::new();
    let mut provider = fixture.provider();
    let receipt = fixture
        .runner
        .holdout
        .consume(fixture.plan.frozen_plan())
        .unwrap();
    let file = OpenOptions::new().write(true).open(&fixture.cas).unwrap();
    let torn_length = file.metadata().unwrap().len() - 1;
    file.set_len(torn_length).unwrap();
    file.sync_all().unwrap();
    assert_eq!(
        provider.release_after_consumption(&receipt),
        Err(ProductProviderErrorV1::Indeterminate)
    );
    assert!(!provider.attempted);
    assert!(!fixture.cut.exists());
    assert_eq!(file.metadata().unwrap().len(), torn_length);
    assert_eq!(fixture.runner.holdout_anchor().record_count, 1);
}

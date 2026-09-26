//! Actual file/CAS recovery with synthetic observations and test-only signers.
//! These checks are not field efficacy or production identity acceptance.
use super::*;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);
const CHILD: &str = "HEPTA_EVAL_PUBLICATION_CRASH_ROOT";
type Runner = ProductEvaluationRunnerV1<crate::LockedFileFinalHoldoutCasStoreV1>;

struct Root(PathBuf);
impl Root {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hepta-product-recovery-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn open_runner(path: &Path, minimum: Option<crate::FinalHoldoutCasAnchorV1>) -> Runner {
    let binding = digest("product-recovery-scope");
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(minimum.is_none())
        .open(path.join("holdout"))
        .unwrap();
    let store = match minimum {
        None => crate::LockedFileFinalHoldoutCasStoreV1::create(file, binding).unwrap(),
        Some(anchor) => {
            crate::LockedFileFinalHoldoutCasStoreV1::recover(file, binding, Some(anchor)).unwrap()
        }
    };
    let mut issuer = crate::HoldoutFenceIssuerV1::resume(
        id("recovery-owner"),
        digest("host-test-authority"),
        minimum,
    )
    .unwrap();
    let fence = issuer.issue(digest("recovery-test-lease")).unwrap();
    let owner = match minimum {
        None => FencedFinalHoldoutOwnerV1::initialize(store, binding, fence).unwrap(),
        Some(_) => FencedFinalHoldoutOwnerV1::recover(store, binding, fence).unwrap(),
    };
    ProductEvaluationRunnerV1::new(owner)
}

fn frozen(f: &Fixture) -> ProductFrozenEvaluationPlanV1 {
    freeze_product_evaluation_plan_v1(
        f.cross_fold.clone(),
        f.roles.clone(),
        f.sources.clone(),
        &f.candidate_plan,
        &f.baseline_plan,
    )
    .unwrap()
}

fn credentials(
    runner: &Runner,
    temporal: &ProductTemporalEvaluationReceiptV1,
) -> (
    ProductQualificationContextV1,
    SignedEvaluationEvidenceV1,
    LearningEvidenceVerifierV1,
) {
    let principal = |name: &str, seed: u8| AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: Digest32::of_bytes(
            &SigningKey::from_bytes(&[seed; 32])
                .verifying_key()
                .to_bytes(),
        ),
        scope_digest: digest("product-eval-scope"),
        authority_epoch: 7,
        authenticated_at: 1,
        expires_at: 100,
    };
    let context = ProductQualificationContextV1 {
        generator: principal("generator", 41),
        evaluator: principal("evaluator", 42),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let bundle = runner.qualification_bundle(temporal, &context).unwrap();
    signed_context(&bundle, &temporal.product_plan.metric_roles)
}

/// Test-only evidence owner: exact single-publication compare-and-append.
/// A production sink must use its declared owner, not this fixture's file.
struct Publication {
    file: File,
    lose_ack: bool,
}
impl Publication {
    fn open(path: &Path, lose_ack: bool) -> Self {
        Self {
            file: OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(path.join("publication"))
                .unwrap(),
            lose_ack,
        }
    }
}
impl ProductQualificationEvidenceSinkV1 for Publication {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut payload = b"hepta.test.product-publication.v1".to_vec();
        payload.extend_from_slice(execution.as_array());
        push_signed_evaluation_decision(&mut payload, decision);
        let mut existing = Vec::new();
        self.file.seek(SeekFrom::Start(0)).unwrap();
        self.file.read_to_end(&mut existing).unwrap();
        if existing.is_empty() {
            self.file.write_all(&payload).unwrap();
            self.file.sync_all().unwrap();
        } else if existing != payload {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        if std::mem::take(&mut self.lose_ack) {
            return Err(ProductEvidenceSinkErrorV1::Indeterminate);
        }
        Ok(Digest32::of_bytes(&payload))
    }
}

#[test]
fn provider_failure_after_consumption_recovers_same_holdout_identity() {
    let root = Root::new();
    let mut f = fixture();
    let plan = frozen(&f);
    let mut runner = open_runner(&root.0, None);
    let inputs = f.provider.inputs.take().unwrap();
    assert!(matches!(
        runner.evaluate_temporal_comparison(
            &plan,
            &f.candidate_plan,
            &f.baseline_plan,
            &mut f.provider,
        ),
        Err(ProductEvaluationError::Provider(_))
    ));
    let anchor = runner.holdout_anchor();
    assert_eq!(anchor.record_count, 1);
    drop(runner);
    let mut runner = open_runner(&root.0, Some(anchor));
    f.provider.inputs = Some(inputs);
    let temporal = runner
        .evaluate_temporal_comparison(&plan, &f.candidate_plan, &f.baseline_plan, &mut f.provider)
        .unwrap();
    assert_eq!(
        temporal.holdout.disposition,
        crate::HoldoutUseDispositionV1::IdempotentReplay
    );
    assert_eq!(runner.holdout_anchor().record_count, 1);
    let (context, evidence, verifier) = credentials(&runner, &temporal);
    assert!(
        runner
            .qualify_and_persist(
                &temporal,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                50,
                &mut Publication::open(&root.0, false)
            )
            .is_ok()
    );
}

#[test]
fn lost_publication_ack_reopens_without_duplicate_or_replacement() {
    let root = Root::new();
    let mut f = fixture();
    let plan = frozen(&f);
    let mut runner = open_runner(&root.0, None);
    let temporal = runner
        .evaluate_temporal_comparison(&plan, &f.candidate_plan, &f.baseline_plan, &mut f.provider)
        .unwrap();
    let (context, evidence, verifier) = credentials(&runner, &temporal);
    assert!(matches!(
        runner.qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            50,
            &mut Publication::open(&root.0, true)
        ),
        Err(ProductEvaluationError::Sink(
            ProductEvidenceSinkErrorV1::Indeterminate
        ))
    ));
    let original = fs::read(root.0.join("publication")).unwrap();
    let anchor = runner.holdout_anchor();
    drop(runner);
    let mut runner = open_runner(&root.0, Some(anchor));
    let mut restored = fixture();
    let resumed = runner
        .evaluate_temporal_comparison(
            &plan,
            &restored.candidate_plan,
            &restored.baseline_plan,
            &mut restored.provider,
        )
        .unwrap();
    assert_eq!(resumed.execution_digest, temporal.execution_digest);
    assert_eq!(
        resumed.holdout.use_receipt.use_digest,
        temporal.holdout.use_receipt.use_digest
    );
    let mut sink = Publication::open(&root.0, false);
    let result = runner
        .qualify_and_persist(
            &resumed,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            50,
            &mut sink,
        )
        .unwrap();
    assert_eq!(result.publication_digest, Digest32::of_bytes(&original));
    assert_eq!(fs::read(root.0.join("publication")).unwrap(), original);
    assert_eq!(runner.holdout_anchor().record_count, 1);
    assert!(
        runner
            .qualify_and_persist(
                &resumed,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                91,
                &mut sink
            )
            .is_err()
    );
    let mut replaced = fixture();
    let row = &mut replaced.provider.inputs.as_mut().unwrap().training[0];
    row.outcome = if row.outcome == FixedQ32::ZERO {
        FixedQ32::ONE
    } else {
        FixedQ32::ZERO
    };
    let changed = runner
        .evaluate_temporal_comparison(
            &plan,
            &replaced.candidate_plan,
            &replaced.baseline_plan,
            &mut replaced.provider,
        )
        .unwrap();
    assert_ne!(changed.execution_digest, temporal.execution_digest);
    assert!(
        runner
            .qualify_and_persist(
                &changed,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                50,
                &mut sink
            )
            .is_err()
    );
    assert_eq!(fs::read(root.0.join("publication")).unwrap(), original);
}

#[test]
fn process_exit_after_durable_publication_recovers_original_result() {
    if let Some(path) = std::env::var_os(CHILD) {
        let path = PathBuf::from(path);
        let mut f = fixture();
        let mut runner = open_runner(&path, None);
        let temporal = runner
            .evaluate_temporal_comparison(
                &frozen(&f),
                &f.candidate_plan,
                &f.baseline_plan,
                &mut f.provider,
            )
            .unwrap();
        let (context, evidence, verifier) = credentials(&runner, &temporal);
        let result = runner
            .qualify_and_persist(
                &temporal,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                50,
                &mut Publication::open(&path, false),
            )
            .unwrap();
        let anchor = runner.holdout_anchor();
        let mut witness = File::create(path.join("independent-witness")).unwrap();
        writeln!(
            witness,
            "{}\n{}\n{}\n{}\n{}",
            anchor.fence_generation,
            anchor.record_count,
            anchor.state_digest,
            temporal.execution_digest,
            result.publication_digest
        )
        .unwrap();
        witness.sync_all().unwrap();
        // Exit without destructors or a response to the parent: OS must release
        // the actual owner lock, and both independently retained files survive.
        std::process::exit(37);
    }
    let root = Root::new();
    let status = Command::new(std::env::current_exe().unwrap())
        .arg("--exact")
        .arg("product_runner::tests::recovery::process_exit_after_durable_publication_recovers_original_result")
        .arg("--nocapture").env(CHILD, &root.0).status().unwrap();
    assert_eq!(status.code(), Some(37));
    let witness = fs::read_to_string(root.0.join("independent-witness")).unwrap();
    let fields: Vec<_> = witness.lines().collect();
    let anchor = crate::FinalHoldoutCasAnchorV1 {
        fence_generation: fields[0].parse().unwrap(),
        record_count: fields[1].parse().unwrap(),
        state_digest: fields[2].parse().unwrap(),
    };
    let original = fs::read(root.0.join("publication")).unwrap();
    let mut runner = open_runner(&root.0, Some(anchor));
    let mut f = fixture();
    let temporal = runner
        .evaluate_temporal_comparison(
            &frozen(&f),
            &f.candidate_plan,
            &f.baseline_plan,
            &mut f.provider,
        )
        .unwrap();
    assert_eq!(temporal.execution_digest.to_string(), fields[3]);
    let (context, evidence, verifier) = credentials(&runner, &temporal);
    let result = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            50,
            &mut Publication::open(&root.0, false),
        )
        .unwrap();
    assert_eq!(result.publication_digest.to_string(), fields[4]);
    assert_eq!(fs::read(root.0.join("publication")).unwrap(), original);
    assert_eq!(runner.holdout_anchor().record_count, 1);
}

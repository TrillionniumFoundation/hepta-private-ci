//! File components execute the original runner over explicitly synthetic
//! component rows and signing keys. They do not attest deployed independent B.

use super::*;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use crate::FileFinalHoldoutErrorV1;
use crate::LockedFileFinalHoldoutCasStoreV1;
use crate::LockedFileFinalHoldoutProviderV1;
use crate::LockedFileProductQualificationEvidenceSinkV1;
use crate::encode_file_final_holdout_material_v1;

static NEXT_FILE: AtomicU64 = AtomicU64::new(0);

struct ComponentFile(PathBuf);

impl ComponentFile {
    fn create(label: &str, bytes: &[u8]) -> (Self, File) {
        let path = std::env::temp_dir().join(format!(
            "hepta-file-evaluation-{label}-{}-{}",
            std::process::id(),
            NEXT_FILE.fetch_add(1, Ordering::Relaxed)
        ));
        let mut options: OpenOptions = OpenOptions::new();
        options.read(true).write(true).create_new(true);
        let mut file: File = options.open(&path).expect("exclusive component file");
        file.write_all(bytes).expect("component material bytes");
        file.sync_all().expect("component material fsync");
        (Self(path), file)
    }

    fn read(&self) -> File {
        File::open(&self.0).expect("owned component material")
    }

    fn read_write(&self) -> File {
        let mut options: OpenOptions = OpenOptions::new();
        options.read(true).write(true);
        options.open(&self.0).expect("owned component journal")
    }
}

impl Drop for ComponentFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn material_fixture() -> (Fixture, Vec<u8>) {
    let fixture = fixture();
    let inputs = fixture.provider.inputs.as_ref().expect("component rows");
    let bytes = encode_file_final_holdout_material_v1(
        fixture.cross_fold.objective_digest,
        fixture.cross_fold.dataset_digest,
        &fixture.cross_fold.final_holdout_window_id,
        inputs,
    )
    .expect("encode actual supplied component rows");
    (fixture, bytes)
}

fn bind_material(fixture: &Fixture, bytes: &[u8]) -> ProductFrozenEvaluationPlanV1 {
    let mut cross_fold = fixture.cross_fold.clone();
    cross_fold.final_holdout_digest = Digest32::of_bytes(bytes);
    freeze_product_evaluation_plan_v1(
        cross_fold,
        fixture.roles.clone(),
        fixture.sources.clone(),
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    )
    .expect("freeze exact component material")
}

fn file_runner() -> (
    ComponentFile,
    ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
) {
    let (journal, file) = ComponentFile::create("holdout", &[]);
    let binding = digest("component holdout namespace");
    let store = LockedFileFinalHoldoutCasStoreV1::create(file, binding)
        .expect("original locked-file CAS");
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        store,
        binding,
        HoldoutWriterFenceV1 {
            owner_id: id("component-file-owner"),
            generation: 1,
            lease_digest: digest("component-file-lease"),
        },
    )
    .expect("actual original fenced owner");
    (journal, ProductEvaluationRunnerV1::new(owner))
}

fn component_context() -> ProductQualificationContextV1 {
    let principal = |name: &str| AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: digest(&format!("{name}-key")),
        scope_digest: digest("component-template-scope"),
        authority_epoch: 7,
        authenticated_at: 1,
        expires_at: 100,
    };
    ProductQualificationContextV1 {
        generator: principal("component-template-generator"),
        evaluator: principal("component-template-evaluator"),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    }
}

#[test]
fn original_file_runner_qualifies_into_a_durable_sink_and_exact_readback() {
    let (fixture, bytes) = material_fixture();
    let frozen = bind_material(&fixture, &bytes);
    let (_material, file) = ComponentFile::create("material", &bytes);
    let mut provider =
        LockedFileFinalHoldoutProviderV1::open(file, &frozen).expect("bound original file");
    let (_holdout, mut runner) = file_runner();
    let temporal = runner
        .evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut provider,
        )
        .expect("actual original comparison");
    assert_eq!(runner.holdout_anchor().record_count, 1);
    let template = runner
        .qualification_bundle(&temporal, &component_context())
        .expect("actual derived bundle");
    let (context, _, _) = signed_context(&template, &fixture.roles);
    let bundle = runner
        .qualification_bundle(&temporal, &context)
        .expect("actual bound component principals");
    let (_, evidence, verifier) = signed_context(&bundle, &fixture.roles);
    let (publication, file) = ComponentFile::create("qualification", &[]);
    let binding = digest("component qualification namespace");
    let mut sink = LockedFileProductQualificationEvidenceSinkV1::create(file, binding)
        .expect("actual evidence file owner");
    let qualification = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            50,
            &mut sink,
        )
        .expect("original signed admission and durable publication");
    let anchor = sink.anchor();
    assert_eq!(anchor.sequence, 2);
    assert!(!qualification.authority.grants_any());
    assert_eq!(
        sink.readback(temporal.execution_digest, &qualification.decision),
        Ok(qualification.publication_digest)
    );
    let committed = std::fs::read(&publication.0).expect("actual committed journal bytes");
    drop(sink);
    let mut recovered = LockedFileProductQualificationEvidenceSinkV1::recover(
        publication.read_write(),
        binding,
        anchor,
    )
    .expect("recover actual original publication prefix");
    assert_eq!(
        recovered.readback(temporal.execution_digest, &qualification.decision),
        Ok(qualification.publication_digest)
    );
    assert_eq!(
        std::fs::read(&publication.0).expect("unchanged original journal"),
        committed
    );
}

#[test]
fn a_copied_receipt_and_consumption_replay_never_release_a_fresh_file_owner() {
    let (fixture, bytes) = material_fixture();
    let frozen = bind_material(&fixture, &bytes);
    let (material, file) = ComponentFile::create("once-material", &bytes);
    let mut provider =
        LockedFileFinalHoldoutProviderV1::open(file, &frozen).expect("original file");
    let (_holdout, mut runner) = file_runner();
    let temporal = runner
        .evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut provider,
        )
        .expect("original recorded consumption");
    let anchor = runner.holdout_anchor();
    let mut fresh = LockedFileFinalHoldoutProviderV1::open(material.read(), &frozen)
        .expect("separate real read descriptor");
    assert_eq!(
        fresh.release_after_consumption(&temporal.holdout).err(),
        Some(ProductProviderErrorV1::Rejected)
    );
    assert!(matches!(
        runner.evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut fresh,
        ),
        Err(ProductEvaluationError::Binding("final holdout already consumed"))
    ));
    assert_eq!(runner.holdout_anchor(), anchor);
    assert_eq!(
        provider.manifest_digest(),
        Err(ProductProviderErrorV1::Rejected)
    );
}

#[test]
fn a_real_permit_for_another_complete_frozen_plan_consumes_no_rows() {
    let (fixture, bytes) = material_fixture();
    let frozen = bind_material(&fixture, &bytes);
    let mut different = fixture.cross_fold.clone();
    different.plan_id = id("different-component-plan");
    different.final_holdout_digest = Digest32::of_bytes(&bytes);
    let different = freeze_product_evaluation_plan_v1(
        different,
        fixture.roles.clone(),
        fixture.sources.clone(),
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    )
    .expect("another legitimate frozen data plan");
    let (_material, file) = ComponentFile::create("different-plan", &bytes);
    let mut provider =
        LockedFileFinalHoldoutProviderV1::open(file, &different).expect("other full plan");
    let (_holdout, mut runner) = file_runner();
    assert!(matches!(
        runner.evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut provider,
        ),
        Err(ProductEvaluationError::Provider(ProductProviderErrorV1::Rejected))
    ));
    // The real CAS happened, but the mismatched provider never decodes/releases.
    assert_eq!(runner.holdout_anchor().record_count, 1);
    assert_eq!(
        provider.manifest_digest(),
        Err(ProductProviderErrorV1::Rejected)
    );
}

#[test]
fn changed_material_refuses_before_consumption_and_bad_encoding_cannot_rearm() {
    let (fixture, bytes) = material_fixture();
    let frozen = bind_material(&fixture, &bytes);
    let (material, file) = ComponentFile::create("changed-material", &bytes);
    let mut provider =
        LockedFileFinalHoldoutProviderV1::open(file, &frozen).expect("original bytes");
    let mut changed = bytes.clone();
    changed[0] ^= 1;
    // Deliberate noncooperating corruption tests digest validation, not custody.
    std::fs::write(&material.0, &changed).expect("component corruption");
    let (_holdout, mut runner) = file_runner();
    assert!(matches!(
        runner.evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut provider,
        ),
        Err(ProductEvaluationError::Provider(ProductProviderErrorV1::Rejected))
    ));
    assert_eq!(runner.holdout_anchor().record_count, 0);
    assert_eq!(
        LockedFileFinalHoldoutProviderV1::open(material.read(), &frozen).err(),
        Some(FileFinalHoldoutErrorV1::Corrupt)
    );

    let mut malformed = bytes;
    malformed.pop().expect("nonempty component material");
    let malformed_plan = bind_material(&fixture, &malformed);
    let (malformed_file, file) = ComponentFile::create("malformed-material", &malformed);
    let mut malformed_provider = LockedFileFinalHoldoutProviderV1::open(file, &malformed_plan)
        .expect("exact but malformed data bytes");
    assert!(matches!(
        runner.evaluate_temporal_comparison(
            &malformed_plan,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut malformed_provider,
        ),
        Err(ProductEvaluationError::Provider(ProductProviderErrorV1::Rejected))
    ));
    assert_eq!(runner.holdout_anchor().record_count, 1);
    let mut reopened =
        LockedFileFinalHoldoutProviderV1::open(malformed_file.read(), &malformed_plan)
            .expect("new owner cannot undo original durable consumption");
    assert!(matches!(
        runner.evaluate_temporal_comparison(
            &malformed_plan,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut reopened,
        ),
        Err(ProductEvaluationError::Binding("final holdout already consumed"))
    ));
}

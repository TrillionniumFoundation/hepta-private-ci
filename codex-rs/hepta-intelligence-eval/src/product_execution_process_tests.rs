//! Real process and file lifetimes with synthetic cohorts and explicit test keys.
use super::*;
use pretty_assertions::assert_eq;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;

use crate::FinalHoldoutCasAnchorV1;
use crate::LockedFileFinalHoldoutCasStoreV1;
use crate::LockedFileProductEvaluationExecutionStoreV1;
use crate::ProductEvaluationExecutionAnchorV1;

fn open(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("authorized test file")
}

fn capture(
    path: &Path,
    holdout: FinalHoldoutCasAnchorV1,
    execution: ProductEvaluationExecutionAnchorV1,
    digest: Digest32,
) {
    fs::write(
        path,
        format!(
            "{}\n{}\n{}\n{}\n{}\n{digest}\n",
            holdout.fence_generation,
            holdout.record_count,
            holdout.state_digest,
            execution.sequence,
            execution.history_digest
        ),
    )
    .expect("external test minima");
}

struct TempDirectory(PathBuf);
impl Drop for TempDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn signed_execution_and_original_holdout_survive_an_abrupt_process_exit() {
    const TEST: &str = "product_runner::tests::execution_tests::process_tests::signed_execution_and_original_holdout_survive_an_abrupt_process_exit";
    if let Ok(directory) = std::env::var("HEPTA_SIGNED_EXECUTION_PROCESS_DIR") {
        let directory = PathBuf::from(directory);
        let mode = std::env::var("HEPTA_SIGNED_EXECUTION_PROCESS_MODE").expect("child mode");
        let minima = fs::read_to_string(directory.join(if mode == "write" {
            "initial"
        } else {
            "completed"
        }))
        .expect("independently retained test minima");
        let fields: Vec<_> = minima.lines().collect();
        assert_eq!(fields.len(), 6);
        let holdout_minimum = FinalHoldoutCasAnchorV1 {
            fence_generation: fields[0].parse().expect("minimum fence"),
            record_count: fields[1].parse().expect("minimum records"),
            state_digest: fields[2].parse().expect("minimum state"),
        };
        let execution_minimum = ProductEvaluationExecutionAnchorV1 {
            sequence: fields[3].parse().expect("minimum sequence"),
            history_digest: fields[4].parse().expect("minimum history"),
        };
        let expected: Digest32 = fields[5].parse().expect("original execution identity");
        let holdout_store = LockedFileFinalHoldoutCasStoreV1::recover(
            open(&directory.join("holdout")),
            digest("holdout-binding"),
            Some(holdout_minimum),
        )
        .expect("current original holdout file");
        let owner = FencedFinalHoldoutOwnerV1::recover(
            holdout_store,
            digest("holdout-binding"),
            HoldoutWriterFenceV1 {
                owner_id: id("evaluation-owner"),
                generation: if mode == "write" { 1 } else { 2 },
                lease_digest: digest(if mode == "write" {
                    "lease-1"
                } else {
                    "lease-2"
                }),
            },
        )
        .expect("current fenced owner");
        let mut runner = ProductEvaluationRunnerV1::new(owner);
        let mut executions = LockedFileProductEvaluationExecutionStoreV1::recover(
            open(&directory.join("executions")),
            digest("execution-store"),
            execution_minimum,
        )
        .expect("same durable execution journal");
        let before = (runner.holdout_anchor(), executions.anchor());
        let mut fixture = Harness::new();
        let clock = || Ok(50);
        let result = runner
            .evaluate_or_readback_temporal_comparison(
                &ProductEvaluationExecutionRequestV1 {
                    plan: &fixture.frozen,
                    candidate_plan: &fixture.fixture.candidate_plan,
                    baseline_plan: &fixture.fixture.baseline_plan,
                    evaluator: &fixture.context.evaluator,
                    verifier: &fixture.verifier,
                    clock: &clock,
                },
                &mut fixture.fixture.provider,
                &mut executions,
                &mut fixture.attestor,
            )
            .expect("authenticated execution or original readback");
        if mode == "write" {
            assert_eq!(
                (
                    fixture.fixture.provider.release_count,
                    fixture.attestor.calls
                ),
                (1, 1)
            );
            capture(
                &directory.join("completed"),
                runner.holdout_anchor(),
                executions.anchor(),
                result.execution_digest,
            );
            // The durable owners must not rely on orderly Rust destruction.
            std::process::exit(/*code*/ 0);
        }
        assert_eq!(mode, "read");
        assert_eq!(result.execution_digest, expected);
        assert_eq!(
            (
                fixture.fixture.provider.release_count,
                fixture.attestor.calls
            ),
            (0, 0)
        );
        assert_eq!((runner.holdout_anchor(), executions.anchor()), before);
        let bundle = runner
            .qualification_bundle(&result, &fixture.context)
            .expect("original evaluator context");
        let (context, evidence, verifier) = signed_context(&bundle, &fixture.fixture.roles);
        let mut sink = Sink::default();
        let qualification = runner
            .qualify_and_persist(
                &result,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                /*now*/ 50,
                &mut sink,
            )
            .expect("unchanged original qualification signature path");
        assert!(!qualification.authority.grants_any());
        fs::write(
            directory.join("readback"),
            result.execution_digest.to_string(),
        )
        .expect("child observed readback");
        return;
    }

    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("fixture clock")
        .as_nanos();
    let directory = TempDirectory(std::env::temp_dir().join(format!(
        "hepta-signed-execution-{}-{unique}",
        std::process::id()
    )));
    fs::create_dir(&directory.0).expect("isolated test directory");
    let new_file = |name: &str| {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(directory.0.join(name))
            .expect("new test owner file")
    };
    let holdout_store =
        LockedFileFinalHoldoutCasStoreV1::create(new_file("holdout"), digest("holdout-binding"))
            .expect("create holdout");
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        holdout_store,
        digest("holdout-binding"),
        HoldoutWriterFenceV1 {
            owner_id: id("evaluation-owner"),
            generation: 1,
            lease_digest: digest("lease-1"),
        },
    )
    .expect("initialize original owner");
    let executions = LockedFileProductEvaluationExecutionStoreV1::create(
        new_file("executions"),
        digest("execution-store"),
    )
    .expect("create execution journal");
    capture(
        &directory.0.join("initial"),
        owner.anchor(),
        executions.anchor(),
        Digest32::ZERO,
    );
    drop(owner);
    drop(executions);
    let executable = std::env::current_exe().expect("current test binary");
    for mode in ["write", "read"] {
        let status = Command::new(&executable)
            .arg("--exact")
            .arg(TEST)
            .arg("--nocapture")
            .env("HEPTA_SIGNED_EXECUTION_PROCESS_DIR", &directory.0)
            .env("HEPTA_SIGNED_EXECUTION_PROCESS_MODE", mode)
            .status()
            .expect("fresh child process");
        assert!(status.success(), "{mode} child failed: {status}");
    }
    let completed = fs::read_to_string(directory.0.join("completed")).expect("original completion");
    assert_eq!(
        fs::read_to_string(directory.0.join("readback")).expect("fresh reader result"),
        completed.lines().last().expect("execution digest")
    );
}

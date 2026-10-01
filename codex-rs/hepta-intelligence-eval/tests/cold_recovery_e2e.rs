//! Actual fresh-process recovery of typed qualification inputs and signatures.
//! Fixture keys, windows and the disk anchor are NOT real host acceptance.
use std::fs;
use std::path::Path;
use std::process::Command;
use std::process::ExitStatus;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_intelligence_eval::*;
use codex_hepta_types::Digest32;

#[path = "selected_host_recovery_support/controller_tests.rs"]
mod controller_tests;
#[path = "selected_host_recovery_support/final_use_archive_tests.rs"]
mod final_use_archive_tests;
#[allow(dead_code)]
#[path = "selected_host_recovery_support/cold_trust.rs"]
mod host;
#[path = "selected_host_recovery_support/eligible_model.rs"]
mod outcome_model;
#[path = "selected_host_recovery_support/qualification_receipt_tests.rs"]
mod qualification_receipt_tests;
#[cfg(target_os = "linux")]
#[path = "selected_host_recovery_support/recovery_sync_eio_tests.rs"]
mod recovery_sync_eio_tests;
#[path = "selected_host_recovery_support/cold_storage.rs"]
mod storage;
#[allow(dead_code)]
#[path = "selected_host_recovery_support/cold_temporal_model.rs"]
mod temporal_model;

static NEXT_ROOT: AtomicU64 = AtomicU64::new(0);

fn namespace() -> Digest32 {
    host::digest("cold-native-holdout-namespace")
}
fn attempt_binding() -> Digest32 {
    host::digest("cold-native-attempt-binding")
}
fn host_binding() -> Digest32 {
    host::digest("cold-selected-host")
}

fn fence() -> HoldoutWriterFenceV1 {
    HoldoutWriterFenceV1 {
        owner_id: host::id("cold-native-owner"),
        generation: 1,
        lease_digest: host::digest("cold-native-lease"),
    }
}

fn produce(root: &Path, family: &str, cut: u64) {
    let mut clock = host::clock(85);
    let result = qualify(root, family, Some(cut), &mut clock, &host::activate());
    panic!("producer did not terminate at the requested native durability cut: {result:?}");
}

fn qualify(
    root: &Path,
    family: &str,
    cut: Option<u64>,
    clock: &mut host::FixtureClock,
    trust: &codex_hepta_learning_ledger::ActivatedLearningTrustV1,
) -> Result<(), RecordedProductEvaluationErrorV1> {
    qualify_with_anchor(
        root,
        family,
        clock,
        trust,
        storage::DiskAnchor::new(&root.join("anchor"), cut),
    )
}

fn qualify_with_anchor<A: ProductEvaluationAttemptAnchorStoreV1>(
    root: &Path,
    family: &str,
    clock: &mut host::FixtureClock,
    trust: &codex_hepta_learning_ledger::ActivatedLearningTrustV1,
    authority: A,
) -> Result<(), RecordedProductEvaluationErrorV1> {
    let store = LockedFileFinalHoldoutCasStoreV1::create(
        storage::create(&root.join("holdout.cas")),
        namespace(),
    )
    .unwrap_or_else(|error| panic!("create holdout store: {error:?}"));
    let owner = FencedFinalHoldoutOwnerV1::initialize(store, namespace(), fence())
        .unwrap_or_else(|error| panic!("create owner: {error:?}"));
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner);
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        storage::create(&root.join("attempt.journal")),
        attempt_binding(),
        authority,
    )
    .unwrap_or_else(|error| panic!("create anchored journal: {error:?}"));
    let attempt = host::id("cold-process-attempt");
    let context = host::context();
    if family == "outcome" {
        let (plan, mut provider, roles) = outcome_model::fixture();
        let receipt = runner
            .evaluate_outcome_comparison(attempt.clone(), &plan, &mut provider, &mut journal)
            .unwrap_or_else(|error| panic!("native multi-outcome estimation: {error:?}"));
        storage::retain_holdout_anchor(&root.join("holdout.anchor"), runner.holdout_anchor());
        let bundle = runner
            .outcome_qualification_bundle(&receipt, &context)
            .unwrap_or_else(|error| panic!("outcome bundle: {error:?}"));
        let evidence = host::evidence(&bundle, &roles, None);
        runner
            .qualify_outcomes_and_persist_on_selected_host(
                &attempt,
                &receipt,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                trust,
                clock,
                &mut journal,
                root.join("artifacts"),
                root.join("publications"),
                host_binding(),
            )
            .map(|_| ())
    } else {
        let longitudinal = family == "longitudinal";
        let (plan, candidate, baseline, mut provider) = temporal_model::fixture(longitudinal);
        let receipt = runner
            .evaluate_temporal_comparison(
                attempt.clone(),
                &plan,
                &candidate,
                &baseline,
                &mut provider,
                &mut journal,
            )
            .unwrap_or_else(|error| panic!("native temporal estimation: {error:?}"));
        storage::retain_holdout_anchor(&root.join("holdout.anchor"), runner.holdout_anchor());
        let bundle = runner
            .qualification_bundle(&receipt, &context)
            .unwrap_or_else(|error| panic!("temporal bundle: {error:?}"));
        let timing = longitudinal.then(|| host::timing(&bundle));
        let evidence = host::evidence(&bundle, &plan.metric_roles, timing.as_ref());
        let timing = match timing.as_ref() {
            Some(timing) => ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros: host::MINIMUM_WINDOW_MICROS,
            },
            None => ProductTimingEvidenceV1::Qualification,
        };
        runner
            .qualify_and_persist_on_selected_host(
                &attempt,
                &receipt,
                &context,
                &evidence,
                timing,
                trust,
                clock,
                &mut journal,
                root.join("artifacts"),
                root.join("publications"),
                host_binding(),
            )
            .map(|_| ())
    }
}

fn recover(root: &Path, family: &str, mode: &str) {
    // This function must not invoke any model/provider/bundle/evidence fixture.
    // It only reconstructs owners from disk and loads current host trust.
    let store = LockedFileFinalHoldoutCasStoreV1::recover(
        storage::reopen(&root.join("holdout.cas")),
        namespace(),
        Some(storage::load_holdout_anchor(&root.join("holdout.anchor"))),
    )
    .unwrap_or_else(|error| panic!("recover holdout bytes: {error:?}"));
    let owner = FencedFinalHoldoutOwnerV1::recover(store, namespace(), fence())
        .unwrap_or_else(|error| panic!("recover owner: {error:?}"));
    let runner = RecordedProductEvaluationRunnerV1::new(owner);
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::recover(
        storage::reopen(&root.join("attempt.journal")),
        attempt_binding(),
        storage::DiskAnchor::new(&root.join("anchor"), None),
    )
    .unwrap_or_else(|error| panic!("recover anchored history: {error:?}"));
    let attempt = host::id("cold-process-attempt");
    let before = journal
        .latest(&attempt)
        .unwrap_or_else(|error| panic!("before: {error:?}"))
        .unwrap_or_else(|| panic!("attempt"));
    let result = if matches!(mode, "page-first" | "page-next" | "page-late-expired") {
        match controller_tests::recover_page(&runner, &mut journal, root, mode, &before) {
            Some(published) => published,
            None => return,
        }
    } else if mode == "reconcile" {
        RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::reconcile_selected_host_publication(
            &mut journal,
            &attempt,
            root.join("publications"),
            host_binding(),
        )
        .unwrap_or_else(|error| panic!("read existing publication: {error:?}"))
    } else {
        let trust = match mode {
            "revoked" => host::activate_revoked(),
            "late-signature-expired" => host::activate_until(100),
            _ => host::activate(),
        };
        let binding = if mode == "wrong-host" {
            host::digest("wrong-host")
        } else {
            host_binding()
        };
        let now = if mode == "expired" { 91 } else { 85 };
        let mut clock = if matches!(mode, "late-expired" | "late-signature-expired") {
            host::scripted_clock(&[85, 91])
        } else {
            host::clock(now)
        };
        let result = if family == "outcome" {
            runner.recover_selected_host_outcome_qualification(
                &mut journal,
                &attempt,
                root.join("artifacts"),
                root.join("publications"),
                binding,
                &trust,
                &mut clock,
            )
        } else {
            runner.recover_selected_host_qualification(
                &mut journal,
                &attempt,
                root.join("artifacts"),
                root.join("publications"),
                binding,
                &trust,
                &mut clock,
            )
        };
        if matches!(mode, "late-expired" | "late-signature-expired") {
            assert!(result.is_err(), "expired final use must not publish");
            let latest = journal
                .latest(&attempt)
                .unwrap_or_else(|error| panic!("latest: {error:?}"))
                .unwrap_or_else(|| panic!("attempt"));
            assert_eq!(
                latest.transition.phase,
                ProductEvaluationAttemptPhaseV1::PublicationPending
            );
            assert_eq!(
                fs::read_dir(root.join("publications"))
                    .unwrap_or_else(|error| panic!("publications: {error:?}"))
                    .count(),
                0
            );
            return;
        }
        if matches!(mode, "revoked" | "expired" | "wrong-host" | "corrupt") {
            assert!(
                result.is_err(),
                "invalid recovery must not reach publication"
            );
            assert_eq!(
                journal
                    .latest(&attempt)
                    .unwrap_or_else(|error| panic!("unchanged: {error:?}")),
                Some(before)
            );
            assert_eq!(
                fs::read_dir(root.join("publications"))
                    .unwrap_or_else(|error| panic!("publication directory: {error:?}"))
                    .count(),
                0
            );
            return;
        }
        result.unwrap_or_else(|error| {
            panic!("cold decode and internal current signature verification: {error:?}")
        })
    };
    use ProductEvaluationAttemptPhaseV1 as Phase;
    assert_eq!(result.transition.phase, Phase::Published);
    assert_eq!(
        fs::read_dir(root.join("publications"))
            .unwrap_or_else(|error| panic!("publications: {error:?}"))
            .count(),
        1
    );
    let history = journal
        .history(&attempt)
        .unwrap_or_else(|error| panic!("history: {error:?}"));
    assert_eq!(
        history
            .iter()
            .map(|row| row.transition.phase)
            .collect::<Vec<_>>(),
        vec![
            Phase::IntentPersisted,
            Phase::HoldoutConsumed,
            Phase::ComparisonSealed,
            Phase::QualificationArtifactsPersisted,
            Phase::QualificationDecided,
            Phase::PublicationPending,
            Phase::Published,
        ]
    );
    assert!(history.iter().all(|row| !row.authority.grants_any()));
    let unchanged = runner.holdout_anchor();
    assert_eq!(
        unchanged,
        storage::load_holdout_anchor(&root.join("holdout.anchor")),
        "cold qualification must not consume or release another final holdout"
    );
}

#[test]
fn selected_host_first_publication_rechecks_time_after_pending_io() {
    for family in ["temporal", "outcome", "longitudinal"] {
        for case in [
            "clock-regressed",
            "distribution-expired",
            "signature-expired",
        ] {
            let late_time = if case == "clock-regressed" { 84 } else { 91 };
            let trust = if case == "signature-expired" {
                host::activate_until(100)
            } else {
                host::activate()
            };
            let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir().join(format!(
                "hepta-final-use-{}-{ordinal}-{family}-{case}",
                std::process::id()
            ));
            fs::create_dir(&root).expect("root");
            let mut clock = host::scripted_clock(&[85, late_time]);
            let result = qualify(&root, family, None, &mut clock, &trust);
            if case == "signature-expired" {
                assert!(trust.is_current_at(late_time));
                assert!(matches!(
                    result,
                    Err(RecordedProductEvaluationErrorV1::Evaluation(
                        ProductEvaluationError::Signed(SignedEvaluationError::Evidence(_))
                    ))
                ));
            } else {
                assert!(matches!(
                    result,
                    Err(RecordedProductEvaluationErrorV1::Invariant(_))
                ));
            }
            assert_eq!(
                fs::read_dir(root.join("publications"))
                    .expect("publications")
                    .count(),
                0
            );
            let mut journal = AnchoredProductEvaluationAttemptJournalV1::recover(
                storage::reopen(&root.join("attempt.journal")),
                attempt_binding(),
                storage::DiskAnchor::new(&root.join("anchor"), None),
            )
            .expect("anchored journal");
            assert_eq!(
                journal
                    .latest(&host::id("cold-process-attempt"))
                    .expect("latest")
                    .expect("attempt")
                    .transition
                    .phase,
                ProductEvaluationAttemptPhaseV1::PublicationPending
            );
            drop(journal);
            fs::remove_dir_all(root).expect("remove fixture");
        }
    }
}

#[test]
fn cold_recovery_rechecks_final_use_and_keeps_pending_unresolved() {
    for family in ["temporal", "outcome", "longitudinal"] {
        for mode in ["late-expired", "late-signature-expired"] {
            let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir().join(format!(
                "hepta-cold-final-use-{}-{ordinal}-{family}-{mode}",
                std::process::id()
            ));
            fs::create_dir(&root).expect("root");
            assert_eq!(child(&root, family, "produce", 4).code(), Some(73));
            assert!(child(&root, family, mode, 4).success());
            let pending = fs::read(root.join("attempt.journal")).expect("pending");
            assert!(child(&root, family, mode, 4).success());
            assert_eq!(
                fs::read(root.join("attempt.journal")).expect("unchanged"),
                pending,
                "a refused final-use publication must not make Pending retryable"
            );
            fs::remove_dir_all(root).expect("remove fixture");
        }
    }
}

#[test]
fn cold_process_entry() {
    let Some(root) = std::env::var_os("HEPTA_EVAL_COLD_TEST_ROOT") else {
        return;
    };
    let family = std::env::var("HEPTA_EVAL_COLD_TEST_FAMILY").expect("family");
    let mode = std::env::var("HEPTA_EVAL_COLD_TEST_MODE").expect("mode");
    let root = Path::new(&root);
    if mode == "produce" {
        let cut = std::env::var("HEPTA_EVAL_COLD_TEST_CUT")
            .expect("cut")
            .parse()
            .expect("numeric cut");
        produce(root, &family, cut);
    } else {
        recover(root, &family, &mode);
    }
}

fn child(root: &Path, family: &str, mode: &str, cut: u64) -> ExitStatus {
    let mut child = Command::new(
        std::env::current_exe().unwrap_or_else(|error| panic!("test executable: {error:?}")),
    )
    .arg("--exact")
    .arg("cold_process_entry")
    .arg("--nocapture")
    .env("HEPTA_EVAL_COLD_TEST_ROOT", root)
    .env("HEPTA_EVAL_COLD_TEST_FAMILY", family)
    .env("HEPTA_EVAL_COLD_TEST_MODE", mode)
    .env("HEPTA_EVAL_COLD_TEST_CUT", cut.to_string())
    .spawn()
    .unwrap_or_else(|error| panic!("start a fresh test process: {error:?}"));
    let started = Instant::now();
    loop {
        if let Some(status) = child
            .try_wait()
            .unwrap_or_else(|error| panic!("observe child: {error:?}"))
        {
            return status;
        }
        if started.elapsed() > Duration::from_secs(90) {
            let _ = child.kill();
            let _ = child.wait();
            panic!("cold recovery child exceeded its watchdog: {family}/{mode}/{cut}");
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

#[test]
fn cold_process_recovery_uses_only_persisted_inputs_and_current_trust() {
    for family in ["temporal", "outcome", "longitudinal"] {
        for cut in [4, 5] {
            let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir().join(format!(
                "hepta-cold-eval-{}-{ordinal}-{family}-{cut}",
                std::process::id()
            ));
            fs::create_dir(&root).expect("root");
            let status = child(&root, family, "produce", cut);
            assert_eq!(
                status.code(),
                Some(73),
                "native durable cut must actually terminate producer"
            );
            let holdout_before = fs::read(root.join("holdout.cas")).expect("holdout bytes");
            for invalid in ["expired", "revoked", "wrong-host"] {
                assert!(
                    child(&root, family, invalid, cut).success(),
                    "{family}/{invalid}/{cut}"
                );
            }
            let path = fs::read_dir(root.join("artifacts"))
                .expect("artifacts")
                .next()
                .expect("archive")
                .expect("entry")
                .path();
            let original = fs::read(&path).expect("archive bytes");
            let mut corrupt = original.clone();
            let last = corrupt.len() - 1;
            corrupt[last] ^= 1;
            fs::write(&path, corrupt).expect("inject corruption");
            assert!(child(&root, family, "corrupt", cut).success());
            fs::write(&path, original).expect("restore exact fixture bytes");
            assert!(
                child(&root, family, "recover", cut).success(),
                "{family}/recover/{cut}"
            );
            let published = fs::read(root.join("attempt.journal")).expect("published journal");
            assert!(child(&root, family, "reconcile", cut).success());
            assert_eq!(
                fs::read(root.join("attempt.journal")).expect("journal"),
                published,
                "read reconciliation must not append a duplicate terminal phase"
            );
            assert_eq!(
                fs::read(root.join("holdout.cas")).expect("holdout"),
                holdout_before,
                "no recovery process may rerun consumption or estimation"
            );
            fs::remove_dir_all(root).expect("remove fixture");
        }
    }
}

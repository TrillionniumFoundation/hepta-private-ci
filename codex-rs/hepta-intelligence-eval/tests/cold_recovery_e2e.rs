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

#[path = "selected_host_recovery_support/eligible_model.rs"]
mod outcome_model;
#[allow(dead_code)]
#[path = "selected_host_recovery_support/cold_temporal_model.rs"]
mod temporal_model;
#[path = "selected_host_recovery_support/cold_storage.rs"]
mod storage;
#[allow(dead_code)]
#[path = "selected_host_recovery_support/cold_trust.rs"]
mod host;
#[path = "selected_host_recovery_support/controller_tests.rs"]
mod controller_tests;

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
    let store = LockedFileFinalHoldoutCasStoreV1::create(
        storage::create(&root.join("holdout.cas")),
        namespace(),
    )
    .expect("create holdout store");
    let owner = FencedFinalHoldoutOwnerV1::initialize(store, namespace(), fence())
        .expect("create owner");
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner);
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::create(
        storage::create(&root.join("attempt.journal")),
        attempt_binding(),
        storage::DiskAnchor::new(&root.join("anchor"), Some(cut)),
    )
    .expect("create anchored journal");
    let attempt = host::id("cold-process-attempt");
    let context = host::context();
    let trust = host::activate();
    if family == "outcome" {
        let (plan, mut provider, roles) = outcome_model::fixture();
        let receipt = runner
            .evaluate_outcome_comparison(attempt.clone(), &plan, &mut provider, &mut journal)
            .expect("native multi-outcome estimation");
        storage::retain_holdout_anchor(
            &root.join("holdout.anchor"),
            runner.holdout_anchor(),
        );
        let bundle = runner
            .outcome_qualification_bundle(&receipt, &context)
            .expect("outcome bundle");
        let evidence = host::evidence(&bundle, &roles, None);
        let result = runner.qualify_outcomes_and_persist_on_selected_host(
            &attempt,
            &receipt,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &trust,
            85,
            &mut journal,
            root.join("artifacts"),
            root.join("publications"),
            host_binding(),
        );
        panic!("producer did not terminate at the requested native durability cut: {result:?}");
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
            .expect("native temporal estimation");
        storage::retain_holdout_anchor(
            &root.join("holdout.anchor"),
            runner.holdout_anchor(),
        );
        let bundle = runner
            .qualification_bundle(&receipt, &context)
            .expect("temporal bundle");
        let timing = longitudinal.then(|| host::timing(&bundle));
        let evidence = host::evidence(&bundle, &plan.metric_roles, timing.as_ref());
        let timing = match timing.as_ref() {
            Some(timing) => ProductTimingEvidenceV1::SystemLongitudinal {
                timing,
                minimum_window_micros: host::MINIMUM_WINDOW_MICROS,
            },
            None => ProductTimingEvidenceV1::Qualification,
        };
        let result = runner.qualify_and_persist_on_selected_host(
            &attempt,
            &receipt,
            &context,
            &evidence,
            timing,
            &trust,
            85,
            &mut journal,
            root.join("artifacts"),
            root.join("publications"),
            host_binding(),
        );
        panic!("producer did not terminate at the requested native durability cut: {result:?}");
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
    .expect("recover holdout bytes");
    let owner = FencedFinalHoldoutOwnerV1::recover(store, namespace(), fence())
        .expect("recover owner");
    let runner = RecordedProductEvaluationRunnerV1::new(owner);
    let mut journal = AnchoredProductEvaluationAttemptJournalV1::recover(
        storage::reopen(&root.join("attempt.journal")),
        attempt_binding(),
        storage::DiskAnchor::new(&root.join("anchor"), None),
    )
    .expect("recover anchored history");
    let attempt = host::id("cold-process-attempt");
    let before = journal.latest(&attempt).expect("before").expect("attempt");
    let result = if matches!(mode, "page-first" | "page-next") {
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
        .expect("read existing publication")
    } else {
        let trust = if mode == "revoked" {
            host::activate_revoked()
        } else {
            host::activate()
        };
        let binding = if mode == "wrong-host" {
            host::digest("wrong-host")
        } else {
            host_binding()
        };
        let now = if mode == "expired" { 91 } else { 85 };
        let result = if family == "outcome" {
            runner.recover_selected_host_outcome_qualification(
                &mut journal,
                &attempt,
                root.join("artifacts"),
                root.join("publications"),
                binding,
                &trust,
                now,
            )
        } else {
            runner.recover_selected_host_qualification(
                &mut journal,
                &attempt,
                root.join("artifacts"),
                root.join("publications"),
                binding,
                &trust,
                now,
            )
        };
        if matches!(mode, "revoked" | "expired" | "wrong-host" | "corrupt") {
            assert!(result.is_err(), "invalid recovery must not reach publication");
            assert_eq!(journal.latest(&attempt).expect("unchanged"), Some(before));
            assert_eq!(
                fs::read_dir(root.join("publications"))
                    .expect("publication directory")
                    .count(),
                0
            );
            return;
        }
        result.expect("cold decode and internal current signature verification")
    };
    use ProductEvaluationAttemptPhaseV1 as Phase;
    assert_eq!(result.transition.phase, Phase::Published);
    assert_eq!(
        fs::read_dir(root.join("publications"))
            .expect("publications")
            .count(),
        1
    );
    let history = journal.history(&attempt).expect("history");
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
    let mut child = Command::new(std::env::current_exe().expect("test executable"))
        .arg("--exact")
        .arg("cold_process_entry")
        .arg("--nocapture")
        .env("HEPTA_EVAL_COLD_TEST_ROOT", root)
        .env("HEPTA_EVAL_COLD_TEST_FAMILY", family)
        .env("HEPTA_EVAL_COLD_TEST_MODE", mode)
        .env("HEPTA_EVAL_COLD_TEST_CUT", cut.to_string())
        .spawn()
        .expect("start a fresh test process");
    let started = Instant::now();
    loop {
        if let Some(status) = child.try_wait().expect("observe child") {
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

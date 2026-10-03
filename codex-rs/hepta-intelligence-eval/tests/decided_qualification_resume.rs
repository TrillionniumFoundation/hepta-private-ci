//! Public prewrite recovery with real file-backed journals and signed inputs.
//! Keys, measurements and the faulting anchor are synthetic test fixtures, not
//! selected-host trust qualification or evidence of future-calendar efficacy.
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence_eval::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

#[allow(dead_code)]
#[path = "selected_host_recovery_support/cold_trust.rs"]
mod host;
#[path = "selected_host_recovery_support/eligible_model.rs"]
mod outcome_model;
#[allow(dead_code)]
#[path = "selected_host_recovery_support/security.rs"]
mod security;
#[allow(dead_code)]
#[path = "selected_host_recovery_support/cold_temporal_model.rs"]
mod temporal_model;

type FixtureResult<T> = Result<T, Box<dyn std::error::Error>>;
type Journal = AnchoredProductEvaluationAttemptJournalV1<security::FaultingAnchorStore>;
static NEXT_ROOT: AtomicU64 = AtomicU64::new(0);

struct Root(PathBuf);

impl Drop for Root {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn create(path: &Path) -> std::io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
}

struct Sink {
    requests: Vec<(Digest32, SignedEvaluationDecisionV1)>,
    path: PathBuf,
}

impl Sink {
    fn new(path: PathBuf) -> std::io::Result<Self> {
        create(&path)?;
        Ok(Self {
            requests: Vec::new(),
            path,
        })
    }
}

impl ProductQualificationEvidenceSinkV1 for Sink {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        // A deliberately small file-backed test sink lets rejected recovery
        // assert byte identity as well as the absence of publication calls.
        let mut bytes = execution.as_array().to_vec();
        for digest in [
            decision.decision.evidence_digest,
            decision.trust_digest,
            decision.authentication_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        fs::write(&self.path, bytes).map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        self.requests.push((execution, decision.clone()));
        Ok(host::digest("synthetic-publication"))
    }
}

struct Fixture {
    runner: RecordedProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    journal: Option<Journal>,
    anchor: security::FaultingAnchorStore,
    attempt: StableId,
    root: Root,
}

impl Fixture {
    fn new() -> FixtureResult<Self> {
        let ordinal = NEXT_ROOT.fetch_add(1, Ordering::Relaxed);
        let root = Root(std::env::temp_dir().join(format!(
            "hepta-decided-resume-{}-{ordinal}",
            std::process::id()
        )));
        fs::create_dir(&root.0)?;
        let namespace = host::digest("resume-fixture-namespace");
        let store =
            LockedFileFinalHoldoutCasStoreV1::create(create(&root.0.join("holdout"))?, namespace)?;
        let runner = RecordedProductEvaluationRunnerV1::new(FencedFinalHoldoutOwnerV1::initialize(
            store,
            namespace,
            HoldoutWriterFenceV1 {
                owner_id: host::id("resume-fixture-owner")?,
                generation: 1,
                lease_digest: host::digest("resume-fixture-lease"),
            },
        )?);
        // The real journal fsyncs QualificationDecided before this fixture loses
        // its fifth anchor acknowledgement. PublicationPending is never written.
        let anchor = security::FaultingAnchorStore::new(/*fail_once_at_event_count*/ 5);
        let journal = AnchoredProductEvaluationAttemptJournalV1::create(
            create(&root.0.join("journal"))?,
            host::digest("resume-fixture-journal"),
            anchor.clone(),
        )?;
        Ok(Self {
            runner,
            journal: Some(journal),
            anchor,
            attempt: host::id("resume-fixture-attempt")?,
            root,
        })
    }

    fn recover(&mut self) -> FixtureResult<Journal> {
        drop(self.journal.take());
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.0.join("journal"))?;
        let mut journal = AnchoredProductEvaluationAttemptJournalV1::recover(
            file,
            host::digest("resume-fixture-journal"),
            self.anchor.clone(),
        )?;
        assert_eq!(
            journal
                .latest(&self.attempt)?
                .ok_or("missing attempt")?
                .transition
                .phase,
            ProductEvaluationAttemptPhaseV1::QualificationDecided
        );
        Ok(journal)
    }

    fn bytes(&self) -> FixtureResult<Vec<Vec<u8>>> {
        ["journal", "holdout", "publication"]
            .into_iter()
            .map(|name| fs::read(self.root.0.join(name)).map_err(Into::into))
            .collect()
    }
}

#[test]
fn temporal_resume_reverifies_signatures_and_publishes_exactly_once() -> FixtureResult<()> {
    let mut fixture = Fixture::new()?;
    let (plan, candidate, baseline, mut provider) =
        temporal_model::fixture(/*longitudinal*/ false)?;
    let temporal = fixture.runner.evaluate_temporal_comparison(
        fixture.attempt.clone(),
        &plan,
        &candidate,
        &baseline,
        &mut provider,
        fixture.journal.as_mut().ok_or("journal")?,
    )?;
    let context = host::context()?;
    let bundle = fixture.runner.qualification_bundle(&temporal, &context)?;
    let evidence = host::evidence(&bundle, &plan.metric_roles, /*timing*/ None)?;
    let verifier = host::verifier(/*revoked*/ false)?;
    let mut sink = Sink::new(fixture.root.0.join("publication"))?;
    let interrupted = fixture.runner.qualify_and_persist_with_artifacts(
        &fixture.attempt,
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &verifier,
        /*now*/ 85,
        fixture.journal.as_mut().ok_or("journal")?,
        fixture.root.0.join("artifacts"),
        host::digest("fixture-host"),
        &mut sink,
    );
    assert!(matches!(
        interrupted,
        Err(RecordedProductEvaluationErrorV1::Journal(
            ProductEvaluationAttemptJournalErrorV1::Indeterminate
        ))
    ));
    assert!(sink.requests.is_empty());
    let mut journal = fixture.recover()?;
    let before = fixture.bytes()?;
    let before_history = journal.history(&fixture.attempt)?;

    for now in [/*not yet valid*/ 79, /*expired*/ 91] {
        assert!(matches!(
            fixture.runner.resume_decided_qualification(
                &mut journal,
                &fixture.attempt,
                &temporal,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                now,
                &mut sink,
            ),
            Err(RecordedProductEvaluationErrorV1::Evaluation(
                ProductEvaluationError::Signed(_)
            ))
        ));
        assert_eq!(fixture.bytes()?, before);
        assert_eq!(journal.history(&fixture.attempt)?, before_history);
        assert!(sink.requests.is_empty());
    }
    let mut tampered = evidence.clone();
    tampered.evaluator_bundle.signature[0] ^= 1;
    assert!(matches!(
        fixture.runner.resume_decided_qualification(
            &mut journal,
            &fixture.attempt,
            &temporal,
            &context,
            &tampered,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            /*now*/ 85,
            &mut sink,
        ),
        Err(RecordedProductEvaluationErrorV1::Evaluation(
            ProductEvaluationError::Signed(_)
        ))
    ));
    assert_eq!(fixture.bytes()?, before);
    assert_eq!(journal.history(&fixture.attempt)?, before_history);
    assert!(sink.requests.is_empty());

    let mut wrong_execution = temporal.clone();
    wrong_execution.execution_digest = host::digest("substituted-execution");
    assert!(matches!(
        fixture.runner.resume_decided_qualification(
            &mut journal,
            &fixture.attempt,
            &wrong_execution,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            /*now*/ 85,
            &mut sink,
        ),
        Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { .. })
    ));
    assert_eq!(fixture.bytes()?, before);
    assert_eq!(journal.history(&fixture.attempt)?, before_history);
    assert!(sink.requests.is_empty());

    let receipt = fixture.runner.resume_decided_qualification(
        &mut journal,
        &fixture.attempt,
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &verifier,
        /*now*/ 85,
        &mut sink,
    )?;
    receipt.validate_integrity()?;
    assert_eq!(
        receipt.transition.phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    assert_eq!(
        receipt.transition.terminal_digest,
        host::digest("synthetic-publication")
    );
    assert_eq!(sink.requests.len(), 1);
    let (execution, decision) = &sink.requests[0];
    assert_eq!(*execution, temporal.execution_digest);
    assert_eq!(
        (
            &decision.decision.candidate_id,
            &decision.decision.baseline_id,
            decision.trust_digest
        ),
        (
            &bundle.candidate_id,
            &bundle.baseline_id,
            verifier.trust_digest()
        )
    );
    assert_eq!(
        decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(!decision.decision.authority.grants_any());
    assert!(!receipt.authority.grants_any());
    assert_eq!(
        journal.history(&fixture.attempt)?.len(),
        before_history.len() + 2
    );
    let published_bytes = fixture.bytes()?;
    assert!(matches!(
        fixture.runner.resume_decided_qualification(
            &mut journal,
            &fixture.attempt,
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            /*now*/ 85,
            &mut sink,
        ),
        Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { .. })
    ));
    assert_eq!(fixture.bytes()?, published_bytes);
    assert_eq!(sink.requests.len(), 1);
    Ok(())
}

#[test]
fn longitudinal_resume_requires_the_original_scope_and_observer_window() -> FixtureResult<()> {
    let mut fixture = Fixture::new()?;
    let (plan, candidate, baseline, mut provider) =
        temporal_model::fixture(/*longitudinal*/ true)?;
    let temporal = fixture.runner.evaluate_temporal_comparison(
        fixture.attempt.clone(),
        &plan,
        &candidate,
        &baseline,
        &mut provider,
        fixture.journal.as_mut().ok_or("journal")?,
    )?;
    let context = host::context()?;
    let bundle = fixture.runner.qualification_bundle(&temporal, &context)?;
    let timing = host::timing(&bundle)?;
    let evidence = host::evidence(&bundle, &plan.metric_roles, Some(&timing))?;
    let verifier = host::verifier(/*revoked*/ false)?;
    let as_timing = || ProductTimingEvidenceV1::SystemLongitudinal {
        timing: &timing,
        minimum_window_micros: host::MINIMUM_WINDOW_MICROS,
    };
    let mut sink = Sink::new(fixture.root.0.join("publication"))?;
    let interrupted = fixture.runner.qualify_and_persist_with_artifacts(
        &fixture.attempt,
        &temporal,
        &context,
        &evidence,
        as_timing(),
        &verifier,
        /*now*/ 85,
        fixture.journal.as_mut().ok_or("journal")?,
        fixture.root.0.join("artifacts"),
        host::digest("fixture-host"),
        &mut sink,
    );
    assert!(matches!(
        interrupted,
        Err(RecordedProductEvaluationErrorV1::Journal(
            ProductEvaluationAttemptJournalErrorV1::Indeterminate
        ))
    ));
    let mut journal = fixture.recover()?;
    let before = fixture.bytes()?;
    let history = journal.history(&fixture.attempt)?;
    assert!(matches!(
        fixture.runner.resume_decided_qualification(
            &mut journal,
            &fixture.attempt,
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            /*now*/ 85,
            &mut sink,
        ),
        Err(RecordedProductEvaluationErrorV1::Evaluation(
            ProductEvaluationError::Binding("recovery qualification scope")
        ))
    ));
    assert_eq!(fixture.bytes()?, before);
    assert_eq!(journal.history(&fixture.attempt)?, history);
    assert!(sink.requests.is_empty());
    let mut changed = timing.clone();
    changed.windows[0].observed_source_cut = host::digest("substituted-observation");
    assert!(matches!(
        fixture.runner.resume_decided_qualification(
            &mut journal,
            &fixture.attempt,
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing: &changed,
                minimum_window_micros: host::MINIMUM_WINDOW_MICROS,
            },
            &verifier,
            /*now*/ 85,
            &mut sink,
        ),
        Err(RecordedProductEvaluationErrorV1::Evaluation(
            ProductEvaluationError::Signed(_)
        ))
    ));
    assert_eq!(fixture.bytes()?, before);
    assert_eq!(journal.history(&fixture.attempt)?, history);
    assert!(sink.requests.is_empty());
    let receipt = fixture.runner.resume_decided_qualification(
        &mut journal,
        &fixture.attempt,
        &temporal,
        &context,
        &evidence,
        as_timing(),
        &verifier,
        /*now*/ 85,
        &mut sink,
    )?;
    assert_eq!(
        receipt.transition.phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    assert_eq!(sink.requests.len(), 1);
    assert_eq!(sink.requests[0].0, temporal.execution_digest);
    assert!(!receipt.authority.grants_any());
    Ok(())
}

#[test]
fn outcome_resume_uses_the_sealed_multi_channel_execution() -> FixtureResult<()> {
    let mut fixture = Fixture::new()?;
    let (plan, mut provider, roles) = outcome_model::fixture()?;
    let temporal = fixture.runner.evaluate_outcome_comparison(
        fixture.attempt.clone(),
        &plan,
        &mut provider,
        fixture.journal.as_mut().ok_or("journal")?,
    )?;
    let context = host::context()?;
    let bundle = fixture
        .runner
        .outcome_qualification_bundle(&temporal, &context)?;
    let evidence = host::evidence(&bundle, &roles, /*timing*/ None)?;
    let verifier = host::verifier(/*revoked*/ false)?;
    let mut sink = Sink::new(fixture.root.0.join("publication"))?;
    let interrupted = fixture.runner.qualify_outcomes_and_persist_with_artifacts(
        &fixture.attempt,
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &verifier,
        /*now*/ 85,
        fixture.journal.as_mut().ok_or("journal")?,
        fixture.root.0.join("artifacts"),
        host::digest("fixture-host"),
        &mut sink,
    );
    assert!(matches!(
        interrupted,
        Err(RecordedProductEvaluationErrorV1::Journal(
            ProductEvaluationAttemptJournalErrorV1::Indeterminate
        ))
    ));
    let mut journal = fixture.recover()?;
    let before = fixture.bytes()?;
    let history = journal.history(&fixture.attempt)?;
    assert!(matches!(
        fixture.runner.resume_decided_outcome_qualification(
            &mut journal,
            &fixture.attempt,
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            /*now*/ 91,
            &mut sink,
        ),
        Err(RecordedProductEvaluationErrorV1::Evaluation(
            ProductEvaluationError::Signed(_)
        ))
    ));
    assert_eq!(fixture.bytes()?, before);
    assert_eq!(journal.history(&fixture.attempt)?, history);
    assert!(sink.requests.is_empty());
    let receipt = fixture.runner.resume_decided_outcome_qualification(
        &mut journal,
        &fixture.attempt,
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &verifier,
        /*now*/ 85,
        &mut sink,
    )?;
    assert_eq!(
        receipt.transition.phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    assert_eq!(sink.requests.len(), 1);
    let (execution, decision) = &sink.requests[0];
    assert_eq!(*execution, temporal.execution_digest());
    assert_eq!(
        (
            &decision.decision.candidate_id,
            &decision.decision.baseline_id,
            decision.trust_digest
        ),
        (
            &bundle.candidate_id,
            &bundle.baseline_id,
            verifier.trust_digest()
        )
    );
    assert_eq!(
        decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(!decision.decision.authority.grants_any());
    assert!(!receipt.authority.grants_any());
    let published_bytes = fixture.bytes()?;
    assert!(matches!(
        fixture.runner.resume_decided_outcome_qualification(
            &mut journal,
            &fixture.attempt,
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            /*now*/ 85,
            &mut sink,
        ),
        Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { .. })
    ));
    assert_eq!(fixture.bytes()?, published_bytes);
    assert_eq!(sink.requests.len(), 1);
    Ok(())
}

#[test]
fn publication_pending_is_not_retried_by_prewrite_resume() -> FixtureResult<()> {
    let mut fixture = Fixture::new()?;
    let (plan, candidate, baseline, mut provider) =
        temporal_model::fixture(/*longitudinal*/ false)?;
    let temporal = fixture.runner.evaluate_temporal_comparison(
        fixture.attempt.clone(),
        &plan,
        &candidate,
        &baseline,
        &mut provider,
        fixture.journal.as_mut().ok_or("journal")?,
    )?;
    let context = host::context()?;
    let bundle = fixture.runner.qualification_bundle(&temporal, &context)?;
    let evidence = host::evidence(&bundle, &plan.metric_roles, /*timing*/ None)?;
    let verifier = host::verifier(/*revoked*/ false)?;
    let mut sink = Sink::new(fixture.root.0.join("publication"))?;
    let interrupted = fixture.runner.qualify_and_persist_with_artifacts(
        &fixture.attempt,
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &verifier,
        /*now*/ 85,
        fixture.journal.as_mut().ok_or("journal")?,
        fixture.root.0.join("artifacts"),
        host::digest("fixture-host"),
        &mut sink,
    );
    assert!(matches!(
        interrupted,
        Err(RecordedProductEvaluationErrorV1::Journal(
            ProductEvaluationAttemptJournalErrorV1::Indeterminate
        ))
    ));
    let mut journal = fixture.recover()?;
    let decided = journal.latest(&fixture.attempt)?.ok_or("decision")?;
    // Model the durable write-ahead boundary at which a sink write may already
    // have happened. Prewrite resume cannot use an empty sink as proof otherwise.
    journal.append(ProductEvaluationAttemptTransitionV1 {
        phase: ProductEvaluationAttemptPhaseV1::PublicationPending,
        ..decided.transition
    })?;
    let before = fixture.bytes()?;
    let history = journal.history(&fixture.attempt)?;
    for _ in 0..2 {
        assert!(matches!(
            fixture.runner.resume_decided_qualification(
                &mut journal,
                &fixture.attempt,
                &temporal,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                /*now*/ 85,
                &mut sink,
            ),
            Err(RecordedProductEvaluationErrorV1::AttemptRequiresRecovery { .. })
        ));
        assert_eq!(fixture.bytes()?, before);
        assert_eq!(journal.history(&fixture.attempt)?, history);
        assert!(sink.requests.is_empty());
    }
    Ok(())
}

//! Actual child-process kill tests, using real file journals and real estimation.
//! Local retained-anchor files are fixtures, not independent-host qualification.
use super::*;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use crate::IndependentEvaluationDecisionV1;
use crate::IndependentEvaluationDispositionV1;
use crate::LockedFileFinalHoldoutCasStoreV1;
use crate::LockedFileProductEvaluationAttemptJournalV1;
use crate::ProductEvaluationAttemptAnchorV1;
use crate::ProductQualificationPublicationRecordV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductQualificationPublicationStoreErrorV1;
use crate::ProductQualificationPublicationStoreV1;
use crate::ReconciledProductQualificationSinkV1;
use crate::SignedEvaluationDecisionV1;
use crate::recorded_publication::RecordedPublicationSinkV1;

const STAGE: &str = "HEPTA_LEARNING_EVAL_CRASH_STAGE";
const ROOT: &str = "HEPTA_LEARNING_EVAL_CRASH_ROOT";

fn create(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(path)
        .expect("new fixture file")
}

fn reopen(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("reopen fixture file")
}

fn sync_write(path: &Path, bytes: &[u8]) {
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(path)
        .expect("fixture write");
    file.write_all(bytes).expect("write bytes");
    file.sync_all().expect("sync fixture");
    File::open(path.parent().expect("parent"))
        .expect("open directory")
        .sync_all()
        .expect("sync directory");
}

fn barrier(root: &Path) -> ! {
    sync_write(&root.join("ready"), b"durable-cut-reached");
    loop {
        thread::sleep(Duration::from_millis(20));
    }
}

fn publication_decision() -> SignedEvaluationDecisionV1 {
    SignedEvaluationDecisionV1 {
        decision: IndependentEvaluationDecisionV1 {
            evaluation_id: id("evaluation"),
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            disposition: IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            failed_metrics: Vec::new(),
            evidence_digest: digest("decision"),
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        },
        trust_digest: digest("trust"),
        authentication_digest: digest("authentication"),
    }
}

fn save_attempt_anchor(root: &Path, anchor: ProductEvaluationAttemptAnchorV1) {
    let mut bytes = anchor.binding.as_array().to_vec();
    bytes.extend_from_slice(&anchor.event_count.to_be_bytes());
    bytes.extend_from_slice(anchor.state_digest.as_array());
    sync_write(&root.join("attempt.anchor"), &bytes);
}

fn load_attempt_anchor(root: &Path) -> ProductEvaluationAttemptAnchorV1 {
    let bytes = fs::read(root.join("attempt.anchor")).expect("retained anchor");
    assert_eq!(bytes.len(), 72);
    ProductEvaluationAttemptAnchorV1 {
        binding: Digest32::from_array(bytes[..32].try_into().expect("binding")),
        event_count: u64::from_be_bytes(bytes[32..40].try_into().expect("count")),
        state_digest: Digest32::from_array(bytes[40..].try_into().expect("digest")),
    }
}

struct CrashCas {
    inner: LockedFileFinalHoldoutCasStoreV1,
    root: PathBuf,
    stage: String,
}

impl FinalHoldoutCasStoreV1 for CrashCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        self.inner.load(binding)
    }
    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        self.inner.compare_and_swap(binding, expected, next)?;
        let anchor = self.inner.anchor().expect("committed holdout anchor");
        let mut bytes = anchor.fence_generation.to_be_bytes().to_vec();
        bytes.extend_from_slice(&anchor.record_count.to_be_bytes());
        bytes.extend_from_slice(anchor.state_digest.as_array());
        sync_write(&self.root.join("holdout.anchor"), &bytes);
        if !next.journal.records.is_empty() && self.stage == "consume_before_attempt" {
            barrier(&self.root);
        }
        Ok(())
    }
}

struct CrashJournal {
    inner: LockedFileProductEvaluationAttemptJournalV1,
    root: PathBuf,
    stage: String,
}

impl ProductEvaluationAttemptJournalV1 for CrashJournal {
    fn append(
        &mut self,
        transition: ProductEvaluationAttemptTransitionV1,
    ) -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1> {
        if transition.phase == ProductEvaluationAttemptPhaseV1::ComparisonSealed
            && self.stage == "computed_before_seal"
        {
            // Reached only after the actual temporal estimator returned.
            barrier(&self.root);
        }
        let phase = transition.phase;
        let receipt = self.inner.append(transition)?;
        save_attempt_anchor(&self.root, self.inner.anchor()?);
        if matches!(
            (phase, self.stage.as_str()),
            (
                ProductEvaluationAttemptPhaseV1::HoldoutConsumed,
                "consumed_before_release"
            ) | (
                ProductEvaluationAttemptPhaseV1::ComparisonSealed,
                "sealed_before_publication"
            ) | (
                ProductEvaluationAttemptPhaseV1::QualificationDecided,
                "decided_before_pending"
            ) | (
                ProductEvaluationAttemptPhaseV1::PublicationPending,
                "pending_before_write"
            )
        ) {
            barrier(&self.root);
        }
        Ok(receipt)
    }
    fn latest(
        &mut self,
        attempt: &StableId,
    ) -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.inner.latest(attempt)
    }
    fn history(
        &mut self,
        attempt: &StableId,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.inner.history(attempt)
    }
    fn pending(
        &mut self,
        after: Option<&StableId>,
        limit: usize,
    ) -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        self.inner.pending(after, limit)
    }
}

/// One-key immutable store fixture. It is deliberately not exported as a host.
struct FilePublicationFixture {
    root: PathBuf,
    kill_after_commit: bool,
}

impl ProductQualificationPublicationStoreV1 for FilePublicationFixture {
    fn load(
        &mut self,
        execution: Digest32,
    ) -> Result<
        Option<ProductQualificationPublicationRecordV1>,
        ProductQualificationPublicationStoreErrorV1,
    > {
        let bytes = match fs::read(self.root.join("publication")) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(ProductQualificationPublicationStoreErrorV1::Unavailable),
        };
        if bytes.len() != 7 * 32 {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        let values: Vec<_> = bytes
            .chunks_exact(32)
            .map(|chunk| Digest32::from_array(chunk.try_into().expect("digest")))
            .collect();
        let record = ProductQualificationPublicationRecordV1 {
            request: ProductQualificationPublicationRequestV1 {
                execution_digest: values[0],
                decision_evidence_digest: values[1],
                trust_digest: values[2],
                authentication_digest: values[3],
                request_digest: values[4],
            },
            publication_digest: values[5],
            record_digest: values[6],
        };
        record.validate()?;
        if record.request.execution_digest != execution {
            return Err(ProductQualificationPublicationStoreErrorV1::Conflict);
        }
        Ok(Some(record))
    }
    fn compare_and_publish(
        &mut self,
        expected: Option<Digest32>,
        request: &ProductQualificationPublicationRequestV1,
    ) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>
    {
        let mut writes = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.root.join("writes"))
            .expect("write counter");
        writes.write_all(b"W").expect("count write");
        writes.sync_all().expect("sync count");
        if expected.is_some() {
            return Err(ProductQualificationPublicationStoreErrorV1::Conflict);
        }
        let record = ProductQualificationPublicationRecordV1::new(
            request.clone(),
            digest("durable-publication"),
        )?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(self.root.join("publication"))
            .map_err(|_| ProductQualificationPublicationStoreErrorV1::Conflict)?;
        for value in [
            request.execution_digest,
            request.decision_evidence_digest,
            request.trust_digest,
            request.authentication_digest,
            request.request_digest,
            record.publication_digest,
            record.record_digest,
        ] {
            file.write_all(value.as_array())
                .map_err(|_| ProductQualificationPublicationStoreErrorV1::Indeterminate)?;
        }
        file.sync_all()
            .map_err(|_| ProductQualificationPublicationStoreErrorV1::Indeterminate)?;
        File::open(&self.root)
            .expect("directory")
            .sync_all()
            .expect("sync directory");
        if self.kill_after_commit {
            barrier(&self.root);
        }
        Ok(record)
    }
}

#[test]
fn product_process_worker() {
    let Ok(stage) = std::env::var(STAGE) else {
        return;
    };
    let root = PathBuf::from(std::env::var(ROOT).expect("child root"));
    let store = CrashCas {
        inner: LockedFileFinalHoldoutCasStoreV1::create(
            create(&root.join("holdout")),
            digest("namespace"),
        )
        .expect("holdout file"),
        root: root.clone(),
        stage: stage.clone(),
    };
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        store,
        digest("namespace"),
        HoldoutWriterFenceV1 {
            owner_id: id("owner"),
            generation: 1,
            lease_digest: digest("lease"),
        },
    )
    .expect("initialize");
    let inner = LockedFileProductEvaluationAttemptJournalV1::create(
        create(&root.join("attempt")),
        digest("attempt-binding"),
    )
    .expect("attempt file");
    save_attempt_anchor(&root, inner.anchor().expect("initial anchor"));
    let mut journal = CrashJournal {
        inner,
        root: root.clone(),
        stage: stage.clone(),
    };
    let mut runner = RecordedProductEvaluationRunnerV1::new(owner);
    let (plan, candidate, baseline) = product_plan();
    let mut provider = Provider {
        manifest_calls: 0,
        release_calls: 0,
        inputs: Some(inputs()),
    };
    let temporal = runner
        .evaluate_temporal_comparison(
            id("attempt"),
            &plan,
            &candidate,
            &baseline,
            &mut provider,
            &mut journal,
        )
        .expect("real estimate");
    // This second half isolates the production publication adapter boundary;
    // signature verification has its separate signed-product E2E qualification.
    let decision = publication_decision();
    let mut sink = ReconciledProductQualificationSinkV1::new(FilePublicationFixture {
        root: root.clone(),
        kill_after_commit: stage == "publication_ack_lost",
    });
    let mut recorded = RecordedPublicationSinkV1 {
        attempt_id: id("attempt"),
        plan_digest: plan.frozen_plan.plan_digest,
        holdout_record_digest: temporal.holdout.record_digest,
        journal: &mut journal,
        inner: &mut sink,
        journal_error: None,
    };
    recorded
        .persist(temporal.execution_digest, &decision)
        .expect("publication");
    panic!("requested cut {stage} was not reached");
}

#[test]
fn process_kill_boundaries_recover_without_releasing_or_republishing() {
    for stage in [
        "consume_before_attempt",
        "consumed_before_release",
        "computed_before_seal",
        "sealed_before_publication",
        "decided_before_pending",
        "pending_before_write",
        "publication_ack_lost",
    ] {
        let marker = tempfile::NamedTempFile::new().expect("unique test root marker");
        let root = marker.path().with_extension("crash-fixture");
        fs::create_dir(&root).expect("isolated root");
        let mut child = Command::new(std::env::current_exe().expect("test binary"))
            .args([
                "--exact",
                "recorded_runner::tests::process_tests::product_process_worker",
                "--nocapture",
            ])
            .env(STAGE, stage)
            .env(ROOT, &root)
            .spawn()
            .expect("spawn isolated child");
        let deadline = Instant::now() + Duration::from_secs(30);
        while !root.join("ready").exists() {
            if let Some(status) = child.try_wait().expect("inspect child") {
                panic!("child exited before {stage}: {status}");
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("child did not reach {stage}");
            }
            thread::sleep(Duration::from_millis(10));
        }
        child
            .kill()
            .expect("kill only the isolated fault-injection child");
        assert!(!child.wait().expect("reap child").success());
        let mut journal = LockedFileProductEvaluationAttemptJournalV1::recover_with_anchor(
            reopen(&root.join("attempt")),
            digest("attempt-binding"),
            load_attempt_anchor(&root),
        )
        .expect("recover anchored journal");
        let bytes = fs::read(root.join("holdout.anchor")).expect("retained holdout anchor");
        assert_eq!(bytes.len(), 48);
        let anchor = FinalHoldoutCasAnchorV1 {
            fence_generation: u64::from_be_bytes(bytes[..8].try_into().expect("generation")),
            record_count: u64::from_be_bytes(bytes[8..16].try_into().expect("count")),
            state_digest: Digest32::from_array(bytes[16..].try_into().expect("state")),
        };
        let mut store = LockedFileFinalHoldoutCasStoreV1::recover(
            reopen(&root.join("holdout")),
            digest("namespace"),
            Some(anchor),
        )
        .expect("recover consumed holdout");
        if stage == "consume_before_attempt" {
            crate::reconcile_product_attempt_holdout_v1(&mut journal, &mut store, &id("attempt"))
                .expect("associate committed consumption");
        }
        assert_eq!(
            store
                .load(digest("namespace"))
                .expect("load")
                .expect("owner")
                .journal
                .records
                .len(),
            1
        );
        if stage == "publication_ack_lost" {
            let before = fs::read(root.join("writes")).expect("one attempted publication");
            assert_eq!(before, b"W");
            let mut sink = FilePublicationFixture {
                root: root.clone(),
                kill_after_commit: false,
            };
            let published = crate::reconcile_product_attempt_publication_v1(
                &mut journal,
                &mut sink,
                &id("attempt"),
            )
            .expect("read-only owner reconciliation");
            assert_eq!(
                published.transition.phase,
                ProductEvaluationAttemptPhaseV1::Published
            );
            assert_eq!(fs::read(root.join("writes")).expect("write count"), before);
        } else if stage == "pending_before_write" {
            let mut sink = FilePublicationFixture {
                root: root.clone(),
                kill_after_commit: false,
            };
            assert_eq!(
                crate::reconcile_product_attempt_publication_v1(
                    &mut journal,
                    &mut sink,
                    &id("attempt")
                ),
                Err(crate::ProductAttemptRecoveryErrorV1::Unresolved)
            );
            assert!(!root.join("writes").exists());
        } else if stage == "decided_before_pending" {
            assert!(!root.join("writes").exists());
            let mut sink = ReconciledProductQualificationSinkV1::new(FilePublicationFixture {
                root: root.clone(),
                kill_after_commit: false,
            });
            // The original full decision is reconstructed from an immutable
            // fixture here. This is not a production evidence-archive claim.
            let decision = publication_decision();
            let mut altered = publication_decision();
            altered.authentication_digest = digest("different-authentication");
            assert!(RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::resume_decided_publication(
                &mut journal, &id("attempt"), &altered, &mut sink,
            ).is_err());
            assert!(!root.join("writes").exists());
            let published = RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::resume_decided_publication(
                &mut journal, &id("attempt"), &decision, &mut sink,
            ).expect("first publication after decided-only crash");
            assert_eq!(
                published.transition.phase,
                ProductEvaluationAttemptPhaseV1::Published
            );
            assert_eq!(
                fs::read(root.join("writes")).expect("one publication"),
                b"W"
            );
            assert!(RecordedProductEvaluationRunnerV1::<LockedFileFinalHoldoutCasStoreV1>::resume_decided_publication(
                &mut journal, &id("attempt"), &decision, &mut sink,
            ).is_err());
            assert_eq!(fs::read(root.join("writes")).expect("no duplicate"), b"W");
        }
        let owner = FencedFinalHoldoutOwnerV1::recover(
            store,
            digest("namespace"),
            HoldoutWriterFenceV1 {
                owner_id: id("recovery-owner"),
                generation: 2,
                lease_digest: digest("recovery-lease"),
            },
        )
        .expect("fenced takeover");
        let mut runner = RecordedProductEvaluationRunnerV1::new(owner);
        let (plan, candidate, baseline) = product_plan();
        let mut provider = Provider {
            manifest_calls: 0,
            release_calls: 0,
            inputs: Some(inputs()),
        };
        let mut wrong_new_journal = InMemoryProductEvaluationAttemptJournalV1::default();
        assert!(
            runner
                .evaluate_temporal_comparison(
                    id("new-attempt"),
                    &plan,
                    &candidate,
                    &baseline,
                    &mut provider,
                    &mut wrong_new_journal
                )
                .is_err()
        );
        assert_eq!(
            provider.release_calls, 0,
            "holdout must not be rereleased at {stage}"
        );
        drop(runner);
        drop(journal);
        fs::remove_dir_all(&root).expect("remove isolated fixture");
    }
}

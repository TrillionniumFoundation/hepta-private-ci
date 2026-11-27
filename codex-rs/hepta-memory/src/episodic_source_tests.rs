use std::sync::atomic::Ordering;

use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use super::AdmittedEpisodicSnapshot;
use super::EpisodicSnapshotAdmission;
use super::EpisodicSnapshotVerifier;
use crate::CognitiveScope;
use crate::MemoryVerification;
use crate::episodic_test_support::GOLDEN;
use crate::episodic_test_support::INCOMPLETE_DEPENDENCY;
use crate::episodic_test_support::SourceWitness;
use crate::episodic_test_support::TestResult;
use crate::episodic_test_support::UNICODE;

#[test]
fn admits_actual_python_unicode_export_with_exact_original_observations() -> TestResult {
    let witness = SourceWitness::current(UNICODE);
    let admitted =
        AdmittedEpisodicSnapshot::admit(UNICODE, &CognitiveScope::AgentPrivate, &witness)?;
    assert_eq!(
        admitted.snapshot.sha256,
        "fb4e834f9e8d6cec04fcbbfa7c20b11f7f42aac1e9385754d336e2825581032e"
    );
    assert_eq!(
        admitted.snapshot.body.records[0].text,
        "更新：蓝色路径 café 🚀\n保留事实，而不是执行指令。"
    );
    assert_eq!(admitted.admitted, witness.admitted);
    admitted.revalidate()?;
    Ok(())
}

#[test]
fn a_valid_digest_cannot_replace_missing_or_different_source_admission() {
    let mut missing = SourceWitness::current(GOLDEN);
    missing.admitted.records.clear();
    let mut different = SourceWitness::current(GOLDEN);
    different
        .admitted
        .records
        .values_mut()
        .next()
        .expect("record")
        .source
        .content = b"unrelated original bytes".to_vec();
    let mut foreign_scope = SourceWitness::current(GOLDEN);
    foreign_scope.authorize_withdrawal();
    foreign_scope
        .admitted
        .withdrawal
        .as_mut()
        .expect("withdrawal")
        .scope = CognitiveScope::WorkspacePrivate {
        workspace_sha256: Sha256Digest::for_bytes(b"another-workspace"),
    };
    for witness in [missing, different, foreign_scope] {
        assert!(
            AdmittedEpisodicSnapshot::admit(GOLDEN, &CognitiveScope::AgentPrivate, &witness)
                .is_err()
        );
    }
    let incomplete = SourceWitness::current(INCOMPLETE_DEPENDENCY);
    assert!(
        AdmittedEpisodicSnapshot::admit(
            INCOMPLETE_DEPENDENCY,
            &CognitiveScope::AgentPrivate,
            &incomplete
        )
        .is_err()
    );
    assert_eq!(incomplete.checks.load(Ordering::SeqCst), 0);
}

#[test]
fn final_source_check_detects_changed_observation_metadata() -> TestResult {
    struct ChangedObservation(SourceWitness);
    impl EpisodicSnapshotVerifier for ChangedObservation {
        fn verify_current(&self, input: &str) -> Result<EpisodicSnapshotAdmission, String> {
            let mut result = self.0.verify_current(input)?;
            if self.0.checks.load(Ordering::SeqCst) > 1 {
                result
                    .records
                    .values_mut()
                    .next()
                    .expect("record")
                    .source
                    .observed_at_unix_seconds += 1;
            }
            Ok(result)
        }
    }
    let witness = ChangedObservation(SourceWitness::current(GOLDEN));
    let admitted =
        AdmittedEpisodicSnapshot::admit(GOLDEN, &CognitiveScope::AgentPrivate, &witness)?;
    assert!(admitted.revalidate().is_err());
    Ok(())
}

#[test]
fn provisional_admission_remains_distinct_from_verified_source_admission() -> TestResult {
    let verified = SourceWitness::current(GOLDEN);
    let mut provisional = SourceWitness::current(GOLDEN);
    provisional
        .admitted
        .records
        .values_mut()
        .next()
        .expect("record")
        .verification = MemoryVerification::Provisional;
    let admitted_verified =
        AdmittedEpisodicSnapshot::admit(GOLDEN, &CognitiveScope::AgentPrivate, &verified)?;
    let admitted_provisional =
        AdmittedEpisodicSnapshot::admit(GOLDEN, &CognitiveScope::AgentPrivate, &provisional)?;
    assert_eq!(admitted_provisional.admitted, provisional.admitted);
    assert_ne!(
        admitted_verified.admission_sha256,
        admitted_provisional.admission_sha256
    );
    Ok(())
}

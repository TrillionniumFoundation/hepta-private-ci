use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_types::Digest32;

use super::prepare;
use super::test_support::LedgerFixture;
use super::test_support::digest;
use super::test_support::id;

#[test]
fn memory_training_ledger_retains_signed_candidate_and_independent_outcome_after_recovery() {
    let fixture = LedgerFixture::new();
    // Fixed evidence exercises the real ledger bridge; the ignored NumPy test
    // separately calls the public factory with an actual opaque trained result.
    let prepared = prepare(fixture.context("ledger-integration"), digest("real-owner-cut-test"),
        digest("code-test"), digest("fit-receipt-test"), digest("bundle-test")).unwrap();
    let signed = fixture.sign("generator", LearningEvidenceRoleV1::Generator, &prepared.signing_payload().unwrap());
    let first = fixture.sink.append_training(Digest32::ZERO, &prepared, &signed, /*now*/ 50).unwrap();
    let retry = fixture.sink.append_training(Digest32::ZERO, &prepared, &signed, /*now*/ 50).unwrap();
    assert_eq!((retry.event_digest, retry.disposition), (first.event_digest, AppendDisposition::IdempotentReplay));
    assert_eq!(prepared.decision().completeness.candidate_count, 1);
    let observation = digest("separately-acquired-test-outcome");
    for principal in ["generator", "same-controller"] {
        let outcome = fixture.outcome(&prepared, principal, observation);
        let evidence = fixture.sign(principal, LearningEvidenceRoleV1::Observer, &outcome_signing_payload_v2(&outcome));
        assert!(fixture.sink.append_outcome(first.chain_digest, &prepared, observation, outcome, &evidence, /*now*/ 50).is_err());
    }
    assert_eq!(fixture.sink.snapshot().unwrap().records().len(), 1);
    let outcome = fixture.outcome(&prepared, "observer", observation);
    let evidence = fixture.sign("observer", LearningEvidenceRoleV1::Observer, &outcome_signing_payload_v2(&outcome));
    fixture.sink.append_outcome(first.chain_digest, &prepared, observation, outcome, &evidence, /*now*/ 50).unwrap();
    let before = fixture.sink.snapshot().unwrap();
    let frontier = fixture.sink.witness_frontier().unwrap();
    let recovered = fixture.reopen();
    assert_eq!(recovered.sink.snapshot().unwrap(), before);
    assert_eq!(recovered.sink.witness_frontier().unwrap(), frontier);
}

#[test]
fn memory_outcome_cannot_move_to_another_candidate_episode_or_unsigned_observation() {
    let fixture = LedgerFixture::new();
    let prepared = prepare(fixture.context("same-episode"), digest("cut"), digest("code"), digest("receipt"), digest("first-bundle")).unwrap();
    let signed = fixture.sign("generator", LearningEvidenceRoleV1::Generator, &prepared.signing_payload().unwrap());
    let first = fixture.sink.append_training(Digest32::ZERO, &prepared, &signed, /*now*/ 50).unwrap();
    let other = prepare(fixture.context("same-episode"), digest("cut"), digest("code"), digest("receipt"), digest("other-bundle")).unwrap();
    let observation = digest("independent-observation");
    let substituted = fixture.outcome(&other, "observer", observation);
    let signed = fixture.sign("observer", LearningEvidenceRoleV1::Observer, &outcome_signing_payload_v2(&substituted));
    assert!(fixture.sink.append_outcome(first.chain_digest, &other, observation, substituted, &signed, /*now*/ 50).is_err());
    let mut wrong_episode = fixture.outcome(&prepared, "observer", observation);
    wrong_episode.episode_id = id("other-episode");
    let signed = fixture.sign("observer", LearningEvidenceRoleV1::Observer, &outcome_signing_payload_v2(&wrong_episode));
    assert!(fixture.sink.append_outcome(first.chain_digest, &prepared, observation, wrong_episode, &signed, /*now*/ 50).is_err());
    let outcome = fixture.outcome(&prepared, "observer", observation);
    let signed = fixture.sign("observer", LearningEvidenceRoleV1::Observer, &outcome_signing_payload_v2(&outcome));
    assert!(fixture.sink.append_outcome(first.chain_digest, &prepared, digest("changed-evidence"), outcome, &signed, /*now*/ 50).is_err());
    assert_eq!(fixture.sink.snapshot().unwrap().records().len(), 1);
}

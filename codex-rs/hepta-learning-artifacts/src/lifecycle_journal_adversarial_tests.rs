use super::*;
use crate::test_support::FixtureValue;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("valid fixture id")
}

fn actor(role: LifecycleActorRoleV2) -> LifecycleActorEvidenceV2 {
    LifecycleActorEvidenceV2 {
        actor_id: id("producer"),
        credential_digest: Digest32::of_bytes(b"credential"),
        role,
        authority_epoch: 1,
        verified_at: 10,
        expires_at: 100,
    }
}

fn event(
    name: &str,
    prior_state: ArtifactLifecycleStateV1,
    next_state: ArtifactLifecycleStateV1,
    occurred_at: u64,
) -> ArtifactLifecycleEventV1 {
    ArtifactLifecycleEventV1 {
        event_id: id(name),
        artifact_id: id("artifact"),
        prior_state,
        next_state,
        actor_id: id("producer"),
        actor_credential_digest: Digest32::of_bytes(b"credential"),
        evidence_digest: Digest32::of_bytes(name.as_bytes()),
        authority_epoch: 1,
        occurred_at,
    }
}

fn trained() -> ArtifactLifecycleJournalV2 {
    let mut journal = ArtifactLifecycleJournalV2::new();
    journal
        .append(
            Digest32::ZERO,
            &id("producer"),
            actor(LifecycleActorRoleV2::Producer),
            event(
                "trained",
                ArtifactLifecycleStateV1::Proposed,
                ArtifactLifecycleStateV1::Trained,
                20,
            ),
            20,
        )
        .fixture("trained fixture");
    journal
}

#[test]
fn producer_substitution_cannot_authorize_self_evaluation() {
    let mut journal = trained();
    let before = journal.snapshot();
    assert!(
        journal
            .append(
                journal.head_digest(),
                &id("substitute-producer"),
                actor(LifecycleActorRoleV2::Evaluator),
                event(
                    "evaluated",
                    ArtifactLifecycleStateV1::Trained,
                    ArtifactLifecycleStateV1::Evaluated,
                    21,
                ),
                21,
            )
            .is_err()
    );
    assert_eq!(journal.snapshot(), before);
}

#[test]
fn exact_replay_rejects_changed_actor_role() {
    let mut journal = trained();
    assert!(
        journal
            .append(
                journal.head_digest(),
                &id("producer"),
                actor(LifecycleActorRoleV2::Selector),
                event(
                    "trained",
                    ArtifactLifecycleStateV1::Proposed,
                    ArtifactLifecycleStateV1::Trained,
                    20,
                ),
                21,
            )
            .is_err()
    );
}

#[test]
fn future_event_is_rejected_without_mutation() {
    let mut journal = ArtifactLifecycleJournalV2::new();
    assert!(
        journal
            .append(
                Digest32::ZERO,
                &id("producer"),
                actor(LifecycleActorRoleV2::Producer),
                event(
                    "future-trained",
                    ArtifactLifecycleStateV1::Proposed,
                    ArtifactLifecycleStateV1::Trained,
                    40,
                ),
                20,
            )
            .is_err()
    );
    assert!(journal.records().is_empty());
}

#[test]
fn recovery_rejects_a_journal_from_the_future() {
    assert!(ArtifactLifecycleJournalV2::from_snapshot(trained().snapshot(), 19).is_err());
}

#[test]
fn lifecycle_time_cannot_move_backwards() {
    let mut journal = trained();
    let mut evaluator = actor(LifecycleActorRoleV2::Evaluator);
    evaluator.actor_id = id("evaluator");
    let mut evaluation = event(
        "backdated-evaluation",
        ArtifactLifecycleStateV1::Trained,
        ArtifactLifecycleStateV1::Evaluated,
        19,
    );
    evaluation.actor_id = evaluator.actor_id.clone();
    assert!(
        journal
            .append(
                journal.head_digest(),
                &id("producer"),
                evaluator,
                evaluation,
                21
            )
            .is_err()
    );
}

use codex_hepta_bellman_operator::FrozenMemoryTrainingV1;
use codex_hepta_bellman_operator::MemoryTrainingError;
use codex_hepta_bellman_operator::MemoryTrainingObservationV1;
use codex_hepta_bellman_operator::MemoryTrainingProfileV1;
use codex_hepta_bellman_operator::MemoryTrainingSourceV1;
use codex_hepta_bellman_operator::finish_memory_training_from_owner_v1;
use codex_hepta_bellman_operator::freeze_memory_training_from_owner_v1;

use super::*;

const SOURCE: &str = "1 3";
const BASE: f64 = 0.0;

fn single_source_dataset() -> TestResult<(Fixture, LedgerWriter, DatasetSnapshotReceiptV3, StableId)>
{
    let fixture = Fixture::new()?;
    let mut owner = fixture.writer()?;
    let first_outcome = collect(&mut owner, "first", 0)?;
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("memory-dataset")?,
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("policy"),
    };
    let signed = sign(
        owner.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&owner.snapshot()?, &plan)?,
    )?;
    let receipt = owner.freeze_dataset(plan, &signed, 50)?;
    Ok((fixture, owner, receipt, first_outcome))
}

fn profile() -> TestResult<MemoryTrainingProfileV1> {
    Ok(MemoryTrainingProfileV1 {
        job_id: id("memory-job")?,
        artifact_id: id("memory-artifact")?,
        producer_id: id("memory-producer")?,
        predecessor_generation: Generation::new(1)?,
        generation: Generation::new(2)?,
        objective_digest: digest("objective"),
        base_digest: digest(BASE.to_le_bytes()),
        encoder_digest: digest("whitespace-decimal"),
        trainer_digest: digest("scalar-mean-step"),
        scope_digest: digest("memory-scope"),
        maximum_steps: 1,
        maximum_tokens_per_step: 2,
        maximum_payload_bytes: 8,
        expires_at: 60,
    })
}

fn source(text: &str) -> MemoryTrainingSourceV1 {
    MemoryTrainingSourceV1 {
        support_digest: digest("first.support"),
        content_digest: digest(text),
        content: text.to_owned(),
    }
}

// One gradient step for the mean half-squared error of a scalar adapter.
// The immutable base and the trained parameter occupy separate storage.
fn scalar_step(
    frozen: &FrozenMemoryTrainingV1,
) -> TestResult<(MemoryTrainingObservationV1, [u8; 8])> {
    let targets = frozen
        .source_text()
        .split_whitespace()
        .map(str::parse::<f64>)
        .collect::<Result<Vec<_>, _>>()?;
    let base = BASE.to_le_bytes();
    let initial = f64::from_le_bytes(base);
    let gradient =
        targets.iter().map(|target| initial - target).sum::<f64>() / targets.len() as f64;
    let payload = (initial - gradient).to_le_bytes();
    let observation = MemoryTrainingObservationV1 {
        job_digest: frozen.job_digest(),
        base_digest: frozen.profile().base_digest,
        frozen_base_after_digest: digest(base),
        encoder_digest: frozen.profile().encoder_digest,
        trainer_digest: frozen.profile().trainer_digest,
        payload_digest: digest(payload),
        payload_bytes: payload.len() as u64,
        completed_steps: 1,
        consumed_tokens: targets.len() as u64,
        trainable_parameters: 1,
        changed_parameters: u64::from(payload != base),
    };
    Ok((observation, payload))
}

#[test]
fn signed_dataset_binds_reproducible_job_and_scalar_training_payload() -> TestResult<()> {
    let (_fixture, owner, dataset, _) = single_source_dataset()?;
    let profile = profile()?;
    let freeze = |profile, text, now| {
        freeze_memory_training_from_owner_v1(&owner, &dataset, profile, source(text), now)
    };
    let frozen = freeze(profile.clone(), SOURCE, 50)?;
    let repeated = freeze(profile.clone(), SOURCE, 51)?;
    assert_eq!(repeated.job_digest(), frozen.job_digest());
    assert_ne!(
        freeze(profile.clone(), "1 4", 50)?.job_digest(),
        frozen.job_digest()
    );
    let another_scope = MemoryTrainingProfileV1 {
        scope_digest: digest("other-scope"),
        ..profile.clone()
    };
    assert_ne!(
        freeze(another_scope, SOURCE, 50)?.job_digest(),
        frozen.job_digest()
    );

    let (observed, payload) = scalar_step(&frozen)?;
    assert_eq!(payload, 2.0_f64.to_le_bytes());
    assert_eq!(scalar_step(&repeated)?, (observed.clone(), payload));
    let job_digest = frozen.job_digest();
    let candidate =
        finish_memory_training_from_owner_v1(&owner, frozen, observed.clone(), &payload, 59)?;
    assert_eq!(candidate.observation(), &observed);
    let admitted = candidate.frozen();
    assert_eq!(admitted.profile(), &profile);
    assert_eq!(admitted.job_digest(), job_digest);
    assert_eq!(
        admitted.dataset().snapshot.dataset_digest,
        dataset.snapshot.dataset_digest
    );
    assert_eq!(admitted.source_text(), SOURCE);
    assert_eq!(admitted.source_support(), digest("first.support"));
    assert_eq!(admitted.content_digest(), digest(SOURCE));
    let debug = format!("{admitted:?}");
    assert!(debug.contains("source_bytes"));
    assert!(!debug.contains(&format!("{SOURCE:?}")));
    Ok(())
}

#[test]
fn freeze_rejects_invalid_profiles_changed_bytes_and_mixed_signed_sources() -> TestResult<()> {
    let (_fixture, owner, dataset, _) = single_source_dataset()?;
    let valid = profile()?;
    for invalid in [
        MemoryTrainingProfileV1 {
            generation: Generation::new(3)?,
            ..valid.clone()
        },
        MemoryTrainingProfileV1 {
            objective_digest: digest("different-objective"),
            ..valid.clone()
        },
        MemoryTrainingProfileV1 {
            maximum_steps: 257,
            ..valid.clone()
        },
        MemoryTrainingProfileV1 {
            maximum_tokens_per_step: 1,
            ..valid.clone()
        },
        MemoryTrainingProfileV1 {
            maximum_payload_bytes: 0,
            ..valid.clone()
        },
        MemoryTrainingProfileV1 {
            expires_at: 50,
            ..valid.clone()
        },
        MemoryTrainingProfileV1 {
            expires_at: 3651,
            ..valid.clone()
        },
    ] {
        let result =
            freeze_memory_training_from_owner_v1(&owner, &dataset, invalid, source(SOURCE), 50);
        assert!(matches!(
            result,
            Err(MemoryTrainingError::Invalid(
                "training profile/source bounds"
            ))
        ));
    }
    let changed = MemoryTrainingSourceV1 {
        content: String::from("1 4"),
        ..source(SOURCE)
    };
    assert!(matches!(
        freeze_memory_training_from_owner_v1(&owner, &dataset, valid.clone(), changed, 50),
        Err(MemoryTrainingError::Invalid(
            "training profile/source bounds"
        ))
    ));
    let (_mixed_fixture, mixed_owner, mixed_dataset, _) = qualified_dataset()?;
    let rejected = freeze_memory_training_from_owner_v1(
        &mixed_owner,
        &mixed_dataset,
        valid,
        source(SOURCE),
        50,
    )
    .expect_err("a second authenticated decision names another source");
    assert!(matches!(
        rejected,
        MemoryTrainingError::Invalid("source support/objective mismatch")
    ));
    assert!(
        rejected
            .to_string()
            .contains("source support/objective mismatch")
    );
    Ok(())
}

#[test]
fn finish_rejects_substitution_expiry_and_inconsistent_training_counters() -> TestResult<()> {
    let (_fixture, owner, dataset, _) = single_source_dataset()?;
    let frozen =
        freeze_memory_training_from_owner_v1(&owner, &dataset, profile()?, source(SOURCE), 50)?;
    let (observed, payload) = scalar_step(&frozen)?;
    let changes: &[fn(&mut MemoryTrainingObservationV1)] = &[
        |observed| observed.job_digest = digest("other-job"),
        |observed| observed.frozen_base_after_digest = digest("changed-base"),
        |observed| observed.encoder_digest = digest("other-encoder"),
        |observed| observed.trainer_digest = digest("other-trainer"),
        |observed| observed.payload_bytes = 7,
        |observed| observed.completed_steps = 0,
        |observed| observed.completed_steps = 2,
        |observed| observed.consumed_tokens = 1,
        |observed| observed.consumed_tokens = 3,
        |observed| observed.trainable_parameters = 16_777_217,
        |observed| observed.changed_parameters = 0,
        |observed| observed.changed_parameters = 2,
    ];
    let reject = |observation, payload: &[u8], now| {
        let result =
            finish_memory_training_from_owner_v1(&owner, frozen.clone(), observation, payload, now);
        assert!(matches!(
            result,
            Err(MemoryTrainingError::Invalid(
                "trainer observation/payload binding"
            ))
        ));
    };
    for change in changes {
        let mut changed = observed.clone();
        change(&mut changed);
        reject(changed, &payload, 50);
    }
    reject(observed.clone(), &3.0_f64.to_le_bytes(), 50);
    reject(observed, &payload, 60);
    Ok(())
}

#[test]
fn signed_outcome_correction_invalidates_new_freeze_and_in_flight_completion() -> TestResult<()> {
    let (_fixture, mut owner, dataset, original_outcome) = single_source_dataset()?;
    let frozen =
        freeze_memory_training_from_owner_v1(&owner, &dataset, profile()?, source(SOURCE), 50)?;
    let (observed, payload) = scalar_step(&frozen)?;
    append_correction(&mut owner, &original_outcome)?;
    assert!(matches!(
        freeze_memory_training_from_owner_v1(&owner, &dataset, profile()?, source(SOURCE), 50),
        Err(MemoryTrainingError::Ledger(_))
    ));
    assert!(matches!(
        finish_memory_training_from_owner_v1(&owner, frozen, observed, &payload, 50),
        Err(MemoryTrainingError::Ledger(_))
    ));
    Ok(())
}

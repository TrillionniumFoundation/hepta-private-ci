//! Synthetic enrollment/history checks; ordinary C is exercised separately.
//! These keys are mechanism fixtures, never original host custody.

use super::*;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateReasonV2;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

fn d(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn fixture() -> anyhow::Result<(OriginalCircuitNextUseReceiptConfigV1, [SigningKey; 3])> {
    fixture_with_controller_collision(None)
}

fn fixture_with_controller_collision(
    collision: Option<usize>,
) -> anyhow::Result<(OriginalCircuitNextUseReceiptConfigV1, [SigningKey; 3])> {
    let (_, _, original) = crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
    let mut request = original.snapshot().request.clone();
    let mut owners = original.snapshot().owners.clone();
    let current = now()?;
    request.envelope.expiry_unix_seconds = current + 600;
    request.budget.maximum_dataset_rows = 1;
    request.budget.maximum_dataset_bytes = 128;
    request.budget.maximum_training_steps = 1;
    request.budget.maximum_training_milliseconds = 1;
    let keys = [
        SigningKey::from_bytes(&[101; 32]),
        SigningKey::from_bytes(&[102; 32]),
        SigningKey::from_bytes(&[103; 32]),
    ];
    let mut signers = Vec::new();
    for (index, (actor, role)) in [
        (&owners.trainer, LearningEvidenceRoleV1::Generator),
        (&owners.selector, LearningEvidenceRoleV1::Selector),
        (&owners.next_use_observer, LearningEvidenceRoleV1::Observer),
    ]
    .into_iter()
    .enumerate()
    {
        let verifying_key = keys[index].verifying_key().to_bytes();
        let controller = if index == 2 {
            collision.unwrap_or(index)
        } else {
            index
        };
        signers.push(TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: actor.clone(),
                credential_chain_digest: d(&format!("explicit-observer-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&verifying_key),
                scope_digest: d("explicit-observer-trust"),
                authority_epoch: 1,
                authenticated_at: current - 60,
                expires_at: current + 1200,
            },
            controller_id: StableId::new(format!("explicit-observer-controller-{controller}"))?,
            verifying_key,
            roles: vec![role],
            revoked_at: None,
        });
    }
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: d("explicit-observer-trust"),
        objective_digest: request.envelope.objective_digest,
        authority_epoch: 1,
        signers: signers.clone(),
    })?;
    owners.evidence_trust_digest = verifier.trust_digest();
    let scope = FrozenLearningScopeV2::freeze(
        &request,
        &owners,
        LearningUpdateScopeV2::Cell,
        d("explicit-observer-rule"),
    )?;
    let retained_bundle = request.selected_bundle.digest()?;
    let completed_task_receipt = request.completed_task_receipt;
    let mut coordinator = LearningIterationCoordinatorV1::new(request, owners)?;
    for observation in [
        LearningIterationObservationV1::Experience {
            episode_digest: d("explicit-episode"),
            completed_task_receipt,
        },
        LearningIterationObservationV1::Dataset {
            snapshot_digest: d("explicit-dataset"),
            episode_digest: d("explicit-episode"),
            withdrawal_frontier: d("explicit-withdrawal"),
            rows: 1,
            bytes: 64,
        },
        LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
            retained_bundle,
            dataset: d("explicit-dataset"),
            update_rule: d("explicit-observer-rule"),
            steps: 1,
            milliseconds: 1,
            reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
        }),
        LearningIterationObservationV1::Selection {
            candidate_bundle: retained_bundle,
            selection_digest: d("explicit-selection"),
        },
    ] {
        let receipt = LearningIterationReceiptV1 {
            operation_id: coordinator.snapshot().request.operation_id.clone(),
            predecessor: coordinator.snapshot().head_digest,
            actor_id: coordinator
                .snapshot()
                .owners
                .owner(observation.stage())
                .clone(),
            evidence_digest: d("explicit-stage-evidence"),
            observed_unix_seconds: current,
            observation,
        };
        coordinator.record(receipt, current)?;
    }
    let selection = coordinator.snapshot().clone();
    let evidence = predecessor_signatures(&selection, &verifier, &keys)?;
    Ok((
        OriginalCircuitNextUseReceiptConfigV1 {
            selection,
            scope,
            signer: signers[2].clone(),
            verifier,
            training_evidence: evidence[0].clone(),
            selection_evidence: evidence[1].clone(),
            maximum_signature_lifetime_seconds: 300,
        },
        keys,
    ))
}

fn opened(root: &Path, name: &str) -> anyhow::Result<File> {
    Ok(std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(root.join(name))?)
}

fn witness(
    root: &Path,
    config: &OriginalCircuitNextUseReceiptConfigV1,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        opened(root, "witness")?,
        JournalScope {
            scope_digest: config.scope.binding(),
            objective_digest: config.selection.request.envelope.objective_digest,
        },
        Generation::new(1)?,
        16,
    )?)
}

fn predecessor_signatures(
    selection: &LearningIterationSnapshotV1,
    verifier: &LearningEvidenceVerifierV1,
    keys: &[SigningKey; 3],
) -> anyhow::Result<[SignedLearningEvidenceV1; 2]> {
    let mut values = Vec::new();
    for (index, (stage, role)) in [
        (
            LearningIterationStageV1::Training,
            LearningEvidenceRoleV1::Generator,
        ),
        (
            LearningIterationStageV1::Selection,
            LearningEvidenceRoleV1::Selector,
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let receipt = selection
            .receipts
            .iter()
            .find(|receipt| receipt.observation.stage() == stage)
            .ok_or_else(|| anyhow::anyhow!("missing original predecessor"))?;
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let mut signed = SignedLearningEvidenceV1 {
            evidence_id: StableId::new(format!("explicit-original-evidence-{index}"))?,
            principal_id: receipt.actor_id.clone(),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: verifier.scope_digest(),
            objective_digest: verifier.objective_digest(),
            authority_epoch: 1,
            issued_at: receipt.observed_unix_seconds,
            expires_at: receipt.observed_unix_seconds + 600,
            payload_digest: Digest32::of_bytes(&payload),
            signature: [0; 64],
        };
        signed.signature = keys[index].sign(&signed.signing_bytes()).to_bytes();
        values.push(signed);
    }
    Ok(values.try_into().expect("two original predecessors"))
}

#[test]
fn original_observer_configuration_rejects_substituted_custody_before_journal_creation()
-> anyhow::Result<()> {
    for scenario in 0..7 {
        let root = tempfile::tempdir()?;
        let (mut config, keys) = fixture()?;
        let original = config.clone();
        match scenario {
            0 => config.signer.verifying_key = keys[0].verifying_key().to_bytes(),
            1 => config.signer.roles = vec![LearningEvidenceRoleV1::Selector],
            2 => config.signer.controller_id = StableId::new("substituted-controller")?,
            3 => config.signer.revoked_at = Some(now()?),
            4 => config.maximum_signature_lifetime_seconds = 0,
            5 => config.maximum_signature_lifetime_seconds = 86_401,
            6 => config.selection.owners.next_use_observer = StableId::new("substituted-observer")?,
            _ => unreachable!(),
        }
        assert!(
            OriginalCircuitNextUseReceiptOwnerV1::create(
                opened(root.path(), "journal")?,
                witness(root.path(), &original)?,
                config,
                keys[2].clone(),
            )
            .is_err()
        );
        assert_eq!(std::fs::metadata(root.path().join("journal"))?.len(), 0);
    }
    Ok(())
}

#[test]
fn original_observer_predecessors_require_bound_signed_roles_and_independent_custody()
-> anyhow::Result<()> {
    let (config, keys) = fixture()?;
    let evidence = predecessor_signatures(&config.selection, &config.verifier, &keys)?;
    assert!(authenticate_predecessors(&config, &evidence, now()?).is_ok());
    for scenario in 0..6 {
        let mut changed = evidence.clone();
        match scenario {
            0 => changed.swap(0, 1),
            1 => changed[0].payload_digest = d("another-training-result"),
            2 => changed[1].role = LearningEvidenceRoleV1::Observer,
            3 => changed[1].principal_id = config.signer.principal.principal_id.clone(),
            4 => changed[0].trust_digest = d("another-trust"),
            5 => changed[1].expires_at = now()? - 1,
            _ => unreachable!(),
        }
        assert!(authenticate_predecessors(&config, &changed, now()?).is_err());
    }
    // Both renewed signatures remain cryptographically valid for the same
    // payload. The fixed original attestation bytes must still reject them.
    for index in 0..2 {
        let mut renewed = evidence.clone();
        renewed[index].expires_at += 1;
        renewed[index].signature = keys[index].sign(&renewed[index].signing_bytes()).to_bytes();
        let (stage, role) = if index == 0 {
            (
                LearningIterationStageV1::Training,
                LearningEvidenceRoleV1::Generator,
            )
        } else {
            (
                LearningIterationStageV1::Selection,
                LearningEvidenceRoleV1::Selector,
            )
        };
        let payload = learning_iteration_receipt_signing_bytes_v1(prior(&config, stage)?)?;
        assert!(
            config
                .verifier
                .verify(role, &renewed[index], &payload, now()?)
                .is_ok()
        );
        assert!(matches!(
            authenticate_predecessors(&config, &renewed, now()?),
            Err(Error::Owner(OwnerError::Binding(_)))
        ));
    }
    // Binding succeeds for these actually enrolled fixture controllers. Only
    // the independent-role check may reject their common control.
    for index in 0..2 {
        let (changed, keys) = fixture_with_controller_collision(Some(index))?;
        assert!(
            changed
                .verifier
                .require_signer_binding(LearningEvidenceRoleV1::Observer, &changed.signer, now()?,)
                .is_ok()
        );
        let evidence = predecessor_signatures(&changed.selection, &changed.verifier, &keys)?;
        assert!(matches!(
            authenticate_predecessors(&changed, &evidence, now()?),
            Err(Error::Evidence(SignedEvidenceError::ControllerCollision))
        ));
    }
    Ok(())
}

#[test]
fn original_observer_deadline_and_saved_signature_window_never_renew() -> anyhow::Result<()> {
    let (config, keys) = fixture()?;
    let started_at = now()?;
    assert!(require_new_attestation(&config, started_at, started_at).is_ok());
    assert!(require_new_attestation(&config, started_at, started_at - 1).is_err());
    assert!(
        require_new_attestation(
            &config,
            started_at,
            config.selection.request.envelope.expiry_unix_seconds,
        )
        .is_err()
    );
    let payload = b"explicit-clock-unit-payload";
    let signed = sign_original(
        &config,
        &keys[2],
        payload,
        d("explicit-identity"),
        started_at,
    )?;
    let saved = learning_owner_evidence::encode(payload, &signed)?;
    let (recovered_payload, recovered) = learning_owner_evidence::decode(&saved)?;
    assert_eq!(recovered, signed);
    assert_eq!(recovered.issued_at, started_at);
    assert_eq!(recovered.expires_at, started_at + 300);
    assert!(
        config
            .verifier
            .verify(
                LearningEvidenceRoleV1::Observer,
                &recovered,
                &recovered_payload,
                recovered.expires_at,
            )
            .is_ok()
    );
    assert!(
        config
            .verifier
            .verify(
                LearningEvidenceRoleV1::Observer,
                &recovered,
                &recovered_payload,
                recovered.expires_at + 1,
            )
            .is_err()
    );
    assert_eq!(
        learning_owner_evidence::encode(&recovered_payload, &recovered)?,
        saved
    );
    Ok(())
}

#[test]
fn original_observer_pending_claim_reopens_without_signing_or_rewriting() -> anyhow::Result<()> {
    let root = tempfile::tempdir()?;
    let (config, keys) = fixture()?;
    let mut owner = OriginalCircuitNextUseReceiptOwnerV1::create(
        opened(root.path(), "journal")?,
        witness(root.path(), &config)?,
        config.clone(),
        keys[2].clone(),
    )?;
    let calls = AtomicUsize::new(0);
    assert!(
        owner
            .journal
            .commit_once(&owner.saved, || {
                calls.fetch_add(1, Ordering::SeqCst);
                Err(OwnerError::CommitUncertain)
            })
            .is_err()
    );
    let original = owner.journal.qualification_file_bytes(1 << 20)?;
    drop(owner);
    let before = std::fs::read(root.path().join("witness"))?;
    // Supplying newly signed, individually valid predecessor windows cannot
    // reopen an existing original journal under a different binding.
    for index in 0..2 {
        let mut renewed = config.clone();
        let evidence = if index == 0 {
            &mut renewed.training_evidence
        } else {
            &mut renewed.selection_evidence
        };
        evidence.expires_at += 1;
        evidence.signature = keys[index].sign(&evidence.signing_bytes()).to_bytes();
        assert!(validate_config(&renewed, &keys[2]).is_ok());
        assert!(
            OriginalCircuitNextUseReceiptOwnerV1::recover(
                opened(root.path(), "journal")?,
                witness(root.path(), &renewed)?,
                renewed,
                keys[2].clone(),
            )
            .is_err()
        );
        assert_eq!(std::fs::read(root.path().join("journal"))?, original);
        assert_eq!(std::fs::read(root.path().join("witness"))?, before);
    }
    let mut recovered = OriginalCircuitNextUseReceiptOwnerV1::recover(
        opened(root.path(), "journal")?,
        witness(root.path(), &config)?,
        config,
        keys[2].clone(),
    )?;
    assert!(matches!(
        recovered.journal.commit_once(&recovered.saved, || {
            calls.fetch_add(1, Ordering::SeqCst);
            Ok(Vec::new())
        }),
        Err(OwnerError::Pending)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        recovered.journal.qualification_file_bytes(1 << 20)?,
        original
    );
    drop(recovered);
    assert_eq!(std::fs::read(root.path().join("witness"))?, before);
    Ok(())
}

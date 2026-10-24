use super::*;

fn digest(index: u64) -> String {
    format!("{index:064x}")
}

fn binding(class: ExecutionClass) -> ExecutionBinding {
    ExecutionBinding {
        schema_version: EXECUTION_SCHEMA_VERSION,
        run_id: "run-1".into(),
        turn_id: "turn-1".into(),
        cell_id: Some("cell-1".into()),
        organ_id: None,
        operation_id: "op-1".into(),
        principal: "agent-1".into(),
        objective_digest: digest(1),
        policy_digest: digest(2),
        candidate_digest: digest(3),
        host: "host-1".into(),
        generation: 1,
        idempotency_key: "idem-1".into(),
        predecessor: None,
        currentness: Currentness::Current,
        final_use: if class.needs_final_use() {
            FinalUse::Verified {
                grant_digest: digest(4),
                verifier_receipt_digest: digest(5),
            }
        } else {
            FinalUse::NotGranted
        },
        rollback_reference: class.needs_final_use().then(|| "rollback-1".into()),
    }
}

fn successor(mut current: ExecutionBinding, previous: &str) -> ExecutionBinding {
    current.predecessor = Some(previous.to_string());
    current
}

struct Allow;

impl ExecutionVerifier for Allow {
    fn verify_start(
        &self,
        _reservation: &ExecutionReservation,
        _started: &ExecutionStarted,
        _class: ExecutionClass,
    ) -> Result<(), ExecutionError> {
        Ok(())
    }
}

impl EffectReceiptVerifier for Allow {
    fn verify_effect(&self, _receipt: &EffectReceipt) -> Result<(), ExecutionError> {
        Ok(())
    }
}

struct Deny;

impl ExecutionVerifier for Deny {
    fn verify_start(
        &self,
        _reservation: &ExecutionReservation,
        _started: &ExecutionStarted,
        _class: ExecutionClass,
    ) -> Result<(), ExecutionError> {
        Err(ExecutionError::AuthorizationDenied)
    }
}

fn prepared(class: ExecutionClass) -> (ExecutionJournal, ExecutionBinding, String) {
    let mut journal = ExecutionJournal::new();
    let original = binding(class);
    let head = journal
        .append(ExecutionRecord::ExecutionIntent(ExecutionIntent {
            binding: original.clone(),
            class,
            payload_digest: digest(6),
        }))
        .unwrap();
    let reservation = ExecutionReservation {
        binding: successor(original.clone(), &head),
        lease_digest: digest(7),
        expires_at_unix_ms: 200,
    };
    let reservation_digest = ExecutionRecord::ExecutionReservation(reservation.clone())
        .digest()
        .unwrap();
    journal
        .append(ExecutionRecord::ExecutionReservation(reservation))
        .unwrap();
    (journal, original, reservation_digest)
}

#[test]
fn read_only_chain_requires_verified_start_and_effect_observation() {
    let (mut journal, binding, reservation_digest) = prepared(ExecutionClass::FileRead);
    let last = journal.events().last().unwrap().digest().unwrap();
    let started = ExecutionStarted {
        binding: successor(binding.clone(), &last),
        reservation_digest,
        approval_receipt_digest: None,
        started_at_unix_ms: 100,
    };
    assert_eq!(
        journal.append(ExecutionRecord::ExecutionStarted(started.clone())),
        Err(ExecutionError::VerifierRequired)
    );
    assert_eq!(
        journal.append_started(started.clone(), &Deny),
        Err(ExecutionError::AuthorizationDenied)
    );
    let head = journal.append_started(started, &Allow).unwrap();
    let completed = ExecutionCompleted {
        binding: successor(binding.clone(), &head),
        status: CompletionStatus::Succeeded,
        output_digest: digest(8),
    };
    let head = journal
        .append(ExecutionRecord::ExecutionCompleted(completed))
        .unwrap();
    let receipt = EffectReceipt {
        binding: successor(binding, &head),
        effect_digest: digest(9),
        verifier_receipt_digest: digest(10),
    };
    assert_eq!(
        journal.append(ExecutionRecord::EffectReceipt(receipt.clone())),
        Err(ExecutionError::VerifierRequired)
    );
    journal.append_effect_receipt(receipt, &Allow).unwrap();
    assert_eq!(journal.events().len(), 5);
}

#[test]
fn mutating_action_rejects_final_use_downgrade_and_stale_generation() {
    let class = ExecutionClass::RestrictedFileWrite;
    let (mut journal, mut binding, reservation_digest) = prepared(class);
    let last = journal.events().last().unwrap().digest().unwrap();
    let original_events = journal.events().to_vec();
    binding.final_use = FinalUse::NotGranted;
    let started = ExecutionStarted {
        binding: successor(binding.clone(), &last),
        reservation_digest: reservation_digest.clone(),
        approval_receipt_digest: None,
        started_at_unix_ms: 100,
    };
    assert_eq!(
        journal.append_started(started, &Allow),
        Err(ExecutionError::Binding(
            "FinalUse witness changed or downgraded"
        ))
    );
    assert_eq!(journal.events(), original_events);
    binding.currentness = Currentness::Stale;
    binding.final_use = FinalUse::Verified {
        grant_digest: digest(4),
        verifier_receipt_digest: digest(5),
    };
    assert_eq!(
        journal.append_started(
            ExecutionStarted {
                binding: successor(binding, &last),
                reservation_digest,
                approval_receipt_digest: None,
                started_at_unix_ms: 100,
            },
            &Allow
        ),
        Err(ExecutionError::AuthorizationDenied)
    );
    assert_eq!(journal.events(), original_events);
}

#[test]
fn privileged_action_requires_approval_and_checks_predecessor() {
    let class = ExecutionClass::PrivilegedAction;
    let (mut journal, binding, reservation_digest) = prepared(class);
    let head = journal.events().last().unwrap().digest().unwrap();
    let started = ExecutionStarted {
        binding: successor(binding.clone(), &head),
        reservation_digest: reservation_digest.clone(),
        approval_receipt_digest: Some(digest(11)),
        started_at_unix_ms: 100,
    };
    assert_eq!(
        journal.append_started(started, &Allow),
        Err(ExecutionError::AuthorizationDenied)
    );
    let head = journal
        .append(ExecutionRecord::ApprovalRequest(ApprovalRequest {
            binding: successor(binding.clone(), &head),
            scope_digest: digest(12),
        }))
        .unwrap();
    let mut bad = successor(binding.clone(), &head);
    bad.generation = 2;
    assert_eq!(
        journal.append_started(
            ExecutionStarted {
                binding: bad,
                reservation_digest: reservation_digest.clone(),
                approval_receipt_digest: Some(digest(11)),
                started_at_unix_ms: 100,
            },
            &Allow
        ),
        Err(ExecutionError::Binding("operation identity changed"))
    );
    journal
        .append_started(
            ExecutionStarted {
                binding: successor(binding, &head),
                reservation_digest,
                approval_receipt_digest: Some(digest(11)),
                started_at_unix_ms: 100,
            },
            &Allow,
        )
        .unwrap();
}

#[test]
fn strict_deserialization_and_hash_chain() {
    let (mut journal, binding, _) = prepared(ExecutionClass::ReadOnlyInspection);
    let last = journal.events().last().unwrap().digest().unwrap();
    assert_eq!(
        journal.append(ExecutionRecord::ExecutionCancelled(ExecutionCancelled {
            binding: binding.clone(),
            reason_code: "operator-rejected".into(),
        })),
        Err(ExecutionError::Sequence("predecessor digest mismatch"))
    );
    let cancelled = ExecutionRecord::ExecutionCancelled(ExecutionCancelled {
        binding: successor(binding, &last),
        reason_code: "operator-rejected".into(),
    });
    let encoded = serde_json::to_vec(&cancelled).unwrap();
    assert_eq!(
        serde_json::from_slice::<ExecutionRecord>(&encoded).unwrap(),
        cancelled
    );
    journal.append(cancelled.clone()).unwrap();
    assert_eq!(
        journal.append(cancelled),
        Err(ExecutionError::Sequence("predecessor digest mismatch"))
    );
    let mut value: serde_json::Value = serde_json::from_slice(&encoded).unwrap();
    value["record"]["unexpected"] = serde_json::json!(true);
    assert!(serde_json::from_value::<ExecutionRecord>(value).is_err());
}

#[test]
fn external_runtime_shadow_abi_has_identical_digest() {
    let mut common = binding(ExecutionClass::ReadOnlyInspection);
    common.objective_digest = "1".repeat(64);
    common.policy_digest = "2".repeat(64);
    common.candidate_digest = "3".repeat(64);
    let intent = ExecutionRecord::ExecutionIntent(ExecutionIntent {
        binding: common,
        class: ExecutionClass::ReadOnlyInspection,
        payload_digest: "6".repeat(64),
    });
    assert_eq!(
        intent.digest().unwrap(),
        "9ef6afcc1658e9d022a321e0d2decaac71445433c96591a7c1c9afbc5b07f9a9"
    );
}

#[test]
fn crash_after_start_reconciles_but_indeterminate_never_authorizes_effect() {
    let (mut journal, binding, reservation_digest) = prepared(ExecutionClass::FileRead);
    let last = journal.events().last().unwrap().digest().unwrap();
    let started = ExecutionStarted {
        binding: successor(binding.clone(), &last),
        reservation_digest,
        approval_receipt_digest: None,
        started_at_unix_ms: 100,
    };
    let head = journal.append_started(started, &Allow).unwrap();
    let reconciled = ExecutionReconciled {
        binding: successor(binding.clone(), &head),
        status: ReconciliationStatus::Indeterminate,
        observation_digest: digest(19),
    };
    let head = journal
        .append(ExecutionRecord::ExecutionReconciled(reconciled))
        .unwrap();
    assert_eq!(
        journal.append_effect_receipt(
            EffectReceipt {
                binding: successor(binding, &head),
                effect_digest: digest(20),
                verifier_receipt_digest: digest(21),
            },
            &Allow
        ),
        Err(ExecutionError::Sequence(
            "cannot attest an effect after no-effect or indeterminate reconciliation"
        ))
    );
}

#[test]
fn mutating_action_without_any_final_use_never_reaches_the_verifier() {
    struct UnexpectedVerifier;
    impl ExecutionVerifier for UnexpectedVerifier {
        fn verify_start(
            &self,
            _reservation: &ExecutionReservation,
            _started: &ExecutionStarted,
            _class: ExecutionClass,
        ) -> Result<(), ExecutionError> {
            panic!("a missing FinalUse must be rejected before host verification");
        }
    }

    let class = ExecutionClass::RestrictedFileWrite;
    let mut binding = binding(class);
    binding.final_use = FinalUse::NotGranted;
    let mut journal = ExecutionJournal::new();
    let intent_digest = journal
        .append(ExecutionRecord::ExecutionIntent(ExecutionIntent {
            binding: binding.clone(),
            class,
            payload_digest: digest(6),
        }))
        .unwrap();
    let reservation_digest = journal
        .append(ExecutionRecord::ExecutionReservation(
            ExecutionReservation {
                binding: successor(binding.clone(), &intent_digest),
                lease_digest: digest(7),
                expires_at_unix_ms: 200,
            },
        ))
        .unwrap();
    let original_events = journal.events().to_vec();
    let started = ExecutionStarted {
        binding: successor(binding, &reservation_digest),
        reservation_digest,
        approval_receipt_digest: None,
        started_at_unix_ms: 100,
    };
    assert_eq!(
        journal.append_started(started, &UnexpectedVerifier),
        Err(ExecutionError::AuthorizationDenied)
    );
    assert_eq!(journal.events(), original_events);
}

#[test]
fn tagged_execution_and_final_use_envelopes_reject_discarded_fields() {
    let intent = ExecutionRecord::ExecutionIntent(ExecutionIntent {
        binding: binding(ExecutionClass::ReadOnlyInspection),
        class: ExecutionClass::ReadOnlyInspection,
        payload_digest: digest(6),
    });
    let original = serde_json::to_value(&intent).unwrap();
    let mut envelope = original.clone();
    envelope["opaque_authority"] = serde_json::json!("forged");
    assert!(serde_json::from_value::<ExecutionRecord>(envelope).is_err());

    for field in [
        "grant_digest",
        "verifier_receipt_digest",
        "opaque_authority",
    ] {
        let mut changed = original.clone();
        changed["record"]["binding"]["final_use"][field] = serde_json::json!(digest(7));
        assert!(serde_json::from_value::<ExecutionRecord>(changed).is_err());
    }
    let restored: ExecutionRecord = serde_json::from_value(original).unwrap();
    assert_eq!(restored, intent);
}

#[test]
fn final_use_decode_preserves_exact_claims_without_granting_authority() {
    for original in [
        FinalUse::NotGranted,
        FinalUse::Verified {
            grant_digest: digest(4),
            verifier_receipt_digest: digest(5),
        },
    ] {
        let bytes = serde_json::to_vec(&original).unwrap();
        let decoded: FinalUse = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(decoded, original);
        assert_eq!(serde_json::to_vec(&decoded).unwrap(), bytes);
        let mut extra = serde_json::to_value(&original).unwrap();
        extra["unverified_grant"] = serde_json::json!(true);
        assert!(serde_json::from_value::<FinalUse>(extra).is_err());
    }
    for invalid in [
        r#"{}"#,
        r#"{"state":null}"#,
        r#"{"state":"not_granted","grant_digest":null}"#,
        r#"{"state":"not_granted","state":"not_granted"}"#,
        r#"{"state":"verified","grant_digest":"unbound"}"#,
    ] {
        assert!(serde_json::from_str::<FinalUse>(invalid).is_err());
    }
}

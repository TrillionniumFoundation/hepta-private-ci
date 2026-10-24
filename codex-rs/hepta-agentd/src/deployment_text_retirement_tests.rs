use super::*;

#[test]
fn retirement_frees_capacity_without_reissuing_past_intents_after_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let owner = super::super::tests::identity(directory.path());
    let path = directory.path().join("issuer");
    let issuer = super::super::tests::issuer(&path, &owner);
    for number in 1..=96 {
        let request_id = format!("session:{number}");
        let original = issuer
            .text(
                &owner,
                &request_id,
                super::super::tests::body(),
                TextIssuerOperation::Sign,
            )
            .unwrap();
        // Unit fixture only. Production can construct the private proof
        // solely by read_original's actual AuthBus+Core terminal readback.
        issuer
            .retire_verified_text(
                &request_id,
                VerifiedTextRetirement {
                    original,
                    agent_id: owner.agent_id.clone(),
                },
            )
            .unwrap();
    }
    assert_eq!(
        issuer
            .store
            .load(STATE_OWNER)
            .unwrap()
            .text_signatures
            .len(),
        0
    );
    drop(issuer);
    let issuer = DeploymentFinalUseIssuer::open(
        &path,
        Arc::new(codex_hepta_contracts::SystemAuthorityClock),
    )
    .unwrap();
    assert_eq!(issuer.next_text_intent().unwrap(), 97);
    assert!(
        issuer
            .text(
                &owner,
                "session:1",
                super::super::tests::body(),
                TextIssuerOperation::Sign
            )
            .is_err()
    );
    assert!(
        issuer
            .text(
                &owner,
                "other-prefix:96",
                super::super::tests::body(),
                TextIssuerOperation::Sign
            )
            .is_err()
    );
    assert!(
        issuer
            .text(
                &owner,
                "session:97",
                super::super::tests::body(),
                TextIssuerOperation::Sign
            )
            .is_ok()
    );
}

#[test]
fn retiring_later_input_keeps_unknown_earlier_identity_and_rejects_wrong_proof() {
    let directory = tempfile::tempdir().unwrap();
    let owner = super::super::tests::identity(directory.path());
    let issuer = super::super::tests::issuer(&directory.path().join("issuer"), &owner);
    let first = issuer
        .text(
            &owner,
            "session:1",
            super::super::tests::body(),
            TextIssuerOperation::Sign,
        )
        .unwrap();
    let later = issuer
        .text(
            &owner,
            "session:2",
            super::super::tests::body(),
            TextIssuerOperation::Sign,
        )
        .unwrap();
    assert!(
        issuer
            .retire_verified_text(
                "session:1",
                VerifiedTextRetirement {
                    original: later.clone(),
                    agent_id: owner.agent_id.clone()
                }
            )
            .is_err()
    );
    issuer
        .retire_verified_text(
            "session:2",
            VerifiedTextRetirement {
                original: later,
                agent_id: owner.agent_id.clone(),
            },
        )
        .unwrap();
    assert_eq!(
        issuer
            .text(
                &owner,
                "session:1",
                super::super::tests::body(),
                TextIssuerOperation::Lookup
            )
            .unwrap(),
        first
    );
    assert!(!issuer.text_reference_retired("session:1").unwrap());
    assert!(issuer.text_reference_retired("session:2").unwrap());
    assert!(
        issuer
            .text(
                &owner,
                "session:2",
                super::super::tests::body(),
                TextIssuerOperation::Sign
            )
            .is_err()
    );
}

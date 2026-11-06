//! Ordinary volatile-byte/accounting checks with an actual local issuer/key.
//! They do not qualify protected Root admission or actual producer delivery.
use super::*;
use codex_hepta_contracts::SystemAuthorityClock;
use std::os::unix::fs::PermissionsExt;

fn issuer() -> Result<(tempfile::TempDir, DeploymentFinalUseIssuer), Box<dyn std::error::Error>> {
    let root = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let issuer = DeploymentFinalUseIssuer::create(
        &root.path().join("issuer"),
        "original-observation-issuer".into(),
        vec![DeploymentGrantPolicy {
            subject_id: "original-owner".into(),
            destination_id: "original-note".into(),
            scope_sha256: [1; 32],
            lifetime_ms: 30_000,
        }],
        Arc::new(SystemAuthorityClock),
    )?;
    Ok((root, issuer))
}

fn issue(
    issuer: &DeploymentFinalUseIssuer,
    request: u8,
) -> Result<SignedFinalUseGrant, Box<dyn std::error::Error>> {
    issuer
        .issue(&FinalUseBinding {
            subject_id: "original-owner".into(),
            destination_id: "original-note".into(),
            scope_sha256: [1; 32],
            request_sha256: [request; 32],
            payload_sha256: [2; 32],
        })?
        .ok_or_else(|| "original fixture grant missing".into())
}

fn captured(value: RootIssuedNotesGrantObservation) -> Result<String, Box<dyn std::error::Error>> {
    match value {
        RootIssuedNotesGrantObservation::Captured {
            signed_grant_json,
            signed_grant_sha256,
            delivery_observed,
            effect_observed,
            ..
        } => {
            assert!(!delivery_observed);
            assert!(!effect_observed);
            assert_eq!(
                signed_grant_sha256,
                Sha256Digest::for_bytes(signed_grant_json.as_bytes())
            );
            Ok(signed_grant_json)
        }
        other => Err(format!("expected an actual observed artifact, got {other:?}").into()),
    }
}

#[test]
fn actual_issuer_result_preserves_original_bytes_id_nonce_epoch_binding_and_signature()
-> Result<(), Box<dyn std::error::Error>> {
    let (_root, issuer) = issuer()?;
    let signed = issue(&issuer, 3)?;
    let actual = serde_json::to_string(&signed)?;
    let observed = OriginalNotesGrantObservations::new();
    observed.record(&signed);
    let raw = captured(observed.observe(&RootIssuedNotesGrantSelection::Exact {
        grant_id: signed.grant.grant_id.clone(),
    }))?;
    assert_eq!(raw, actual);
    let retained: SignedFinalUseGrant = serde_json::from_str(&raw)?;
    assert_eq!(retained, signed);
    let key = ed25519_dalek::VerifyingKey::from_bytes(&issuer.trust_key()?.verifying_key)?;
    key.verify_strict(
        &retained.grant.signing_bytes()?,
        &ed25519_dalek::Signature::from_slice(&retained.signature)?,
    )?;
    Ok(())
}

#[test]
fn dropped_capture_cannot_return_an_older_artifact_as_latest_issue()
-> Result<(), Box<dyn std::error::Error>> {
    let (_root, issuer) = issuer()?;
    let first = issue(&issuer, 3)?;
    let second = issue(&issuer, 4)?;
    let observed = OriginalNotesGrantObservations::new();
    observed.record(&first);
    let held = observed
        .state
        .lock()
        .map_err(|_| "fixture observation mutex poisoned")?;
    observed.record(&second); // Must try-lock and return, never block issuance.
    drop(held);
    assert!(matches!(
        observed.observe(&RootIssuedNotesGrantSelection::Latest {}),
        RootIssuedNotesGrantObservation::Unknown {
            reason: "latest_original_issue_observation_was_lost"
        }
    ));
    assert_eq!(
        captured(observed.observe(&RootIssuedNotesGrantSelection::Exact {
            grant_id: first.grant.grant_id.clone()
        }))?,
        serde_json::to_string(&first)?
    );
    assert!(matches!(
        observed.observe(&RootIssuedNotesGrantSelection::Exact {
            grant_id: second.grant.grant_id
        }),
        RootIssuedNotesGrantObservation::Unknown { .. }
    ));
    Ok(())
}

#[test]
fn eviction_and_restart_are_unknown_and_never_reissue_or_extend_storage()
-> Result<(), Box<dyn std::error::Error>> {
    let (_root, issuer) = issuer()?;
    let observed = OriginalNotesGrantObservations::new();
    let first = issue(&issuer, 3)?;
    observed.record(&first);
    for index in 4..24 {
        observed.record(&issue(&issuer, index)?);
    }
    assert!(matches!(
        observed.observe(&RootIssuedNotesGrantSelection::Exact {
            grant_id: first.grant.grant_id
        }),
        RootIssuedNotesGrantObservation::Unknown { .. }
    ));
    let held = observed
        .state
        .lock()
        .map_err(|_| "fixture observation mutex poisoned")?;
    assert_eq!(held.entries.len(), MAX_ENTRIES);
    assert!(
        held.bytes
            + std::mem::size_of::<OriginalNotesGrantObservations>()
            + held.entries.capacity() * std::mem::size_of::<Entry>()
            <= MAX_BYTES
    );
    drop(held);
    let before = issuer.revocations()?;
    let restarted = OriginalNotesGrantObservations::new();
    assert!(matches!(
        restarted.observe(&RootIssuedNotesGrantSelection::Latest {}),
        RootIssuedNotesGrantObservation::Unknown { .. }
    ));
    assert_eq!(issuer.revocations()?, before);
    Ok(())
}

#[test]
fn oversized_metadata_and_counter_overflow_cannot_fall_back_to_old_latest()
-> Result<(), Box<dyn std::error::Error>> {
    let (_root, issuer) = issuer()?;
    let signed = issue(&issuer, 3)?;
    let observed = OriginalNotesGrantObservations::new();
    observed.record(&signed);
    let mut impossible_original_result = signed.clone();
    impossible_original_result.grant.grant_id = "x".repeat(MAX_BYTES);
    observed.record(&impossible_original_result);
    assert!(matches!(
        observed.observe(&RootIssuedNotesGrantSelection::Latest {}),
        RootIssuedNotesGrantObservation::Unknown { .. }
    ));
    observed.attempts.store(u64::MAX, Ordering::Release);
    observed.record(&signed);
    assert!(matches!(
        observed.observe(&RootIssuedNotesGrantSelection::Latest {}),
        RootIssuedNotesGrantObservation::Unknown {
            reason: "observation_counter_exhausted"
        }
    ));
    Ok(())
}

#[test]
fn issued_observation_selector_rejects_unknown_and_duplicate_fields() {
    for invalid in [
        r#"{"kind":"latest","grant_id":"caller-chosen"}"#,
        r#"{"kind":"latest","kind":"latest"}"#,
        r#"{"kind":"exact","grant_id":"a","grant_id":"b"}"#,
        r#"{"kind":"exact","grant_id":"a","extra":1}"#,
    ] {
        assert!(serde_json::from_str::<RootIssuedNotesGrantSelection>(invalid).is_err());
    }
}

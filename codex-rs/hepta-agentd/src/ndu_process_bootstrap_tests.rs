use super::*;
use codex_hepta_agent_protocol::NduControlRequestV1;
use codex_hepta_agent_protocol::NduControlResultV1;
use codex_hepta_agent_protocol::NduMutationOperationV1;
use codex_hepta_agent_protocol::NduMutationV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_ndu::NduOwnerError;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn signed_feed_advance_during_admission_rejects_physical_mutation() -> TestResult {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let store = root.join("store");
    let authority_dir = root.join("authority");
    for path in [&store, &authority_dir] {
        std::fs::create_dir(path)?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))?;
    }
    let issuer = SigningKey::from_bytes(&[73; 32]);
    let distributor = SigningKey::from_bytes(&[74; 32]);
    let path = root.join("feed.json");
    let first = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let publish = |revision, revoked_grant_ids| -> Result<(), AgentdNduOwnerErrorV1> {
        let now = now_ms()?;
        let update = FinalUseRevocationUpdate::new(
            "feed".into(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision,
                revoked_grant_ids,
            },
            now.saturating_sub(1_000),
            now + 240_000,
        );
        let signature = distributor
            .sign(&update.signing_bytes().map_err(invalid)?)
            .to_bytes()
            .to_vec();
        let bytes = serde_json::to_vec(&SignedFinalUseRevocationUpdate { update, signature })
            .map_err(invalid)?;
        let temporary = path.with_extension("tmp");
        std::fs::write(&temporary, bytes).map_err(invalid)?;
        std::fs::rename(temporary, &path).map_err(invalid)?;
        Ok(())
    };
    publish(1, BTreeSet::new())?;
    let authority = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "issuer".into(),
        issuer.verifying_key().to_bytes(),
        first,
    )?;
    let policy: Policy = serde_json::from_value(serde_json::json!({
        "profile_id":"profile","policy_id":"policy",
        "axis_registry_digest":Digest32::of_bytes(b"axes").to_string(),
        "normalization_manifest_digest":Digest32::of_bytes(b"normalization").to_string(),
        "utility_axes":[{"id":"success","direction":"maximize","aggregation":"sum",
            "uncertainty_aggregation":"maximum","tolerance_raw":0}],
        "risk_axes":[],"resource_axes":[],"required_organs":["planner"],"scalarization":null
    }))?;
    let host = AgentdNduOwnerHostV1::open_with_feed(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c79")?,
        1,
        AgentdNduOwnerBootstrapV1 {
            store_root: store,
            authority,
            policy: policy.native()?,
        },
        Some(NduRevocationSourceV1 {
            path: path.clone(),
            verifier: FinalUseRevocationFeedVerifier::new(
                "feed".into(),
                distributor.verifying_key().to_bytes(),
            )?,
            trust_digest: Digest32::of_bytes(b"test-trust"),
        }),
    )?;
    let mutation = NduMutationV1 {
        operation: NduMutationOperationV1::AppendPreference,
        identity: [1; 32],
        objective: [2; 32],
        subject: [3; 32],
        projection: [4; 32],
        expected_predecessor: None,
    };
    let NduControlResultV1::Prepared {
        binding,
        journal_head,
    } = host.control(
        NduControlRequestV1::Prepare {
            mutation: mutation.clone(),
            expected_head: [0; 32],
        },
        || Ok(()),
    )?
    else {
        return Err("unexpected prepared result".into());
    };
    let now = now_ms()?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "issuer".into(),
        authority_epoch: 1,
        grant_id: "late-revoked".into(),
        nonce: [7; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 60_000,
    };
    let signature = issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    let mut observations = 0;
    let result = host.control(
        NduControlRequestV1::Apply {
            mutation: mutation.clone(),
            expected_head: journal_head,
            grant: SignedFinalUseGrant { grant, signature },
        },
        || {
            observations += 1;
            if observations == 2 {
                publish(2, BTreeSet::from(["late-revoked".to_string()]))?;
            }
            Ok(())
        },
    );
    assert_eq!(observations, 2);
    assert!(matches!(
        result,
        Err(AgentdNduOwnerErrorV1::Owner(NduOwnerError::InvalidContext(
            "revocation feed changed before mutation"
        )))
    ));
    assert!(matches!(
        host.control(
            NduControlRequestV1::Outcome {
                identity: mutation.identity
            },
            || Ok(())
        )?,
        NduControlResultV1::Outcome { entry: None }
    ));
    assert!(
        matches!(host.control(NduControlRequestV1::Context, || Ok(()))?, NduControlResultV1::Context { journal_head, .. } if journal_head == [0; 32])
    );
    Ok(())
}

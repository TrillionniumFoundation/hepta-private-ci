#![cfg(all(unix, not(any(target_os = "illumos", target_os = "solaris"))))]

use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::AuthBusMutationDisposition;
use codex_hepta_authbus::IssuerPurpose;
use codex_hepta_authbus::IssuerSpec;
use codex_hepta_authbus::PolicyEffect;
use codex_hepta_authbus::PolicySpec;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_authbus::TrustedTimeAttestationClaims;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tempfile::TempDir;

struct Paths {
    _root: TempDir,
    database: PathBuf,
    checkpoint: PathBuf,
}

fn private_paths() -> Paths {
    let root = TempDir::new().expect("temporary root");
    let database_root = root.path().join("database");
    let checkpoint_root = root.path().join("checkpoint");
    std::fs::create_dir_all(&database_root).expect("database root");
    std::fs::create_dir_all(&checkpoint_root).expect("checkpoint root");
    std::fs::set_permissions(&database_root, std::fs::Permissions::from_mode(0o700))
        .expect("database permissions");
    std::fs::set_permissions(&checkpoint_root, std::fs::Permissions::from_mode(0o700))
        .expect("checkpoint permissions");
    Paths {
        database: database_root.join("authority.sqlite"),
        checkpoint: checkpoint_root.join("authority-checkpoint.json"),
        _root: root,
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn signed_time(
    key: &SigningKey,
    issuer_id: &StableId,
    wall_time_ms: u64,
    source_revision: u64,
) -> SignedTrustedTimeAttestation {
    let claims = TrustedTimeAttestationClaims {
        issuer_id: issuer_id.clone(),
        key_epoch: Generation::new(1).expect("time epoch"),
        wall_time_ms,
        source_revision,
        source_digest: Digest32::of_bytes(&source_revision.to_be_bytes()),
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    SignedTrustedTimeAttestation { claims, signature }
}

#[tokio::test]
async fn deterministic_rejection_does_not_claim_separately_observed_time_was_rolled_back() {
    let paths = private_paths();
    let host = AuthBusAuthorityHost::bootstrap(
        &paths.database,
        paths.checkpoint.clone(),
        "mutation-contract-owner",
    )
    .await
    .expect("bootstrap owner");

    let time_issuer = id("issuer:contract-time");
    let time_key = SigningKey::from_bytes(&[71; 32]);
    host.enroll_issuer(
        IssuerPurpose::TrustedTime,
        IssuerSpec {
            issuer_id: time_issuer.clone(),
            key_epoch: Generation::new(1).expect("time epoch"),
            verifying_key: time_key.verifying_key(),
        },
    )
    .await
    .expect("enroll time issuer");

    let first_time = host
        .observe_trusted_time_attestation(&signed_time(&time_key, &time_issuer, 100, 1))
        .await
        .expect("observe first trusted time");
    let policy_id = id("policy:mutation-contract");
    let principal = id("principal:mutation-contract");
    let action = id("action:mutation-contract");
    let scope_digest = Digest32::of_bytes(b"mutation-contract-scope");
    let allow = PolicySpec {
        policy_id: policy_id.clone(),
        principal: principal.clone(),
        action: action.clone(),
        scope_digest,
        effect: PolicyEffect::Allow,
        not_before_ms: 1,
        expires_at_ms: 1_000,
    };
    host.create_policy(allow, first_time)
        .await
        .expect("create policy");

    let second_time = host
        .observe_trusted_time_attestation(&signed_time(&time_key, &time_issuer, 200, 2))
        .await
        .expect("observe second trusted time");
    let rejected = host
        .replace_policy(
            PolicySpec {
                policy_id: policy_id.clone(),
                principal: principal.clone(),
                action: action.clone(),
                scope_digest,
                effect: PolicyEffect::Deny,
                not_before_ms: 1,
                expires_at_ms: 1_000,
            },
            999,
            second_time.clone(),
        )
        .await
        .expect_err("stale revision must reject replacement");
    assert!(matches!(&rejected, AuthBusAuthorityError::RevisionConflict));
    assert_eq!(
        rejected.mutation_disposition(),
        AuthBusMutationDisposition::NotCommitted
    );

    let decision = host
        .authorize(&principal, &action, scope_digest, 1, second_time)
        .await
        .expect("original policy remains authoritative");
    assert!(decision.allowed());
    assert_eq!(decision.policy_id(), &policy_id);
}

#[cfg(unix)]
use std::collections::BTreeSet;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
#[cfg(unix)]
use std::time::SystemTime;
#[cfg(unix)]
use std::time::UNIX_EPOCH;

#[cfg(unix)]
use codex_hepta_contracts::FinalUseAuthority;
#[cfg(unix)]
use codex_hepta_contracts::FinalUseGrant;
#[cfg(unix)]
use codex_hepta_contracts::FinalUseRevocations;
#[cfg(unix)]
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
#[cfg(unix)]
use ed25519_dalek::Signer;
#[cfg(unix)]
use ed25519_dalek::SigningKey;

use super::*;
use crate::PrepareOperationIntent;

fn stable_id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}

fn config(temp: &tempfile::TempDir) -> SqliteConfig {
    let home = AbsolutePathBuf::try_from(temp.path().to_path_buf()).expect("absolute tempdir");
    SqliteConfig::new_for_testing(home)
}

#[tokio::test]
async fn dispatcher_claims_only_bounded_ready_work() {
    let temp = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&config(&temp)).await.expect("open");
    for index in 0..2 {
        let request = PrepareOperationIntent {
            scope: stable_id("scope:dispatcher"),
            operation_id: stable_id(&format!("operation:dispatcher:{index}")),
            predecessor_digest: None,
            payload_digest: Digest32::of_bytes(format!("payload-{index}").as_bytes()),
            destination: stable_id("destination:dispatcher"),
            owner_generation: generation(3),
            authority_epoch: generation(9),
        };
        store.prepare_intent(&request).await.expect("prepare");
    }
    let dispatcher = DurableDispatcher::new(
        store,
        stable_id("worker:dispatcher"),
        generation(3),
        1000,
    )
    .expect("dispatcher");
    let claims = dispatcher.claim_ready(1).await.expect("claim batch");
    assert_eq!(claims.len(), 1);
}

#[cfg(unix)]
#[tokio::test]
async fn authorized_dispatch_acknowledges_without_inventing_terminal_success() {
    let temp = tempfile::tempdir().expect("tempdir");
    let store = DurableOperationStore::open(&config(&temp)).await.expect("open");
    let request = PrepareOperationIntent {
        scope: stable_id("scope:authorized-dispatch"),
        operation_id: stable_id("operation:authorized-dispatch"),
        predecessor_digest: None,
        payload_digest: Digest32::of_bytes(b"payload"),
        destination: stable_id("destination:authorized-dispatch"),
        owner_generation: generation(3),
        authority_epoch: generation(9),
    };
    let record = store.prepare_intent(&request).await.expect("prepare");
    let dispatcher = DurableDispatcher::new(
        store.clone(),
        stable_id("worker:authorized-dispatch"),
        generation(3),
        1000,
    )
    .expect("dispatcher");
    let lease = dispatcher
        .claim_ready(1)
        .await
        .expect("claims")
        .pop()
        .expect("lease");

    let signing_key = SigningKey::from_bytes(&[51; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let binding = record.final_use_binding();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "security-owner".to_string(),
        authority_epoch: 9,
        grant_id: "dispatch-grant".to_string(),
        nonce: [21; 32],
        binding: binding.clone(),
        not_before_unix_ms: now.saturating_sub(1000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signing_key
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let authority_dir = tempfile::tempdir().expect("authority dir");
    std::fs::set_permissions(authority_dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("permissions");
    let authority = FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "security-owner".to_string(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let signed = SignedFinalUseGrant { grant, signature };

    let result = dispatcher
        .dispatch_authorized(
            &authority,
            &signed,
            &lease,
            Digest32::of_bytes(b"dispatch-attempt"),
            |_| DispatchBoundaryResult::Acknowledged {
                value: 7_u64,
                acknowledgement_digest: Digest32::of_bytes(b"transport-ack"),
            },
        )
        .await
        .expect("dispatch");
    assert_eq!(
        result,
        DispatchBoundaryResult::Acknowledged {
            value: 7,
            acknowledgement_digest: Digest32::of_bytes(b"transport-ack"),
        }
    );
    let operation = store
        .get_operation(&request.scope, &request.operation_id)
        .await
        .expect("lookup")
        .expect("operation");
    assert_eq!(operation.state, crate::DurableOperationState::Dispatched);
    assert!(!operation.state.is_terminal());
}

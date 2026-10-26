//! Real original SQLite/prefix owner with a scripted native history transport.
//! No native image, production Root, issuer or hardware qualification is claimed.

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::HOS2_DESTINATION_V1;
use codex_hepta_memory::HOS2_INSTALL_TOPIC_V1;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionFinalUseOutboxDispatcher;
use codex_hepta_memory::ProductionHos2Target;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::os::unix::fs::PermissionsExt;

#[tokio::test]
async fn g2_history_successor_requires_original_durable_prefix_and_retries_only_exact_retirement()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let fleet_path = directory.path().join("fleet");
    fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c065")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let source_digest = Sha256Digest::for_bytes(b"history-only-owner-explicit-test-authority");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        source_digest.clone(),
        /*authority_epoch*/ 31,
        /*owner_epoch*/ 41,
        /*lease_expires_at_unix_seconds*/ 4_000_000_000,
        ProductionAuthorityToken::from_verified_bytes(b"history-only-test-token".to_vec())?,
    )?;
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
            if &lease.agent_id != expected || lease.grant_digest != source_digest {
                return Err("explicit history-only fixture authority mismatch".to_string());
            }
            Ok(())
        },
    );
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store,
        authority,
        verifier,
        "history-only-original-owner",
        /*generation*/ 1,
    )
    .await?;
    let final_use_path = directory.path().join("final-use");
    fs::create_dir(&final_use_path)?;
    fs::set_permissions(&final_use_path, fs::Permissions::from_mode(0o700))?;
    let key = SigningKey::from_bytes(&[55; 32]);
    let final_use = FinalUseAuthority::open_state_dir(
        &final_use_path,
        "history-only-test-issuer".to_string(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 71,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let mut acknowledged = vec![0; 16];
    acknowledged[..8].copy_from_slice(&1_u64.to_le_bytes());
    acknowledged[8..].copy_from_slice(&2_u64.to_le_bytes());
    let io = script(
        [4; 16],
        VecDeque::from([
            (4, Ok(applied())),
            (
                5,
                Err("retirement reply lost after the native fixture saved its frontier".into()),
            ),
            (5, Ok(acknowledged)),
        ]),
    );
    let device = Arc::new(AgentdHos2HistoryDevice::attach(
        Box::new(io.clone()),
        &page(),
        process(),
    )?);
    let target = Arc::new(ProductionHos2Target::new(device.clone()));
    let dispatcher = ProductionFinalUseOutboxDispatcher::attach(final_use, target.clone());
    let request = request([2; 16])?;
    let operation = OperationIntentV1::new(
        StableId::new("hos2:history-only:original-k")?,
        StableId::new(owner.as_str())?,
        StableId::new(HOS2_DESTINATION_V1)?,
        Digest32::of_bytes(request.to_json()?.as_bytes()),
        request.scope_digest(),
        Generation::new(1)?,
        /*expected_predecessor*/ None,
    )?;
    let queued = writer
        .prepare_operation(operation, HOS2_INSTALL_TOPIC_V1, request.to_json()?)
        .await?;
    assert!(
        writer
            .retire_hos2_through(&target, &request.delivery)
            .await
            .is_err()
    );
    writer
        .mark_indeterminate(
            &queued.occurrence_key,
            "explicit prior-image lost-reply fixture",
        )
        .await?;
    assert!(
        writer
            .retire_hos2_through(&target, &request.delivery)
            .await
            .is_err()
    );
    assert!(device.install(&request).is_err());
    assert_eq!(
        io.requests.lock().unwrap().len(),
        1,
        "unknown prefix and attempted effects perform no history ACK"
    );
    assert_eq!(dispatcher.reconcile(&writer, /*limit*/ 8).await?, 1);
    assert_eq!(
        writer.status(&queued.occurrence_key).await?,
        LocalOutcomeState::Committed
    );
    let cut = writer.recovery_anchor().await?;
    assert!(
        writer
            .retire_hos2_through(&target, &request.delivery)
            .await
            .is_err()
    );
    assert_eq!(writer.recovery_anchor().await?, cut);
    assert_eq!(
        writer
            .retire_hos2_through(&target, &request.delivery)
            .await?,
        Hos2RetirementObservation {
            retired_through: 1,
            next_sequence: 2
        }
    );
    assert_eq!(
        writer.recovery_anchor().await?,
        cut,
        "retirement creates no alternate source journal"
    );
    let requests = io.requests.lock().unwrap();
    let opcodes = requests
        .iter()
        .map(|bytes| read_u16(bytes, /*offset*/ 8))
        .collect::<Result<Vec<_>, _>>()?;
    assert_eq!(opcodes, vec![1, 4, 5, 5]);
    assert_eq!(
        requests[2], requests[3],
        "only the exact durable-prefix ACK is repeated"
    );
    assert!(io.replies.lock().unwrap().is_empty());
    Ok(())
}

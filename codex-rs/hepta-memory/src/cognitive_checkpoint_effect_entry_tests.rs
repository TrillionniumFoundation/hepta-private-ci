//! Original FinalUse + Notes adapter with explicit issuer, channel and Root peer
//! fixtures. This does not qualify an application process or production issuer.

use super::*;
use crate::NotesPrivateChannel;
use crate::NotesTargetIdentity;
use crate::ProductionFinalUseOutboxDispatcher;
use crate::ProductionNotesTarget;
use crate::ProductionQueuedReceipt;
use crate::notes_operation_intent;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::AtomicUsize;

struct EntryClock;
impl AuthorityClock for EntryClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(1_000_000)
    }
}
struct Channel {
    request: Vec<u8>,
    response: Vec<u8>,
    calls: AtomicUsize,
    peer: Arc<ProtocolPeer>,
    entry_head: Mutex<Option<CognitiveCheckpointReceipt>>,
}
impl NotesPrivateChannel for Channel {
    fn exchange(&self, request: &[u8]) -> Result<Vec<u8>, String> {
        assert_eq!(request, self.request);
        self.calls.fetch_add(1, Ordering::SeqCst);
        *self.entry_head.lock().unwrap() = Some(self.peer.receipt.lock().unwrap().clone());
        Ok(self.response.clone())
    }
    fn invalidate(&self) {}
}
struct PreparedEntry {
    queued: ProductionQueuedReceipt,
    binding: FinalUseBinding,
    signed: SignedFinalUseGrant,
    dispatcher: ProductionFinalUseOutboxDispatcher,
    channel: Arc<Channel>,
}
async fn prepared_entry(fixture: &ManagedFixture) -> PreparedEntry {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-target-v1.json")).unwrap();
    let payload = golden["request_utf8"].as_str().unwrap().to_string();
    let request: serde_json::Value = serde_json::from_str(&payload).unwrap();
    let identity: NotesTargetIdentity = serde_json::from_value(request["target"].clone()).unwrap();
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(fixture.writer.owner_agent_id().as_str()).unwrap(),
        Generation::new(1).unwrap(),
    )
    .unwrap();
    let queued = fixture
        .writer
        .prepare_operation(intent, crate::NOTES_REPLACE_TOPIC_V1, payload.clone())
        .await
        .unwrap();
    let binding = fixture
        .writer
        .final_use_binding(&queued, &identity.destination_id())
        .await
        .unwrap();
    let channel = Arc::new(Channel {
        request: payload.into_bytes(),
        response: golden["application_response_utf8"]
            .as_str()
            .unwrap()
            .as_bytes()
            .to_vec(),
        calls: AtomicUsize::new(0),
        peer: fixture.peer.clone(),
        entry_head: Mutex::new(None),
    });
    let target = Arc::new(ProductionNotesTarget::new(identity, channel.clone()).unwrap());
    let authority_dir = fixture._temp.path().join("effect-final-use");
    std::fs::create_dir(&authority_dir).unwrap();
    std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700)).unwrap();
    let issuer = SigningKey::from_bytes(&[87; 32]);
    let final_use = FinalUseAuthority::open_state_dir_with_clock(
        &authority_dir,
        "effect-entry-fixture".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 71,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        Arc::new(EntryClock),
    )
    .unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "effect-entry-fixture".to_string(),
        authority_epoch: 71,
        grant_id: "effect-entry-test-grant".to_string(),
        nonce: [88; 32],
        binding: binding.clone(),
        not_before_unix_ms: 999_000,
        expires_at_unix_ms: 1_060_000,
    };
    let signature = issuer
        .sign(&grant.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    PreparedEntry {
        queued,
        binding,
        signed: SignedFinalUseGrant { grant, signature },
        dispatcher: ProductionFinalUseOutboxDispatcher::attach(final_use, target),
        channel,
    }
}

#[tokio::test]
async fn managed_effect_entry_never_dispatches_before_bound_entered_cut_ack() {
    let fixture = ManagedFixture::new().await;
    let entry = prepared_entry(&fixture).await;
    fixture
        .peer
        .hold_current_reply
        .store(true, Ordering::SeqCst);
    let operation = entry.queued.occurrence_key.clone();
    let result = entry
        .dispatcher
        .dispatch(&fixture.writer, &entry.signed, &entry.binding, entry.queued)
        .await;
    assert_eq!(
        entry.channel.calls.load(Ordering::SeqCst),
        0,
        "the actual synchronous Notes adapter cannot enter while its original entered claim has no independent Current acknowledgement"
    );
    assert!(result.is_err());
    assert!(fixture.store.commit_gate.is_fenced());
    assert_eq!(
        fixture.writer.status(&operation).await.unwrap(),
        crate::LocalOutcomeState::Indeterminate
    );
}

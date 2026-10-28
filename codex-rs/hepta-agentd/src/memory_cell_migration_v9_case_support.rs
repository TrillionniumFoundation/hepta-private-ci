use std::path::Path;

use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::ProviderEffectTaskFlowDriver;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_paths::HeptaAgentLayout;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use crate::MemoryCellMigrationImageV9;
use crate::MemoryCellMigrationProviderV9;
use super::process_support::DESTINATION;
use super::process_support::Process;
use super::process_support::Spec;
use super::process_support::receiver_key;
use super::process_support::source_key;
use super::target_support::copy_tree;
use super::taskflow_support::Effect;

pub(super) async fn transfer_case(directory: &Path, root: &Path, layout: &HeptaAgentLayout, name: &str,
    image: &MemoryCellMigrationImageV9, crash: Option<&str>) -> (Value, ProviderEffectIntent) {
    let receiver = Process::spawn(directory, &format!("{name}-receiver"), Spec::Receiver { root: root.to_path_buf(),
        manifest: image.manifest().clone(), crash: crash.map(str::to_string) }).await;
    let adapter = MemoryCellMigrationProviderV9::new(receiver.ready["endpoint"].as_str().expect("TCP address").parse().expect("address"),
        DESTINATION.into(), source_key(), receiver_key().verifying_key()).expect("configured transport identity");
    let mut driver = ProviderEffectTaskFlowDriver::new(DESTINATION.into(), adapter).expect("existing TaskFlow provider seam");
    let mut effect = Effect::prepare(layout, name, image.bytes()).await;
    effect.reject_invalid_grant(&mut driver, image.bytes()).await;
    let dispatched = effect.execute(&mut driver, image.bytes()).await;
    let mut processes = Vec::new();
    let mut reconciled = None;
    let receiver = if crash.is_some() {
        assert_eq!(dispatched.observation, Some(TaskFlowStepObservation::Indeterminate));
        processes.push(receiver.finish(/*crashed*/ true).await);
        effect.store.close().await;
        effect.store = AutomationStore::open(layout).await.expect("TaskFlow restart from durable owner state");
        effect.reject_ambiguous_retry(&mut driver, image.bytes()).await;
        let restarted = Process::spawn(directory, &format!("{name}-restarted"), Spec::Receiver { root: root.to_path_buf(),
            manifest: image.manifest().clone(), crash: None }).await;
        driver.adapter_mut().reconnect(restarted.ready["endpoint"].as_str().expect("TCP endpoint").parse().expect("address")).expect("same authenticated peer");
        let AuthorizedEffectRecoveryResult::Observed(receipt) = effect.recover(&driver).await else { panic!("reconciled observation") };
        assert_eq!(receipt.final_outcome, Some(TaskFlowReconcileOutcome::Succeeded));
        reconciled = Some(receipt);
        restarted
    } else {
        assert_eq!(dispatched.observation, Some(TaskFlowStepObservation::Succeeded));
        receiver
    };
    let key = ProviderEffectKey::for_logical_effect(DESTINATION, &format!("taskflow:{name}:transfer")).expect("same logical key");
    let intent = ProviderEffectIntent::new(key, image.digest());
    let before = std::fs::read(root.join("CURRENT.json")).expect("durable CURRENT");
    let ProviderEffectLookup::Ack(ack) = driver.adapter().lookup_for_intent(&intent).await else { panic!("durable provider completion") };
    // These calls qualify the adapter contract, independently of TaskFlow's
    // already-settled attempt. They cannot consume or synthesize a new grant.
    assert_eq!(driver.adapter().dispatch_with_payload(&intent, image.bytes()).await, ProviderEffectDispatch::Ack(ack.clone()));
    let probes = reject_invalid_images(driver.adapter(), image, &intent).await;
    assert_eq!(std::fs::read(root.join("CURRENT.json")).expect("unchanged CURRENT"), before);
    let traffic = driver.adapter().traffic().expect("actual transport accounting");
    assert!(traffic.transmitted_bytes > image.bytes().len() as u64 && traffic.received_bytes > 0);
    processes.push(receiver.finish(/*crashed*/ false).await);
    let authority = copy_tree(effect.directory.path(), &directory.join(format!("{name}-fixture-authority")));
    let evidence = json!({"run":name,"crash_checkpoint":crash,"effect_intent":effect.intent,"signed_fixture_grant":effect.signed,
        "final_use_binding":effect.binding,"taskflow_dispatched":dispatched,"taskflow_reconciled":reconciled,"provider_receipt":ack,
        "provider_key":intent,"probes":probes,"traffic":traffic,"processes":processes,"authority_files":authority,
        "duplicate_current_unchanged":true,"invalid_grant_provider_contacts":0,"ambiguous_retry_provider_contacts":0});
    effect.store.close().await;
    (evidence, intent)
}

async fn reject_invalid_images(adapter: &MemoryCellMigrationProviderV9, image: &MemoryCellMigrationImageV9, original: &ProviderEffectIntent) -> Value {
    let mut corrupt = image.bytes().to_vec();
    *corrupt.last_mut().expect("image contents") ^= 1;
    let conflict = ProviderEffectIntent::new(original.key.clone(), Sha256Digest::for_bytes(&corrupt));
    assert_eq!(adapter.dispatch_with_payload(&conflict, &corrupt).await, ProviderEffectDispatch::Unknown);
    assert_eq!(adapter.lookup_for_intent(&conflict).await, ProviderEffectLookup::Conflict { observed_payload_sha256: Some(image.digest()) });
    let header_offset = b"HEPTA-MEMORY-IMAGE-V9\0".len() + 4;
    let header_bytes = u32::from_be_bytes(image.bytes()[header_offset - 4..header_offset].try_into().expect("framed header")) as usize;
    let mut header = serde_json::to_value(image.manifest()).expect("manifest JSON");
    header["files"].as_array_mut().expect("inventory").reverse();
    let raw = serde_json::to_vec(&header).expect("reordered manifest");
    let mut reordered = image.bytes()[..header_offset - 4].to_vec();
    reordered.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    reordered.extend_from_slice(&raw);
    reordered.extend_from_slice(&image.bytes()[header_offset + header_bytes..]);
    let mut observations = Vec::new();
    for (label, payload) in [("corrupt", corrupt), ("reordered", reordered)] {
        let key = ProviderEffectKey::for_logical_effect(DESTINATION, &format!("probe:{}:{label}", original.key.as_str())).expect("probe key");
        let intent = ProviderEffectIntent::new(key, Sha256Digest::for_bytes(&payload));
        let rejected = adapter.dispatch_with_payload(&intent, &payload).await;
        let status = adapter.lookup_for_intent(&intent).await;
        assert_eq!(rejected, ProviderEffectDispatch::Unknown);
        assert_eq!(status, ProviderEffectLookup::NotFound);
        observations.push(json!({"label":label,"intent":intent,"dispatch":rejected,"lookup":status}));
    }
    json!({"conflicting_key":conflict,"invalid_images":observations})
}
